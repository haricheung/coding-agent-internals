"""
Claude ↔ Qwen 协议适配层

本模块实现 Claude tool_use 协议与 Qwen 原生 chat template 格式之间的双向转换。

架构定位：
    Client (说 Claude 协议)  ←→  Adapter (本模块)  ←→  Qwen 模型 (说原生格式)

设计意图：
    Claude Code 的工具调用是 API 层结构化协议——客户端发送/接收的是带类型的
    content blocks（tool_use, tool_result），而非原始文本。我们在 model_server
    中嵌入这个适配层，让客户端代码直接映射 Claude Code 的真实架构，同时底层
    Qwen 模型使用其训练时的原生格式（<tool_call> XML 标签），最大化推理可靠性。

    这个适配层做的事情，本质上就是 Anthropic API 基础设施在做的事——
    把模型的原始文本输出结构化为 typed content blocks。区别是：
    Anthropic 用前沿模型 + 约束解码做确定性保证；
    我们用本地模型 + 鲁棒解析做概率性兜底。

协议格式对比：

    Claude tool_use 格式（客户端侧）：
    ┌─────────────────────────────────────────────┐
    │ tools: [                                     │
    │   {"name": "Read",                           │
    │    "description": "...",                     │
    │    "input_schema": {"type":"object",...}}     │
    │ ]                                            │
    │ messages: [                                   │
    │   {"role":"assistant", "content": [           │
    │     {"type":"text", "text":"..."},            │
    │     {"type":"tool_use", "id":"toolu_xxx",    │
    │      "name":"Read", "input":{...}}           │
    │   ]},                                        │
    │   {"role":"user", "content": [               │
    │     {"type":"tool_result",                   │
    │      "tool_use_id":"toolu_xxx",              │
    │      "content":"..."}                        │
    │   ]}                                         │
    │ ]                                            │
    └─────────────────────────────────────────────┘

    Qwen 原生格式（模型侧）：
    ┌─────────────────────────────────────────────┐
    │ <|im_start|>system                           │
    │ ...                                          │
    │ # Tools                                      │
    │ <tools>                                      │
    │ {"type":"function","function":{...}}          │
    │ </tools>                                     │
    │ <|im_end|>                                   │
    │                                              │
    │ <|im_start|>assistant                        │
    │ Let me read it.                              │
    │ <tool_call>                                  │
    │ {"name":"Read","arguments":{...}}            │
    │ </tool_call>                                 │
    │ <|im_end|>                                   │
    │                                              │
    │ <|im_start|>user                             │
    │ <tool_response>                              │
    │ file contents...                             │
    │ </tool_response>                             │
    │ <|im_end|>                                   │
    └─────────────────────────────────────────────┘
"""

import uuid
import re
import json
from typing import List, Dict, Any, Optional
from parser import parse_tool_calls, _try_parse_json, _extract_tool_call
from trajectory import trace


# ---------------------------------------------------------------------------
# 入口转换：Claude → Qwen
# ---------------------------------------------------------------------------

def claude_tools_to_qwen(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Claude 格式的工具定义转换为 Qwen/OpenAI 格式。

    Claude 格式（input_schema）:
        {"name": "Read", "description": "...", "input_schema": {"type": "object", ...}}

    Qwen/OpenAI 格式（parameters）:
        {"type": "function", "function": {"name": "Read", "description": "...",
         "parameters": {"type": "object", ...}}}

    两者的核心差异：
    - Claude 用 "input_schema" 描述参数，Qwen/OpenAI 用 "parameters"
    - Qwen/OpenAI 多一层 {"type": "function", "function": {...}} 的包裹

    Args:
        tools: Claude 格式的工具定义列表

    Returns:
        Qwen/OpenAI 格式的工具定义列表，可直接传给 apply_chat_template(tools=...)
    """
    qwen_tools = []
    for tool in tools:
        qwen_tool = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {})
            }
        }
        qwen_tools.append(qwen_tool)
    return qwen_tools


def claude_messages_to_qwen(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Claude 格式的对话消息转换为 Qwen chat template 格式。

    核心转换规则：
    1. 纯文本消息（content 是 string）→ 直接传递，无需转换
    2. content blocks 中的 tool_use → Qwen 的 assistant message + tool_calls 字段
    3. content blocks 中的 tool_result → Qwen 的 tool role message + tool_response 标签

    Claude 的 tool_use_id 机制：
        Claude 用唯一 id 关联 tool_use 和 tool_result，支持并发多工具调用。
        Qwen 的 chat template 没有显式 id 关联（靠位置顺序匹配），
        所以转换时 id 信息会丢失——这是文本层协议相比 API 层协议的固有局限。

    Args:
        messages: Claude 格式的消息列表（可能包含 content blocks）

    Returns:
        Qwen chat template 兼容的消息列表
    """
    qwen_messages = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        # Case 1: 纯文本消息（最常见的情况：用户输入、系统消息）
        if isinstance(content, str):
            qwen_messages.append({"role": role, "content": content})
            continue

        # Case 2: content 是 block 列表（Claude 格式的结构化消息）
        if isinstance(content, list):
            # 分离文本块、tool_use 块、tool_result 块
            text_parts = []
            tool_uses = []
            tool_results = []

            for block in content:
                block_type = block.get("type", "")
                if block_type == "text":
                    text_parts.append(block["text"])
                elif block_type == "tool_use":
                    tool_uses.append(block)
                elif block_type == "tool_result":
                    tool_results.append(block)

            # Case 2a: assistant 消息包含 tool_use
            # → 转为 Qwen 的 assistant message + tool_calls 结构
            if role == "assistant" and tool_uses:
                assistant_msg = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else "",
                    "tool_calls": []
                }
                for tu in tool_uses:
                    assistant_msg["tool_calls"].append({
                        "function": {
                            "name": tu["name"],
                            "arguments": tu["input"]
                        }
                    })
                qwen_messages.append(assistant_msg)

            # Case 2b: user 消息包含 tool_result
            # → 转为 Qwen 的 tool role messages（每个 result 一条）
            # 如果同时有 text blocks（如意图提醒），追加为 user message
            elif tool_results:
                for tr in tool_results:
                    # Qwen chat template 会把 tool role 的消息
                    # 包裹在 <tool_response></tool_response> 标签中
                    result_content = tr.get("content", "")
                    # 如果 content 是列表（Claude 支持多种内容类型），提取文本
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            item.get("text", str(item))
                            for item in result_content
                        )
                    qwen_messages.append({
                        "role": "tool",
                        "content": result_content
                    })
                # 如果同时有文本块（如用户意图提醒），作为 user 消息追加
                if text_parts:
                    qwen_messages.append({
                        "role": "user",
                        "content": "\n".join(text_parts)
                    })

            # Case 2c: 纯文本 content blocks（没有 tool_use 也没有 tool_result）
            else:
                combined_text = "\n".join(text_parts)
                qwen_messages.append({"role": role, "content": combined_text})

    return qwen_messages


