"""
Tool call parser —— 从模型原始输出中提取工具调用

本模块从 Qwen 模型的原始文本输出中解析工具调用请求。
这是适配层的底层组件，由 adapter.py 的 qwen_response_to_claude() 调用。

支持两种 JSON 格式（兼容 MVP v1 自定义格式和 Qwen 原生格式）：
- MVP v1 格式：  {"tool": "Read", "parameters": {"file_path": "..."}}
- Qwen 原生格式：{"name": "Read", "arguments": {"file_path": "..."}}

支持三种包裹格式（按优先级尝试）：
1. XML 标签：<tool_call>...</tool_call>（Qwen 原生格式，最可靠）
2. 代码块：  ```json\n...\n```（小模型常见的替代格式）
3. 裸 JSON： {..."name"...}（最后的 fallback，用花括号配对提取）

同时处理小模型常见的 JSON 畸变：
- Python 三引号字符串（\"\"\"...\"\"\") → 转为 \\n 分隔的单行字符串
- 尾部多余逗号（{..., }）→ 删除
- 缺失或多余的转义
"""

import json
import re
from typing import List, Dict, Any, Optional
from trajectory import trace


class ToolCall:
    """
    表示一个解析出的工具调用。

    统一使用 tool_name / parameters 作为内部字段名，
    无论原始格式是 "tool"/"parameters" 还是 "name"/"arguments"。
    """
    def __init__(self, tool_name: str, parameters: Dict[str, Any]):
        self.tool_name = tool_name
        self.parameters = parameters

    def __repr__(self):
        return f"ToolCall(tool_name={self.tool_name}, parameters={self.parameters})"


def _strip_line_comments(text: str) -> str:
    """
    去除 JS 风格的单行注释（// ...），但保留 JSON 字符串内的 //。

    7B 模型有时在生成 JSON 时混入 JS 注释，例如：
        {"file_path": "/tmp/a.py",  // target file
         "old_string": "x = 1"}

    策略：逐行扫描，追踪引号状态，只删除字符串外的 // 注释。

    注意：JSON 字符串中的 URL（如 "https://..."）不会被误删，
    因为 // 在引号内时 in_string=True，会被跳过。
    """
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        in_string = False
        i = 0
        result_line = line
        while i < len(line):
            c = line[i]
            if c == '\\' and in_string:
                i += 2  # 跳过转义字符
                continue
            if c == '"':
                in_string = not in_string
            elif c == '/' and not in_string and i + 1 < len(line) and line[i + 1] == '/':
                result_line = line[:i].rstrip()
                break
            i += 1
        cleaned.append(result_line)
    return '\n'.join(cleaned)


def _sanitize_json(text: str) -> str:
    """
    修复小模型常见的 JSON 畸变。

    问题背景：7B 模型在生成 JSON 时经常产生格式错误，
    因为 JSON 的严格语法（每个引号、逗号都必须精确）
    与模型的概率生成机制天然冲突。

    处理的畸变类型：
    0a. JS 单行注释：// comment → 删除（字符串内的 // 保留）
    0b. JS 块注释：/* comment */ → 删除
    1. Python 三引号字符串：模型生成了 Python 风格而非 JSON 风格的多行字符串
    2. 尾部逗号：{"key": "value",} → JSON 不允许但 Python/JS 允许
    """
    result = text

    # Fix 0a: 去除 JS 单行注释（// ...），保留字符串内的
    result = _strip_line_comments(result)

    # Fix 0b: 去除 JS 块注释（/* ... */）
    # JSON 中 /* 和 */ 不可能合法出现在字符串外，安全删除
    result = re.sub(r'/\*.*?\*/', '', result, flags=re.DOTALL)

    # Fix 1: 将 Python 三引号字符串转为 JSON 字符串
    # 例如 """line1\nline2""" → "line1\\nline2"
    triple_quote_pattern = r'"""(.*?)"""'
    def replace_triple_quote(m):
        content = m.group(1)
        content = content.replace('\\', '\\\\')
        content = content.replace('"', '\\"')
        content = content.replace('\n', '\\n')
        content = content.replace('\t', '\\t')
        return '"' + content + '"'
    result = re.sub(triple_quote_pattern, replace_triple_quote, result, flags=re.DOTALL)

    # Fix 2: 删除 } 或 ] 前的尾部逗号
    result = re.sub(r',\s*([}\]])', r'\1', result)

    if result != text:
        trace("_sanitize_json applied fixes",
              original_len=len(text), result_len=len(result))

    return result


