# Demo 2 录制：tool_use 协议拆解

## 演示目标

拆解工具调用协议的**三层结构**，让观众看到 tool calling 不是黑魔法，而是可审计的 JSON 变换：

1. **模型原生层**：Qwen 的 `<tool_call>` XML 格式
2. **适配层**：adapter.py 的双向转换
3. **客户端层**：Claude 的 tool_use content blocks

核心洞察：Adapter 做的事情，本质上就是 Anthropic API 基础设施在做的——把模型的原始文本输出结构化为 typed content blocks。

---

## 架构全景图

```
                    Claude 协议                              Qwen 协议
                 (content blocks)                         (chat template)

 ┌──────────┐                     ┌──────────────┐                     ┌──────────┐
 │          │   tools (Claude)    │              │   tools (Qwen)      │          │
 │  Client  │ ─────────────────→ │   Adapter    │ ─────────────────→  │  Model   │
 │          │   messages (blocks) │ (adapter.py) │   messages (text)   │  (Qwen)  │
 │          │                     │              │                     │          │
 │          │ ←───────────────── │  + parser.py │ ←─────────────────  │          │
 │          │   Claude response   │              │   raw text          │          │
 │          │   (typed blocks)    │              │   (<tool_call>)     │          │
 └──────────┘                     └──────────────┘                     └──────────┘
```

---

## Step 1：查看适配层核心代码 (adapter.py)

> **🎬 [00:00]** 打开 adapter.py，展示三个核心转换函数的签名

```bash
$ cat mvp/src/adapter.py
```

adapter.py 包含三个核心转换函数：

| 函数 | 方向 | 作用 |
|------|------|------|
| `claude_tools_to_qwen()` | Claude -> Qwen | 工具定义格式转换 |
| `claude_messages_to_qwen()` | Claude -> Qwen | 消息格式转换 |
| `qwen_response_to_claude()` | Qwen -> Claude | 模型输出解析为 content blocks |

辅助函数：

| 函数 | 作用 |
|------|------|
| `make_tool_result_message()` | 构造 Claude 格式的 tool_result 消息 |
| `is_tool_use_response()` | 判断响应是否包含工具调用 |
| `extract_tool_uses()` | 从响应中提取所有 tool_use blocks |
| `extract_text()` | 从响应中提取纯文本内容 |

> **💡 重点解说**
> adapter.py 的模块文档开头就写明了设计意图：
> _"这个适配层做的事情，本质上就是 Anthropic API 基础设施在做的——
> 把模型的原始文本输出结构化为 typed content blocks。区别是：
> Anthropic 用前沿模型 + 约束解码做确定性保证；
> 我们用 7B 模型 + 鲁棒解析做概率性兜底。"_

---

## Step 2：查看三策略解析器 (parser.py)

> **🎬 [01:30]** 打开 parser.py，展示三策略优先级

```bash
$ cat mvp/src/parser.py
```

parser.py 的核心是 `parse_tool_calls()` 函数，按优先级尝试三种解析策略：

```
策略一 XML 标签    ──命中──→ 返回结果（最可靠，Qwen 原生训练格式）
  │ 未命中
  ↓
策略二 代码块      ──命中──→ 返回结果（小模型常见替代格式）
  │ 未命中
  ↓
策略三 裸 JSON     ──命中──→ 返回结果（花括号配对，最后兜底）
  │ 未命中
  ↓
返回空列表（无工具调用）
```

核心类 `ToolCall`——统一的内部表示：

```python
class ToolCall:
    def __init__(self, tool_name: str, parameters: Dict[str, Any]):
        self.tool_name = tool_name
        self.parameters = parameters
```

兼容双 JSON 格式：

| 格式 | 工具名字段 | 参数字段 | 来源 |
|------|-----------|---------|------|
| MVP v1 自定义 | `"tool"` | `"parameters"` | 项目早期版本 |
| Qwen/OpenAI 原生 | `"name"` | `"arguments"` | 标准格式 |

