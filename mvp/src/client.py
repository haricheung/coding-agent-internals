"""
Main Client class for the Claude Code MVP
Manages conversation context and interfaces with the model server
"""

import os
import json
import requests
from typing import List, Dict, Any, Optional
from tools import get_tools, Tool
from parser import extract_text_and_tool_calls, ToolCall


class Client:
    """Main client that manages conversation and tool execution"""

    def __init__(self, server_url: str = "http://localhost:9981", working_dir: str = None):
        """Initialize the client with a model server URL"""
        self.server_url = server_url.rstrip("/")
        self.tools = get_tools(working_dir=working_dir)
        self.conversation: List[Dict[str, str]] = []
        self.working_dir = working_dir or os.getcwd()

        # Snapshot the file tree so the model knows what's available
        self._file_tree = self._scan_files()

        # Check server is up
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
        """Scan working directory and return a file tree string"""
        lines = []
        for root, dirs, files in os.walk(self.working_dir):
            # Skip hidden dirs and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            depth = root.replace(self.working_dir, '').count(os.sep)
            indent = '  ' * depth
            basename = os.path.basename(root) or '.'
            lines.append(f"{indent}{basename}/")
            for f in sorted(files):
                if not f.startswith('.'):
                    lines.append(f"{indent}  {f}")
        return '\n'.join(lines[:50])  # Cap at 50 lines

    def get_system_prompt(self) -> str:
        """Generate the system prompt that teaches tool usage"""
        tools_desc = []
        for tool_name, tool in self.tools.items():
            params = tool.parameters.get("properties", {})
            param_list = ", ".join(f'{k}: {v.get("description", "")}' for k, v in params.items())
            tools_desc.append(f"- {tool.name}({param_list}): {tool.description}")

        return f"""You are a coding agent that helps users with software engineering tasks. You work inside a codebase and use tools to read, write, and execute code.

Working directory: {self.working_dir}

Files in this project:
{self._file_tree}

You have access to these tools:
{chr(10).join(tools_desc)}

IMPORTANT RULES:
1. ALWAYS use tools to act. Use Read to examine files, Write to create/modify them, Bash to run commands.
2. NEVER ask the user to paste code or upload files. You can access the filesystem directly.
3. Use the file tree above to locate files. Construct absolute paths as: {self.working_dir}/<relative_path>.
4. If the user gives a partial filename like "buggy_code", match it to the closest file in the tree (e.g. buggy_code.py in tests/).
5. Keep your text responses short and focused on what you found.

To call a tool, use EXACTLY this format:
<tool_call>
{{"tool": "ToolName", "parameters": {{"param1": "value1"}}}}
</tool_call>

Example:
User: read buggy_code
Assistant: I see `tests/buggy_code.py` in the project. Let me read it.
<tool_call>
{{"tool": "Read", "parameters": {{"file_path": "{self.working_dir}/tests/buggy_code.py"}}}}
</tool_call>
"""

    def run(self, user_input: str) -> str:
        """Process user input and return assistant response"""
        self.conversation.append({"role": "user", "content": user_input})

        max_rounds = 5  # Prevent infinite loops
        for _ in range(max_rounds):
            messages = [{"role": "system", "content": self.get_system_prompt()}]
            messages.extend(self.conversation)

            print("\n🤖 ", end="", flush=True)
            response = self._generate(messages)

            text, tool_calls = extract_text_and_tool_calls(response)

            if not tool_calls:
                # No tool calls — final response, done
                self.conversation.append({"role": "assistant", "content": response})
                return None

            # Execute tool calls
            tool_results = []
            for tc in tool_calls:
                print(f"\n  🔧 Executing {tc.tool_name}...", flush=True)
                result = self._execute_tool(tc)
                tool_results.append(f"Tool: {tc.tool_name}\nResult: {result}")

            # Add to conversation and loop for next round
            self.conversation.append({"role": "assistant", "content": response})
            tool_results_text = "\n\n".join(tool_results)
            self.conversation.append({"role": "user", "content": f"Tool results:\n{tool_results_text}"})

        return None

    def _generate(self, messages: List[Dict[str, str]]) -> str:
        """Call the model server and stream tokens to stdout"""
        resp = requests.post(
            f"{self.server_url}/generate",
            json={"messages": messages},
            stream=True,
            timeout=300
        )
        resp.raise_for_status()

        full_text = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = json.loads(line[6:])  # strip "data: "
            if "token" in data:
                print(data["token"], end="", flush=True)
                full_text += data["token"]
            elif data.get("done"):
                full_text = data.get("full_text", full_text)

        return full_text.strip()

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """Execute a single tool call"""
        tool_name = tool_call.tool_name
        if tool_name not in self.tools:
            return f"Error: Unknown tool '{tool_name}'"

        tool = self.tools[tool_name]
        try:
            result = tool.execute(**tool_call.parameters)
            return result
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    def reset(self):
        """Reset the conversation history"""
        self.conversation = []
