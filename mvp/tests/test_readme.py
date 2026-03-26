#!/usr/bin/env python3
"""
Automated test runner for all README.md test cases.
Runs each prompt against the live model server and checks pass criteria.

Usage:
    python test_readme.py [--server http://localhost:9981]

Requires model_server to be running.
"""

import os
import sys
import json
import shutil
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from client import Client

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Helpers ──────────────────────────────────────────────────────────────

def get_trajectory(client):
    """Extract the last trajectory data from the client's conversation."""
    tool_calls = []
    texts = []
    for msg in client.conversation:
        content = msg.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        tool_calls.append(block)
                    elif block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        texts.append(block.get("content", ""))
    return tool_calls, " ".join(texts)


def check(name, condition, detail=""):
    status = "PASS ✅" if condition else "FAIL ❌"
    print(f"  [{status}] {name}")
    if detail and not condition:
        print(f"           {detail}")
    return condition


# ── Test Cases ───────────────────────────────────────────────────────────

def test_1_1(client):
    """1.1: Read buggy_code.py → uses Read tool, shows file, does NOT analyze"""
    print("\n── Test 1.1: Read buggy_code.py ──")
    client.reset()
    client.run("Read buggy_code.py")
    tool_calls, full_text = get_trajectory(client)

    read_tools = [t for t in tool_calls if t["name"] == "Read"]
    p1 = check("Uses Read tool", len(read_tools) >= 1)
    p2 = check("Shows calculate_sum", "calculate_sum" in full_text)
    # Should NOT have Edit/Write/Bash calls (just read and show)
    other_tools = [t for t in tool_calls if t["name"] in ("Edit", "Write")]
    p3 = check("Does NOT try to fix", len(other_tools) == 0,
               f"Found unexpected tool calls: {[t['name'] for t in other_tools]}")
    return p1 and p2 and p3


def test_1_2(client):
    """1.2: List all files → uses Bash"""
    print("\n── Test 1.2: List all files in this directory ──")
    client.reset()
    client.run("List all files in this directory")
    tool_calls, full_text = get_trajectory(client)

    bash_tools = [t for t in tool_calls if t["name"] == "Bash"]
    p1 = check("Uses Bash tool", len(bash_tools) >= 1)
    p2 = check("Shows .py files", ".py" in full_text)
    return p1 and p2


def test_1_3(client):
    """1.3: Create hello.py → uses Write tool"""
    print("\n── Test 1.3: Create hello.py ──")
    client.reset()
    hello_path = os.path.join(WORKING_DIR, "hello.py")
    if os.path.exists(hello_path):
        os.remove(hello_path)

    client.run('Create a file called hello.py that prints "Hello World"')
    tool_calls, full_text = get_trajectory(client)

    write_tools = [t for t in tool_calls if t["name"] == "Write"]
    p1 = check("Uses Write tool", len(write_tools) >= 1)
    p2 = check("hello.py created", os.path.exists(hello_path))
    if p2:
        content = open(hello_path).read()
        p3 = check("Contains print", "print" in content and "Hello" in content)
    else:
        p3 = check("Contains print", False, "File not created")

    # Cleanup
    if os.path.exists(hello_path):
        os.remove(hello_path)
    return p1 and p2 and p3


def test_2_1(client):
    """2.1: Find and analyze bugs → reads code, identifies off-by-one"""
    print("\n── Test 2.1: Find and analyze any bugs in the code ──")
    client.reset()
    client.run("Find and analyze any bugs in the code")
    tool_calls, full_text = get_trajectory(client)

    read_tools = [t for t in tool_calls if t["name"] == "Read"]
    p1 = check("Uses Read tool", len(read_tools) >= 1)
    p2 = check("Identifies off-by-one",
               "i + 1" in full_text or "i+1" in full_text or "off-by-one" in full_text.lower())
    return p1 and p2


def test_2_2(client):
    """2.2: Read, find bug, write fixed version"""
    print("\n── Test 2.2: Read buggy_code.py, find the bug, write fixed version ──")
    client.reset()
    fixed_path = os.path.join(WORKING_DIR, "fixed_code.py")
    if os.path.exists(fixed_path):
        os.remove(fixed_path)

    client.run("Read buggy_code.py, find the bug, and write a fixed version to fixed_code.py")
    tool_calls, full_text = get_trajectory(client)

    read_tools = [t for t in tool_calls if t["name"] == "Read"]
    write_or_edit = [t for t in tool_calls if t["name"] in ("Write", "Edit")]
    p1 = check("Uses Read tool", len(read_tools) >= 1)
    p2 = check("Uses Write/Edit tool", len(write_or_edit) >= 1)
    p3 = check("fixed_code.py created", os.path.exists(fixed_path))

    if p3:
        content = open(fixed_path).read()
        p4 = check("Fix is correct (numbers[i] not numbers[i+1])",
                    "numbers[i]" in content and "numbers[i + 1]" not in content and "numbers[i+1]" not in content)
    else:
        p4 = check("Fix is correct", False, "File not created")

    return p1 and p2 and p3 and p4


def test_2_3(client):
    """2.3: Run buggy code → reports IndexError"""
    print("\n── Test 2.3: Run python buggy_code.py ──")
    client.reset()
    client.run("Run python buggy_code.py and tell me what happens")
    tool_calls, full_text = get_trajectory(client)

    bash_tools = [t for t in tool_calls if t["name"] == "Bash"]
    p1 = check("Uses Bash tool", len(bash_tools) >= 1)
    p2 = check("Reports IndexError", "IndexError" in full_text or "index" in full_text.lower())
    return p1 and p2


