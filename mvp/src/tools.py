"""
Agent 工具集 —— 编程 Agent 的「手和脚」

本模块实现了 Agent 可以调用的全部工具（Tools）。
工具是 Agent 与外部世界交互的唯一方式——没有工具，Agent 就只是一个聊天机器人。

工具设计哲学（课程模块二 ACI 设计）：
    每个工具的设计都遵循「最小惊讶原则」：
    - 工具名称是动词（Read / Write / Edit / Grep / Bash），一目了然
    - 参数用 JSON Schema 描述，模型通过 schema 理解如何调用
    - 返回值始终是字符串（成功信息或错误信息），简单统一
    - 错误以 "Error" 开头，客户端据此判断 is_error

工具演进路线（对应 4 天开发计划）：
    Day 1: Read, Write, Bash         — 基础文件操作 + 命令执行
    Day 2: + Edit, Glob, Grep        — 精确编辑 + 文件搜索 + 代码搜索
    Day 3: + TaskCreate/Update/List  — 任务管理（在 task_tools.py 中实现）
    Day 4: + Agent                   — 子 Agent 生成（在 agent_tool.py 中实现）

ACI 信息粒度控制（课程 2.2 节核心概念）：
    工具的输出长度直接影响 Agent 的推理质量。关键设计：
    - Read 的 offset/limit 参数：让模型按需精读，而非一次性读入整个文件
    - Grep 的 head_limit 参数：限制搜索结果条数，防止大项目搜索撑爆上下文
    - Edit 替代 Write 做修改：只发送 diff 而非全文，节省上下文窗口
    这些都是「粗粒度定位 → 细粒度精读」漏斗策略的具体体现。
"""

import os
import re
import subprocess
from typing import Dict, Any


# ===========================================================================
# 基类
# ===========================================================================