def claude_messages_to_openai(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Claude 格式的对话消息转换为 OpenAI API 格式。

    与 claude_messages_to_qwen() 的核心差异：
    - OpenAI tool_calls 需要 id 和 type 字段（Qwen chat template 不需要）
    - OpenAI tool_calls 的 arguments 是 JSON 字符串，不是对象
    - OpenAI tool 消息需要 tool_call_id 字段关联工具调用

    用于 vLLM serve 的 OpenAI 兼容 API（/v1/chat/completions）。
    """
    openai_messages = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        # 纯文本消息
        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            text_parts = []
            tool_uses = []
            tool_results = []

            for block in content:
                block_type = block.get("type", "")
                if block_type == "text":
                    text_parts.append(block["text"])
                elif block_type == "tool_use":
                    tool_uses.append(block)
                elif block_type == "tool_result":
                    tool_results.append(block)

            # assistant + tool_use → OpenAI assistant with tool_calls
            if role == "assistant" and tool_uses:
                assistant_msg = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else None,
                    "tool_calls": []
                }
                for tu in tool_uses:
                    args = tu["input"]
                    if isinstance(args, dict):
                        args = json.dumps(args, ensure_ascii=False)
                    assistant_msg["tool_calls"].append({
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": args
                        }
                    })
                openai_messages.append(assistant_msg)

            # tool_result → OpenAI tool messages (each with tool_call_id)
            elif tool_results:
                for tr in tool_results:
                    result_content = tr.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            item.get("text", str(item))
                            for item in result_content
                        )
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": result_content
                    })
                if text_parts:
                    openai_messages.append({
                        "role": "user",
                        "content": "\n".join(text_parts)
                    })

            # 纯文本 blocks
            else:
                combined_text = "\n".join(text_parts)
                openai_messages.append({"role": role, "content": combined_text})

    return openai_messages


# ---------------------------------------------------------------------------
# 出口转换：Qwen → Claude
# ---------------------------------------------------------------------------

def _generate_tool_use_id() -> str:
    """
    生成 Claude 风格的 tool_use_id。

    Claude API 的 tool_use_id 格式为 "toolu_" + 随机字符串，
    用于在 tool_use 和 tool_result 之间建立精确关联。
    """
    return f"toolu_{uuid.uuid4().hex[:24]}"


def qwen_response_to_claude(raw_text: str) -> Dict[str, Any]:
    """
    将 Qwen 模型的原始文本输出转换为 Claude 格式的结构化响应。

    这是适配层最核心的函数——它做的事情本质上就是 Anthropic API 基础设施
    在做的：把模型的原始文本输出解析、验证、结构化为 typed content blocks。

    区别在于：
    - Anthropic 有前沿模型（几乎不出格式错）+ 约束解码（确定性保证）
    - 我们有本地模型（可能出格式错）+ parser.py 的鲁棒解析（概率性兜底）

    转换规则：
    - 原始文本中的 <tool_call> 块 → {"type": "tool_use", "id": ..., "name": ..., "input": ...}
    - <tool_call> 之外的文本 → {"type": "text", "text": ...}
    - 如果包含 tool_use → stop_reason = "tool_use"
    - 如果不包含 → stop_reason = "end_turn"

    文本提取策略（v2 重构）：
    - 从原始文本中剥离所有已识别的工具调用模式（XML 标签、代码块）
    - 剩余的文本即为 text content block
    - 这比之前基于标记位置查找的方式更鲁棒，
      尤其是对代码块格式的工具调用

    Args:
        raw_text: Qwen 模型生成的原始文本（可能包含 <tool_call> 标签）

    Returns:
        Claude 格式的响应字典：
        {
            "role": "assistant",
            "content": [content_blocks...],
            "stop_reason": "tool_use" | "end_turn"
        }
    """
    content_blocks = []

    # 使用 parser.py 的鲁棒解析提取工具调用
    tool_calls = parse_tool_calls(raw_text)

    if not tool_calls:
        # 没有工具调用——纯文本响应
        clean_text = raw_text.strip()
        if clean_text:
            content_blocks.append({"type": "text", "text": clean_text})

        trace("qwen_response_to_claude",
              raw_len=len(raw_text), text_blocks=len(content_blocks),
              tool_use_blocks=0, stop_reason="end_turn")

        return {
            "role": "assistant",
            "content": content_blocks,
            "stop_reason": "end_turn"
        }

    # ── 从原始文本中剥离工具调用模式，提取纯文本 ──────────────────
    clean_text = raw_text

    # 剥离 XML 标签格式：<tool_call>...</tool_call>
    clean_text = re.sub(r'<tool_call>.*?</tool_call>', '', clean_text, flags=re.DOTALL)
    # 剥离孤立闭标签变体（JSON 格式）
    clean_text = re.sub(
        r'\{[^<]*?(?:"tool"|"name")[^<]*?\}\s*</tool_call>',
        '', clean_text, flags=re.DOTALL
    )
    # 剥离 Qwen3 格式：<function=Name>...</function> (with or without </tool_call>)
    clean_text = re.sub(
        r'<function=\w+>.*?</function>\s*(?:</tool_call>)?',
        '', clean_text, flags=re.DOTALL
    )

    # 剥离包含工具调用的代码块
    def _is_tool_call_block(match):
        content = match.group(1)
        data = _try_parse_json(content)
        if data and isinstance(data, dict):
            return _extract_tool_call(data) is not None
        return False

    for match in reversed(list(re.finditer(
            r'```(?:\w+)?\s*\n(.*?)\n```', clean_text, re.DOTALL))):
        if _is_tool_call_block(match):
            clean_text = clean_text[:match.start()] + clean_text[match.end():]

    clean_text = clean_text.strip()

    # ── 构建 content blocks：text 在前，tool_use 在后 ─────────────
    if clean_text:
        content_blocks.append({"type": "text", "text": clean_text})

    for tc in tool_calls:
        content_blocks.append({
            "type": "tool_use",
            "id": _generate_tool_use_id(),
            "name": tc.tool_name,
            "input": tc.parameters
        })

    # 兜底：如果解析出了 tool_use 但 content_blocks 意外为空
    if not content_blocks:
        content_blocks.append({"type": "text", "text": raw_text.strip()})

    tool_use_count = sum(1 for b in content_blocks if b.get("type") == "tool_use")
    trace("qwen_response_to_claude",
          raw_len=len(raw_text),
          text_blocks=sum(1 for b in content_blocks if b.get("type") == "text"),
          tool_use_blocks=tool_use_count,
          stop_reason="tool_use")

    return {
        "role": "assistant",
        "content": content_blocks,
        "stop_reason": "tool_use"
    }


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def is_tool_use_response(response: Dict[str, Any]) -> bool:
    """
    判断 Claude 格式的响应是否包含工具调用。

    客户端用此函数决定是否需要执行工具并继续对话。

    Args:
        response: Claude 格式的响应字典

    Returns:
        True 如果响应包含 tool_use content block
    """
    return response.get("stop_reason") == "tool_use"


def extract_tool_uses(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从 Claude 格式的响应中提取所有 tool_use blocks。

    Args:
        response: Claude 格式的响应字典

    Returns:
        tool_use content blocks 列表
    """
    return [
        block for block in response.get("content", [])
        if block.get("type") == "tool_use"
    ]


def extract_text(response: Dict[str, Any]) -> str:
    """
    从 Claude 格式的响应中提取所有文本内容。

    Args:
        response: Claude 格式的响应字典

    Returns:
        拼接后的文本内容
    """
    text_parts = [
        block["text"]
        for block in response.get("content", [])
        if block.get("type") == "text"
    ]
    return "\n".join(text_parts)


def make_tool_result_message(tool_use_id: str, result: str,
                              is_error: bool = False) -> Dict[str, Any]:
    """
    构造 Claude 格式的 tool_result 消息。

    当客户端执行完工具后，用此函数构造回传给服务端的 tool_result 消息。
    Claude API 通过 tool_use_id 将 result 与对应的 tool_use 精确关联。

    Args:
        tool_use_id: 对应的 tool_use block 的 id
        result: 工具执行结果（文本）
        is_error: 工具执行是否出错

    Returns:
        Claude 格式的 user message，content 包含 tool_result block
    """
    return {
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result,
            "is_error": is_error
        }]
    }
