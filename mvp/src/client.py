"""
Agent 客户端 —— 说 Claude tool_use 协议

本模块实现了一个编程 Agent 的核心循环（ReAct loop），
客户端侧完全使用 Claude tool_use 协议——与 Claude Code 的真实架构对齐。

架构定位：
    本客户端只负责三件事：
    1. 构造请求（tools 定义 + 对话消息，Claude 格式）
    2. 处理响应（检测 tool_use blocks → 执行工具 → 回传 tool_result）
    3. 管理对话上下文（conversation history）

    所有格式转换（Claude ↔ Qwen）都在 model_server 的适配层完成。
    客户端不需要做任何文本解析——拿到的就是结构化的 content blocks。

    这与 Claude Code 的真实架构一致：
    Claude Code 客户端 → Anthropic API（返回 content blocks）→ 客户端处理
    MVP 客户端        → Model Server（适配层返回 content blocks）→ 客户端处理

ReAct 循环：
    用户输入 → [Thought → Action → Observation] × N → 最终回答

    其中：
    - Thought：模型的推理文本（text content block）
    - Action：模型请求调用工具（tool_use content block）
    - Observation：工具执行结果（tool_result content block）

    stop_reason 决定是否继续循环：
    - "tool_use"：模型想调用工具 → 执行工具 → 回传结果 → 继续循环
    - "end_turn"：模型认为任务完成 → 退出循环 → 返回最终回答
"""

import os
import json
import requests
from typing import List, Dict, Any, Optional
from tools import get_tools


# ---------------------------------------------------------------------------
# 工具定义：Claude 格式
# ---------------------------------------------------------------------------

def get_tool_definitions(tools: Dict) -> List[Dict[str, Any]]:
    """
    将内部工具对象转为 Claude API 格式的工具定义。

    Claude 格式的工具定义结构：
    {
        "name": "Read",
        "description": "Read the contents of a file",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string", ...}},
            "required": ["file_path"]
        }
    }

    这些定义会随每次请求发送给 model_server，
    由适配层转为 Qwen 的 function definition 格式后注入 chat template。

    Args:
        tools: get_tools() 返回的工具字典

    Returns:
        Claude 格式的工具定义列表
    """
    definitions = []
    for tool_name, tool in tools.items():
        definitions.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters
        })
    return definitions


# ---------------------------------------------------------------------------
# 客户端主类
# ---------------------------------------------------------------------------

