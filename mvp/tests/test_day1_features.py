#!/usr/bin/env python3
"""
Day 1 Feature Tests
Tests each feature independently with the Qwen2.5-Coder-7B model
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

SERVER_URL = os.environ.get("MODEL_SERVER", "http://localhost:9981")
TEST_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Helper ────────────────────────────────────────────────────────

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")
        if detail:
            print(f"    → {detail}")


# ── Test 1: Tools (no model needed) ──────────────────────────────

def test_tools():
    print("\n[1/6] Tool Execution")
    from tools import ReadTool, WriteTool, BashTool

    # Read existing file
    r = ReadTool()
    out = r.execute(file_path=os.path.join(TEST_DIR, "buggy_code.py"))
    check("Read existing file", "calculate_sum" in out)

    # Read non-existent file
    out = r.execute(file_path="/tmp/__no_such_file__")
    check("Read missing file returns error", "Error" in out)

    # Write file
    w = WriteTool()
    tmp = "/tmp/test_day1_write.py"
    out = w.execute(file_path=tmp, content="x = 1\n")
    check("Write file succeeds", "Successfully" in out)
    check("Written content correct", open(tmp).read() == "x = 1\n")
    os.remove(tmp)

    # Write to nested dir
    nested = "/tmp/day1_test_nested/a/b/file.txt"
    out = w.execute(file_path=nested, content="hi")
    check("Write creates parent dirs", os.path.exists(nested))
    os.remove(nested)

    # Bash basic
    b = BashTool()
    out = b.execute(command="echo hello")
    check("Bash echo", "hello" in out)

    # Bash with cwd
    b2 = BashTool(working_dir=TEST_DIR)
    out = b2.execute(command="ls *.py")
    check("Bash cwd respected", "buggy_code.py" in out)

    # Bash error
    out = b.execute(command="ls /nonexistent_dir_xyz")
    check("Bash error returns stderr", "No such file" in out or "Return code" in out)

    # Bash timeout
    out = b.execute(command="sleep 60")
    check("Bash timeout works", "timed out" in out)


# ── Test 2: Parser ───────────────────────────────────────────────

def test_parser():
    print("\n[2/6] Tool Call Parser")
    from parser import parse_tool_calls, extract_text_and_tool_calls

    # XML format
    xml_text = 'Let me read.\n<tool_call>\n{"tool": "Read", "parameters": {"file_path": "a.py"}}\n</tool_call>'
    calls = parse_tool_calls(xml_text)
    check("Parse XML format", len(calls) == 1 and calls[0].tool_name == "Read")

    # Code block format
    cb_text = 'Reading file.\n```python\n{"tool": "Read", "parameters": {"file_path": "b.py"}}\n```'
    calls = parse_tool_calls(cb_text)
    check("Parse code block format", len(calls) == 1 and calls[0].tool_name == "Read")

    # JSON format
    cb_text = 'Reading file.\n```json\n{"tool": "Bash", "parameters": {"command": "ls"}}\n```'
    calls = parse_tool_calls(cb_text)
    check("Parse json code block", len(calls) == 1 and calls[0].tool_name == "Bash")

    # Plain JSON
    plain = 'Here: {"tool": "Write", "parameters": {"file_path": "c.py", "content": "x=1"}}'
    calls = parse_tool_calls(plain)
    check("Parse plain JSON", len(calls) == 1 and calls[0].tool_name == "Write")

    # No tool calls
    calls = parse_tool_calls("Just a regular message with no tools.")
    check("No false positives", len(calls) == 0)

    # Multiple tool calls
    multi = '<tool_call>\n{"tool": "Read", "parameters": {"file_path": "a.py"}}\n</tool_call>\ntext\n<tool_call>\n{"tool": "Bash", "parameters": {"command": "ls"}}\n</tool_call>'
    calls = parse_tool_calls(multi)
    check("Parse multiple XML tool calls", len(calls) == 2)

    # extract_text_and_tool_calls
    text, calls = extract_text_and_tool_calls(xml_text)
    check("Extract text removes tool tags", "<tool_call>" not in text and "Let me read" in text)
    check("Extract returns tool calls", len(calls) == 1)

    # Malformed JSON ignored
    bad = '<tool_call>\nnot valid json\n</tool_call>'
    calls = parse_tool_calls(bad)
    check("Malformed JSON gracefully ignored", len(calls) == 0)


# ── Test 3: Client structure ─────────────────────────────────────

def test_client_structure():
    print("\n[3/6] Client Structure")
    from client import Client

    check("Client class importable", True)
    check("Has run()", hasattr(Client, 'run'))
    check("Has get_system_prompt()", hasattr(Client, 'get_system_prompt'))
    check("Has _generate()", hasattr(Client, '_generate'))
    check("Has _execute_tool()", hasattr(Client, '_execute_tool'))
    check("Has reset()", hasattr(Client, 'reset'))
    check("Accepts server_url", 'server_url' in Client.__init__.__code__.co_varnames)
    check("Accepts working_dir", 'working_dir' in Client.__init__.__code__.co_varnames)


# ── Test 4: System prompt quality ────────────────────────────────

def test_system_prompt():
    print("\n[4/6] System Prompt Quality")
    # We don't need the server here, just test prompt generation
    from client import Client
    # Monkey-patch to skip server connection
    original_init = Client.__init__
    def fake_init(self, *a, **kw):
        self.tools = __import__('tools').get_tools()
        self.conversation = []
        self.working_dir = "/tmp/test_project"
        self.server_url = "http://fake"
        self._file_tree = "(empty)"
    Client.__init__ = fake_init

    c = Client.__new__(Client)
    c.__init__()
    prompt = c.get_system_prompt()

    check("Prompt includes working dir", "/tmp/test_project" in prompt)
    check("Prompt mentions Read tool", "Read" in prompt)
    check("Prompt mentions Write tool", "Write" in prompt)
    check("Prompt mentions Bash tool", "Bash" in prompt)
    check("Prompt has tool_call format", "<tool_call>" in prompt)
    check("Prompt says never ask to paste", "NEVER" in prompt)
    check("Prompt includes file tree", "(empty)" in prompt or "Files in this project" in prompt)
    check("Prompt has example", "Example" in prompt)

    Client.__init__ = original_init


# ── Test 5: Model integration (requires model) ──────────────────

def test_model_integration():
    print(f"\n[5/6] Model Integration (connecting to {SERVER_URL}...)")
    from client import Client

    try:
        client = Client(server_url=SERVER_URL, working_dir=TEST_DIR)
        check("Connected to server", True)
    except ConnectionError as e:
        print(f"  ✗ Cannot connect to model server: {e}")
        print(f"  Start it first: python model_server.py <model_path>")
        check("Connected to server", False, "Server not running")
        return None

    check("Working dir set", client.working_dir == TEST_DIR)

    # Test conversation management
    client.conversation = []
    check("Empty conversation", len(client.conversation) == 0)

    # Test reset
    client.conversation.append({"role": "user", "content": "hi"})
    client.reset()
    check("Reset clears conversation", len(client.conversation) == 0)

    return client


# ── Test 6: End-to-end with model ────────────────────────────────

def test_e2e(client):
    print("\n[6/6] End-to-End (model generates + tool executes)")

    # Test: ask model to read a file — it should use Read tool
    client.reset()
    print("  Prompting: 'List the python files in the working directory'")
    print("  --- model output start ---")
    client.run("List the python files in the working directory")
    print("\n  --- model output end ---")

    # Check conversation has entries (at minimum user + assistant)
    check("Conversation has entries", len(client.conversation) >= 2)

    # Check if tool was used (conversation should have tool results)
    has_tool_result = any("Tool results:" in m.get("content", "") for m in client.conversation)
    check("Model used a tool", has_tool_result,
          "Model did not invoke any tool — system prompt may need tuning")

    # Test: ask about buggy code
    client.reset()
    print("\n  Prompting: 'Read and analyze buggy_code.py in the working directory'")
    print("  --- model output start ---")
    client.run("Read and analyze buggy_code.py in the working directory")
    print("\n  --- model output end ---")

    has_tool_result = any("Tool results:" in m.get("content", "") for m in client.conversation)
    check("Model read buggy_code.py", has_tool_result,
          "Model did not read the file")

    # Check if the model mentioned the bug
    last_msg = client.conversation[-1].get("content", "")
    mentions_bug = any(w in last_msg.lower() for w in ["bug", "error", "off-by-one", "i + 1", "index"])
    check("Model identified the bug", mentions_bug,
          f"Last response didn't mention bug keywords")


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Day 1 Feature Tests")
    print("=" * 60)

    test_tools()
    test_parser()
    test_client_structure()
    test_system_prompt()
    client = test_model_integration()
    if client:
        test_e2e(client)
    else:
        print("\n[6/6] End-to-End — SKIPPED (no server)")


    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