class Tool:
    """
    工具基类 —— 所有工具的统一接口。

    每个工具需要提供三样东西：
    1. name: 工具名称，模型在 tool_use 请求中通过此名称指定要调用的工具
    2. description: 工具描述，帮助模型理解这个工具的用途和使用场景
    3. parameters: JSON Schema 格式的参数定义，模型据此生成正确的参数

    这三样东西会被 client.py 的 get_tool_definitions() 转为 Claude API 格式，
    随每次请求发送给 model_server，最终由 Qwen 的 chat template 注入 system prompt。

    设计意图：
        工具定义本身就是 ACI（Agent-Computer Interface）的一部分。
        好的工具定义 = 好的 API 文档 = 模型更准确地调用工具。
        description 要写清楚「什么时候用」和「怎么用」，而非只写「是什么」。
    """

    def __init__(self, name: str, description: str, parameters: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters

    def execute(self, **kwargs) -> str:
        """
        执行工具，返回结果字符串。

        所有工具的返回值都是字符串，这是有意为之的设计简化：
        - 成功时返回结果文本（文件内容、命令输出、操作确认等）
        - 失败时返回以 "Error" 开头的错误信息
        - 客户端通过 result.startswith("Error") 判断 is_error

        子类必须重写此方法。
        """
        raise NotImplementedError


# ===========================================================================
# Read 工具 —— 文件读取（支持分页）
# ===========================================================================

class ReadTool(Tool):
    """
    读取文件内容，支持按行分页。

    这是 Agent 最常用的工具——在 SWE-bench 数据集上，Read 的调用频率
    占所有工具调用的约 40%。Agent 的工作模式通常是：
    先用 Grep 定位 → 再用 Read 精读 → 最后用 Edit 修改。

    分页设计（ACI 信息粒度控制）：
        offset 和 limit 参数实现了「按需精读」能力。
        上下文窗口是稀缺资源——一个 500 行的文件可能就占掉 2000+ tokens。
        如果 Agent 一次性读入整个大文件，后续推理的质量会显著下降。

        分页策略：
        - 不传 offset/limit → 小文件读全文，大文件拒绝并提示用分页
        - 传 offset=50, limit=30 → 只读第 50-79 行（大文件精确定位）
        - 输出带行号前缀（如 "  50 | code here"），方便模型定位和引用

    大文件防护（对齐 CC 的 token gate 设计）：
        CC 的 FileReadTool 用两层防护：
        1. 文件大小 > 256KB → FileTooLargeError（预读检查）
        2. 输出 token > 25,000 → MaxFileReadTokenExceededError（后读检查）
        两层都返回错误信息，引导模型用 offset/limit 重新读取。

        我们简化为行数检查（MAX_LINES_WITHOUT_LIMIT = 250 行）：
        超过时返回 Error + 文件前 20 行预览 + 总行数，
        引导模型用 Grep/Glob 搜索或 offset/limit 读取需要的部分。
        关键设计：返回 Error（不是静默截断），迫使模型学习分页行为。

    带行号输出的设计意图：
        行号不仅是给人看的，更是给模型看的。
        当模型需要用 Edit 工具修改代码时，行号帮助它精确定位目标代码段。
        格式 "  行号 | 内容" 模仿了 cat -n 的输出，模型在训练数据中见过大量这种格式。
    """

    # 大文件门槛：超过此行数且未指定 limit 时，返回错误而非全文
    # CC 用 2000 行（200K context），按比例：2000 * (16K/200K) ≈ 160 行
    # 取 250 行稍留余量——小于此的文件可直接整文件阅读
    MAX_LINES_WITHOUT_LIMIT = 250
    # 错误时预览的行数（够模型判断文件结构，不必太多）
    PREVIEW_LINES = 20

    def __init__(self):
        super().__init__(
            name="Read",
            description=(
                "Read the contents of a file. "
                "Returns the file content with line numbers. "
                "For large files (over 250 lines), use Grep or Glob to search first, "
                "or specify offset and limit to read a section. "
                "Do NOT read a large file page by page — use Grep to find the relevant lines first. "
                "Example: offset=10, limit=20 reads lines 10-29."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to read"
                    },
                    "offset": {
                        "type": "integer",
                        "description": (
                            "Line number to start reading from (0-based). "
                            "Omit to read from the beginning."
                        )
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of lines to read. "
                            "Omit to read until end of file."
                        )
                    }
                },
                "required": ["file_path"]
            }
        )

    def execute(self, file_path: str, offset: int = None, limit: int = None) -> str:
        """
        读取文件内容，返回带行号的文本。

        大文件防护（对齐 CC 的 token gate）：
            CC 的 FileReadTool 在读取后检查 token 数，超过 25K tokens 时
            抛出 MaxFileReadTokenExceededError，告诉模型"file too large,
            use offset and limit"。我们用行数做类似检查：
            - 文件 > MAX_LINES_WITHOUT_LIMIT 且未指定 limit → 返回 Error
            - Error 包含文件前 PREVIEW_LINES 行 + 总行数 → 模型有足够信息重试

            关键：返回 Error 而非静默截断。这与 CC 的设计一致——
            Error 是 ACI 原则三"信息丰富的反馈"的体现，
            迫使模型主动学习用 offset/limit 精确读取。

        Args:
            file_path: 文件绝对路径
            offset: 起始行号（0-based），None 表示从头开始
            limit: 读取行数上限，None 表示读到文件末尾

        Returns:
            带行号的文件内容，或错误信息
        """
        # 模型可能传入字符串类型的数字（如 "130"），需要强制转换
        if offset is not None:
            offset = int(offset)
        if limit is not None:
            limit = int(limit)

        try:
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"

            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            total_lines = len(lines)

            # ── 大文件防护（CC token gate 的简化版）──────────────────
            # 未指定 offset/limit 且文件过大 → 返回 Error + 预览
            # 这迫使模型用 offset/limit 重试，而非被大文件撑爆上下文
            if (offset is None and limit is None
                    and total_lines > self.MAX_LINES_WITHOUT_LIMIT):
                # 给模型前 N 行预览，帮助它决定需要读哪个范围
                preview = lines[:self.PREVIEW_LINES]
                width = len(str(total_lines))
                preview_text = "\n".join(
                    f"{i+1:>{width}} | {line.rstrip()}"
                    for i, line in enumerate(preview)
                )
                return (
                    f"Error: File too large ({total_lines} lines). "
                    f"Use Grep to search for specific patterns instead of reading the whole file. "
                    f"If you must read, specify offset and limit. "
                    f"Example: Grep(pattern=\"validate|reject|error\", path=\"{file_path}\") "
                    f"or Read(file_path=\"{file_path}\", offset=0, limit=100)\n\n"
                    f"Preview (first {self.PREVIEW_LINES} lines):\n{preview_text}"
                )

            # ── 分页切片 ──────────────────────────────────────────────
            # CC 不限制单次 Read 的行数——只在无 limit 时触发大文件门槛
            # 真正的上下文保护靠 microcompact（清除旧工具结果）
            start = offset if offset is not None else 0
            end = start + (limit if limit is not None else total_lines - start)

            # 边界保护：防止 offset 超出文件范围
            start = max(0, min(start, total_lines))
            end = max(start, min(end, total_lines))

            selected_lines = lines[start:end]

            # ── 添加行号 ─────────────────────────────────────────────
            # 行号宽度动态计算，保证对齐
            # 例如：100 行的文件用 3 位宽，1000 行用 4 位宽
            width = len(str(total_lines))
            numbered_lines = []
            for i, line in enumerate(selected_lines):
                line_num = start + i + 1  # 行号从 1 开始（符合编辑器惯例）
                # rstrip 去掉行尾换行符，避免输出中出现多余空行
                numbered_lines.append(f"{line_num:>{width}} | {line.rstrip()}")

            result = "\n".join(numbered_lines)

            # ── 附加元信息 ────────────────────────────────────────────
            # 告诉模型文件总行数和当前显示范围，帮助它决定是否需要继续读取
            if offset is not None or limit is not None:
                result += f"\n\n[Showing lines {start + 1}-{end} of {total_lines} total]"
            else:
                result += f"\n\n[{total_lines} lines total]"

            return result

        except Exception as e:
            return f"Error reading file: {str(e)}"


