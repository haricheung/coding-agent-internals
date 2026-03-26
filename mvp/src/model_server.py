#!/usr/bin/env python3
"""
Model Server —— 模型推理服务 + Claude ↔ Qwen 协议适配 + Dashboard

本服务扮演三个角色：
1. 推理引擎：加载 Qwen 模型到 GPU，通过 HTTP 提供推理服务
2. 协议适配：将客户端发来的 Claude tool_use 格式转为 Qwen 原生格式，
             推理完成后再将 Qwen 的原始输出转回 Claude 格式
3. Dashboard：提供 Web UI 展示测试结果和 agent 轨迹

架构图：
    Client ──Claude格式──→ Model Server ──Qwen格式──→ Qwen Model
                              ↑ adapter.py
    Client ←──Claude格式── Model Server ←──原始文本── Qwen Model
                              ↑
    Browser ──────────────→ /dashboard (Web UI)
                           /api/trajectories | /api/stats | /api/tests

Usage:
    python model_server.py <model_path> [--port 9981]
"""

import sys
import os
import json
import glob
import re
import time as _time
import argparse
import subprocess
from threading import Thread
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer

# vLLM lazy import (only when --backend vllm is used)
vllm_model = None  # vllm.LLM instance
BACKEND = "vllm"   # "hf" or "vllm"

from adapter import (
    claude_tools_to_qwen,
    claude_messages_to_qwen,
    qwen_response_to_claude,
)
from trajectory import trace


