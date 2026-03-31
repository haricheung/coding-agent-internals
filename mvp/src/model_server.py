#!/usr/bin/env python3
"""
Model Server —— Claude 协议适配层 + Dashboard

本服务扮演两个角色：
1. 协议适配：接收 Claude tool_use 格式请求，转为 OpenAI 格式调用 vLLM，
             再将 vLLM 的 OpenAI 格式响应转回 Claude 格式
2. Dashboard：提供 Web UI 展示测试结果和 agent 轨迹

架构图（v2: vLLM 解耦）：
    Client ──Claude格式──→ Model Server ──OpenAI格式──→ vLLM serve (AsyncEngine)
    Client ←──Claude格式── Model Server ←──OpenAI格式── vLLM serve
                              ↑
    Browser ──────────────→ /dashboard | /demo

    vLLM serve 独立进程运行，提供：
    - AsyncLLMEngine + continuous batching（并发请求）
    - PagedAttention（高效 KV cache 管理）
    - OpenAI 兼容 API（/v1/chat/completions）

Usage:
    # 一键启动（自动检测空闲 GPU、启动 vLLM、启动适配层）
    python model_server.py /path/to/Qwen2.5-Coder-7B-Instruct

    # 指定 GPU
    python model_server.py /path/to/model --gpu 5,6

    # 连接已有 vLLM 实例
    python model_server.py --vllm-url http://localhost:8000
"""

import sys
import os
import json
import glob
import re
import uuid
import time as _time
import argparse
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests as _requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from adapter import claude_tools_to_qwen, claude_messages_to_openai
from trajectory import trace