# ===========================================================================
# Write 工具 —— 文件写入（全量覆盖）
# ===========================================================================

class WriteTool(Tool):
    """
    将内容写入文件（创建新文件或覆盖已有文件）。

    使用场景：
    - 创建新文件（如生成测试文件、配置文件）
    - 完全重写小文件

    注意：对于修改已有文件的场景，应优先使用 Edit 工具而非 Write。
    原因：
    1. Edit 只发送 diff（节省上下文 tokens）
    2. Edit 有唯一性检查（防止误改）
    3. Write 会覆盖全文，如果模型遗漏了某些内容，会导致数据丢失

    安全设计：
    - 自动创建父目录（os.makedirs）—— 避免「目录不存在」的常见错误
    - 使用 UTF-8 编码 —— 覆盖绝大多数源代码文件
    """

    def __init__(self):
        super().__init__(
            name="Write",
            description=(
                "Write content to a file (creates or overwrites). "
                "Creates parent directories if they don't exist. "
                "For modifying existing files, prefer Edit tool instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        )

    def execute(self, file_path: str, content: str) -> str:
        """
        将内容写入文件。

        Args:
            file_path: 文件绝对路径
            content: 要写入的内容

        Returns:
            成功信息（含文件路径），或错误信息
        """
        try:
            # 自动创建父目录
            # exist_ok=True：目录已存在时不报错
            dir_path = os.path.dirname(file_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


# ===========================================================================
# Edit 工具 —— 精确替换（search/replace + 唯一性检查）
# ===========================================================================

class EditTool(Tool):
    """
    通过搜索替换精确修改文件内容。

    这是 Day 2 新增的核心工具，对应 SWE-agent 论文中的 edit 命令。
    与 Write 工具的全量覆盖不同，Edit 工具只修改文件中的特定片段。

    设计对标：Claude Code 的 Edit 工具
        Claude Code 的 Edit 工具使用 old_string / new_string 做精确替换，
        并要求 old_string 在文件中唯一出现。我们完全复刻这个设计。

    唯一性检查（Uniqueness Check）—— 为什么这很关键：
        如果 old_string 在文件中出现多次，替换哪一个？
        答案是：哪个都不替换，直接报错。

        这个设计看似严格，实则是防御性编程的典范：
        1. 防止「误伤」：模型想改第 50 行的 `return x`，但第 20 行也有 `return x`，
           如果不检查唯一性，可能把第 20 行也改了——bug 修复变成了 bug 引入
        2. 迫使模型提供足够上下文：当 old_string 不唯一时，模型需要扩大搜索范围，
           包含更多上下文行，直到 old_string 在文件中唯一——这反而提高了精确度
        3. 对齐 Claude Code：真实的 Claude Code 就是这么做的

    工作流程：
        1. 读取文件全文
        2. 检查 old_string 出现次数
           - 0 次：报错（目标文本不存在，可能是模型记错了）
           - 1 次：执行替换（精确命中）
           - 2+ 次：报错（不唯一，要求模型提供更多上下文）
        3. 执行替换并写回文件

    与 Write 的分工：
        - Edit：修改已有文件的局部内容（推荐用于所有修改场景）
        - Write：创建新文件或完全重写文件
    """

    def __init__(self):
        super().__init__(
            name="Edit",
            description=(
                "Edit a file by replacing an exact string match. "
                "The old_string must appear EXACTLY ONCE in the file. "
                "If it appears 0 times (not found) or 2+ times (ambiguous), "
                "the edit will fail. Include enough surrounding context in "
                "old_string to make it unique."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to edit"
                    },
                    "old_string": {
                        "type": "string",
                        "description": (
                            "The exact string to find and replace. "
                            "Must match exactly once in the file. "
                            "Include surrounding lines for uniqueness if needed."
                        )
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The string to replace old_string with"
                    }
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        )

    def execute(self, file_path: str, old_string: str, new_string: str) -> str:
        """
        执行精确搜索替换。

        执行流程：
        1. 验证文件存在
        2. 读取文件全文
        3. 计算 old_string 出现次数（唯一性检查）
        4. 执行替换并写回

        Args:
            file_path: 文件绝对路径
            old_string: 要替换的原始文本（必须在文件中恰好出现一次）
            new_string: 替换后的新文本

        Returns:
            成功信息（含替换预览），或错误信息（含具体原因）
        """
        try:
            # ── Step 1: 验证文件存在 ──────────────────────────────────
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"

            # ── Step 2: 读取文件全文 ──────────────────────────────────
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # ── Step 3: 唯一性检查 ────────────────────────────────────
            # 统计 old_string 在文件中的出现次数
            count = content.count(old_string)

            if count == 0:
                # old_string 不存在——可能是模型记错了内容，或者文件已被修改
                # 返回文件前 5 行作为提示，帮助模型重新定位
                preview_lines = content.split('\n')[:5]
                preview = '\n'.join(preview_lines)
                return (
                    f"Error: old_string not found in {file_path}. "
                    f"The string to replace does not exist in the file.\n"
                    f"File starts with:\n{preview}"
                )

            if count > 1:
                # old_string 出现多次——替换会有歧义
                # 告诉模型出现次数，提示它扩大 old_string 的范围
                return (
                    f"Error: old_string appears {count} times in {file_path}. "
                    f"It must appear exactly once. Include more surrounding "
                    f"context in old_string to make it unique."
                )

            # ── Step 4: 执行替换 ──────────────────────────────────────
            # count == 1，可以安全替换
            new_content = content.replace(old_string, new_string, 1)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # ── 构造成功信息 ──────────────────────────────────────────
            # 显示替换前后的摘要，方便审计
            old_preview = old_string[:60].replace('\n', '\\n')
            new_preview = new_string[:60].replace('\n', '\\n')
            return (
                f"Successfully edited {file_path}\n"
                f"Replaced: \"{old_preview}{'...' if len(old_string) > 60 else ''}\"\n"
                f"    With: \"{new_preview}{'...' if len(new_string) > 60 else ''}\""
            )

        except Exception as e:
            return f"Error editing file: {str(e)}"


# ===========================================================================
# Glob 工具 —— 文件模式匹配（对标 CC 的 GlobTool）
# ===========================================================================

class GlobTool(Tool):
    """
    通过 glob 模式查找文件（如 **/*.ts, src/**/test_*.py）。

    这是从 Bash("find ...") 升级为专用工具的关键改进（课程 §4.6 工具映射）：
    - SWE-agent 的 find_file → CC 的 Glob → MVP 的 Glob
    - 专用工具输出更紧凑（只返回文件路径），符合 ACI "紧凑输出"原则
    - 比 Bash find 更安全（不会执行任意命令）

    在 Localization 漏斗中的角色（Agentless 第一层）：
        Glob 是"文件级定位"的核心工具：
        Glob("**/*Edit*.ts") → 找到 FileEditTool 相关文件
        → Grep("validate", path=<file>) → 定位具体代码
        → Read(file, offset=N, limit=50) → 精读

    输出限制：最多返回 100 个文件路径（CC 同样限制 100）。
    """

    MAX_RESULTS = 100

    def __init__(self, working_dir: str = None):
        self.working_dir = working_dir or os.getcwd()
        super().__init__(
            name="Glob",
            description=(
                "Find files matching a glob pattern. "
                "Returns file paths sorted by modification time. "
                "Use patterns like '**/*.ts' to find all TypeScript files, "
                "or '**/FileEdit*' to find files by name. "
                "Max 100 results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Glob pattern to match files. "
                            "Examples: '**/*.py', 'src/**/*.ts', '**/test_*.py', '**/Edit*'"
                        )
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory to search in. Defaults to working directory if omitted."
                        )
                    }
                },
                "required": ["pattern"]
            }
        )

    def execute(self, pattern: str, path: str = None) -> str:
        """
        执行 glob 匹配，返回文件路径列表。

        使用 Python 的 glob.glob(recursive=True) 实现，
        支持 ** 跨目录匹配。

        Args:
            pattern: glob 模式（如 **/*.ts）
            path: 搜索目录，None 则用当前工作目录

        Returns:
            匹配的文件路径列表（每行一个），或错误信息
        """
        import glob as _glob

        try:
            search_dir = path or self.working_dir
            if not os.path.isdir(search_dir):
                return f"Error: Directory not found: {search_dir}"

            # 构造完整 glob 路径
            full_pattern = os.path.join(search_dir, pattern)
            matches = _glob.glob(full_pattern, recursive=True)

            # 只保留文件（排除目录）
            files = [f for f in matches if os.path.isfile(f)]

            # 按修改时间排序（最近修改的在前），对齐 CC 的行为
            files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

            total = len(files)
            truncated = total > self.MAX_RESULTS
            files = files[:self.MAX_RESULTS]

            if not files:
                return f"No files found matching pattern '{pattern}' in {search_dir}"

            result = "\n".join(files)
            if truncated:
                result += f"\n\n[Showing {self.MAX_RESULTS} of {total} matches]"

            return result

        except Exception as e:
            return f"Error: {str(e)}"