> **💡 重点解说**
> 为什么需要三策略？因为 7B 模型的输出格式并不总是确定性的。
> Qwen 训练时见过 `<tool_call>` 标签格式（策略一最可靠），
> 但有时候模型可能用 markdown 代码块或者裸 JSON 输出。
> 三策略按可靠性降序排列，是"概率性兜底"的工程实现。

---

## Step 3：查看 curl 演示命令

> **🎬 [03:00]** 展示 demo2_curl_commands.sh 中的两个对比请求

```bash
$ cat mvp/demo/demo2_curl_commands.sh
```

脚本包含两个关键 curl 请求：

**请求 1：普通对话（无工具）——"开环"**

```bash
curl -N http://localhost:9981/generate \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Read the file /tmp/test.py and tell me what it does."}
    ],
    "max_new_tokens": 256,
    "temperature": 0.7
  }'
```

**请求 2：带工具定义（有 Read 工具）——"闭环"**

```bash
curl -N http://localhost:9981/generate \
  -H "Content-Type: application/json" \
  -d '{
    "tools": [
      {
        "name": "Read",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
          "type": "object",
          "properties": {
            "file_path": {
              "type": "string",
              "description": "The absolute path to the file to read"
            }
          },
          "required": ["file_path"]
        }
      }
    ],
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant. Use tools to interact with the filesystem."},
      {"role": "user", "content": "Read the file /tmp/test.py and tell me what it does."}
    ],
    "max_new_tokens": 256,
    "temperature": 0.7
  }'
```

> **💡 重点解说**
> 两个请求的唯一差别就是有没有 `tools` 字段。
> 没有 tools -> 模型只能"说"（纯文本描述）-> `stop_reason: "end_turn"`
> 有 tools -> 模型可以"做"（生成 tool_use）-> `stop_reason: "tool_use"`
> 这就是 tool calling 的全部秘密：**给模型一份"API 文档"，模型就知道该写调用代码。**

---

## Step 4：实际运行适配层转换函数

### 4.1 claude_tools_to_qwen()：工具定义转换

> **🎬 [04:30]** 运行 Python，展示工具定义从 Claude 格式到 Qwen 格式的转换

```python
import json
from adapter import claude_tools_to_qwen

claude_tools = [
    {
        "name": "Read",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to read"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "Bash",
        "description": "Execute a bash command and return its output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute"
                }
            },
            "required": ["command"]
        }
    }
]

qwen_tools = claude_tools_to_qwen(claude_tools)
print(json.dumps(qwen_tools, indent=2))
```

**真实运行输出：**

```json
[
  {
    "type": "function",
    "function": {
      "name": "Read",
      "description": "Read the contents of a file. Returns the file content with line numbers.",
      "parameters": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string",
            "description": "The absolute path to the file to read"
          }
        },
        "required": [
          "file_path"
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "Bash",
      "description": "Execute a bash command and return its output.",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string",
            "description": "The command to execute"
          }
        },
        "required": [
          "command"
        ]
      }
    }
  }
]
```

> **💡 重点解说**
> 转换是纯机械的：
> - `input_schema` -> `parameters`（字段重命名）
> - 外面包一层 `{"type": "function", "function": {...}}`（结构重排）
> - JSON Schema 内容**完全不变**
>
> 两种格式承载的语义信息完全相同，只是 JSON 结构的"摆法"不同。

**格式对比：**

```
Claude 格式                              Qwen/OpenAI 格式
─────────────                            ─────────────────
{                                        {
  "name": "Read",                          "type": "function",
  "description": "...",                    "function": {
  "input_schema": {  ◄── 字段名不同 ──►     "name": "Read",
    "type": "object",                        "description": "...",
    ...                                      "parameters": {
  }                                            "type": "object",
}                                              ...
                                             }
                                           }
                                         }
```

---

### 4.2 claude_messages_to_qwen()：消息格式转换

> **🎬 [06:00]** 运行三种消息转换场景

**场景 1：纯文本消息（直接透传）**

