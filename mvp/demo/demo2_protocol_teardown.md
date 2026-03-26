# Demo 2: tool_use 协议拆解

## 演示目标

让观众看到 **tool calling 不是黑魔法，而是可审计的 JSON 请求/响应**。

通过逐层拆解 Claude tool_use 协议与 Qwen 原生格式之间的双向转换，展示：
1. 工具定义如何从一种 JSON Schema 格式映射到另一种
2. 消息（纯文本、tool_use、tool_result）如何在两种协议间转换
3. 模型原始文本输出如何被解析为结构化的 content blocks
4. 整个过程没有任何"魔法"——全是确定性的 JSON 变换

---

## 架构图

```
┌──────────┐   Claude 格式    ┌──────────────┐   Qwen 格式    ┌──────────┐
│          │  (content blocks) │              │  (chat template) │          │
│  Client  │ ───────────────→ │   Adapter    │ ───────────────→ │  Model   │
│          │                   │ (adapter.py) │                   │  (Qwen)  │
│          │ ←─────────────── │              │ ←─────────────── │          │
│          │  Claude 格式      │              │   原始文本        │          │
│          │  (typed blocks)   │  + parser.py │  (<tool_call>)   │          │
└──────────┘                   └──────────────┘                   └──────────┘
```

**核心洞察**：Adapter 做的事情，本质上就是 Anthropic API 基础设施在做的——把模型的原始文本输出结构化为 typed content blocks。区别在于：
- Anthropic 用前沿模型 + 约束解码做**确定性保证**
- 我们用 7B 模型 + 鲁棒解析做**概率性兜底**

---

## 第一层拆解：工具定义转换

### 转换规则

```
Claude 格式:  "input_schema": {...}     →  Qwen 格式:  "parameters": {...}
              平铺结构                               多一层 {"type":"function","function":{...}} 包裹
```

### 代码入口

`adapter.py` 中的 `claude_tools_to_qwen()` 函数。

### 实际运行结果

**输入：Claude 格式工具定义**

```json
[
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
      "required": [
        "file_path"
      ]
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
      "required": [
        "command"
      ]
    }
  }
]
```

**输出：Qwen/OpenAI 格式工具定义**

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

**关键差异对比**：

| 维度 | Claude 格式 | Qwen/OpenAI 格式 |
|------|------------|------------------|
| 参数字段名 | `input_schema` | `parameters` |
| 外层包裹 | 无 | `{"type": "function", "function": {...}}` |
| JSON Schema 内容 | 完全一致 | 完全一致 |

> 核心观察：两种格式承载的**语义信息完全相同**（工具名、描述、参数 Schema），只是 JSON 结构的"摆法"不同。转换是纯机械的字段重命名 + 结构重排。

---

## 第二层拆解：消息转换

### 代码入口

`adapter.py` 中的 `claude_messages_to_qwen()` 函数。

### 场景 1：纯文本消息（直接透传）

最简单的情况——`content` 是字符串，直接传递，不做任何转换。

**输入：**

```json
[
  {
    "role": "user",
    "content": "请读取 /tmp/test.py 文件"
  }
]
```

**输出：**

```json
[
  {
    "role": "user",
    "content": "请读取 /tmp/test.py 文件"
  }
]
```

> 观察：输入输出完全一致。纯文本消息在两种协议中格式相同，不需要转换。

### 场景 2：tool_use blocks --> Qwen tool_calls 结构

当 Claude 的 assistant 消息包含 `tool_use` content block 时，需要转为 Qwen 的 `tool_calls` 字段结构。

**输入（Claude 格式）：**

```json
[
  {
    "role": "assistant",
    "content": [
      {
        "type": "text",
        "text": "让我读取这个文件。"
      },
      {
        "type": "tool_use",
        "id": "toolu_abc123",
        "name": "Read",
        "input": {
          "file_path": "/tmp/test.py"
        }
      }
    ]
  }
]
```

**输出（Qwen 格式）：**