# ===========================================================================
# Grep 工具 —— 代码搜索（正则 + 递归 + 行数限制）
# ===========================================================================

class GrepTool(Tool):
    """
    在文件或目录中搜索匹配正则表达式的内容。

    这是 Day 2 新增的搜索工具，对应 SWE-agent 论文中的 search 命令，
    也是 Claude Code 工具集中的 Grep 工具的简化版。

    在 Bug 修复工作流中的定位（L-R-V 中的 L = Localization）：
        Agent 修复 bug 的第一步是「定位」——找到 bug 在哪个文件、哪一行。
        Grep 是定位阶段的核心工具：
        1. Grep("error_message", "/project/src") → 找到报错来源
        2. Read(file, offset=行号-5, limit=20) → 精读上下文
        3. Edit(file, old_string, new_string) → 修复

        这个 Grep → Read → Edit 的三步模式，是 SWE-bench 上表现最好的
        Agent 系统（如 SWE-agent、Agentless）共同使用的核心模式。

    ACI 信息粒度控制 —— head_limit 参数：
        为什么要限制输出行数？
        想象在一个 10 万行的项目中 grep "import"——可能返回 5000 行结果。
        这些结果塞入上下文后，模型的注意力会被淹没，后续推理质量暴跌。

        head_limit 的设计：
        - 默认 50 行：对大多数搜索场景足够
        - 模型可以调小（如 limit=10）获得更精确的结果
        - 超出 limit 时附加 "[N more matches not shown]" 提示，
          模型看到这个提示后可以缩小搜索范围重试

    输出格式设计：
        每行格式：文件路径:行号: 匹配内容
        这与 grep -rn 的输出格式一致，模型在训练数据中见过大量这种格式，
        能直接从输出中提取文件路径和行号用于后续的 Read/Edit 操作。

    搜索策略：
        - 如果 path 是文件 → 搜索该文件
        - 如果 path 是目录 → 递归搜索所有文本文件
        - 自动跳过：隐藏文件/目录（.git 等）、__pycache__、二进制文件
    """

    def __init__(self):
        super().__init__(
            name="Grep",
            description=(
                "Search for a pattern in files using regex. "
                "If path is a directory, searches recursively. "
                "Returns matching lines with file paths and line numbers. "
                "Use head_limit to control output size (default 50 lines)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "The regex pattern to search for. "
                            "Examples: 'def my_func', 'TODO|FIXME', 'import\\s+os'"
                        )
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "File or directory to search in. "
                            "If a directory, searches recursively."
                        )
                    },
                    "head_limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of matching lines to return. "
                            "Default is 50. Use smaller values for broad patterns."
                        )
                    }
                },
                "required": ["pattern", "path"]
            }
        )

    def execute(self, pattern: str, path: str, head_limit: int = 50) -> str:
        """
        执行正则搜索，返回匹配行。

        执行流程：
        1. 编译正则表达式（失败则报错）
        2. 确定搜索范围（单文件 or 递归目录）
        3. 逐文件逐行匹配
        4. 格式化输出（带路径和行号）
        5. 应用 head_limit 截断

        Args:
            pattern: 正则表达式模式
            path: 搜索路径（文件或目录）
            head_limit: 输出行数上限，默认 50

        Returns:
            匹配结果（文件路径:行号: 内容），或错误信息
        """
        if head_limit is not None:
            head_limit = int(head_limit)
        try:
            # ── Step 1: 编译正则 ──────────────────────────────────────
            try:
                regex = re.compile(pattern)
            except re.error as e:
                return f"Error: Invalid regex pattern '{pattern}': {e}"

            # ── Step 2: 确定搜索文件列表 ──────────────────────────────
            if not os.path.exists(path):
                return f"Error: Path not found: {path}"

            if os.path.isfile(path):
                # 单文件搜索
                files_to_search = [path]
            else:
                # 目录递归搜索
                files_to_search = self._collect_files(path)

            # ── Step 3: 逐文件搜索 ────────────────────────────────────
            matches = []        # 收集匹配结果
            total_matches = 0   # 总匹配数（含被 head_limit 截断的）

            for file_path in sorted(files_to_search):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                total_matches += 1
                                if len(matches) < head_limit:
                                    # 格式：文件路径:行号: 内容
                                    # 与 grep -rn 输出格式一致
                                    line_text = line.rstrip()
                                    matches.append(
                                        f"{file_path}:{line_num}: {line_text}"
                                    )
                except (IOError, UnicodeDecodeError):
                    # 跳过无法读取的文件（二进制文件、权限问题等）
                    continue

            # ── Step 4: 格式化输出 ────────────────────────────────────
            if not matches:
                return f"No matches found for pattern '{pattern}' in {path}"

            result = "\n".join(matches)

            # 如果还有更多匹配未显示，附加提示
            # 这个提示帮助模型意识到搜索结果不完整，可能需要缩小范围
            if total_matches > head_limit:
                result += (
                    f"\n\n[Showing {head_limit} of {total_matches} matches. "
                    f"Use a more specific pattern or smaller path to narrow results.]"
                )
            else:
                result += f"\n\n[{total_matches} matches found]"

            return result

        except Exception as e:
            return f"Error searching: {str(e)}"

    def _collect_files(self, directory: str) -> list:
        """
        递归收集目录下所有可搜索的文本文件。

        跳过规则（避免搜索噪音和性能问题）：
        - 隐藏目录（以 . 开头）：.git, .venv, .idea 等
        - __pycache__：Python 编译缓存，搜索它毫无意义
        - node_modules：JS 依赖目录，体积巨大且与用户代码无关
        - 隐藏文件（以 . 开头）：.gitignore, .env 等

        这些跳过规则是 ACI 设计的一部分——减少无关信息，
        让搜索结果更聚焦于用户的源代码。

        Args:
            directory: 要搜索的目录路径

        Returns:
            文件路径列表
        """
        files = []
        # 需要跳过的目录名集合
        skip_dirs = {
            '.git', '.svn', '.hg',          # 版本控制
            '__pycache__', '.pytest_cache',   # Python 缓存
            'node_modules', '.next',          # JS/Node 依赖
            '.venv', 'venv', 'env',           # Python 虚拟环境
            '.idea', '.vscode',               # IDE 配置
            'dist', 'build',                  # 构建产物
        }

        for root, dirs, filenames in os.walk(directory):
            # 原地修改 dirs 列表来控制 os.walk 的递归行为
            # 这是 os.walk 的标准用法：删除不想递归的子目录
            dirs[:] = [
                d for d in dirs
                if d not in skip_dirs and not d.startswith('.')
            ]

            for filename in sorted(filenames):
                # 跳过隐藏文件
                if filename.startswith('.'):
                    continue
                files.append(os.path.join(root, filename))

        return files