def _try_parse_json(text: str) -> Optional[dict]:
    """
    尝试解析 JSON，失败后用 _sanitize_json 修复再试。

    两步策略：先原样解析（快），失败再修复后解析（兜底）。
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        sanitized = _sanitize_json(text)
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass
    return None


def _extract_tool_call(data: dict) -> Optional[ToolCall]:
    """
    从解析后的 JSON 字典中提取 ToolCall，兼容两种格式。

    格式一（MVP v1 自定义格式）：
        {"tool": "Read", "parameters": {"file_path": "..."}}

    格式二（Qwen/OpenAI 原生格式）：
        {"name": "Read", "arguments": {"file_path": "..."}}

    无论输入是哪种格式，输出统一为 ToolCall(tool_name=..., parameters=...)。

    Args:
        data: JSON 解析后的字典

    Returns:
        ToolCall 对象，或 None（如果不是有效的工具调用）
    """
    if not isinstance(data, dict):
        return None

    # 尝试格式一："tool" + "parameters"
    tool_name = data.get("tool")
    if tool_name:
        parameters = data.get("parameters", {})
        return ToolCall(tool_name, parameters)

    # 尝试格式二："name" + "arguments"（Qwen 原生格式）
    tool_name = data.get("name")
    if tool_name:
        parameters = data.get("arguments", {})
        # arguments 可能是字符串（小模型偶尔输出 JSON 字符串而非对象）
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except json.JSONDecodeError:
                parameters = {}
        return ToolCall(tool_name, parameters)

    return None


def parse_tool_calls(text: str) -> List[ToolCall]:
    """
    从模型原始输出中解析工具调用。

    三策略解析（按优先级）：

    策略一：XML 标签（最可靠）
        <tool_call>{"name": "Read", "arguments": {...}}</tool_call>
        这是 Qwen 原生格式的主路径。<tool_call> 和 </tool_call>
        是 Qwen 词表中的专用 token（id 151657/151658），
        模型在训练时见过大量这种格式，输出最稳定。

    策略二：代码块（fallback）
        ```json\n{"name": "Read", "arguments": {...}}\n```
        小模型有时会用 markdown 代码块包裹工具调用，
        特别是在 system prompt 的 few-shot 示例使用了代码块格式时。

    策略三：裸 JSON（最后手段）
        {"name": "Read", "arguments": {...}}
        通过花括号深度配对提取 JSON 对象。
        这是最宽容的策略，但也最容易误匹配，所以放在最后。

    Args:
        text: 模型的原始文本输出

    Returns:
        解析出的 ToolCall 列表（可能为空）
    """
    tool_calls = []
    strategy_used = None

    # ── 策略一：XML 标签 ─────────────────────────────────────────
    # 标准格式：<tool_call>...</tool_call>
    pattern = r'<tool_call>(.*?)</tool_call>'
    matches = re.findall(pattern, text, re.DOTALL)

    # 变体：缺少开标签的孤立闭标签（小模型偶尔的格式残缺）
    # 匹配 "name" 或 "tool" 以兼容两种 JSON 格式
    if not matches:
        orphan_pattern = r'(\{[^<]*?(?:"tool"|"name")[^<]*?\})\s*</tool_call>'
        matches = re.findall(orphan_pattern, text, re.DOTALL)

    # 变体：Qwen3 格式的孤立闭标签（缺少 <tool_call> 开标签）
    # 匹配 <function=ToolName>...</function></tool_call>
    if not matches:
        orphan_qwen3_pattern = r'(<function=\w+>.*?</function>)\s*</tool_call>'
        matches = re.findall(orphan_qwen3_pattern, text, re.DOTALL)

    # 变体：Qwen3 格式完全没有 <tool_call> 包裹
    # 匹配独立的 <function=ToolName>...</function>
    if not matches:
        bare_qwen3_pattern = r'(<function=\w+>.*?</function>)'
        matches = re.findall(bare_qwen3_pattern, text, re.DOTALL)

    for match in matches:
        # Qwen3 format: <function=ToolName><parameter=key>value</parameter>...</function>
        func_m = re.search(r'<function=(\w+)>', match)
        if func_m:
            fname = func_m.group(1)
            params = {}
            for pm in re.finditer(r'<parameter=(\w+)>\s*(.*?)\s*</parameter>', match, re.DOTALL):
                params[pm.group(1)] = pm.group(2)
            if fname:
                tool_calls.append(ToolCall(fname, params))
                continue
        # Qwen2.5 format: JSON inside <tool_call> tags
        data = _try_parse_json(match)
        if data:
            tc = _extract_tool_call(data)
            if tc:
                tool_calls.append(tc)

    if tool_calls:
        strategy_used = "XML"

    # ── 策略二：代码块 ───────────────────────────────────────────
    # \w+ 匹配任意语言标识符（json/python/bash/javascript/text 等）
    if not tool_calls:
        code_block_pattern = r'```(?:\w+)?\s*\n(.*?)\n```'
        code_matches = re.findall(code_block_pattern, text, re.DOTALL)
        for match in code_matches:
            data = _try_parse_json(match)
            if data:
                if isinstance(data, dict):
                    tc = _extract_tool_call(data)
                    if tc:
                        tool_calls.append(tc)
                elif isinstance(data, list):
                    for item in data:
                        tc = _extract_tool_call(item)
                        if tc:
                            tool_calls.append(tc)

        if tool_calls:
            strategy_used = "code_block"

    # ── 策略三：裸 JSON（花括号配对）─────────────────────────────
    if not tool_calls:
        for m in re.finditer(r'\{', text):
            start = m.start()
            depth = 0
            end = start
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if depth == 0 and end > start:
                candidate = text[start:end]
                data = _try_parse_json(candidate)
                if data:
                    tc = _extract_tool_call(data)
                    if tc:
                        tool_calls.append(tc)

        if tool_calls:
            strategy_used = "bare_JSON"

    # ── 策略四：函数调用语法 ToolName("arg") ──────────────────────
    # 小模型有时输出 Python 函数调用风格而非 JSON：
    #   Bash("rm /tmp/hello.py")
    #   Read("/path/to/file.py")
    # 需要将位置参数映射到工具的第一个必需参数名
    if not tool_calls:
        # 已知工具名 → 第一个参数名的映射
        _primary_param = {
            "Read": "file_path", "Write": "file_path", "Edit": "file_path",
            "Grep": "pattern", "Bash": "command", "Agent": "prompt",
            "TaskCreate": "subject", "TaskUpdate": "task_id", "TaskList": None,
        }
        # 匹配 ToolName("...") 或 ToolName({...})
        func_pattern = r'\b(' + '|'.join(_primary_param.keys()) + r')\s*\(\s*(".*?"|\{.*?\})\s*\)'
        for m in re.finditer(func_pattern, text, re.DOTALL):
            fname, raw_arg = m.group(1), m.group(2)
            param_name = _primary_param.get(fname)
            if not param_name:
                continue
            # 尝试解析参数
            if raw_arg.startswith('{'):
                data = _try_parse_json(raw_arg)
                if data and isinstance(data, dict):
                    tool_calls.append(ToolCall(fname, data))
            elif raw_arg.startswith('"'):
                # 去引号，得到字符串值
                try:
                    arg_value = json.loads(raw_arg)
                except json.JSONDecodeError:
                    arg_value = raw_arg.strip('"')
                tool_calls.append(ToolCall(fname, {param_name: arg_value}))

        if tool_calls:
            strategy_used = "func_call"

    # ── 轨迹日志 ─────────────────────────────────────────────────
    trace("parse_tool_calls",
          strategy=strategy_used or "none",
          count=len(tool_calls),
          tools=", ".join(tc.tool_name for tc in tool_calls) if tool_calls else "none",
          input_len=len(text))

    return tool_calls


def extract_text_and_tool_calls(text: str) -> tuple[str, List[ToolCall]]:
    """
    从模型输出中同时提取文本和工具调用。

    这是 v1 客户端使用的接口（客户端直接解析原始文本）。
    v2 架构中，这个函数被 adapter.py 的 qwen_response_to_claude() 替代，
    但保留用于向后兼容和测试。

    Returns:
        (去掉工具调用标记的纯文本, 工具调用列表)
    """
    tool_calls = parse_tool_calls(text)

    # 清除 XML 标签
    clean_text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    clean_text = re.sub(
        r'\{[^<]*?(?:"tool"|"name")[^<]*?\}\s*</tool_call>',
        '', clean_text, flags=re.DOTALL
    )

    # 清除包含工具调用的代码块
    def should_remove_block(match):
        content = match.group(1)
        data = _try_parse_json(content)
        return data is not None and isinstance(data, dict) and ("tool" in data or "name" in data)

    code_blocks = list(re.finditer(
        r'```(?:\w+)?\s*\n(.*?)\n```', clean_text, re.DOTALL
    ))
    for match in reversed(code_blocks):
        if should_remove_block(match):
            clean_text = clean_text[:match.start()] + clean_text[match.end():]

    clean_text = clean_text.strip()
    return clean_text, tool_calls
