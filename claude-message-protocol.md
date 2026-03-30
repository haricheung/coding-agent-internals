# Claude Messages API 协议格式参考

> 本文档描述 Claude Messages API 的消息格式与协议机制，是理解 Claude Code 控制流的基础。课程模块一（1.2 节）和 MVP 适配层（5.2a 节）均引用本文档。

---

## 1. 基础消息结构

Claude Messages API 的核心是 **对话轮次（turns）** 的交替序列：

```
user → assistant → user → assistant → ...
```

每条消息由 `role` 和 `content` 组成。`content` 是一个 **content block 数组**，不是纯文本字符串——这是与 OpenAI Chat API 最关键的区别。

### 1.1 请求格式

```json
{
  "model": "claude-opus-4-6",
  "max_tokens": 8192,
  "system": "You are a coding assistant...",
  "tools": [ ... ],
  "messages": [
    {"role": "user", "content": "Read the file buggy_code.py"},
    {"role": "assistant", "content": [...]},
    {"role": "user", "content": [...]}
  ]
}
```

关键字段：
- `system`：系统提示（不在 messages 数组里，是顶层字段）
- `tools`：工具定义数组（JSON Schema 格式）
- `messages`：对话历史（严格 user/assistant 交替）

### 1.2 Content Block 类型

`content` 字段是一个数组，可以包含多种类型的 block：

```
┌─────────────────────────────────────────────────────┐
│  assistant 可以输出的 content block 类型：           │
│                                                     │
│  1. text        — 自然语言文本                      │
│  2. tool_use    — 工具调用请求                      │
│  3. thinking    — 扩展思维（Extended Thinking）      │
│                                                     │
│  user 可以发送的 content block 类型：                │
│                                                     │
│  1. text        — 自然语言输入                      │
│  2. tool_result — 工具执行结果                      │
│  3. image       — 图片（base64 或 URL）             │
└─────────────────────────────────────────────────────┘
```

---

## 2. 工具调用协议（Tool Use Protocol）

这是 Claude Code 的核心交互机制。一次完整的 ReAct 循环在协议层面表现为：

### 2.1 工具定义（请求时传入）

```json
{
  "tools": [
    {
      "name": "Read",
      "description": "Read a file from the filesystem",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {"type": "string", "description": "Absolute path to the file"},
          "offset": {"type": "integer", "description": "Line number to start reading from"},
          "limit": {"type": "integer", "description": "Number of lines to read"}
        },
        "required": ["file_path"]
      }
    }
  ]
}
```

### 2.2 Tool Use — 模型发起工具调用

当模型决定调用工具时，assistant 消息的 content 包含 `tool_use` block：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Let me read the file to understand the bug."
    },
    {
      "type": "tool_use",
      "id": "toolu_01A09q90qw90lq917835lh9l",
      "name": "Read",
      "input": {
        "file_path": "/path/to/buggy_code.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

关键点：
- `id`：每次工具调用的唯一标识符（`toolu_` 前缀），用于关联请求和结果
- `stop_reason: "tool_use"`：表示模型暂停等待工具结果（不是 `end_turn`）
- **一条 assistant 消息可以包含多个 `tool_use` block**（并行工具调用）
- `text` block 在 `tool_use` 之前出现时，对应 ReAct 中的 Thought

### 2.3 Tool Result — 客户端返回工具结果

客户端执行工具后，将结果封装为 `tool_result` block 发回：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_01A09q90qw90lq917835lh9l",
      "content": "1 | def calculate_sum(numbers):\n2 |     total = 0\n3 |     for i in range(len(numbers)):\n4 |         total += numbers[i + 1]  # Bug: off-by-one\n5 |     return total"
    }
  ]
}
```

关键点：
- `tool_use_id` 必须与对应的 `tool_use` block 的 `id` 匹配
- `content` 可以是字符串或 content block 数组
- 可以标记 `is_error: true` 表示工具执行出错
- **多个 `tool_result` 可以在同一条 user 消息中**（对应并行调用的结果）

### 2.4 完整的一轮 ReAct 交互

```
                    Messages API 层面                    ReAct 层面
                    ──────────────                      ──────────
用户:   "Fix the bug"                                   用户输入
                         │
                         ▼
助手:   [text: "Let me read..."]                        T (Thought)
        [tool_use: Read, id=toolu_01]                   A (Action)
        stop_reason: "tool_use"
                         │
                         ▼
用户:   [tool_result: id=toolu_01, "code..."]           O (Observation)
                         │
                         ▼
助手:   [text: "I found the bug..."]                    T (Thought)
        [tool_use: Edit, id=toolu_02]                   A (Action)
        stop_reason: "tool_use"
                         │
                         ▼