app = FastAPI(title="Coding Agent Model Server + Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
model = None
tokenizer = None


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
# 模型加载
# ---------------------------------------------------------------------------

def load_model(model_path: str):
    """
    加载 Qwen 模型和 tokenizer。

    支持两种后端：
    - hf: HuggingFace transformers（默认，兼容性好）
    - vllm: vLLM 引擎（3-5x 加速，推荐用于 30B+ 模型）
    """
    global model, tokenizer, vllm_model, BACKEND
    t0 = _time.time()
    print(f"Loading model from {model_path} (backend={BACKEND})...")

    if BACKEND == "vllm":
        print("  [1/2] Initializing vLLM engine...", flush=True)
        try:
            from vllm import LLM
            vllm_model = LLM(
                model=model_path,
                dtype="auto",
                trust_remote_code=True,
                max_model_len=32768,
                max_num_seqs=16,
                gpu_memory_utilization=0.90,
                enforce_eager=True,
            )
            tokenizer = vllm_model.get_tokenizer()
            print(f"  [2/2] vLLM ready! Total time: {_time.time()-t0:.1f}s", flush=True)
        except Exception as e:
            err_msg = str(e).lower()
            if "not supported" in err_msg or "not implemented" in err_msg:
                print(f"  ⚠️  vLLM does not support this model: {e}", flush=True)
                print("  Falling back to HuggingFace backend...", flush=True)
                BACKEND = "hf"
                vllm_model = None
            else:
                raise

    if BACKEND == "hf":
        print("  [1/3] Loading tokenizer...", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        print(f"  [1/3] Tokenizer ready ({_time.time()-t0:.1f}s)", flush=True)

        print("  [2/3] Loading model weights (this may take a few minutes)...", flush=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=torch.bfloat16,
            device_map="auto"
        )
        print(f"  [2/3] Model weights loaded ({_time.time()-t0:.1f}s)", flush=True)

        gpu_mem = torch.cuda.memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
        print(f"  [3/3] Model ready! GPU memory: {gpu_mem:.1f} GB | Total time: {_time.time()-t0:.1f}s", flush=True)


# ---------------------------------------------------------------------------
# 推理 + 流式输出
# ---------------------------------------------------------------------------

def generate_stream(request: GenerateRequest):
    """
    核心推理流程：Claude 格式输入 → Qwen 推理 → Claude 格式输出。

    支持两种后端：
    - hf: HuggingFace transformers（逐 token 流式）
    - vllm: vLLM 引擎（批量生成，3-5x 加速）
    """

    # ── Step 1: 入口转换 ──────────────────────────────────────────
    t0 = _time.time()

    qwen_tools = None
    if request.tools:
        qwen_tools = claude_tools_to_qwen(request.tools)

    qwen_messages = claude_messages_to_qwen(request.messages)

    trace("generate_stream: input conversion",
          tools=len(request.tools) if request.tools else 0,
          messages=len(request.messages))

    # ── Step 2: 模板渲染 ──────────────────────────────────────────
    template_kwargs = {
        "tokenize": False,
        "add_generation_prompt": True,
    }
    if qwen_tools:
        template_kwargs["tools"] = qwen_tools

    text = tokenizer.apply_chat_template(qwen_messages, **template_kwargs)

    if BACKEND == "vllm":
        # ── vLLM 路径：高速批量生成 ─────────────────────────────
        from vllm import SamplingParams
        params = SamplingParams(
            max_tokens=request.max_new_tokens,
            temperature=max(request.temperature, 0.01),
        )

        trace("generate_stream: vllm generating",
              prompt_len=len(text))

        outputs = vllm_model.generate([text], params, use_tqdm=False)
        full_text = outputs[0].outputs[0].text

        # 逐 chunk 发送（模拟流式效果）
        chunk_size = 4
        for i in range(0, len(full_text), chunk_size):
            chunk = full_text[i:i+chunk_size]
            yield f"data: {json.dumps({'token': chunk})}\n\n"

    else:
        # ── HuggingFace 路径：逐 token 流式 ─────────────────────
        inputs = tokenizer(text, return_tensors="pt").to(model.device)

        trace("generate_stream: template rendered",
              input_tokens=inputs["input_ids"].shape[-1])

        streamer = TextIteratorStreamer(
            tokenizer,
            skip_prompt=True,
            skip_special_tokens=True
        )

        gen_kwargs = dict(
            **inputs,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            streamer=streamer
        )

        thread = Thread(target=model.generate, kwargs=gen_kwargs)
        thread.start()

        full_text = ""
        for chunk in streamer:
            full_text += chunk
            yield f"data: {json.dumps({'token': chunk})}\n\n"

        thread.join()

    # ── Step 3: 出口转换 ──────────────────────────────────────────
    # 推理结束后，将 Qwen 的原始文本输出转为 Claude 格式的结构化响应
    #
    # 这一步是适配层的核心：
    # - 解析 <tool_call> 标签，提取工具名和参数
    # - 分离文本和工具调用，构造 content blocks
    # - 生成 tool_use_id 用于后续的 tool_result 关联
    # - 设置 stop_reason（tool_use / end_turn）

    t1 = _time.time()
    trace("generate_stream: raw output",
          gen_time=f"{t1-t0:.1f}s",
          output_len=len(full_text),
          preview=repr(full_text[:200]))

    claude_response = qwen_response_to_claude(full_text.strip())

    trace("generate_stream: done",
          stop_reason=claude_response.get("stop_reason"),
          content_blocks=len(claude_response.get("content", [])))

    # 发送最终的结构化响应
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
    return {"status": "ok", "model_loaded": model is not None or vllm_model is not None}


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
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Model inference server with Claude protocol adapter")
    parser.add_argument("model_path", help="Path to the Qwen model")
    parser.add_argument("--port", type=int, default=9981, help="Server port (default: 9981)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--backend", choices=["hf", "vllm"], default="vllm",
                        help="Inference backend: vllm (default, fast) or hf (HuggingFace, slower)")
    parser.add_argument("--trace", action="store_true",
                        help="Enable trajectory logging (dim [TRACE] lines)")
    args = parser.parse_args()

    global BACKEND
    BACKEND = args.backend

    if args.trace:
        import trajectory
        trajectory.enable()

    load_model(args.model_path)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
