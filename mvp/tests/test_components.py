#!/usr/bin/env python3
"""
Unit tests for Day 1 components (without requiring full model)
Tests the tool system, parser, and basic client structure
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from tools import ReadTool, WriteTool, BashTool, get_tools
from parser import parse_tool_calls, extract_text_and_tool_calls


def test_tools():
    """Test that tools work correctly"""
    print("=== Testing Tools ===\n")

    # Test Read tool
    print("1. Testing Read tool...")
    read_tool = ReadTool()
    result = read_tool.execute(file_path="/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py")
    assert "calculate_sum" in result, "Read tool failed to read file"
    print("✓ Read tool works\n")

    # Test Write tool
    print("2. Testing Write tool...")
    write_tool = WriteTool()
    test_file = "/tmp/test_write.txt"
    result = write_tool.execute(file_path=test_file, content="Hello, World!")
    assert "Successfully" in result, "Write tool failed"
    print("✓ Write tool works\n")

    # Test Bash tool
    print("3. Testing Bash tool...")
    bash_tool = BashTool()
    result = bash_tool.execute(command="echo 'test'")
    assert "test" in result, "Bash tool failed"
    print("✓ Bash tool works\n")

    # Test get_tools
    print("4. Testing get_tools()...")
    tools = get_tools()
    assert len(tools) == 3, "Should have 3 tools"
    assert "Read" in tools and "Write" in tools and "Bash" in tools
    print("✓ get_tools() works\n")


def test_parser():
    """Test the tool call parser"""
    print("=== Testing Parser ===\n")

    # Test XML-style tool call
    print("1. Testing XML-style tool call parsing...")
    text = """Let me read the file.
<tool_call>
{"tool": "Read", "parameters": {"file_path": "test.py"}}
</tool_call>
"""
    tool_calls = parse_tool_calls(text)
    assert len(tool_calls) == 1, "Should parse 1 tool call"
    assert tool_calls[0].tool_name == "Read", "Tool name should be Read"
    assert tool_calls[0].parameters["file_path"] == "test.py"
    print("✓ XML-style parsing works\n")

    # Test extract_text_and_tool_calls
    print("2. Testing extract_text_and_tool_calls...")
    clean_text, tool_calls = extract_text_and_tool_calls(text)
    assert "Let me read" in clean_text
    assert "<tool_call>" not in clean_text
    assert len(tool_calls) == 1
    print("✓ Text extraction works\n")


def test_client_structure():
    """Test client structure without loading model"""
    print("=== Testing Client Structure ===\n")

    print("1. Checking client.py imports...")
    try:
        from client import Client
        print("✓ Client class can be imported\n")
    except Exception as e:
        print(f"✗ Failed to import Client: {e}\n")
        return

    print("2. Checking Client has required methods...")
    required_methods = ['run', 'get_system_prompt', '_generate', '_execute_tool', 'reset']
    for method in required_methods:
        assert hasattr(Client, method), f"Client missing method: {method}"
    print("✓ Client has all required methods\n")


def main():
    """Run all tests"""
    print("\n" + "="*50)
    print("Day 1 Component Tests (No Model Required)")
    print("="*50 + "\n")

    try:
        test_tools()
        test_parser()
        test_client_structure()

        print("\n" + "="*50)
        print("✓ All tests passed!")
        print("="*50 + "\n")

        print("Next steps:")
        print("1. Download the Qwen model:")
        print("   huggingface-cli download Qwen/Qwen3-Coder-30B-A3B-Instruct \\")
        print("     --local-dir /root/work/qlzhang/code/models/Qwen3-Coder-30B-A3B-Instruct")
        print("\n2. Run the full test:")
        print("   python test_day1.py")

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
