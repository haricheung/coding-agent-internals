"""
Core tools for the Claude Code MVP - Day 1
Implements Read, Write, and Bash tools
"""

import os
import subprocess
from typing import Dict, Any, Callable


class Tool:
    """Base class for all tools"""
    def __init__(self, name: str, description: str, parameters: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters

    def execute(self, **kwargs) -> str:
        raise NotImplementedError


class ReadTool(Tool):
    """Read file contents"""
    def __init__(self):
        super().__init__(
            name="Read",
            description="Read the contents of a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to read"
                    }
                },
                "required": ["file_path"]
            }
        )

    def execute(self, file_path: str) -> str:
        try:
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return content
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteTool(Tool):
    """Write content to a file"""
    def __init__(self):
        super().__init__(
            name="Write",
            description="Write content to a file (creates or overwrites)",
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
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class BashTool(Tool):
    """Execute bash commands"""
    def __init__(self, working_dir: str = None):
        super().__init__(
            name="Bash",
            description="Execute a bash command and return its output",
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


def get_tools(working_dir: str = None) -> Dict[str, Tool]:
    """Return a dictionary of all available tools"""
    return {
        "Read": ReadTool(),
        "Write": WriteTool(),
        "Bash": BashTool(working_dir=working_dir)
    }

