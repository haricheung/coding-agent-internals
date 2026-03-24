"""
Tool call parser for extracting and executing tool calls from model output
"""

import json
import re
from typing import List, Dict, Any, Optional


class ToolCall:
    """Represents a single tool call"""
    def __init__(self, tool_name: str, parameters: Dict[str, Any]):
        self.tool_name = tool_name
        self.parameters = parameters

    def __repr__(self):
        return f"ToolCall(tool_name={self.tool_name}, parameters={self.parameters})"


def parse_tool_calls(text: str) -> List[ToolCall]:
    """
    Parse tool calls from model output.

    Supports multiple formats:
    1. XML-style: <tool_call>{"tool": "ToolName", "parameters": {...}}</tool_call>
    2. Code blocks: ```python\n{"tool": "ToolName", "parameters": {...}}\n```
    3. Plain JSON: {"tool": "ToolName", "parameters": {...}}
    """
    tool_calls = []

    # Try XML-style tags first
    pattern = r'<tool_call>(.*?)</tool_call>'
    matches = re.findall(pattern, text, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match.strip())
            tool_name = data.get("tool")
            parameters = data.get("parameters", {})
            if tool_name:
                tool_calls.append(ToolCall(tool_name, parameters))
        except json.JSONDecodeError:
            continue

    # Try code blocks (```python, ```json, ```bash, or just ```)
    if not tool_calls:
        code_block_pattern = r'```(?:python|json|bash)?\s*\n(.*?)\n```'
        code_matches = re.findall(code_block_pattern, text, re.DOTALL)
        for match in code_matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, dict) and "tool" in data:
                    tool_calls.append(ToolCall(data["tool"], data.get("parameters", {})))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "tool" in item:
                            tool_calls.append(ToolCall(item["tool"], item.get("parameters", {})))
            except json.JSONDecodeError:
                continue

    # If still no tool calls, try to find JSON objects in plain text
    # Use a brace-matching approach to handle nested objects
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
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict) and "tool" in data:
                        tool_calls.append(ToolCall(data["tool"], data.get("parameters", {})))
                except json.JSONDecodeError:
                    continue

    return tool_calls


def extract_text_and_tool_calls(text: str) -> tuple[str, List[ToolCall]]:
    """
    Extract both the text response and tool calls from model output.
    Returns (text_without_tool_calls, tool_calls)
    """
    tool_calls = parse_tool_calls(text)

    # Remove tool call tags and code blocks containing tool calls from text
    clean_text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)

    # Remove code blocks that contain tool calls
    def should_remove_block(match):
        content = match.group(1)
        try:
            data = json.loads(content.strip())
            return isinstance(data, dict) and "tool" in data
        except:
            return False

    # Find and remove code blocks with tool calls
    code_blocks = list(re.finditer(r'```(?:python|json|bash)?\s*\n(.*?)\n```', clean_text, re.DOTALL))
    for match in reversed(code_blocks):  # Reverse to maintain indices
        if should_remove_block(match):
            clean_text = clean_text[:match.start()] + clean_text[match.end():]

    clean_text = clean_text.strip()

    return clean_text, tool_calls