用户:   [tool_result: id=toolu_02, "ok"]                O (Observation)
                         │
                         ▼
助手:   [text: "Fixed! The issue was..."]               R (Response)
        stop_reason: "end_turn"                         循环结束
```

---

## 3. Stop Reason 信令

### 3.1 为什么叫 "stop_reason"？

这个命名揭示了一个深层事实。LLM 的本质是自回归 token 生成器——它一直在往后吐 token，直到**某个原因让它停下来**。`stop_reason` 描述的是"**模型为什么停止生成**"，而不是"模型想做什么"。命名视角是推理引擎侧，不是应用侧——推理引擎不知道什么 ReAct、什么 Agent，它只知道"我在生成 token，然后我停了，原因是 X"。

（OpenAI 的同功能字段叫 `finish_reason`，意思完全相同。）

| stop_reason | 停止原因 | 谁决定的 |
|-------------|---------|---------|
| `"end_turn"` | 模型生成了 end-of-turn token，它认为说完了 | 模型自己 |
| `"tool_use"` | 模型生成了 tool_use block，它想调工具 | 模型自己 |
| `"max_tokens"` | 撞到 token 上限，被截断了 | 外部约束 |
| `"stop_sequence"` | 命中了预设的停止序列 | 外部约束 |

### 3.2 关键洞察：模型不知道自己在"循环"

这个命名揭示了 Agent 系统最容易被误解的真相：

> **Agent 循环不是模型在驱动，是 harness 在驱动。模型每次只是做一次 completion 然后停。循环是 harness 制造的幻觉。**

模型不知道自己在"第 3 轮 ReAct 循环"——它只看到一段对话历史，做一次 next-token prediction，然后停。是 `client.py` 的 while 循环检查 `stop_reason` 来决定"要不要再喂一轮"：

```python
if stop_reason == "tool_use":    # 停下来是因为要调工具 → 执行工具，继续循环
if stop_reason == "end_turn":    # 停下来是因为说完了 → 退出循环
```

这与 Toolformer 的 token 级工具调用形成根本区别：

| 维度 | Toolformer（token 级） | Claude（API turn 级） |
|------|----------------------|---------------------|
| 中断位置 | 文本生成中间，插入 `[API_CALL]` | 完整消息结束后，`stop_reason: "tool_use"` |
| 控制流在哪 | 模型内部的自回归循环 | **harness 外部的 while 循环** |
| 对模型的要求 | 需要介入解码过程（侵入式） | 只需标准 API 调用（非侵入式） |
| 循环的本质 | 模型自己在循环 | **harness 制造的循环幻觉** |

这也是为什么 MVP 能用任意模型后端（vLLM / HuggingFace）+ adapter 层模拟出相同行为——因为控制流在 harness 侧，不在模型侧。模型只需要学会一件事：在合适的时候生成 tool_use 格式的输出。

### 3.3 ReAct 循环驱动器

**这就是 Claude Code 的 ReAct 循环驱动器：**

```python
while True:
    response = call_claude_api(messages)

    # 提取 text blocks (Thought) 和 tool_use blocks (Action)
    for block in response.content:
        if block.type == "text":
            print(block.text)              # 显示思考过程
        elif block.type == "tool_use":
            result = execute_tool(block)    # 执行工具
            tool_results.append(result)     # 收集结果

    if response.stop_reason == "end_turn":
        break                               # 任务完成，退出循环

    # 将 tool_result 作为下一轮 user 消息发回
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})
```

---

## 4. 并行工具调用（Parallel Tool Use）

模型可以在一条 assistant 消息中发起多个工具调用：

```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Let me read both files..."},
    {"type": "tool_use", "id": "toolu_01", "name": "Read", "input": {"file_path": "a.py"}},
    {"type": "tool_use", "id": "toolu_02", "name": "Read", "input": {"file_path": "b.py"}}
  ],
  "stop_reason": "tool_use"
}
```

客户端应并行执行这些工具，然后在一条 user 消息中返回所有结果：

```json
{
  "role": "user",
  "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "contents of a.py..."},
    {"type": "tool_result", "tool_use_id": "toolu_02", "content": "contents of b.py..."}
  ]
}
```

**这是 Agent Team 并行 spawn 的协议基础**——Lead 在一条消息中发出多个 `Agent` tool_use，harness 并行 spawn 多个 worker，各自完成后将结果作为多个 tool_result 一起返回。

---

## 5. Team 模式消息格式

### 5.1 Teammate Message 包裹

在 Team 模式中，Lead 发给 Worker 的消息被包裹在 `<teammate-message>` 标签中：

```xml
<teammate-message teammate_id="team-lead">
  Read the buggy_code.py file and identify all bugs. Write your findings to /tmp/team/task1-bugs.md