app = FastAPI(title="Coding Agent Model Server + Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# vLLM 服务配置
VLLM_URL = "http://localhost:8000"
VLLM_MODEL_NAME = "default"
app_port = 9981  # updated in main()


# ---------------------------------------------------------------------------
# 请求模型：接受 Claude 格式
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """
    客户端请求格式，对齐 Claude API 的核心字段。

    与 Claude Messages API 的对应关系：
    - tools: 等价于 Claude API 请求中的 tools 参数
    - messages: 等价于 Claude API 的 messages 参数，支持 content blocks
    - max_new_tokens / temperature: 推理参数（Claude API 中为 max_tokens / temperature）

    客户端代码用这个接口，就像在调一个本地版的 Claude API。
    """
    tools: Optional[List[Dict[str, Any]]] = None  # Claude 格式的工具定义
    messages: List[Dict[str, Any]]                  # 支持 content blocks 的消息列表
    max_new_tokens: int = 2048
    temperature: float = 0.3


# ---------------------------------------------------------------------------
# 推理：通过 vLLM OpenAI API 代理
# ---------------------------------------------------------------------------

def generate_stream(request: GenerateRequest):
    """
    核心推理流程：Claude 格式 → OpenAI 格式 → vLLM → OpenAI 格式 → Claude 格式。

    不再自己加载模型，而是调用 vLLM 的 OpenAI 兼容 API。
    vLLM 内部使用 AsyncLLMEngine + continuous batching 处理并发请求。

    流程：
    1. Claude tools/messages → OpenAI tools/messages（adapter.py）
    2. POST /v1/chat/completions（流式）
    3. 流式转发 text tokens 给客户端
    4. 累积 tool_calls，构造 Claude 格式响应
    """
    t0 = _time.time()

    # ── Step 1: Claude → OpenAI 格式转换 ────────────────────────────
    openai_tools = None
    if request.tools:
        openai_tools = claude_tools_to_qwen(request.tools)  # OpenAI 和 Qwen 工具格式一致

    openai_messages = claude_messages_to_openai(request.messages)

    trace("generate_stream: openai conversion",
          tools=len(request.tools) if request.tools else 0,
          messages=len(openai_messages))

    # ── Step 2: 构造 OpenAI API 请求 ────────────────────────────────
    payload = {
        "model": VLLM_MODEL_NAME,
        "messages": openai_messages,
        "max_tokens": request.max_new_tokens,
        "temperature": max(request.temperature, 0.01),
        "stream": True,
    }
    if openai_tools:
        payload["tools"] = openai_tools

    # ── Step 3: 流式调用 vLLM ───────────────────────────────────────
    try:
        resp = _requests.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=300
        )
        resp.raise_for_status()
    except _requests.RequestException as e:
        trace("generate_stream: vllm request failed", error=str(e))
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    full_content = ""
    tool_calls_acc = {}  # index → {id, name, arguments}
    finish_reason = None

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload_str = line[6:].strip()
        if payload_str == "[DONE]":
            break

        try:
            data = json.loads(payload_str)
        except json.JSONDecodeError:
            continue

        choice = data["choices"][0]
        delta = choice.get("delta", {})

        # 流式传递文本 token
        if delta.get("content"):
            token = delta["content"]
            full_content += token
            yield f"data: {json.dumps({'token': token})}\n\n"

        # 累积 tool_calls（参数可能跨多个 chunk）
        if "tool_calls" in delta:
            for tc in delta["tool_calls"]:
                idx = tc.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
                        "name": "",
                        "arguments": ""
                    }
                if "function" in tc:
                    if tc["function"].get("name"):
                        tool_calls_acc[idx]["name"] = tc["function"]["name"]
                    if tc["function"].get("arguments"):
                        tool_calls_acc[idx]["arguments"] += tc["function"]["arguments"]

        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    t1 = _time.time()

    # ── Fallback: vLLM 未解析 tool_calls 时，用 parser.py 兜底 ─────
    # 当 vLLM 未启用 --enable-auto-tool-choice 时，工具调用
    # 以原始文本（<tool_call> 标签）出现在 content 中，需要手动解析
    if not tool_calls_acc and full_content:
        from parser import parse_tool_calls
        parsed = parse_tool_calls(full_content)
        if parsed:
            # 从文本中剥离工具调用标签
            clean = full_content
            clean = re.sub(r'<tool_call>.*?</tool_call>', '', clean, flags=re.DOTALL)
            clean = re.sub(r'<function=\w+>.*?</function>\s*(?:</tool_call>)?', '', clean, flags=re.DOTALL)
            full_content = clean.strip()

            for i, tc in enumerate(parsed):
                tool_calls_acc[i] = {
                    "id": f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.parameters, ensure_ascii=False)
                }
            trace("generate_stream: fallback parser used", tool_calls=len(parsed))

    # ── Step 4: 构造 Claude 格式响应 ────────────────────────────────
    content_blocks = []
    if full_content.strip():
        content_blocks.append({"type": "text", "text": full_content.strip()})

    for idx in sorted(tool_calls_acc.keys()):
        tc = tool_calls_acc[idx]
        try:
            args = json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"]
        except (json.JSONDecodeError, TypeError):
            args = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc["id"],
            "name": tc["name"],
            "input": args
        })

    has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)
    stop_reason = "tool_use" if has_tool_use else "end_turn"

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    claude_response = {
        "role": "assistant",
        "content": content_blocks,
        "stop_reason": stop_reason
    }

    trace("generate_stream: done",
          gen_time=f"{t1-t0:.1f}s",
          content_len=len(full_content),
          tool_calls=len(tool_calls_acc),
          stop_reason=stop_reason)

    yield f"data: {json.dumps({'done': True, 'response': claude_response})}\n\n"


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

@app.post("/generate")
async def generate(request: GenerateRequest):
    """
    主推理端点。

    接受 Claude 格式的请求，返回 SSE 流：
    - 推理中：{"token": "..."}（逐 token）
    - 结束时：{"done": true, "response": {Claude 格式的结构化响应}}
    """
    return StreamingResponse(
        generate_stream(request),
        media_type="text/event-stream"
    )


@app.get("/health")
async def health():
    """健康检查端点，客户端启动时调用以确认服务可用。"""
    try:
        resp = _requests.get(f"{VLLM_URL}/health", timeout=3)
        vllm_ok = resp.status_code == 200
    except Exception:
        vllm_ok = False
    return {
        "status": "ok" if vllm_ok else "degraded",
        "vllm_connected": vllm_ok,
        "vllm_url": VLLM_URL,
        "model": VLLM_MODEL_NAME
    }