```python
from adapter import claude_messages_to_qwen

msgs = [{"role": "user", "content": "Read /tmp/test.py and tell me what it does."}]
result = claude_messages_to_qwen(msgs)
```

**真实运行输出：**

```json
[
  {
    "role": "user",
    "content": "Read /tmp/test.py and tell me what it does."
  }
]
```

输入输出完全一致——纯文本消息在两种协议中格式相同，无需转换。

---

**场景 2：tool_use blocks -> Qwen tool_calls**

```python
msgs = [{
    "role": "assistant",
    "content": [
        {"type": "text", "text": "Let me read that file."},
        {"type": "tool_use", "id": "toolu_abc123", "name": "Read",
         "input": {"file_path": "/tmp/test.py"}}
    ]
}]
result = claude_messages_to_qwen(msgs)
```

**真实运行输出：**

```json
[
  {
    "role": "assistant",
    "content": "Let me read that file.",
    "tool_calls": [
      {
        "function": {
          "name": "Read",
          "arguments": {
            "file_path": "/tmp/test.py"
          }
        }
      }
    ]
  }
]
```

> **💡 重点解说**
> 关键差异：
> - Claude 的 `content` 是 **block 列表**（text 和 tool_use 混在一起）
> - Qwen 的 `content` 是**纯文本**，`tool_calls` 是**单独字段**
> - Claude 的 `input` -> Qwen 的 `arguments`
> - Claude 的 `id: "toolu_abc123"` 在 Qwen 格式中**丢失**（靠位置顺序匹配）

---

**场景 3：tool_result blocks -> Qwen tool role**

```python
msgs = [{
    "role": "user",
    "content": [
        {"type": "tool_result", "tool_use_id": "toolu_abc123",
         "content": "def hello():\n    print(\"Hello World\")"}
    ]
}]
result = claude_messages_to_qwen(msgs)
```

**真实运行输出：**

```json
[
  {
    "role": "tool",
    "content": "def hello():\n    print(\"Hello World\")"
  }
]
```

> **💡 重点解说**
> 关键差异：
> - Claude: role 是 `user`，用 content block 中的 `type: "tool_result"` 标记
> - Qwen: role 直接改为 `tool`（专用角色），Qwen chat template 会自动包裹 `<tool_response>` 标签
> - `tool_use_id` 关联信息在 Qwen 格式中**丢失**

---

### 4.3 qwen_response_to_claude()：模型输出解析

> **🎬 [08:00]** 运行模型输出解析的三种场景

**场景 1：纯文本响应（无工具调用）**

```python
from adapter import qwen_response_to_claude

raw_text = "This file defines a hello function that prints Hello World."
result = qwen_response_to_claude(raw_text)
```

**真实运行输出：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "This file defines a hello function that prints Hello World."
    }
  ],
  "stop_reason": "end_turn"
}
```

---

**场景 2：包含单个工具调用的响应**

```python
raw_text = """Let me read that file for you.
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
</tool_call>"""
result = qwen_response_to_claude(raw_text)
```

**真实运行输出：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Let me read that file for you."
    },
    {
      "type": "tool_use",
      "id": "toolu_4142875d8e5848cd89cfabea",
      "name": "Read",
      "input": {
        "file_path": "/tmp/test.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

> **💡 重点解说**
> 这是适配层最核心的转换。注意发生了什么：
> 1. `<tool_call>` 之前的文本 -> `{"type": "text"}` block
> 2. `<tool_call>` 内的 JSON -> `{"type": "tool_use"}` block，自动生成 `toolu_` 前缀的唯一 id
> 3. 有 tool_use -> `stop_reason: "tool_use"`（告诉客户端需要执行工具）
>
> 模型输出的是**原始文本**，adapter 将它**结构化**为 typed content blocks。
> 这正是 Anthropic API 在幕后做的事情。

---

**场景 3：包含多个工具调用的响应**

```python
raw_text = """I will check both files.
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/a.py"}}
</tool_call>
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/b.py"}}
</tool_call>"""
result = qwen_response_to_claude(raw_text)
```

**真实运行输出：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "I will check both files."
    },
    {
      "type": "tool_use",
      "id": "toolu_e3e0567e6c0a4a6abc66301e",
      "name": "Read",
      "input": {
        "file_path": "/tmp/a.py"
      }
    },
    {
      "type": "tool_use",
      "id": "toolu_35cbb40261144b4d9eea4749",
      "name": "Read",
      "input": {
        "file_path": "/tmp/b.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

> **💡 重点解说**
> 单次响应可以包含多个 tool_use blocks，每个都有独立的 `toolu_` id。
> 这支持**并发工具调用**——客户端可以同时执行多个工具，然后分别回传结果。

---

### 4.4 make_tool_result_message()：构造工具执行结果

> **🎬 [10:00]** 运行工具结果构造

**成功结果：**

```python
from adapter import make_tool_result_message

