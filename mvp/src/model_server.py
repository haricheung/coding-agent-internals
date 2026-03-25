#!/usr/bin/env python3
"""
Model Server —— 模型推理服务 + Claude ↔ Qwen 协议适配

本服务在模型与客户端之间扮演两个角色：
1. 推理引擎：加载 Qwen 模型到 GPU，通过 HTTP 提供推理服务
2. 协议适配：将客户端发来的 Claude tool_use 格式转为 Qwen 原生格式，
             推理完成后再将 Qwen 的原始输出转回 Claude 格式

架构图：
    Client ──Claude格式──→ Model Server ──Qwen格式──→ Qwen Model
                              ↑ adapter.py
    Client ←──Claude格式── Model Server ←──原始文本── Qwen Model

这个适配层做的事情，本质上就是 Anthropic API 基础设施在做的：
把模型的原始文本输出结构化为 typed content blocks。
区别在于 Anthropic 有前沿模型 + 约束解码做确定性保证，
我们有 7B 模型 + 鲁棒解析做概率性兜底。

Usage:
    python model_server.py <model_path> [--port 9981]
"""

import sys
import json
import argparse
from threading import Thread

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer

from adapter import (
    claude_tools_to_qwen,
    claude_messages_to_qwen,
    qwen_response_to_claude,
)


app = FastAPI()
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
    temperature: float = 0.7


# ---------------------------------------------------------------------------
# 模型加载
# ---------------------------------------------------------------------------

def load_model(model_path: str):
    """
    加载 Qwen 模型和 tokenizer 到 GPU。

    模型只加载一次，后续请求复用。这是推理服务的基本模式——
    模型加载耗时数分钟（取决于模型大小和 GPU），但推理响应只需数秒。
    """
    global model, tokenizer
    print(f"Loading model from {model_path}...")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        device_map="auto"
    )
    print("Model loaded successfully!")


# ---------------------------------------------------------------------------
# 推理 + 流式输出
# ---------------------------------------------------------------------------

def generate_stream(request: GenerateRequest):
    """
    核心推理流程：Claude 格式输入 → Qwen 推理 → Claude 格式输出。

    处理步骤：
    1. [入口转换] Claude 格式的 tools → Qwen 格式的 function definitions
    2. [入口转换] Claude 格式的 messages → Qwen chat template 格式
    3. [模板渲染] apply_chat_template 将消息 + 工具定义渲染为模型输入
    4. [推理] 模型生成 token，通过 SSE 实时流式返回给客户端
    5. [出口转换] 完整文本 → 解析 <tool_call> → Claude content blocks

    流式输出设计：
    - 推理过程中：逐 token 发送 {"token": "..."} 事件（客户端实时打印）
    - 推理结束后：发送 {"done": true, "response": {...}} 事件
      其中 response 是 Claude 格式的结构化响应（content blocks）

    这样客户端同时获得：
    - 实时 token 流（Live Demo 的视觉效果）
    - 结构化响应（工具调用的可靠解析）
    """

    # ── Step 1: 入口转换 ──────────────────────────────────────────
    # 将 Claude 格式转为 Qwen 格式

    # 转换工具定义
    qwen_tools = None
    if request.tools:
        qwen_tools = claude_tools_to_qwen(request.tools)

    # 转换消息（处理 content blocks → 纯文本 + tool_calls 结构）
    qwen_messages = claude_messages_to_qwen(request.messages)

    # ── Step 2: 模板渲染 ──────────────────────────────────────────
    # Qwen 的 chat template (Jinja2) 会自动处理：
    # - 如果有 tools：在 system prompt 中注入 <tools></tools> 块和格式说明
    # - tool_calls 在 assistant 消息中渲染为 <tool_call></tool_call>
    # - tool role 消息渲染为 <tool_response></tool_response>
    #
    # 这就是"顺应模型训练分布"的关键——用模型训练时见过的格式，
    # 而非 system prompt 硬教的自定义格式

    template_kwargs = {
        "tokenize": False,
        "add_generation_prompt": True,
    }
    if qwen_tools:
        template_kwargs["tools"] = qwen_tools

    text = tokenizer.apply_chat_template(qwen_messages, **template_kwargs)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    # ── Step 3: 流式推理 ──────────────────────────────────────────
    # TextIteratorStreamer 让我们在生成过程中逐 token 读取输出，
    # skip_prompt=True 跳过输入部分，skip_special_tokens=True 跳过 <|im_end|> 等

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

    # 在后台线程中运行生成，主线程通过 streamer 迭代读取 token
    thread = Thread(target=model.generate, kwargs=gen_kwargs)
    thread.start()

    # ── Step 4: 逐 token 流式输出 ────────────────────────────────
    full_text = ""
    for chunk in streamer:
        full_text += chunk
        # 实时发送每个 token 给客户端（SSE 格式）
        # 客户端收到后立即打印到终端，营造"模型在思考"的视觉效果
        yield f"data: {json.dumps({'token': chunk})}\n\n"

    thread.join()

    # ── Step 5: 出口转换 ──────────────────────────────────────────
    # 推理结束后，将 Qwen 的原始文本输出转为 Claude 格式的结构化响应
    #
    # 这一步是适配层的核心：
    # - 解析 <tool_call> 标签，提取工具名和参数
    # - 分离文本和工具调用，构造 content blocks
    # - 生成 tool_use_id 用于后续的 tool_result 关联
    # - 设置 stop_reason（tool_use / end_turn）

    claude_response = qwen_response_to_claude(full_text.strip())

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
    return {"status": "ok", "model_loaded": model is not None}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Model inference server with Claude protocol adapter")
    parser.add_argument("model_path", help="Path to the Qwen model")
    parser.add_argument("--port", type=int, default=9981, help="Server port (default: 9981)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    args = parser.parse_args()

    load_model(args.model_path)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