@app.get("/")
async def index():
    """首页导航。"""
    html = """<!DOCTYPE html><html><head><meta charset="UTF-8">
    <title>MVP Server</title>
    <style>
      body{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
      .card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px 48px;max-width:420px}
      h1{font-size:22px;margin-bottom:24px}
      a{display:block;padding:12px 20px;margin:8px 0;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#58a6ff;text-decoration:none;font-size:15px;transition:background .15s}
      a:hover{background:#30363d}
      .desc{color:#8b949e;font-size:12px;margin-top:2px}
    </style></head><body><div class="card">
    <h1>MVP Server</h1>
    <a href="/demo">Demo: Chat vs Agent<div class="desc">左右分栏对比演示</div></a>
    <a href="/dashboard">Dashboard<div class="desc">轨迹查看 + 测试运行</div></a>
    <a href="/health">Health Check<div class="desc">服务状态 JSON</div></a>
    <a href="/api/stats">API Stats<div class="desc">执行统计 JSON</div></a>
    </div></body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Dashboard —— 测试可视化面板
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
TRAJ_DIR = SCRIPT_DIR / ".." / "tests" / "trajectories"
TESTS_DIR = SCRIPT_DIR / ".." / "tests"

_traj_cache: Dict[str, Any] = {}
_traj_cache_time: float = 0
_test_results: Dict[str, Any] = {}
CACHE_TTL = 5


def _load_trajectories() -> Dict[str, Any]:
    global _traj_cache, _traj_cache_time
    now = _time.time()
    if _traj_cache and (now - _traj_cache_time) < CACHE_TTL:
        return _traj_cache
    result = {}
    for fp in sorted(glob.glob(str(TRAJ_DIR / "session_*.json")), reverse=True):
        try:
            with open(fp) as f:
                data = json.load(f)
            result[data.get("session_id", Path(fp).stem)] = data
        except (json.JSONDecodeError, IOError):
            continue
    _traj_cache = result
    _traj_cache_time = now
    return result


def _compute_stats(trajectories: Dict[str, Any]) -> Dict[str, Any]:
    total_sessions = len(trajectories)
    if total_sessions == 0:
        return {"total_sessions": 0}
    total_rounds = total_tool_calls = total_errors = 0
    total_duration = 0.0
    tool_usage: Dict[str, int] = {}
    durations: list[float] = []
    for data in trajectories.values():
        s = data.get("summary", {})
        total_rounds += s.get("total_rounds", 0)
        total_tool_calls += s.get("tool_calls", 0)
        dur = s.get("duration", 0)
        total_duration += dur
        durations.append(dur)
        for rnd in data.get("rounds", []):
            for a in rnd.get("actions", []):
                t = a.get("tool", "unknown")
                tool_usage[t] = tool_usage.get(t, 0) + 1
                if a.get("is_error"):
                    total_errors += 1
    actual = sum(tool_usage.values()) or 1
    return {
        "total_sessions": total_sessions, "total_tool_calls": total_tool_calls,
        "total_rounds": total_rounds,
        "avg_duration": round(total_duration / total_sessions, 1),
        "avg_rounds": round(total_rounds / total_sessions, 1),
        "avg_tool_calls": round(total_tool_calls / total_sessions, 1),
        "error_rate": round(total_errors / actual * 100, 1),
        "tool_usage": dict(sorted(tool_usage.items(), key=lambda x: -x[1])),
        "durations": sorted(durations),
    }


class TestRunRequest(BaseModel):
    suite: str = "unit"
    server_url: Optional[str] = "http://localhost:9981"


def _parse_unittest_output(output: str) -> Dict[str, Any]:
    details = []
    for m in re.finditer(
        r'^(test_\w+)\s+\((?:__main__\.)?(\w+)\)\n.*?\.\.\.\s+(ok|FAIL|ERROR)',
        output, re.MULTILINE
    ):
        details.append({"method": m.group(1), "class": m.group(2),
                        "status": "pass" if m.group(3) == "ok" else "fail"})
    passed = sum(1 for d in details if d["status"] == "pass")
    sm = re.search(r'Ran (\d+) tests? in ([\d.]+)s', output)
    return {"total": int(sm.group(1)) if sm else len(details),
            "passed": passed, "failed": len(details) - passed, "details": details}


def _parse_readme_output(output: str) -> Dict[str, Any]:
    details = []
    for m in re.finditer(r'^\s+([✅❌])\s+(.+)$', output, re.MULTILINE):
        details.append({"name": m.group(2).strip(),
                        "status": "pass" if m.group(1) == "✅" else "fail"})
    passed = sum(1 for d in details if d["status"] == "pass")
    mp = re.search(r'Day 1 minimum pass.*?(✅ PASS|❌ FAIL)', output)
    return {"total": len(details), "passed": passed, "failed": len(details) - passed,
            "min_pass": bool(mp and "PASS" in mp.group(1)), "details": details}


@app.get("/dashboard")
async def dashboard():
    """Dashboard Web UI."""
    return FileResponse(SCRIPT_DIR / "dashboard.html", media_type="text/html")


@app.get("/demo")
async def demo_page():
    """Demo 1: Chat vs Agent 对比演示 UI."""
    return FileResponse(SCRIPT_DIR / "demo.html", media_type="text/html")


@app.get("/api/trajectories")
async def list_trajectories():
    trajs = _load_trajectories()
    # Build child_session_ids by scanning all trajectories
    children_map: Dict[str, List[str]] = {}  # parent_sid -> [child_sids]
    for sid, d in trajs.items():
        psid = d.get("parent_session_id")
        if psid:
            children_map.setdefault(psid, []).append(sid)
    return [{"session_id": sid, "start_time": d.get("start_time", ""),
             "user_input": d.get("user_input", ""), "summary": d.get("summary", {}),
             "parent_session_id": d.get("parent_session_id"),
             "child_session_ids": children_map.get(sid, [])}
            for sid, d in trajs.items()]


@app.get("/api/trajectories/{session_id}")
async def get_trajectory(session_id: str):
    trajs = _load_trajectories()
    data = trajs.get(session_id)
    if not data:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # Collect child sessions for this parent (by parent_session_id field)
    child_trajs = [v for v in trajs.values()
                   if v.get("parent_session_id") == session_id]
    child_idx = 0  # index into child_trajs for fallback matching

    # Embed sub-agent trajectories inline for Agent tool actions
    for rnd in data.get("rounds", []):
        for action in rnd.get("actions", []):
            if action.get("tool") != "Agent":
                continue
            # Primary: match by explicit sub_session_id
            sub_sid = action.get("sub_session_id")
            if sub_sid and sub_sid in trajs:
                action["sub_trajectory"] = trajs[sub_sid]
            # Fallback: for old trajectories without sub_session_id,
            # match child sessions by order of appearance
            elif not sub_sid and child_idx < len(child_trajs):
                action["sub_trajectory"] = child_trajs[child_idx]
                child_idx += 1
    return data


@app.get("/api/stats")
async def get_stats():
    return _compute_stats(_load_trajectories())


@app.get("/api/tests/results")
async def get_test_results():
    return _test_results if _test_results else {"status": "no_results"}


@app.post("/api/tests/run")
async def run_tests(req: TestRunRequest):
    global _test_results
    if req.suite == "unit":
        cmd = [sys.executable, str(TESTS_DIR / "test_all.py")]
        timeout = 120
    elif req.suite == "live":
        cmd = [sys.executable, str(TESTS_DIR / "test_readme.py"),
               "--server", req.server_url or "http://localhost:9981"]
        timeout = 600
    else:
        return JSONResponse({"error": f"Unknown suite: {req.suite}"}, status_code=400)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, cwd=str(TESTS_DIR))
        output = result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Test run timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    parsed = _parse_unittest_output(output) if req.suite == "unit" else _parse_readme_output(output)
    parsed.update(suite=req.suite, timestamp=datetime.now().isoformat(),
                  raw_output=output[-5000:])
    _test_results[req.suite] = parsed
    return parsed


# ---------------------------------------------------------------------------
# Demo API —— Chat vs Agent 对比演示
# ---------------------------------------------------------------------------

class DemoRequest(BaseModel):
    prompt: str
    working_dir: str = ""

@app.post("/api/demo/chat")
async def demo_chat(req: DemoRequest):
    """Chat 模式：无工具，单次生成。返回 SSE 流。"""
    messages = [
        {"role": "system", "content": "You are a helpful programming assistant. Answer concisely."},
        {"role": "user", "content": req.prompt}
    ]
    gen_req = GenerateRequest(messages=messages, tools=None, max_new_tokens=1024, temperature=0.3)
    return StreamingResponse(generate_stream(gen_req), media_type="text/event-stream")


@app.post("/api/demo/agent")
async def demo_agent(req: DemoRequest):
    """Agent 模式：完整 ReAct 循环（与 client.py 功能一致）。返回 SSE 流。"""
    import queue as _queue

    working_dir = req.working_dir or str(TESTS_DIR)

    def agent_stream():
        q = _queue.Queue()

        def run_client():
            try:
                from client import Client, get_tool_definitions

                # 创建 Client 获取完整工具集 + 系统提示词（与 client.py 完全一致）
                client = Client(
                    server_url=f"http://localhost:{app_port}",
                    working_dir=working_dir
                )
                tools = client.tools
                tool_defs = client.tool_definitions
                system_prompt = client.get_system_prompt()

                q.put({"type": "thought", "round": 0,
                       "content": f"Agent ready. Tools: {', '.join(tools.keys())}",
                       "tool": None, "tool_input": None})

                def call_model(messages):
                    """直接调用 generate_stream，不走 HTTP 回环。"""
                    gen_req = GenerateRequest(
                        tools=tool_defs, messages=messages,
                        max_new_tokens=2048, temperature=0.3
                    )
                    claude_response = None
                    for chunk in generate_stream(gen_req):
                        if not chunk.startswith("data: "):
                            continue
                        data = json.loads(chunk[6:].strip())
                        if data.get("done"):
                            claude_response = data.get("response")
                    return claude_response

                def execute_tool(tool_name, tool_input):
                    tool = tools.get(tool_name)
                    if not tool:
                        return f"Error: Unknown tool '{tool_name}'"
                    try:
                        return tool.execute(**tool_input)
                    except Exception as e:
                        return f"Error executing {tool_name}: {e}"

                conversation = [{"role": "user", "content": req.prompt}]
                already_nudged = False
                max_rounds = 10

                for round_num in range(1, max_rounds + 1):
                    messages = [{"role": "system", "content": system_prompt}]
                    messages.extend(conversation)

                    response = call_model(messages)
                    if response is None:
                        q.put({"type": "error", "content": "No response from model"})
                        break

                    # 提取思考文本
                    thought_parts = []
                    for block in response.get("content", []):
                        if block.get("type") == "text":
                            thought_parts.append(block.get("text", ""))
                    thought_text = " ".join(thought_parts)

                    conversation.append(response)

                    # 非 tool_use 响应
                    if response.get("stop_reason") != "tool_use":
                        # Nudge 机制（与 client.py Issue 14 一致）
                        full_text = " ".join(thought_parts)
                        check_tools = [t for t in tools.keys()
                                       if t in ("Edit", "Write", "Bash", "Grep")]
                        mentioned = [t for t in check_tools if t in full_text]

                        if mentioned and not already_nudged:
                            already_nudged = True
                            nudge = (
                                f"You described using {', '.join(mentioned)} "
                                f"but did not actually call the tool. "
                                f"Do NOT describe tool calls in text. "
                                f"You MUST invoke the tool directly. Try again."
                            )
                            q.put({"type": "thought", "round": round_num,
                                   "content": f"[NUDGE] {nudge}",
                                   "tool": None, "tool_input": None})
                            conversation.append({"role": "user", "content": nudge})
                            continue

                        # 通用 nudge：模型第一轮就不调工具（仅 round 1）
                        if not already_nudged and round_num == 1:
                            already_nudged = True
                            nudge = (
                                "You have tools available: "
                                + ", ".join(tools.keys())
                                + ". You MUST call a tool. Use Read(file_path=...) to start."
                            )
                            q.put({"type": "thought", "round": round_num,
                                   "content": f"[NUDGE] {nudge}",
                                   "tool": None, "tool_input": None})
                            conversation.append({"role": "user", "content": nudge})
                            continue

                        q.put({"type": "final", "round": round_num,
                               "content": thought_text})
                        break

                    # 执行工具调用
                    tool_results = []
                    for block in response.get("content", []):
                        if block.get("type") != "tool_use":
                            continue
                        tool_name = block["name"]
                        tool_input_data = block["input"]
                        tool_use_id = block["id"]

                        q.put({"type": "thought", "round": round_num,
                               "content": thought_text,
                               "tool": tool_name,
                               "tool_input": tool_input_data})
                        thought_text = ""

                        result = execute_tool(tool_name, tool_input_data)
                        is_error = isinstance(result, str) and result.startswith("Error")

                        q.put({"type": "tool_result", "round": round_num,
                               "tool": tool_name,
                               "result": str(result)[:2000],
                               "is_error": is_error})

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": str(result),
                            "is_error": is_error
                        })

                    # Intent reminder（与 client.py 一致）
                    intent_reminder = {
                        "type": "text",
                        "text": (f"[Reminder: user's original request was: \"{req.prompt}\". "
                                 f"Do ONLY what was asked. "
                                 f"If user asked to find/show/analyze, do NOT call Edit or Write. "
                                 f"If user asked to fix/repair, do Read → Edit → Bash then STOP.]")
                    }
                    conversation.append({
                        "role": "user",
                        "content": tool_results + [intent_reminder]
                    })
                else:
                    q.put({"type": "max_rounds", "rounds": max_rounds})

            except Exception as e:
                import traceback
                q.put({"type": "error", "content": f"{e}\n{traceback.format_exc()}"})
            finally:
                q.put(None)  # sentinel

        t = threading.Thread(target=run_client, daemon=True)
        t.start()

        while True:
            try:
                event = q.get(timeout=300)
            except _queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'content': 'Timeout'})}\n\n"
                break
            if event is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(agent_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GPU 自动检测 & vLLM 进程管理
# ---------------------------------------------------------------------------

def _detect_free_gpus(min_free_mb: int = 40000) -> List[int]:
    """检测空闲 GPU（空闲显存 > min_free_mb 的卡）。"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.free",
             "--format=csv,noheader,nounits"],
            text=True
        )
        free_gpus = []
        for line in out.strip().split("\n"):
            idx, free = line.split(",")
            if int(free.strip()) >= min_free_mb:
                free_gpus.append(int(idx.strip()))
        return free_gpus
    except Exception as e:
        print(f"Warning: cannot detect GPUs: {e}")
        return []