result_msg = make_tool_result_message(
    tool_use_id="toolu_abc123def456",
    result='def hello():\n    print("Hello World")'
)
```

**真实运行输出：**

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_abc123def456",
      "content": "def hello():\n    print(\"Hello World\")",
      "is_error": false
    }
  ]
}
```

**错误结果：**

```python
error_msg = make_tool_result_message(
    tool_use_id="toolu_xyz789",
    result='FileNotFoundError: [Errno 2] No such file or directory: "/tmp/nonexistent.py"',
    is_error=True
)
```

**真实运行输出：**

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_xyz789",
      "content": "FileNotFoundError: [Errno 2] No such file or directory: \"/tmp/nonexistent.py\"",
      "is_error": true
    }
  ]
}
```

> **💡 重点解说**
> 注意 `tool_use_id` 的关联机制：
> - assistant 消息中的 `tool_use` block 有 `id: "toolu_abc123def456"`
> - user 消息中的 `tool_result` block 用 `tool_use_id: "toolu_abc123def456"` 精确关联
> - `is_error: true` 告诉模型工具执行失败，模型可以据此决定是否重试

---

## Step 5：parser 三策略实际运行

> **🎬 [11:30]** 依次演示三种解析策略

### 策略一：XML 标签（Qwen 原生，最可靠）

```python
from parser import parse_tool_calls

text = """<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
</tool_call>"""
result = parse_tool_calls(text)
```

**真实运行输出：**

```
[ToolCall(tool_name=Read, parameters={'file_path': '/tmp/test.py'})]
```

### 策略二：代码块（fallback）

```python
text = """Let me help you read the file.
```json
{"name": "Bash", "arguments": {"command": "ls -la /tmp"}}
```"""
result = parse_tool_calls(text)
```

**真实运行输出：**

```
[ToolCall(tool_name=Bash, parameters={'command': 'ls -la /tmp'})]
```

### 策略三：裸 JSON（最后手段）

```python
text = """OK, I will run the command.
{"name": "Bash", "arguments": {"command": "cat /etc/hostname"}}"""
result = parse_tool_calls(text)
```

**真实运行输出：**

```
[ToolCall(tool_name=Bash, parameters={'command': 'cat /etc/hostname'})]
```

### 双格式兼容：MVP v1 自定义格式

```python
text = """<tool_call>
{"tool": "Read", "parameters": {"file_path": "/tmp/hello.py"}}
</tool_call>"""
result = parse_tool_calls(text)
```

**真实运行输出：**

```
[ToolCall(tool_name=Read, parameters={'file_path': '/tmp/hello.py'})]
```

### 鲁棒性：JSON 尾部逗号修复

```python
text = """<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py",}}
</tool_call>"""
result = parse_tool_calls(text)
```

**真实运行输出：**

```
[ToolCall(tool_name=Read, parameters={'file_path': '/tmp/test.py'})]
```

> **💡 重点解说**
> `{"file_path": "/tmp/test.py",}` 是**非法 JSON**（尾部多余逗号），
> 但 parser 的 `_sanitize_json()` 自动修复后成功解析。
> 7B 模型经常犯这类格式错误，鲁棒解析是必须的。

---

## Step 6：端到端完整流程

> **🎬 [13:00]** 运行完整的 tool calling 往返流程

```python
from adapter import (
    claude_tools_to_qwen, claude_messages_to_qwen,
    qwen_response_to_claude, make_tool_result_message,
    is_tool_use_response, extract_tool_uses, extract_text
)
```

### 完整流程图

```
Step 1          Step 2              Step 3           Step 4           Step 5-7
Client          Adapter             Model            Adapter          Client
  │               │                   │                │                │
  │  Claude tools │                   │                │                │
  │  + messages   │                   │                │                │
  │──────────────→│  Qwen tools       │                │                │
  │               │  + messages       │                │                │
  │               │──────────────────→│                │                │
  │               │                   │  raw text      │                │
  │               │                   │  (<tool_call>) │                │
  │               │                   │───────────────→│                │
  │               │                   │                │  Claude blocks │
  │               │                   │                │  (tool_use)    │
  │←─────────────────────────────────────────────────────────────────── │
  │                                                                    │
  │  Execute tool locally                                              │
  │  Construct tool_result                                             │
  │────────────────────────────────────────────────────────────────────→│
  │                                   (next round...)                  │