class Client:
    """
    Agent 客户端：管理对话上下文，驱动 ReAct 循环。

    核心设计：
    - 对话历史（self.conversation）存储 Claude 格式的消息（含 content blocks）
    - 每轮请求携带完整对话历史 + 工具定义发送给 model_server
    - model_server 返回结构化响应（content blocks），客户端直接处理
    - 客户端不做任何文本解析，所有格式转换在 model_server 适配层完成
    """

    def __init__(self, server_url: str = "http://localhost:9981", working_dir: str = None):
        """
        初始化客户端。

        Args:
            server_url: model_server 的地址
            working_dir: 工作目录，Agent 将在此目录中操作文件
        """
        self.server_url = server_url.rstrip("/")
        self.tools = get_tools(working_dir=working_dir)
        self.tool_definitions = get_tool_definitions(self.tools)
        self.conversation: List[Dict[str, Any]] = []
        self.working_dir = working_dir or os.getcwd()

        # 扫描工作目录的文件树，嵌入 system prompt
        # 这是 ACI 设计的一部分：给模型一个项目全景，帮助它定位文件
        # 50 行上限是信息粒度控制——防止大项目的文件树撑爆上下文
        self._file_tree = self._scan_files()

        # 健康检查：确认 model_server 已启动
        try:
            resp = requests.get(f"{self.server_url}/health", timeout=3)
            resp.raise_for_status()
            print(f"Connected to model server at {self.server_url}")
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to model server at {self.server_url}\n"
                f"Start it first: python model_server.py <model_path>"
            )

    def _scan_files(self) -> str:
        """
        扫描工作目录，生成文件树快照。

        限制 50 行是有意为之的 ACI 设计决策（课程 2.2 节内容）：
        - 给模型"刚好够定位"的信息量（粗粒度全景）
        - 模型需要精读时再用 Read 工具按需获取（细粒度局部）
        - 防止大项目的文件列表挤占有限的上下文窗口
        """
        lines = []
        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            depth = root.replace(self.working_dir, '').count(os.sep)
            indent = '  ' * depth
            basename = os.path.basename(root) or '.'
            lines.append(f"{indent}{basename}/")
            for f in sorted(files):
                if not f.startswith('.'):
                    lines.append(f"{indent}  {f}")
        return '\n'.join(lines[:50])

    def get_system_prompt(self) -> str:
        """
        生成系统提示词。

        与 v1 的关键区别：
        - 不再包含工具定义（工具定义通过 tools 参数传递，由 chat template 注入）
        - 不再包含格式说明（模型使用其训练时的原生 <tool_call> 格式）
        - 只保留行为指令：做什么（主动探索）、怎么做（先读后改）、不做什么（别猜路径）

        这使得 system prompt 更短、更聚焦，也更符合 SWE-agent 论文的 ACI 设计理念：
        system prompt 负责行为引导，工具接口负责能力定义，两者分离。
        """
        return f"""You are a coding agent that helps users with software engineering tasks.
You work inside a codebase and use tools to read, write, and execute code.

Working directory: {self.working_dir}

Files in this project:
{self._file_tree}

IMPORTANT RULES:
1. ALWAYS use tools to act. Use Read to examine files, Write to create/modify them, Bash to run commands.
2. NEVER ask the user to paste code or upload files. You can access the filesystem directly.
3. Use the file tree above to locate files. Construct absolute paths as: {self.working_dir}/<relative_path>.
4. If the user gives a partial filename like "buggy_code", match it to the closest file in the tree.
5. When fixing bugs: first Read the file to understand the code, then Write the fix, then Bash to verify.
6. Keep your text responses short and focused on what you found or did."""

    def run(self, user_input: str) -> Optional[str]:
        """
        处理用户输入，驱动 ReAct 循环直至任务完成。

        这是 Agent 的核心循环，对应课程模块一的 TAO（Thought-Action-Observation）：

        循环流程：
        1. 将用户输入加入对话历史
        2. 发送请求（tools + system prompt + 对话历史）给 model_server
        3. 接收 Claude 格式的结构化响应
        4. 检查 stop_reason：
           - "tool_use"：提取 tool_use blocks → 执行工具 → 构造 tool_result → 继续循环
           - "end_turn"：任务完成，退出循环

        防死循环机制（Circuit Breaker）：
        max_rounds 限制最大循环次数。对应课程中"OODA 循环卡死"的工程兜底——
        当模型的 Orient 环节失灵（无法从重复的 Observation 中提取新信息）时，
        强制终止循环，避免无限消耗 token。

        Args:
            user_input: 用户的自然语言指令

        Returns:
            None（所有输出已通过 print 实时展示）
        """
        self.conversation.append({"role": "user", "content": user_input})

        # Circuit Breaker：最大循环轮数
        # 5 轮足够覆盖 Read → 分析 → Write fix → Bash verify → 收尾
        # 超过 5 轮通常意味着模型陷入了死循环
        max_rounds = 5
        round_num = 0

        while round_num < max_rounds:
            round_num += 1

            # 构造请求：system prompt + tools + 对话历史
            # system prompt 作为对话的第一条消息
            messages = [{"role": "system", "content": self.get_system_prompt()}]
            messages.extend(self.conversation)

            # ── 发送请求，接收流式响应 ────────────────────────────
            print("\n🤖 ", end="", flush=True)
            response = self._generate(messages)

            if response is None:
                print("\n  ⚠️ No response from server.", flush=True)
                return None

            # ── 将 assistant 响应加入对话历史 ─────────────────────
            # 存储完整的 content blocks，保持对话历史的结构化
            self.conversation.append(response)

            # ── 检查是否需要执行工具 ──────────────────────────────
            if response.get("stop_reason") != "tool_use":
                # 模型认为任务完成（stop_reason: "end_turn"）
                # 打印最终文本响应
                return None

            # ── 执行工具调用 ──────────────────────────────────────
            # 提取所有 tool_use blocks，逐个执行
            tool_results = []
            for block in response.get("content", []):
                if block.get("type") != "tool_use":
                    continue

                tool_name = block["name"]
                tool_input = block["input"]
                tool_use_id = block["id"]

                print(f"\n  🔧 Executing {tool_name}...", flush=True)
                result = self._execute_tool(tool_name, tool_input)

                # 判断执行是否出错
                is_error = result.startswith("Error")
                if is_error:
                    print(f"  ❌ {result}", flush=True)
                else:
                    preview = result[:80].replace('\n', ' ')
                    print(f"  ✅ {preview}{'...' if len(result) > 80 else ''}", flush=True)

                # 构造 tool_result block
                # tool_use_id 关联确保多工具并发时结果不会错配
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                    "is_error": is_error
                })

            # 将所有 tool_result 作为一条 user 消息回传
            # Claude API 的约定：tool_result 放在 user role 的 content blocks 中
            self.conversation.append({
                "role": "user",
                "content": tool_results
            })

        print("\n  ⚠️ Reached maximum rounds. Stopping.", flush=True)
        return None

    def _generate(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        调用 model_server 进行推理，实时打印 token 流，返回结构化响应。

        通信协议（SSE）：
        - 推理中：收到 {"token": "Let"} → 直接打印到终端
        - 结束时：收到 {"done": true, "response": {...}} → 返回 Claude 格式响应

        实时打印 token 是 Live Demo 的关键视觉效果——
        观众能看到模型"逐字思考"的过程，而不是等几秒后突然蹦出一大段文字。

        Args:
            messages: 完整的对话消息列表（含 system prompt）

        Returns:
            Claude 格式的结构化响应字典，或 None（请求失败时）
        """
        try:
            resp = requests.post(
                f"{self.server_url}/generate",
                json={
                    "tools": self.tool_definitions,
                    "messages": messages,
                },
                stream=True,
                timeout=300
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"\n  ❌ Request failed: {e}", flush=True)
            return None

        claude_response = None

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            data = json.loads(line[6:])  # 去掉 "data: " 前缀

            if "token" in data:
                # 实时打印 token（流式输出的视觉效果）
                print(data["token"], end="", flush=True)

            elif data.get("done"):
                # 推理结束，获取结构化响应
                # 这是适配层的输出：Qwen 原始文本已被解析为 Claude content blocks
                claude_response = data.get("response")

        return claude_response

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        """
        执行单个工具调用。

        Args:
            tool_name: 工具名（Read / Write / Bash）
            parameters: 工具参数字典

        Returns:
            执行结果文本（成功或错误信息）
        """
        if tool_name not in self.tools:
            return f"Error: Unknown tool '{tool_name}'"

        tool = self.tools[tool_name]
        try:
            return tool.execute(**parameters)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    def reset(self):
        """重置对话历史，开始新的会话。"""
        self.conversation = []
