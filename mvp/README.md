# Claude Code MVP - Day 1 Implementation

A simplified Claude Code system with tool-use capabilities, powered by a local Qwen model served via HTTP.

## Architecture

```
┌─────────────────────┐     HTTP (SSE streaming)     ┌──────────────────────┐
│   Client (main.py)  │  ──────────────────────────>  │  Model Server        │
│   - REPL            │                               │  - FastAPI + uvicorn │
│   - Tools           │  POST /generate               │  - Model loaded once │
│   - Parser          │  {messages: [...]}             │  - Streams tokens    │
│   - Conversation    │  <── SSE stream ───            │                      │
└─────────────────────┘                               └──────────────────────┘
```

The model runs as a persistent HTTP server, so clients can restart instantly without reloading the model.

## Project Structure

```
mvp/
├── src/
│   ├── model_server.py  # FastAPI model inference server
│   ├── main.py          # REPL entry point (lightweight client)
│   ├── client.py        # Client class (talks to server via HTTP)
│   ├── tools.py         # Tool implementations (Read, Write, Bash)
│   └── parser.py        # Tool call parser (XML, code blocks, plain JSON)
├── tests/
│   ├── buggy_code.py         # Test file with off-by-one bug
│   ├── test_day1_features.py # Full test suite (41 tests)
│   └── test_components.py    # Offline component tests
├── ISSUES.md
├── requirements.txt
└── README.md
```

## Installation

```bash
pip install transformers torch accelerate fastapi uvicorn requests
```

## Usage

**Terminal 1 — Start the model server (loads model once):**
```bash
cd mvp/src
python model_server.py /root/work/qlzhang/code/models/Qwen2.5-Coder-7B-Instruct
```

**Terminal 2 — Run the client (connects instantly):**
```bash
cd mvp/src
python main.py [--server http://localhost:9981] [working_dir]

# Example:
python main.py ../tests
```

**REPL commands:**
- Type a message to interact with the agent
- `reset` — clear conversation history
- `exit` — quit

## Features

- 🤖 **Streaming output**: Tokens appear in real-time as the model generates
- 🔧 **Three core tools**: Read, Write, Bash
- 🧑 **Agent behavior**: Proactively uses tools to explore files instead of asking user to paste code
- 📡 **Client-server split**: Model stays loaded across client restarts

## Tool Call Format

The parser supports multiple formats from the model:

```xml
<!-- XML tags (preferred) -->
<tool_call>
{"tool": "Read", "parameters": {"file_path": "test.py"}}
</tool_call>
```

````
```json
{"tool": "Bash", "parameters": {"command": "ls"}}
```
````

## API

**Model server endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate` | POST | Generate text (SSE streaming). Body: `{"messages": [...], "max_new_tokens": 2048}` |
| `/health` | GET | Health check. Returns `{"status": "ok", "model_loaded": true}` |

## Testing

```bash
# Offline tests (no server needed) — tests tools, parser, client structure
cd mvp/tests
python test_day1_features.py

