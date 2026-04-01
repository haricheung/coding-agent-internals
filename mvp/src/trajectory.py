"""
轨迹日志模块 —— Agent 执行过程的可观测性

两层日志：
1. trace()  — 开发调试用的行级日志（灰色 [TRACE]，写到 stderr）
2. Trajectory — 结构化的会话轨迹（保存到 JSON 文件，用于复盘和教学）

Trajectory 记录的是 Agent 的"故事"：
    用户说了什么 → 模型想了什么 → 调了什么工具 → 得到什么结果 → 最终回答了什么

    每个 session 保存为一个 JSON 文件：
    trajectories/session_20260326_103412.json

    结构：
    {
        "session_id": "20260326_103412",
        "start_time": "2026-03-26T10:34:12",
        "rounds": [
            {
                "round": 1,
                "thought": "Let me read the file first.",
                "actions": [
                    {"tool": "Read", "input": {"file_path": "..."}, "output": "...", "time": 0.02}
                ],
                "response": null  // 非最后一轮
            },
            {
                "round": 2,
                "thought": "Found the bug. Fixing with Edit.",
                "actions": [
                    {"tool": "Edit", "input": {...}, "output": "Success", "time": 0.01}
                ],
                "response": null
            },
            {
                "round": 3,
                "thought": null,
                "actions": [],
                "response": "Fixed the off-by-one error."
            }
        ],
        "summary": {"total_rounds": 3, "tool_calls": 2, "duration": 12.3}
    }
"""

import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional


# ===========================================================================
# Layer 1: trace() — 开发调试行级日志（保持原有功能）
# ===========================================================================

_enabled = os.environ.get("TRACE", "0") == "1"
_start_time = time.time()

_DIM = "\033[2m"
_RESET = "\033[0m"


def is_enabled() -> bool:
    return _enabled


def enable():
    global _enabled
    _enabled = True


def disable():
    global _enabled
    _enabled = False


def trace(msg: str, **kwargs):
    """行级调试日志。格式：[TRACE  12.34s] msg | key=val"""
    if not _enabled:
        return
    elapsed = time.time() - _start_time
    ts = f"{elapsed:7.2f}s"
    kv = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{msg} | {kv}" if kv else msg
    print(f"{_DIM}[TRACE {ts}] {full}{_RESET}", flush=True)


# ===========================================================================
# Layer 2: Trajectory — 结构化会话轨迹
# ===========================================================================

class Trajectory:
    """
    记录一个完整会话的 Agent 轨迹。

    使用方式（在 client.py 的 run() 中）：
        traj = Trajectory(user_input, save_dir="trajectories")

        # 每轮循环
        traj.start_round()
        traj.record_thought("Let me read the file.")
        traj.record_action("Read", {"file_path": "..."}, "file contents...", 0.02)
        traj.end_round()

        # 最后一轮（end_turn）
        traj.start_round()
        traj.record_response("Fixed the bug.")
        traj.end_round()

        # 保存
        traj.finish()

    同时打印人类可读的实时轨迹到终端。
    """

    def __init__(self, user_input: str, save_dir: str = "trajectories",
                 parent_session_id: str = None):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.user_input = user_input
        self.save_dir = save_dir
        self.parent_session_id = parent_session_id
        self.start_time = time.time()
        self.rounds: List[Dict[str, Any]] = []
        self._current_round: Optional[Dict[str, Any]] = None

        os.makedirs(save_dir, exist_ok=True)

        # 打印会话头
        print(f"\n{'═' * 60}", flush=True)
        print(f"Session: {self.session_id}", flush=True)
        print(f"{'═' * 60}", flush=True)
        print(f"\n[User] {user_input}", flush=True)

    def start_round(self, round_num: int):
        """开始新的一轮"""
        self._current_round = {
            "round": round_num,
            "thought": None,
            "actions": [],
            "response": None,
            "start_time": time.time()
        }
        # Round header 由 client.py 打印，这里不重复

    def record_thought(self, thought: str):
        """记录模型的思考/推理文本"""
        if self._current_round is not None:
            self._current_round["thought"] = thought
            # Thought 已由 client.py 的流式输出 🤖 打印，不重复

    def record_action(self, tool_name: str, tool_input: Dict, tool_output: str,
                      duration: float, is_error: bool = False,
                      sub_session_id: str = None):
        """记录一次工具调用"""
        action = {
            "tool": tool_name,
            "input": tool_input,
            "output": tool_output[:500],  # 截断保存
            "time": round(duration, 3),
            "is_error": is_error
        }
        if sub_session_id:
            action["sub_session_id"] = sub_session_id
        if self._current_round is not None:
            self._current_round["actions"].append(action)

        # 打印
        input_preview = json.dumps(tool_input, ensure_ascii=False)
        if len(input_preview) > 100:
            input_preview = input_preview[:100] + "..."
        print(f"  [Action]   {tool_name}({input_preview})", flush=True)

        output_preview = tool_output[:120].replace('\n', '\\n')
        if len(tool_output) > 120:
            output_preview += "..."
        status = "Error" if is_error else "OK"
        print(f"  [Result]   ({status}, {duration:.2f}s) {output_preview}", flush=True)

    def record_response(self, response: str):
        """记录模型的最终回答（end_turn）"""
        if self._current_round is not None:
            self._current_round["response"] = response
            # Response 已由 client.py 的流式输出打印，不重复

    def end_round(self):
        """结束当前轮"""
        if self._current_round is not None:
            self._current_round["duration"] = round(
                time.time() - self._current_round.pop("start_time"), 2
            )
            self.rounds.append(self._current_round)
            self._current_round = None

    def finish(self):
        """结束会话，保存轨迹到 JSON 文件"""
        total_duration = round(time.time() - self.start_time, 2)
        total_tool_calls = sum(len(r["actions"]) for r in self.rounds)

        summary = {
            "total_rounds": len(self.rounds),
            "tool_calls": total_tool_calls,
            "duration": total_duration
        }

        trajectory = {
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "user_input": self.user_input,
            "rounds": self.rounds,
            "summary": summary
        }

        # 保存 JSON
        filepath = os.path.join(self.save_dir, f"session_{self.session_id}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(trajectory, f, indent=2, ensure_ascii=False)

        # 打印会话尾
        print(f"\n{'═' * 60}", flush=True)
        print(f"End ({len(self.rounds)} rounds, {total_tool_calls} tool calls, {total_duration}s)", flush=True)
        print(f"Saved: {filepath}", flush=True)
        print(f"{'═' * 60}\n", flush=True)

        return filepath
