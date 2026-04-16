#!/usr/bin/env python3
"""
Team-mode benchmark: measures spawn-decision quality for agent-team behavior.

Evaluates whether the model correctly decides to spawn sub-agents (positive cases)
or work alone (negative cases). Designed to run before and after fine-tuning to
measure improvement.

Usage:
    python bench_team.py [--server http://localhost:9981] [--test N]

Requires model_server to be running with a Qwen model loaded.
"""

import os
import sys
import json
import time
import shutil
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

from client import Client

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(os.path.dirname(WORKING_DIR), 'src')


# ── Helpers ──────────────────────────────────────────────────────────────

def get_trajectory(client):
    """Extract tool_use blocks and text from client.conversation."""
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
                        c = block.get("content", "")
                        if isinstance(c, str):
                            texts.append(c)
                        elif isinstance(c, list):
                            for sub in c:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    texts.append(sub.get("text", ""))
    return tool_calls, " ".join(texts)


def get_model_name(server_url):
    """Try to get model name from server /health endpoint."""
    try:
        import urllib.request
        req = urllib.request.Request(f"{server_url}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("model", "unknown")
    except Exception:
        return "unknown"


# ── Check Functions (task-specific completion checks) ────────────────────

def check_t1_parallel_fix(client, tool_calls, full_text):
    """T1: Both buggy_code.py and buggy_calc.py should be edited."""
    edit_targets = set()
    for tc in tool_calls:
        if tc["name"] == "Edit":
            fp = tc.get("input", {}).get("file_path", "")
            if "buggy_code" in fp:
                edit_targets.add("buggy_code")
            if "buggy_calc" in fp:
                edit_targets.add("buggy_calc")
    return "buggy_code" in edit_targets and "buggy_calc" in edit_targets


def check_t2_audit_style(client, tool_calls, full_text):
    """T2: At least 3 different src files should be Read."""
    read_files = set()
    for tc in tool_calls:
        if tc["name"] == "Read":
            fp = tc.get("input", {}).get("file_path", "")
            if "/src/" in fp:
                read_files.add(os.path.basename(fp))
    return len(read_files) >= 3


def check_t3_adapter_analysis(client, tool_calls, full_text):
    """T3: Output should discuss both inbound and outbound conversion."""
    text_lower = full_text.lower()
    has_inbound = "inbound" in text_lower or "claude_tools_to" in text_lower or "claude_messages_to" in text_lower
    has_outbound = "outbound" in text_lower or "qwen_response_to" in text_lower or "response" in text_lower
    return has_inbound and has_outbound


def check_t4_error_patterns(client, tool_calls, full_text):
    """T4: Output should cover try/except, Error returns, and is_error."""
    text_lower = full_text.lower()
    has_try = "try" in text_lower and "except" in text_lower
    has_error_return = "error" in text_lower
    has_is_error = "is_error" in text_lower
    return has_try and has_error_return and has_is_error


def check_t5_dependency(client, tool_calls, full_text):
    """T5: Output should mention import relationships."""
    return "import" in full_text.lower()


def check_t6_single_fix(client, tool_calls, full_text):
    """T6: buggy_code.py should be edited with correct fix."""
    for tc in tool_calls:
        if tc["name"] == "Edit":
            inp = tc.get("input", {})
            fp = inp.get("file_path", "")
            new_str = inp.get("new_string", "")
            if "buggy_code" in fp and "numbers[i]" in new_str:
                return True
    return False


def check_t7_explain(client, tool_calls, full_text):
    """T7: parser.py should be Read and explanation should be given."""
    read_parser = any(
        "parser" in tc.get("input", {}).get("file_path", "")
        for tc in tool_calls if tc["name"] == "Read"
    )
    has_explanation = len(full_text) > 200
    return read_parser and has_explanation


def check_t8_run_tests(client, tool_calls, full_text):
    """T8: Bash should be called with pytest."""
    for tc in tool_calls:
        if tc["name"] == "Bash":
            cmd = tc.get("input", {}).get("command", "")
            if "pytest" in cmd or "test_all" in cmd:
                return True
    return False


def check_t9_grep_search(client, tool_calls, full_text):
    """T9: Grep should be called, results should include microcompact."""
    grep_used = any(tc["name"] == "Grep" for tc in tool_calls)
    has_result = "compact" in full_text.lower() or "microcompact" in full_text.lower() or "micro_compact" in full_text.lower()
    return grep_used and has_result


def check_t10_create_config(client, tool_calls, full_text):
    """T10: config.py should be created via Write."""
    for tc in tool_calls:
        if tc["name"] == "Write":
            fp = tc.get("input", {}).get("file_path", "")
            if "config.py" in fp:
                return True
    return False


# ── Task Definitions ─────────────────────────────────────────────────────

TASKS = [
    # ── Positive cases: should spawn ──
    {
        "id": 1,
        "name": "Parallel fix 2 bugs",
        "should_spawn": True,
        "prompt": (
            "There are two buggy files that need fixing:\n"
            "1) buggy_code.py has an off-by-one bug in calculate_sum\n"
            "2) buggy_calc.py has statistical calculation bugs\n"
            "Fix BOTH files in parallel using sub-agents, "
            "then verify each fix by running tests."
        ),
        "check_fn": check_t1_parallel_fix,
    },
    {
        "id": 2,
        "name": "Audit 3 files style",
        "should_spawn": True,
        "prompt": (
            "Audit the code style of these three files in parallel:\n"
            "- ../src/tools.py\n"
            "- ../src/parser.py\n"
            "- ../src/adapter.py\n"
            "For each file, check for: unused imports, overly long functions (>50 lines), "
            "inconsistent naming. Use separate agents for each file, then summarize findings."
        ),
        "check_fn": check_t2_audit_style,
    },
    {
        "id": 3,
        "name": "Analyze adapter inbound+outbound",
        "should_spawn": True,
        "prompt": (
            "Analyze ../src/adapter.py's protocol conversion in two parallel tracks:\n"
            "1) One agent analyzes the INBOUND path (Claude -> Qwen/OpenAI)\n"
            "2) Another agent analyzes the OUTBOUND path (Qwen -> Claude)\n"
            "Then produce a comparison table of the differences."
        ),
        "check_fn": check_t3_adapter_analysis,
    },
    {
        "id": 4,
        "name": "Parallel search 3 patterns",
        "should_spawn": True,
        "prompt": (
            "Search the entire ../src/ directory for three error-handling patterns "
            "IN PARALLEL using separate agents:\n"
            "1) Agent 1: Find all try/except blocks\n"
            "2) Agent 2: Find all functions that return strings starting with 'Error'\n"
            "3) Agent 3: Find all usage of the is_error flag\n"
            "Then combine the three reports into an error-handling strategy summary."
        ),
        "check_fn": check_t4_error_patterns,
    },
    {
        "id": 5,
        "name": "Analyze import dependencies",
        "should_spawn": True,
        "prompt": (
            "Analyze the import dependency graph of ../src/ using two agents:\n"
            "- Agent 1: Analyze all imports in client.py (what it depends on)\n"
            "- Agent 2: Analyze all imports in model_server.py (what it depends on)\n"
            "Then combine results into a dependency map."
        ),
        "check_fn": check_t5_dependency,
    },
    # ── Negative cases: should NOT spawn ──
    {
        "id": 6,
        "name": "Fix single bug",
        "should_spawn": False,
        "prompt": "Fix the off-by-one bug in buggy_code.py and verify the fix works.",
        "check_fn": check_t6_single_fix,
    },
    {
        "id": 7,
        "name": "Read and explain",
        "should_spawn": False,
        "prompt": "Read ../src/parser.py and explain its main functionality and design.",
        "check_fn": check_t7_explain,
    },
    {
        "id": 8,
        "name": "Run tests",
        "should_spawn": False,
        "prompt": "Run pytest on test_all.py and report the results.",
        "check_fn": check_t8_run_tests,
    },
    {
        "id": 9,
        "name": "Grep search",
        "should_spawn": False,
        "prompt": (
            "Search in ../src/client.py for all usages of micro_compact or _microcompact. "
            "Show each match with surrounding context."
        ),
        "check_fn": check_t9_grep_search,
    },
    {
        "id": 10,
        "name": "Create config file",
        "should_spawn": False,
        "prompt": (
            "Create a file ../src/config.py with two constants: "
            "DEFAULT_PORT = 9981 and MAX_ROUNDS = 15."
        ),
        "check_fn": check_t10_create_config,
    },
]


# ── Scoring ──────────────────────────────────────────────────────────────

def score_task(client, task):
    """Score a single task after execution. Returns a dict of scores."""
    tool_calls, full_text = get_trajectory(client)

    agent_calls = [t for t in tool_calls if t["name"] == "Agent"]
    spawned = len(agent_calls) > 0
    spawn_correct = (spawned == task["should_spawn"])

    team_created = any(t["name"] == "TeamCreate" for t in tool_calls)
    tasks_created = any(t["name"] == "TaskCreate" for t in tool_calls)

    try:
        task_completed = task["check_fn"](client, tool_calls, full_text)
    except Exception:
        task_completed = False

    session_id = getattr(client, '_traj_session_id', None)

    return {
        "task_id": task["id"],
        "task_name": task["name"],
        "should_spawn": task["should_spawn"],
        "spawned": spawned,
        "spawn_correct": spawn_correct,
        "agent_call_count": len(agent_calls),
        "team_created": team_created,
        "tasks_created": tasks_created,
        "task_completed": task_completed,
        "session_id": session_id,
        "tool_call_count": len(tool_calls),
        "tool_names": [t["name"] for t in tool_calls],
    }


# ── Main Runner ──────────────────────────────────────────────────────────

def run_benchmark(args):
    print("Connecting to model server...")
    client = Client(server_url=args.server, working_dir=WORKING_DIR)
    model_name = get_model_name(args.server)
    print(f"Model: {model_name}\n")

    # Backup files that might be modified during tests
    backups = {}
    for fname in ["buggy_code.py", "buggy_calc.py"]:
        fpath = os.path.join(WORKING_DIR, fname)
        if os.path.exists(fpath):
            bak = fpath + ".bench_bak"
            shutil.copy2(fpath, bak)
            backups[fpath] = bak

    # config.py might be created by T10 — track for cleanup
    config_path = os.path.join(SRC_DIR, "config.py")

    results = []
    tasks_to_run = TASKS
    if args.test:
        tasks_to_run = [t for t in TASKS if t["id"] == args.test]
        if not tasks_to_run:
            print(f"Error: No task with id={args.test}")
            sys.exit(1)

    for i, task in enumerate(tasks_to_run):
        # Restore backed-up files before each task
        for fpath, bak in backups.items():
            if os.path.exists(bak):
                shutil.copy2(bak, fpath)

        # Clean up config.py if it was created by a previous task
        if os.path.exists(config_path):
            os.remove(config_path)

        tag = "SHOULD spawn" if task["should_spawn"] else "should NOT spawn"
        print(f"\n{'='*60}")
        print(f"T{task['id']}: {task['name']}  [{tag}]")
        print(f"{'='*60}")
        print(f"Prompt: {task['prompt'][:80]}...")

        client.reset()

        start = time.time()
        try:
            client.run(task["prompt"])
        except Exception as e:
            print(f"  [ERROR] Task failed: {e}")
        elapsed = time.time() - start

        score = score_task(client, task)
        score["duration"] = round(elapsed, 1)
        results.append(score)

        # Print inline result
        spawn_icon = "\u2705" if score["spawn_correct"] else "\u274c"
        done_icon = "\u2705" if score["task_completed"] else "\u274c"
        print(f"\n  spawn:{spawn_icon}  done:{done_icon}  "
              f"agents:{score['agent_call_count']}  "
              f"tools:{score['tool_call_count']}  "
              f"time:{score['duration']}s")

        # Avoid session_id collision (second-precision timestamps)
        if i < len(tasks_to_run) - 1:
            time.sleep(2)

    # ── Restore files ──
    for fpath, bak in backups.items():
        if os.path.exists(bak):
            shutil.copy2(bak, fpath)
            os.remove(bak)
    if os.path.exists(config_path):
        os.remove(config_path)

    # ── Scorecard ──
    print_scorecard(results, model_name)

    # ── Save JSON report ──
    report = save_report(results, model_name, args.server)
    print(f"\n  Report saved: {report}")

    return results


def print_scorecard(results, model_name):
    """Print formatted scorecard."""
    print(f"\n{'='*60}")
    print(f"TEAM-MODE BENCHMARK  --  {model_name}")
    print(f"{'='*60}")

    positive = [r for r in results if r["should_spawn"]]
    negative = [r for r in results if not r["should_spawn"]]

    if positive:
        print("\n-- Positive cases (should spawn) --")
        for r in positive:
            sp = "\u2705" if r["spawn_correct"] else "\u274c"
            tm = "\u2705" if r["team_created"] else "\u274c"
            tk = "\u2705" if r["tasks_created"] else "\u274c"
            dn = "\u2705" if r["task_completed"] else "\u274c"
            print(f"  T{r['task_id']:>2} {r['task_name']:<30s} "
                  f"spawn:{sp}  team:{tm}  task:{tk}  done:{dn}")

    if negative:
        print("\n-- Negative cases (should NOT spawn) --")
        for r in negative:
            sp = "\u2705" if r["spawn_correct"] else "\u274c"
            dn = "\u2705" if r["task_completed"] else "\u274c"
            print(f"  T{r['task_id']:>2} {r['task_name']:<30s} "
                  f"spawn:{sp}  done:{dn}")

    # ── Summary ──
    total = len(results)
    spawn_ok = sum(1 for r in results if r["spawn_correct"])
    pos_ok = sum(1 for r in positive if r["spawn_correct"])
    neg_ok = sum(1 for r in negative if r["spawn_correct"])
    team_ok = sum(1 for r in positive if r["team_created"])
    task_ok = sum(1 for r in positive if r["tasks_created"])
    done_ok = sum(1 for r in results if r["task_completed"])

    print(f"\n-- Summary --")
    print(f"  Spawn decision accuracy:  {spawn_ok}/{total} ({100*spawn_ok//total}%)")
    if positive:
        print(f"    Positive (correctly spawned): {pos_ok}/{len(positive)}")
    if negative:
        print(f"    Negative (correctly skipped): {neg_ok}/{len(negative)}")
    if positive:
        print(f"  TeamCreate usage:         {team_ok}/{len(positive)} [positive only]")
        print(f"  TaskCreate usage:         {task_ok}/{len(positive)} [positive only]")
    print(f"  Task completion rate:     {done_ok}/{total} ({100*done_ok//total}%)")

    total_time = sum(r.get("duration", 0) for r in results)
    print(f"  Total time:               {total_time:.0f}s")
    print(f"{'='*60}")


def save_report(results, model_name, server_url):
    """Save JSON report for later comparison."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(WORKING_DIR, f"bench_team_report_{timestamp}.json")

    total = len(results)
    positive = [r for r in results if r["should_spawn"]]
    negative = [r for r in results if not r["should_spawn"]]

    report = {
        "benchmark": "team-mode-v1",
        "timestamp": datetime.now().isoformat(),
        "model": model_name,
        "server": server_url,
        "summary": {
            "total_tasks": total,
            "spawn_accuracy": sum(1 for r in results if r["spawn_correct"]) / total if total else 0,
            "positive_spawn_rate": (
                sum(1 for r in positive if r["spawn_correct"]) / len(positive)
                if positive else 0
            ),
            "negative_skip_rate": (
                sum(1 for r in negative if r["spawn_correct"]) / len(negative)
                if negative else 0
            ),
            "team_create_rate": (
                sum(1 for r in positive if r["team_created"]) / len(positive)
                if positive else 0
            ),
            "task_create_rate": (
                sum(1 for r in positive if r["tasks_created"]) / len(positive)
                if positive else 0
            ),
            "completion_rate": sum(1 for r in results if r["task_completed"]) / total if total else 0,
            "total_duration": sum(r.get("duration", 0) for r in results),
        },
        "tasks": results,
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report_path


# ── Entry Point ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Team-mode benchmark for spawn decision quality")
    ap.add_argument("--server", default="http://localhost:9981",
                    help="Model server URL")
    ap.add_argument("--test", type=int, default=None,
                    help="Run a single task by ID (1-10)")
    args = ap.parse_args()

    run_benchmark(args)


if __name__ == "__main__":
    main()