# Full tests (start server first) — includes end-to-end model tests
python test_day1_features.py
```

## Manual Test Prompts & Expected Results

### 1. Basic Tool Usage

| # | Prompt | Expected Result |
|---|--------|----------------|
| 1.1 | `Read buggy_code.py` | 🔧 Uses Read tool, displays file contents with `calculate_sum` function |
| 1.2 | `List all files in this directory` | 🔧 Uses Bash(`ls` or `find`), shows `.py` files in working dir |
| 1.3 | `Create a file called hello.py that prints "Hello World"` | 🔧 Uses Write tool, creates `hello.py` with `print("Hello World")` |

### 2. Bug Finding & Fixing

| # | Prompt | Expected Result |
|---|--------|----------------|
| 2.1 | `Find and analyze any bugs in the code` | 🔧 Bash to list files → Read to examine → identifies off-by-one error (`numbers[i+1]` → `numbers[i]`) |
| 2.2 | `Read buggy_code.py, find the bug, and write a fixed version to fixed_code.py` | 🔧 Read → identifies bug → Write fixed version with `numbers[i]` |
| 2.3 | `Run python buggy_code.py and tell me what happens` | 🔧 Bash(`python buggy_code.py`) → reports `IndexError: list index out of range` |

### 3. Code Understanding

| # | Prompt | Expected Result |
|---|--------|----------------|
| 3.1 | `Read buggy_code.py and explain what each function does` | 🔧 Reads file → explains `calculate_sum` sums a list, `main` creates list and prints result |
| 3.2 | `What Python files are in this project? Give me a summary of each` | 🔧 Bash to list → Reads multiple files → brief summary of each |

### 4. Multi-Step Tasks

| # | Prompt | Expected Result |
|---|--------|----------------|
| 4.1 | `Read buggy_code.py, fix the bug, write the fix to fixed_v2.py, then run it to verify` | 🔧 Read → identify bug → Write → Bash(`python fixed_v2.py`) → outputs `Sum: 15` |
| 4.2 | `Explore this directory and summarize what this project does` | 🔧 Bash(`ls`) → Read a few files → summary like "test files with a buggy sum function" |

### 5. Edge Cases

| # | Prompt | Expected Result |
|---|--------|----------------|
| 5.1 | `Read a file called nonexistent.py` | 🔧 Read tool → "Error: File not found" → model reports file doesn't exist |
| 5.2 | *(empty, just press enter)* | Nothing happens, prompt re-appears |
| 5.3 | `Fix the code` | ✅ Model uses tools to discover and fix files. ❌ Asks "which code?" without trying |
| 5.4 | `What's wrong?` | ✅ Model proactively explores files. ❌ Asks user to provide context |

### 6. Conversation Memory

| # | Prompt | Expected Result |
|---|--------|----------------|
| 6.1 | `Read buggy_code.py` | 🔧 Reads and shows the file |
| 6.2 | *(follow-up)* `What's the bug in that code?` | No tool call needed — uses conversation context to explain the off-by-one error |
| 6.3 | *(follow-up)* `Now fix it` | 🔧 Uses Write tool to create fixed version (remembers which file) |
| 6.4 | `reset` then `What bug were we looking at?` | 🔄 After reset, model has no memory — should say it doesn't know or explore files |

### 7. Task Management

| # | Prompt | Expected Result |
|---|--------|----------------|
| 7.1 | `Create three tasks: read buggy_code.py, find the bug, write a fix. Then execute them one by one.` | 🔧 TaskCreate × 3 → TaskUpdate("1", "in_progress") → Read → TaskUpdate("1", "completed") → ... chains through all three |
| 7.2 | `What tasks do we have?` *(after 7.1)* | 🔧 TaskList → shows Markdown checklist with completed/pending status |
| 7.3 | `Refactor buggy_code.py: extract the loop into a helper function, add type annotations, then verify it runs` | 🔧 TaskCreate to plan steps → executes each with TaskUpdate tracking → Bash to verify |

### 8. Agent Team

| # | Prompt | Expected Result |
|---|--------|----------------|
| 8.1 | `Spawn a sub-agent to read buggy_code.py and report what it does` | 🔧 Agent(prompt="read buggy_code.py and explain...") → sub-agent runs independently → returns summary |
| 8.2 | `Create two tasks: analyze buggy_code.py for bugs, and list all files. Spawn a sub-agent for each.` | 🔧 TaskCreate × 2 → Agent(prompt=..., task_id="1") → Agent(prompt=..., task_id="2") → TaskList shows both completed |
| 8.3 | `There are multiple Python files here. Review each one for bugs in parallel.` | 🔧 TaskCreate per file → Agent per task → sub-agents run with isolated contexts → main agent summarizes findings |

### Scorecard

| Category | Tests | Key Pass Criteria |
|----------|-------|-------------------|
| Basic Tool Usage | 1.1–1.3 | Tools invoked correctly, correct output |
| Bug Finding | 2.1–2.3 | Identifies off-by-one error, produces working fix |
| Code Understanding | 3.1–3.2 | Accurate explanations, reads files first |
| Multi-Step | 4.1–4.2 | Chains multiple tools, end result is correct |
| Edge Cases | 5.1–5.4 | Handles errors gracefully, proactive not passive |
| Memory | 6.1–6.4 | Remembers context, reset clears it |
| Task Management | 7.1–7.3 | Creates tasks, tracks progress, completes all |
| Agent Team | 8.1–8.3 | Spawns sub-agents, isolated contexts, tasks auto-update |

**Minimum pass: 2.1, 2.2, 5.3 all pass** (model can find and fix bugs proactively).