```json
[
  {
    "role": "assistant",
    "content": "让我读取这个文件。",
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

**关键差异对比：**

| 维度 | Claude 格式 | Qwen 格式 |
|------|------------|----------|
| 消息结构 | `content` 是 block 列表（text + tool_use 混合） | `content` 是纯文本，`tool_calls` 单独字段 |
| 工具参数字段 | `input` | `arguments` |
| 调用 ID | `id: "toolu_abc123"`（显式关联） | 无（靠位置顺序匹配） |

> 观察：Claude 用 `id` 精确关联 tool_use 和 tool_result，支持并发多工具调用。Qwen 的 chat template 没有显式 id 关联（靠位置顺序匹配），所以转换时 **id 信息会丢失**——这是文本层协议相比 API 层协议的固有局限。

### 场景 3：tool_result blocks --> Qwen tool role 消息

当用户消息包含 `tool_result` block（工具执行结果）时，转为 Qwen 的 `tool` 角色消息。

**输入（Claude 格式）：**

```json
[
  {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_abc123",
        "content": "def hello():\n    print(\"Hello World\")"
      }
    ]
  }
]
```

**输出（Qwen 格式）：**

```json
[
  {
    "role": "tool",
    "content": "def hello():\n    print(\"Hello World\")"
  }
]
```

**关键差异对比：**

| 维度 | Claude 格式 | Qwen 格式 |
|------|------------|----------|
| 角色 | `user`（content block 中标记 type） | `tool`（专用角色） |
| 关联方式 | `tool_use_id` 显式关联 | 无（靠消息顺序） |
| 内容 | 包裹在 block 结构中 | 直接作为 content 字符串 |

> 观察：Qwen 的 chat template 会自动把 `role: "tool"` 的消息包裹在 `<tool_response></tool_response>` 标签中。

---

## 第三层拆解：响应解析（parser 三策略）

### 架构定位

这是适配层**最核心**的部分。模型输出是原始文本，需要从中"认出"工具调用并结构化。

```
模型原始文本 → parser.py (parse_tool_calls) → ToolCall 对象列表
                                                      ↓
                                              adapter.py (qwen_response_to_claude)
                                                      ↓
                                              Claude content blocks
