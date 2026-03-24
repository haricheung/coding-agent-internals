#!/usr/bin/env python3
"""
Model Server - loads the model once and serves inference via HTTP.
Streams tokens back to clients via Server-Sent Events (SSE).

Usage:
    python model_server.py <model_path> [--port 8000]
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
from typing import List, Dict, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer


app = FastAPI()
model = None
tokenizer = None


class GenerateRequest(BaseModel):
    messages: List[Dict[str, str]]
    max_new_tokens: int = 2048
    temperature: float = 0.7


def load_model(model_path: str):
    global model, tokenizer
    print(f"Loading model from {model_path}...")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        device_map="auto"
    )
    print("Model loaded successfully!")


def generate_stream(request: GenerateRequest):
    """Generator that yields SSE events with streamed tokens."""
    text = tokenizer.apply_chat_template(
        request.messages,
        tokenize=False,
        add_generation_prompt=True
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

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
    # Final event with complete response
    yield f"data: {json.dumps({'done': True, 'full_text': full_text.strip()})}\n\n"


@app.post("/generate")
async def generate(request: GenerateRequest):
    return StreamingResponse(
        generate_stream(request),
        media_type="text/event-stream"
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": model is not None}


def main():
    parser = argparse.ArgumentParser(description="Model inference server")
    parser.add_argument("model_path", help="Path to the model")
    parser.add_argument("--port", type=int, default=9981, help="Server port (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    args = parser.parse_args()

    load_model(args.model_path)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