# ===========================================================================
# Bash 工具 —— 命令执行
# ===========================================================================

class BashTool(Tool):
    """
    在指定工作目录下执行 Bash 命令。

    这是 Agent 的「万能工具」——任何无法通过 Read/Write/Edit/Grep 完成的操作，
    都可以通过 Bash 命令实现（安装依赖、运行测试、查看进程、git 操作等）。

    在 Bug 修复工作流中的定位（L-R-V 中的 V = Validation）：
        修复 bug 后，Agent 需要验证修复是否有效。
        Bash("python test_file.py") 或 Bash("pytest") 就是验证的主要手段。
        如果测试失败，Agent 会分析错误输出，进入下一轮 L-R-V 循环。

    安全设计：
    - timeout=30s：防止命令无限挂起（如 while true 死循环）
    - 捕获 stdout 和 stderr：完整错误信息帮助 Agent 诊断问题
    - 返回退出码：非零退出码表示命令失败

    注意事项：
    - 命令通过 shell=True 执行，支持管道、重定向等 shell 特性
    - 每次调用是独立的子进程，不保留 shell 状态（cd 不会持续生效）
    - working_dir 参数确保命令在正确的目录下执行
    """

    def __init__(self, working_dir: str = None):
        super().__init__(
            name="Bash",
            description=(
                "Execute a bash command and return its output. "
                "Commands run in the working directory. "
                "Timeout: 30 seconds. Use for running tests, "
                "installing packages, git operations, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    }
                },
                "required": ["command"]
            }
        )
        self.working_dir = working_dir

    def execute(self, command: str) -> str:
        """
        执行 Bash 命令，返回输出。

        执行流程：
        1. 通过 subprocess.run 在子进程中执行命令
        2. 捕获 stdout 和 stderr
        3. 如果有 stderr 或非零退出码，附加到输出中

        Args:
            command: 要执行的 bash 命令

        Returns:
            命令输出（stdout + stderr），或错误信息
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.working_dir
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\nReturn code: {result.returncode}"
            return output if output else "Command executed successfully (no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {str(e)}"


# ===========================================================================
# 工具注册表
# ===========================================================================

def get_tools(working_dir: str = None) -> Dict[str, Tool]:
    """
    返回所有可用工具的字典。

    这是工具系统的「注册表」——客户端通过此函数获取全部工具。
    返回的字典以工具名为 key，工具对象为 value。

    工具注册后，会被两个地方使用：
    1. client.py 的 get_tool_definitions() → 转为 Claude API 格式发送给模型
    2. client.py 的 _execute_tool() → 根据模型返回的工具名查找并执行

    Args:
        working_dir: 工作目录，Bash 工具在此目录下执行命令

    Returns:
        {工具名: 工具对象} 字典
    """
    return {
        "Read": ReadTool(),
        "Write": WriteTool(),
        "Edit": EditTool(),
        "Glob": GlobTool(working_dir=working_dir),
        "Grep": GrepTool(),
        "Bash": BashTool(working_dir=working_dir),
    }