</teammate-message>
```

Worker 发回给 Lead 的消息也使用相同格式：

```xml
<teammate-message teammate_id="code-reviewer" color="cyan" summary="Task #1 completed">
  Found 2 bugs in buggy_code.py. Report written to /tmp/team/task1-bugs.md
</teammate-message>
```

### 5.2 SendMessage — Agent 间通信

Worker 通过 `SendMessage` 工具与 Lead 或其他 Worker 通信：

```json
{
  "type": "tool_use",
  "name": "SendMessage",
  "input": {
    "to": "team-lead",
    "message": "Task #1 completed. Found 2 bugs in buggy_code.py."
  }
}
```

广播消息（发给所有 teammate）：

```json
{
  "type": "tool_use",
  "name": "SendMessage",
  "input": {
    "to": "*",
    "message": "Heads up: I'm modifying the auth module, avoid conflicts."
  }
}
```

关闭协议：

```json
{
  "type": "tool_use",
  "name": "SendMessage",
  "input": {
    "to": "code-reviewer",
    "message": {"type": "shutdown_request"}
  }
}
```

### 5.3 Worker 系统提示差异

Worker 的系统提示额外包含 "Agent Teammate Communication" 部分：

```
You are part of an agent team. Your text output is NOT visible to the team.
To communicate with teammates, you MUST use the SendMessage tool.
To update task status, use TaskUpdate.
```

这意味着 Worker 的 `text` content block（Thought）对 Lead 不可见——只有通过 `SendMessage` 发送的消息和通过文件系统写入的内容才能被 Lead 感知。

---

## 6. 协议格式对比：Claude vs OpenAI vs Qwen 原生

| 维度 | Claude Messages API | OpenAI Chat Completions | Qwen 原生文本 |
|------|-------------------|------------------------|--------------|
| content 类型 | **typed block 数组** (`text`, `tool_use`, `tool_result`, `image`, `thinking`) | 字符串或 block 数组 | 纯文本流 |
| 工具调用 | `{type:"tool_use", id:"toolu_xxx", name:"Read", input:{...}}` | `function_call` / `tool_calls` 数组 | `<tool_call>{"name":"Read","arguments":{...}}</tool_call>` |
| 工具结果 | `{type:"tool_result", tool_use_id:"toolu_xxx", content:"..."}` | `{role:"tool", tool_call_id:"call_xxx", content:"..."}` | `<tool_response>...</tool_response>` |
| ID 关联 | `tool_use_id` 精确匹配 | `tool_call_id` 精确匹配 | **无 ID，靠位置顺序** |
| 停止信号 | `stop_reason: "tool_use" \| "end_turn"` | `finish_reason: "tool_calls" \| "stop"` | 文本层无显式信号 |
| 并行调用 | 多个 `tool_use` block 在同一条消息中 | `tool_calls` 数组中多个条目 | 多个 `<tool_call>` 标签 |
| 系统提示 | 顶层 `system` 字段（不在 messages 中） | `{role:"system"}` 消息 | 模板中的 `<|im_start|>system` |
| 扩展思维 | `{type:"thinking", thinking:"..."}` block | 无原生支持 | 无原生支持 |

---

## 7. MVP 适配层映射

我们的 MVP 使用 Qwen 模型，但客户端代码按 Claude 协议编写。适配层 (`adapter.py`) 负责双向转换：

```
Claude 格式（客户端侧）          适配层              Qwen 原生格式（模型侧）
─────────────────────         ──────              ────────────────────
tools JSON Schema      →    tools 描述注入系统提示   →   <|im_start|>system
content blocks         →    拼接为纯文本消息         →   <|im_start|>user/assistant
tool_use block         ←    解析 <tool_call> 标签   ←   模型原始输出
stop_reason: tool_use  ←    检测到工具调用标签       ←   文本中含 <tool_call>
stop_reason: end_turn  ←    未检测到工具调用         ←   纯文本输出
tool_result            →    格式化为文本回传         →   <tool_response> 标签
tool_use_id            →    adapter 自动生成并追踪   →   模型侧无 ID 概念
```

**这个适配层做的事情，本质上就是 Anthropic API 基础设施在做的事**——把模型的原始文本输出结构化为 typed content blocks。区别在于 Anthropic 用前沿模型 + 约束解码做确定性保证，我们用 Qwen + 鲁棒解析做概率性兜底。

---

*本文档版本：v1.0 | 2026-03-30 | 配套课程《掀起 AI 编程智能体的引擎盖》v3.3+*