def test_3_1(client):
    """3.1: Read and explain functions"""
    print("\n── Test 3.1: Read buggy_code.py and explain functions ──")
    client.reset()
    client.run("Read buggy_code.py and explain what each function does")
    tool_calls, full_text = get_trajectory(client)

    read_tools = [t for t in tool_calls if t["name"] == "Read"]
    p1 = check("Uses Read tool", len(read_tools) >= 1)
    p2 = check("Explains calculate_sum", "calculate_sum" in full_text or "sum" in full_text.lower())
    p3 = check("Explains main", "main" in full_text)
    return p1 and p2 and p3


def test_5_1(client):
    """5.1: Read nonexistent file → error handled"""
    print("\n── Test 5.1: Read nonexistent.py ──")
    client.reset()
    client.run("Read a file called nonexistent.py")
    tool_calls, full_text = get_trajectory(client)

    p1 = check("Uses Read tool", any(t["name"] == "Read" for t in tool_calls))
    p2 = check("Reports not found",
               "not found" in full_text.lower() or "error" in full_text.lower() or
               "does not exist" in full_text.lower() or "doesn't exist" in full_text.lower())
    return p1 and p2


def test_5_3(client):
    """5.3: 'Fix the code' → proactively discovers and fixes files"""
    print("\n── Test 5.3: Fix the code (proactive) ──")
    client.reset()
    client.run("Fix the code")
    tool_calls, full_text = get_trajectory(client)

    # Should use tools, not ask "which code?"
    p1 = check("Uses tools (not asks)", len(tool_calls) >= 1,
               f"tool_calls={len(tool_calls)}")
    p2 = check("Does NOT ask 'which code'",
               "which code" not in full_text.lower() and "please provide" not in full_text.lower() and
               "could you" not in full_text.lower())
    return p1 and p2


def test_6_memory(client):
    """6.1-6.4: Conversation memory"""
    print("\n── Test 6.1-6.4: Conversation memory ──")
    client.reset()

    # 6.1: Read
    client.run("Read buggy_code.py")
    tool_calls_1, text_1 = get_trajectory(client)
    p1 = check("6.1: Reads file", any(t["name"] == "Read" for t in tool_calls_1))

    # 6.2: Follow-up about the bug (should NOT need to re-read)
    client.run("What's the bug in that code?")
    tool_calls_2, text_2 = get_trajectory(client)
    # Check if model mentions the bug
    p2 = check("6.2: Explains bug from context",
               "i + 1" in text_2 or "i+1" in text_2 or "off" in text_2.lower() or "index" in text_2.lower())

    # 6.4: Reset and ask
    client.reset()
    client.run("What bug were we looking at?")
    _, text_4 = get_trajectory(client)
    p4 = check("6.4: After reset, no memory of bug",
               "don't" in text_4.lower() or "no" in text_4.lower() or
               "not sure" in text_4.lower() or "haven't" in text_4.lower() or
               len([t for t in get_trajectory(client)[0] if t["name"] in ("Read", "Bash")]) >= 1)
    # Either says "I don't know" or proactively explores files — both acceptable

    return p1 and p2 and p4


# ── Runner ───────────────────────────────────────────────────────────────

ALL_TESTS = [
    ("1.1 Basic Read", test_1_1),
    ("1.2 List Files", test_1_2),
    ("1.3 Create File", test_1_3),
    ("2.1 Find Bugs", test_2_1),
    ("2.2 Read+Fix+Write", test_2_2),
    ("2.3 Run Buggy Code", test_2_3),
    ("3.1 Explain Code", test_3_1),
    ("5.1 Nonexistent File", test_5_1),
    ("5.3 Proactive Fix", test_5_3),
    ("6.x Memory", test_6_memory),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:9981")
    ap.add_argument("--test", help="Run specific test (e.g., '1.1' or '2.2')")
    args = ap.parse_args()

    client = Client(server_url=args.server, working_dir=WORKING_DIR)

    results = {}
    buggy_code_path = os.path.join(WORKING_DIR, "buggy_code.py")
    buggy_code_backup = buggy_code_path + ".bak"
    # Backup buggy_code.py — agent may modify it during tests
    if os.path.exists(buggy_code_path):
        shutil.copy2(buggy_code_path, buggy_code_backup)
    for name, test_fn in ALL_TESTS:
        if args.test and args.test not in name:
            continue
        # Restore buggy_code.py before each test
        if os.path.exists(buggy_code_backup):
            shutil.copy2(buggy_code_backup, buggy_code_path)
        try:
            passed = test_fn(client)
            results[name] = passed
        except Exception as e:
            print(f"  [ERROR ❌] {e}")
            import traceback
            traceback.print_exc()
            results[name] = False

    # ── Scorecard ──
    print("\n" + "=" * 60)
    print("SCORECARD")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n  {passed}/{total} passed")

    # Check minimum pass criteria
    min_pass = all(results.get(k, False) for k in
                   ["2.1 Find Bugs", "2.2 Read+Fix+Write", "5.3 Proactive Fix"])
    print(f"\n  Day 1 minimum pass (2.1 + 2.2 + 5.3): {'✅ PASS' if min_pass else '❌ FAIL'}")
    print("=" * 60)

    # Restore buggy_code.py and clean up backup
    if os.path.exists(buggy_code_backup):
        shutil.copy2(buggy_code_backup, buggy_code_path)
        os.remove(buggy_code_backup)

    sys.exit(0 if min_pass else 1)


if __name__ == "__main__":
    main()
