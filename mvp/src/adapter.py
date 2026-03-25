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
    我们用 7B 模型 + 鲁棒解析做概率性兜底。

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
import json
from typing import List, Dict, Any, Optional
from parser import parse_tool_calls


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

            # Case 2c: 纯文本 content blocks（没有 tool_use 也没有 tool_result）
            else:
                combined_text = "\n".join(text_parts)
                qwen_messages.append({"role": role, "content": combined_text})

    return qwen_messages


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
    - 我们有 7B 模型（可能出格式错）+ parser.py 的鲁棒解析（概率性兜底）

    转换规则：
    - 原始文本中的 <tool_call> 块 → {"type": "tool_use", "id": ..., "name": ..., "input": ...}
    - <tool_call> 之外的文本 → {"type": "text", "text": ...}
    - 如果包含 tool_use → stop_reason = "tool_use"
    - 如果不包含 → stop_reason = "end_turn"

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
    # parser 支持三种格式：XML 标签、代码块、裸 JSON——
    # 用 Qwen 原生格式后主要命中 XML 路径，但保留其他路径作为 fallback
    tool_calls = parse_tool_calls(raw_text)

    if not tool_calls:
        # 没有工具调用——纯文本响应
        clean_text = raw_text.strip()
        if clean_text:
            content_blocks.append({"type": "text", "text": clean_text})
        return {
            "role": "assistant",
            "content": content_blocks,
            "stop_reason": "end_turn"
        }

    # 有工具调用——需要分离文本部分和工具调用部分
    # 策略：找到第一个 <tool_call> 之前的文本作为 text block
    remaining_text = raw_text

    for tc in tool_calls:
        # 尝试找到这个 tool_call 在原文中的位置，提取前面的文本
        # 查找 <tool_call> 标签或 JSON 块的起始位置
        markers = ["<tool_call>", '{"name"', "{'name'"]
        split_pos = -1
        for marker in markers:
            pos = remaining_text.find(marker)
            if pos != -1 and (split_pos == -1 or pos < split_pos):
                split_pos = pos

        if split_pos > 0:
            # <tool_call> 之前有文本，作为 text block
            preceding_text = remaining_text[:split_pos].strip()
            if preceding_text:
                content_blocks.append({"type": "text", "text": preceding_text})

        # 添加 tool_use block
        # 从 parser 的 ToolCall 对象转换为 Claude 的 tool_use content block
        tool_use_block = {
            "type": "tool_use",
            "id": _generate_tool_use_id(),
            "name": tc.tool_name,
            "input": tc.parameters
        }
        content_blocks.append(tool_use_block)

        # 移动 remaining_text 到这个 tool_call 之后
        # 查找 </tool_call> 的结束位置
        end_marker = "</tool_call>"
        end_pos = remaining_text.find(end_marker)
        if end_pos != -1:
            remaining_text = remaining_text[end_pos + len(end_marker):]
        else:
            # 没有闭合标签，跳过已处理的部分
            remaining_text = ""

    # 检查所有 tool_call 之后是否还有文本
    trailing_text = remaining_text.strip()
    if trailing_text:
        content_blocks.append({"type": "text", "text": trailing_text})

    # 如果解析出了 tool_use 但 content_blocks 为空（不应该发生），兜底
    if not content_blocks:
        content_blocks.append({"type": "text", "text": raw_text.strip()})

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
