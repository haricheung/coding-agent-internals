"""
轨迹日志模块 —— Agent 执行过程的可观测性

用途：
    在 client 和 server 两侧输出 Agent 的执行轨迹，包括：
    - ReAct 循环的轮次、stop_reason
    - 工具调用的输入/输出/耗时
    - Parser 的解析策略和结果
    - 模型原始输出的预览

    轨迹行使用 ANSI dim（灰色）渲染 + [TRACE] 前缀，
    与用户关注的信息（🤖/🔧/✅/❌）在视觉上明确区分。

启用方式：
    - 环境变量：TRACE=1 python main.py ../tests
    - CLI 参数：python main.py --trace ../tests
    - 代码调用：trajectory.enable()
"""

import os
import time

# 模块加载时检查环境变量
_enabled = os.environ.get("TRACE", "0") == "1"
_start_time = time.time()

# ANSI 转义码：dim（灰色）
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
    """
    输出一条轨迹日志行。

    格式：[TRACE  12.34s] msg | key1=val1 | key2=val2
    仅在 TRACE 模式启用时输出。

    Args:
        msg: 主消息
        **kwargs: 附加的 key=value 对
    """
    if not _enabled:
        return
    elapsed = time.time() - _start_time
    ts = f"{elapsed:7.2f}s"
    kv = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{msg} | {kv}" if kv else msg
    print(f"{_DIM}[TRACE {ts}] {full}{_RESET}", flush=True)