```

### 实际运行

**Step 1 -- 客户端发送 Claude 格式请求：**

```json
tools: [{"name": "Read", "description": "Read a file.", "input_schema": {...}}]
messages: [{"role": "user", "content": "Read /tmp/test.py"}]
```

**Step 2 -- Adapter 转为 Qwen 格式：**

```json
qwen_tools: [{"type": "function", "function": {"name": "Read", "parameters": {...}}}]
qwen_messages: [{"role": "user", "content": "Read /tmp/test.py"}]
```

**Step 3 -- 模型生成原始文本：**

```
I will read the file for you.
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
</tool_call>
```

**Step 4 -- Adapter 解析为 Claude 格式：**

```json
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "I will read the file for you."},
    {"type": "tool_use", "id": "toolu_1d2d678a2b654d68adfda205",
     "name": "Read", "input": {"file_path": "/tmp/test.py"}}
  ],
  "stop_reason": "tool_use"
}
```

**Step 5 -- 客户端检查并提取工具调用：**

```python
is_tool_use_response(claude_response)  # True
extract_tool_uses(claude_response)     # [{"type":"tool_use", "id":"toolu_1d2d...", ...}]
extract_text(claude_response)          # 'I will read the file for you.'
```

**Step 6 -- 客户端执行工具，构造 tool_result：**

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_1d2d678a2b654d68adfda205",
      "content": "def hello():\n    print(\"Hello World\")",
      "is_error": false
    }
  ]
}
```

**Step 7 -- Adapter 转为 Qwen 格式（下一轮对话）：**

```json
[
  {
    "role": "tool",
    "content": "def hello():\n    print(\"Hello World\")"
  }
]
```

> **💡 重点解说**
> 完整往返 7 步，每一步都是确定性的 JSON 变换，没有任何"魔法"。
> 这就是 tool calling 的全部——模型在"写 JSON"，外围系统在"解析和执行"。

---

## Step 7：三层协议格式对比

> **🎬 [15:00]** 展示协议对比表

### 工具定义格式对比

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────────┐
│  Claude 客户端层                      │      │  Qwen 模型原生层                          │
│                                     │      │                                         │
│  {                                  │      │  {                                      │
│    "name": "Read",                  │ ───→ │    "type": "function",                  │
│    "description": "...",            │      │    "function": {                        │
│    "input_schema": {                │      │      "name": "Read",                    │
│      "type": "object",             │      │      "description": "...",              │
│      ...                           │      │      "parameters": {                    │
│    }                                │      │        "type": "object",               │
│  }                                  │      │        ...                             │
│                                     │      │      }                                  │
│                                     │      │    }                                    │
│                                     │      │  }                                      │
└─────────────────────────────────────┘      └─────────────────────────────────────────┘
          input_schema                                   parameters