def _estimate_model_info(model_path: str) -> Dict[str, Any]:
    """
    读取模型信息，返回 {size_mb, is_moe, max_model_len_override} 。

    MoE 模型（如 Qwen3-30B-A3B）虽然权重大（所有 expert 都加载），
    但 KV cache 远小于同参数量 Dense（因为 hidden_size 小），
    单卡 80G 可以跑，只需限制 max_model_len。
    """
    info = {"size_mb": 0, "is_moe": False, "max_model_len_override": None}

    # 模型权重大小
    total_bytes = sum(
        os.path.getsize(os.path.join(model_path, f))
        for f in os.listdir(model_path)
        if f.endswith((".safetensors", ".bin"))
    )
    info["size_mb"] = total_bytes / (1024 * 1024)

    # 读 config.json 判断是否 MoE
    config_path = os.path.join(model_path, "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        if cfg.get("num_experts") or "moe" in cfg.get("architectures", [""])[0].lower():
            info["is_moe"] = True

    return info


def _estimate_tp_size(model_path: str, gpu_mem_mb: int = 80000) -> tuple:
    """
    根据模型大小估算 (tp_size, extra_vllm_args)。

    策略：尽量单卡跑（避免 NCCL 兼容性问题），通过 enforce-eager + max-model-len 省显存。
    只有模型权重超过单卡 95% 时才启用多卡。
    """
    info = _estimate_model_info(model_path)
    size_mb = info["size_mb"]
    extra_args = []

    # 能塞进单卡就不拆（权重 < 95% 显存）
    if size_mb < gpu_mem_mb * 0.95:
        remaining_mb = gpu_mem_mb * 0.95 - size_mb

        if remaining_mb > 30000:
            # 充裕（如 7B, 14GB 权重）：不需要额外参数
            print(f"  Model: {size_mb:.0f}MB weights, single GPU (plenty of room)")
        elif remaining_mb > 10000:
            # 中等（如 MoE 30B, 58GB 权重）：enforce-eager 省 CUDA graph，限制 context
            max_len = min(16384, max(4096, int(remaining_mb * 2)))
            extra_args = ["--gpu-memory-utilization", "0.95",
                          "--enforce-eager",
                          "--max-model-len", str(max_len)]
            print(f"  Model: {size_mb:.0f}MB weights, single GPU (eager, max_len={max_len})")
        else:
            # 紧张（如 Dense 32B, 62GB 权重）：最大限度省显存
            max_len = min(8192, max(2048, int(remaining_mb * 1.5)))
            extra_args = ["--gpu-memory-utilization", "0.95",
                          "--enforce-eager",
                          "--max-model-len", str(max_len)]
            print(f"  Model: {size_mb:.0f}MB weights, single GPU (tight, eager, max_len={max_len})")

        return 1, extra_args
    else:
        # 单卡放不下，多卡
        tp = 2
        while size_mb / tp > gpu_mem_mb * 0.70:
            tp *= 2
            if tp > 8:
                break
        print(f"  Model: {size_mb:.0f}MB weights, needs TP={tp}")
        return tp, extra_args


def _detect_tool_parser(model_path: str) -> str:
    """根据模型架构自动选择 vLLM tool call parser。"""
    config_path = os.path.join(model_path, "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        arch = (cfg.get("architectures") or [""])[0].lower()
        model_type = cfg.get("model_type", "").lower()

        if "qwen3" in arch or "qwen3" in model_type:
            # Qwen3 系列用 XML 格式：<function=Name><parameter=key>value</parameter>
            if "moe" in arch:
                return "qwen3_coder"  # Qwen3-Coder MoE
            return "qwen3_coder"      # Qwen3 全系列
        # Qwen2.5 及其他用 hermes 格式：<tool_call>{"name":...}</tool_call>
    return "hermes"


def _launch_vllm(model_path: str, port: int, gpus: List[int], tp: int,
                  extra_args: List[str] = None) -> subprocess.Popen:
    """启动 vLLM serve 子进程。"""
    gpu_str = ",".join(str(g) for g in gpus[:tp])
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = gpu_str

    parser_name = _detect_tool_parser(model_path)

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_path,
        "--port", str(port),
        "--tensor-parallel-size", str(tp),
        "--enable-auto-tool-choice",
        "--tool-call-parser", parser_name,
    ]
    if extra_args:
        cmd.extend(extra_args)

    print(f"Launching vLLM on GPU [{gpu_str}] (TP={tp}):")
    print(f"  {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, env=env, start_new_session=True)
    return proc


def _wait_for_vllm(url: str, timeout: int = 300):
    """等待 vLLM 服务就绪。"""
    print(f"Waiting for vLLM at {url} ...", end="", flush=True)
    t0 = _time.time()
    while _time.time() - t0 < timeout:
        try:
            resp = _requests.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                print(" ready!")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        _time.sleep(3)
    print(" TIMEOUT!")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Coding Agent Server — 自动启动 vLLM + 协议适配层",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 传入模型路径，自动检测 GPU 并启动 vLLM
  python model_server.py /path/to/Qwen2.5-Coder-7B-Instruct

  # 手动指定 GPU
  python model_server.py /path/to/model --gpu 5,6

  # 已有 vLLM 实例，只启动适配层
  python model_server.py --vllm-url http://localhost:8000
"""
    )
    parser.add_argument("model_path", nargs="?", default=None,
                        help="模型路径（传入则自动启动 vLLM）")
    parser.add_argument("--vllm-url", default=None,
                        help="已有 vLLM 服务的 URL（与 model_path 二选一）")
    parser.add_argument("--vllm-port", type=int, default=8000,
                        help="vLLM 服务端口 (default: 8000)")
    parser.add_argument("--gpu", default=None,
                        help="指定 GPU，如 '5,6'（默认自动检测空闲卡）")
    parser.add_argument("--port", type=int, default=9981, help="适配层端口 (default: 9981)")
    parser.add_argument("--host", default="0.0.0.0", help="适配层地址 (default: 0.0.0.0)")
    parser.add_argument("--no-trace", action="store_true",
                        help="禁用 trajectory 日志")
    args = parser.parse_args()

    if not args.model_path and not args.vllm_url:
        parser.error("需要 model_path（自动启动 vLLM）或 --vllm-url（连接已有 vLLM）")

    global VLLM_URL, VLLM_MODEL_NAME, app_port
    app_port = args.port
    vllm_proc = None

    # ── 模式 A: 传了模型路径 → 自动启动 vLLM ──────────────────────
    if args.model_path:
        model_path = os.path.abspath(args.model_path)
        if not os.path.isdir(model_path):
            print(f"Error: model path not found: {model_path}")
            sys.exit(1)

        VLLM_URL = f"http://localhost:{args.vllm_port}"

        # 检测 GPU
        if args.gpu:
            gpus = [int(g) for g in args.gpu.split(",")]
            tp = len(gpus)
            extra_args = []
            print(f"Using specified GPUs: {gpus} (TP={tp})")
        else:
            tp, extra_args = _estimate_tp_size(model_path)
            gpus = _detect_free_gpus()
            if len(gpus) < tp:
                print(f"Error: need {tp} free GPUs but only found {len(gpus)}: {gpus}")
                sys.exit(1)
            gpus = gpus[:tp]
            print(f"Auto-detected: model needs TP={tp}, using GPUs {gpus}")

        # 启动 vLLM
        vllm_proc = _launch_vllm(model_path, args.vllm_port, gpus, tp, extra_args)

        if not _wait_for_vllm(VLLM_URL):
            print("Error: vLLM failed to start. Check GPU memory / model path.")
            vllm_proc.terminate()
            sys.exit(1)

    # ── 模式 B: 连接已有 vLLM ────────────────────────────────────
    else:
        VLLM_URL = args.vllm_url.rstrip("/")

    # 获取模型名
    try:
        resp = _requests.get(f"{VLLM_URL}/v1/models", timeout=5)
        resp.raise_for_status()
        models = resp.json()["data"]
        VLLM_MODEL_NAME = models[0]["id"] if models else "default"
        print(f"Connected to vLLM at {VLLM_URL} (model: {VLLM_MODEL_NAME})")
    except Exception as e:
        print(f"Warning: Cannot connect to vLLM at {VLLM_URL}: {e}")
        VLLM_MODEL_NAME = "default"

    if not args.no_trace:
        import trajectory
        trajectory.enable()

    # 清理：Ctrl+C 时同时杀 vLLM 子进程树
    import signal
    def _shutdown(*_):
        print("\n  Shutting down...")
        if vllm_proc and vllm_proc.poll() is None:
            print("  Stopping vLLM process tree...")
            # 杀整个进程组（包括 EngineCore 子进程）
            try:
                os.killpg(os.getpgid(vllm_proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                vllm_proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(vllm_proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        sys.exit(0)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(f"Starting adapter server on {args.host}:{args.port} → vLLM at {VLLM_URL}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