```

### 代码入口

`parser.py` 中的 `parse_tool_calls()` 函数，以及 `adapter.py` 中的 `qwen_response_to_claude()` 函数。

### 策略一：XML 标签解析（Qwen 原生格式，最可靠）

Qwen 模型训练时见过大量 `<tool_call>...</tool_call>` 格式，`<tool_call>` 和 `</tool_call>` 是词表中的专用 token（id 151657/151658），输出最稳定。

**输入文本：**

```
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
</tool_call>
```

**解析结果：**

```
ToolCall(tool_name="Read", parameters={"file_path": "/tmp/test.py"})
```

**转为 Claude 格式后：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_demo_abc123def456",
      "name": "Read",
      "input": {
        "file_path": "/tmp/test.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

### 策略二：代码块解析（小模型 fallback）

小模型有时会用 markdown 代码块包裹工具调用，特别是在 system prompt 的 few-shot 示例使用了代码块格式时。

**输入文本：**

````
我来帮你读取文件。
```json
{"name": "Bash", "arguments": {"command": "ls -la /tmp"}}
```
````

**解析结果：**

```
ToolCall(tool_name="Bash", parameters={"command": "ls -la /tmp"})
```

> 注意：只有策略一未命中时才尝试策略二，避免误匹配普通代码块。

### 策略三：裸 JSON 花括号配对（最后手段）

通过花括号深度配对提取 JSON 对象。最宽容但最容易误匹配，所以放在最后。

**输入文本：**

```
好的，我来执行命令。
{"name": "Bash", "arguments": {"command": "cat /etc/hostname"}}
```

**解析结果：**

```
ToolCall(tool_name="Bash", parameters={"command": "cat /etc/hostname"})
```

### 三策略优先级总结

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

### 兼容性：双格式 JSON 支持

parser 同时兼容两种 JSON 格式：

| 格式 | 工具名字段 | 参数字段 | 来源 |
|------|-----------|---------|------|
| MVP v1 自定义 | `"tool"` | `"parameters"` | 项目早期版本 |
| Qwen/OpenAI 原生 | `"name"` | `"arguments"` | 标准格式 |

**MVP v1 格式示例：**

```
<tool_call>
{"tool": "Read", "parameters": {"file_path": "/tmp/hello.py"}}
</tool_call>
```

**解析结果：**

```
ToolCall(tool_name="Read", parameters={"file_path": "/tmp/hello.py"})
```

无论输入是哪种格式，输出统一为 `ToolCall(tool_name=..., parameters=...)`。

### 鲁棒性：JSON 畸变修复

7B 模型在生成 JSON 时经常产生格式错误。parser 内置了 `_sanitize_json()` 修复常见畸变：

**尾部逗号修复：**

```
原始（非法 JSON）：{"name": "Read", "arguments": {"file_path": "/tmp/test.py",}}
修复后（合法 JSON）：{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
```

**Python 三引号字符串修复：**

```
原始："""line1\nline2"""  →  修复后："line1\\nline2"
```

### 多工具调用解析

单次响应中可以包含多个 `<tool_call>` 块，parser 会全部提取：

**输入：**

```
让我检查两个文件。
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/a.py"}}
</tool_call>
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/b.py"}}
</tool_call>
```

**解析结果：**

```
[0] ToolCall(tool_name="Read", parameters={"file_path": "/tmp/a.py"})
[1] ToolCall(tool_name="Read", parameters={"file_path": "/tmp/b.py"})
```

---

## 完整响应转换：qwen_response_to_claude

### 纯文本响应

**输入原始文本：**

```
这个文件定义了一个 hello 函数，用于打印 Hello World。
```

**输出 Claude 格式：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "这个文件定义了一个 hello 函数，用于打印 Hello World。"
    }
  ],
  "stop_reason": "end_turn"
}
```

### 包含工具调用的响应

**输入原始文本：**

```
让我读取这个文件。
<tool_call>
{"name": "Read", "arguments": {"file_path": "/tmp/test.py"}}
</tool_call>
```

**输出 Claude 格式：**

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "让我读取这个文件。"
    },
    {
      "type": "tool_use",
      "id": "toolu_demo_abc123def456",
      "name": "Read",
      "input": {
        "file_path": "/tmp/test.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

**关键设计点：**

- `<tool_call>` 之前的文本 → `{"type": "text"}` block
- `<tool_call>` 内的 JSON → `{"type": "tool_use"}` block，自动生成 `toolu_` 前缀的唯一 id
- 有 tool_use → `stop_reason: "tool_use"`（客户端据此决定是否执行工具）
- 无 tool_use → `stop_reason: "end_turn"`（对话结束）

---

## curl 命令对比：普通 chat vs tool_use 请求

### 请求 1：普通对话（无工具定义）

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

**预期响应特征：**
- `stop_reason: "end_turn"`
- 纯文本回答（模型只能"说"，不能"做"）

### 请求 2：带工具定义的对话

```bash
curl -N http://localhost:9981/generate \
  -H "Content-Type: application/json" \
  -d '{
    "tools": [
      {
        "name": "Read",
        "description": "Read the contents of a file.",
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

**预期响应特征：**
- `stop_reason: "tool_use"`
- 包含 `tool_use` content block（模型可以"做"）

### 两个请求的核心差异

```
请求 1（无 tools 字段）:
  → 模型不知道有工具可用
  → 只能用自然语言描述"我会读取文件..."
  → 这是「开环」—— 说了但做不了

请求 2（有 tools 字段）:
  → Adapter 将 tools 转为 Qwen 的 <tools> 块注入 system prompt
  → 模型知道有 Read 工具，生成 <tool_call> 调用
  → Adapter 将 <tool_call> 解析为 tool_use content block
  → 客户端执行工具，回传 tool_result
  → 这是「闭环」—— 说了就能做
```

---

## 教学要点

### tool calling = 应用层 JSON 协议，不是 tokenizer 魔法

```
传统误解：                              真实情况：
"tool calling 是模型内部的魔法"          "tool calling 是三段 JSON 变换"

                                        ① 请求时：把工具的 JSON Schema
                                           塞进上下文（像给 API 文档）

                                        ② 推理时：模型生成调用请求的 JSON
                                           （像写 API 调用代码）

                                        ③ 响应时：解析 JSON，执行工具，
                                           回传结果（像 API 网关）
```

### 关键认知

1. **没有黑魔法**：整个过程全是可审计的 JSON 请求/响应，打开 adapter.py 就能看到每一步转换
2. **协议只是"摆法"不同**：Claude 格式和 Qwen 格式承载的语义信息完全相同，只是 JSON 结构不同
3. **模型只是在"写 JSON"**：tool calling 对模型来说就是生成一段特定格式的文本，不涉及特殊的推理机制
4. **鲁棒性是工程问题**：前沿模型用约束解码保证格式正确，小模型需要 parser 兜底——但本质上做的是同一件事
5. **Adapter 就是 Anthropic 基础设施的缩影**：我们的 adapter.py + parser.py 做的事情，就是 Anthropic API 在幕后做的事情的简化版

### 一句话总结

> **Tool calling 不是模型学会了"使用工具"，而是模型学会了"生成符合约定格式的 JSON"，外围系统负责解析和执行。**

---

## 涉及的源文件

| 文件 | 职责 |
|------|------|
| `mvp/src/adapter.py` | Claude <--> Qwen 双向协议转换 |
| `mvp/src/parser.py` | 从模型原始文本中解析工具调用（三策略） |
| `mvp/src/model_server.py` | 推理服务，集成 Adapter 完成端到端流程 |
| `mvp/demo/demo2_curl_commands.sh` | curl 命令对，用于现场演示 |