```

### 工具调用格式对比

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────────┐
│  Claude 客户端层                      │      │  Qwen 模型原生层                          │
│                                     │      │                                         │
│  {                                  │      │  Let me read the file.                  │
│    "type": "tool_use",              │ ←─── │  <tool_call>                            │
│    "id": "toolu_abc123...",         │      │  {"name": "Read",                       │
│    "name": "Read",                  │      │   "arguments": {"file_path": "..."}}    │
│    "input": {                       │      │  </tool_call>                           │
│      "file_path": "/tmp/test.py"    │      │                                         │
│    }                                │      │                                         │
│  }                                  │      │                                         │
└─────────────────────────────────────┘      └─────────────────────────────────────────┘
     结构化 content block                           原始文本 + XML 标签
```

### 工具结果格式对比

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────────┐
│  Claude 客户端层                      │      │  Qwen 模型原生层                          │
│                                     │      │                                         │
│  {                                  │      │  <|im_start|>tool                       │
│    "role": "user",                  │ ───→ │  <tool_response>                        │
│    "content": [{                    │      │  def hello():                           │
│      "type": "tool_result",         │      │      print("Hello World")              │
│      "tool_use_id": "toolu_abc..",  │      │  </tool_response>                      │
│      "content": "def hello():..."   │      │  <|im_end|>                             │
│    }]                               │      │                                         │
│  }                                  │      │                                         │
└─────────────────────────────────────┘      └─────────────────────────────────────────┘
     typed block + id 关联                         role: tool + 位置顺序关联
```

---

## 📊 协议对比总结

### 三层结构总览

| 层次 | 格式 | 特征 | 文件 |
|------|------|------|------|
| **客户端层** | Claude tool_use content blocks | 结构化、typed、有 id 关联 | client.py 使用 |
| **适配层** | 双向 JSON 转换 | 确定性映射、鲁棒解析 | adapter.py + parser.py |
| **模型原生层** | Qwen `<tool_call>` XML | 原始文本、训练格式、概率输出 | model_server.py 处理 |

### 关键字段映射表

| 概念 | Claude 格式 | Qwen/OpenAI 格式 | 转换方向 |
|------|------------|------------------|---------|
| 工具参数 Schema | `input_schema` | `parameters` | Claude -> Qwen |
| 工具定义包裹 | 无 | `{"type":"function","function":{...}}` | Claude -> Qwen |
| 工具调用参数 | `input` | `arguments` | 双向 |
| 调用 ID | `id: "toolu_xxx"` | 无（位置顺序） | 自动生成 / 丢失 |
| 工具结果角色 | `role: "user"` + `type: "tool_result"` | `role: "tool"` | Claude -> Qwen |
| 停止原因 | `stop_reason: "tool_use"` / `"end_turn"` | 无（由 adapter 判断） | Qwen -> Claude |

### 解析策略优先级

| 优先级 | 策略 | 模式 | 可靠性 |
|--------|------|------|--------|
| 1 | XML 标签 | `<tool_call>...</tool_call>` | 最高（Qwen 原生训练格式） |
| 2 | 代码块 | `` ```json ... ``` `` | 中等（小模型常见替代） |
| 3 | 裸 JSON | `{...}` 花括号配对 | 最低（最后兜底） |

### JSON 鲁棒性处理

| 畸变类型 | 示例 | 修复方式 |
|----------|------|---------|
| 尾部逗号 | `{"key": "val",}` | 正则删除 `,` before `}` / `]` |
| Python 三引号 | `"""line1\nline2"""` | 转为 `"line1\\nline2"` |
| arguments 是字符串 | `"arguments": "{...}"` | 二次 `json.loads()` |

### 一句话总结

> **Tool calling 不是模型学会了"使用工具"，而是模型学会了"生成符合约定格式的 JSON"，外围系统（adapter + parser）负责解析和执行。我们的 adapter.py 就是 Anthropic API 基础设施的简化版——把原始文本结构化为 typed content blocks。**

---

*录制时间：2026-03-26 | 源文件：`mvp/src/adapter.py`, `mvp/src/parser.py`, `mvp/demo/demo2_curl_commands.sh`*
