# Demo 1: Chat vs Agent -- 开环与闭环的区别

> **演示目标**：在 30 秒内让观众直观感受「纯对话 Chat」和「工具增强 Agent」的本质区别。
> 核心观点：Agent 的价值不在于"生成能力更强"，而在于"能验证自己的输出"。

---

## 一、场景设定

我们有一个包含 bug 的 Python 文件 `buggy_code.py`：

```python
"""
A simple Python file with a bug for testing Day 1
"""

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total


def main():
    nums = [1, 2, 3, 4, 5]
    result = calculate_sum(nums)
    print(f"Sum: {result}")


if __name__ == "__main__":
    main()
```

**Bug 说明**：`numbers[i + 1]` 存在越界错误（off-by-one）。当 `i = len(numbers) - 1` 时，`i + 1` 超出列表索引范围，会抛出 `IndexError`。正确写法应该是 `numbers[i]`。

**用户指令**：「帮我修复 buggy_code.py 中的 bug」

下面我们分别看 Chat 模式和 Agent 模式如何处理这个任务。

---

## 二、Chat 模式（开环）

### 2.1 请求构造

Chat 模式下，请求中 **没有 tools 字段**，模型只能生成文本：

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful programming assistant."
    },
    {
      "role": "user",
      "content": "帮我修复 buggy_code.py 中的 bug，文件内容如下：\n\ndef calculate_sum(numbers):\n    total = 0\n    for i in range(len(numbers)):\n        total += numbers[i + 1]  # Bug: off-by-one error\n    return total\n"
    }
  ]
}
```

> **注意**：用户不得不自己打开文件、复制代码、粘贴到对话框中。模型没有能力自己去读文件。

### 2.2 模型响应（纯文本）

```json
{
  "role": "assistant",
  "content": "我发现了代码中的 bug！在第 9 行：\n\n```python\ntotal += numbers[i + 1]  # Bug: off-by-one error\n```\n\n这里 `i + 1` 会导致索引越界。当 `i` 等于 `len(numbers) - 1`（即最后一个元素）时，`i + 1` 就超出了列表范围。\n\n**修复方法**：将 `numbers[i + 1]` 改为 `numbers[i]`：\n\n```python\ntotal += numbers[i]\n```\n\n请手动修改文件并重新运行测试。",
  "stop_reason": "end_turn"
}
```

### 2.3 开环标注

```
┌──────────────────────────────────────────────────────────────────┐
│                    Chat 模式 = 开环系统                          │
│                                                                  │
│  用户 ──(贴代码)──→ 模型 ──(说文本)──→ 用户                      │
│                                                                  │
│  ● 模型无法自己读取文件（需要用户复制粘贴）                        │
│  ● 模型无法自己修改文件（只能告诉用户怎么改）                      │
│  ● 模型无法自己验证修复（"请手动运行测试"）                        │
│  ● 如果模型的建议是错的，它自己不知道                              │
│                                                                  │
│  输出后就结束了，没有反馈回路 → 这就是「开环」                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、Agent 模式（闭环）

### 3.1 请求构造

Agent 模式下，请求携带 **tools 定义**（从 `client.py` 的 `get_tool_definitions` 生成）：

```json
{
  "tools": [
    {
      "name": "Read",
      "description": "Read the contents of a file at the given path.",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string",
            "description": "Absolute path to the file to read"
          }
        },
        "required": ["file_path"]
      }
    },
    {
      "name": "Edit",
      "description": "Make precise text replacements in a file.",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string",
            "description": "Absolute path to the file to edit"
          },
          "old_string": {
            "type": "string",
            "description": "The exact text to find and replace"
          },
          "new_string": {
            "type": "string",
            "description": "The replacement text"
          }
        },
        "required": ["file_path", "old_string", "new_string"]
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
            "description": "The bash command to execute"
          }
        },
        "required": ["command"]
      }
    }
  ],
  "messages": [
    {
      "role": "system",
      "content": "You are a coding agent that helps users with software engineering tasks.\nYou work inside a codebase and use tools to read, write, search, and execute code.\n\nWorking directory: /root/work/project\n\nFiles in this project:\n  project/\n    tests/\n      buggy_code.py\n\nTOOL USAGE RULES:\n1. ALWAYS use tools to act. Never just describe what you would do.\n2. NEVER ask the user to paste code or upload files.\n..."
    },
    {
      "role": "user",
      "content": "帮我修复 buggy_code.py 中的 bug"
    }
  ]
}
```

> **注意**：用户只需要说「修复 bug」，不需要贴代码。模型会自己去读文件。

### 3.2 Agent 的 ReAct 循环

Agent 会进入 Thought-Action-Observation 循环（即 client.py 中 `run()` 方法的 `while round_num < max_rounds` 循环）。以下是完整的多轮交互过程：

---

#### Round 1: 读取文件

**Thought（模型的推理文本）**：

> 用户要我修复 buggy_code.py 的 bug。我先读取文件内容来了解代码。

**Action（模型发出 tool_use 请求）**：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "让我先读取 buggy_code.py 的内容来了解代码。"
    },
    {
      "type": "tool_use",
      "id": "toolu_abc123def456",
      "name": "Read",
      "input": {
        "file_path": "/root/work/project/tests/buggy_code.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

> `stop_reason: "tool_use"` -- 客户端检测到这个信号，知道模型在请求调用工具，于是执行 Read 工具。

**Observation（工具执行结果，由客户端回传给模型）**：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_abc123def456",
      "content": "\"\"\"\\nA simple Python file with a bug for testing Day 1\\n\"\"\"\\n\\ndef calculate_sum(numbers):\\n    \"\"\"Calculate the sum of a list of numbers\"\"\"\\n    total = 0\\n    for i in range(len(numbers)):\\n        total += numbers[i + 1]  # Bug: off-by-one error\\n    return total\\n\\n\\ndef main():\\n    nums = [1, 2, 3, 4, 5]\\n    result = calculate_sum(nums)\\n    print(f\"Sum: {result}\")\\n\\n\\nif __name__ == \"__main__\":\\n    main()\\n",
      "is_error": false
    }
  ]
}
```

> `tool_use_id` 将 tool_result 与前面的 tool_use 精确关联。这条消息以 `role: "user"` 自动回传给模型，模型现在「看到」了文件内容。

---

#### Round 2: 分析 bug 并修复

**Thought（模型分析 bug）**：

> 我看到第 9 行 `total += numbers[i + 1]` 有越界错误。当 i 等于最后一个索引时，i+1 超出范围。应该改为 `numbers[i]`。我用 Edit 工具精确修复。

**Action（模型发出 Edit 工具调用）**：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "找到了 bug：第 9 行的 `numbers[i + 1]` 存在 off-by-one 越界错误。当 i 为最后一个索引时，i+1 会超出列表范围。我来修复它。"
    },
    {
      "type": "tool_use",
      "id": "toolu_789ghi012jkl",
      "name": "Edit",
      "input": {
        "file_path": "/root/work/project/tests/buggy_code.py",
        "old_string": "        total += numbers[i + 1]  # Bug: off-by-one error",
        "new_string": "        total += numbers[i]"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

> `stop_reason: "tool_use"` -- 客户端再次检测到工具调用请求，执行 Edit 工具。

**Observation（编辑结果回传）**：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_789ghi012jkl",
      "content": "Successfully edited /root/work/project/tests/buggy_code.py",
      "is_error": false
    }
  ]
}
```

> 文件已实际修改成功。模型收到了来自环境的正向反馈。

---

#### Round 3: 运行验证

**Thought（模型决定验证修复）**：

> 修复完成，但我需要运行代码验证修复是否正确。这是 L-R-V（Localize-Repair-Validate）工作流的最后一步。

**Action（模型发出 Bash 工具调用）**：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "编辑成功。让我运行代码来验证修复是否正确。"
    },
    {
      "type": "tool_use",
      "id": "toolu_345mno678pqr",
      "name": "Bash",
      "input": {
        "command": "cd /root/work/project && python tests/buggy_code.py"
      }
    }
  ],
  "stop_reason": "tool_use"
}
```

**Observation（运行结果回传）**：

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_345mno678pqr",
      "content": "Sum: 15",
      "is_error": false
    }
  ]
}
```

> `Sum: 15` -- 即 1+2+3+4+5=15，结果正确！模型现在有了**实际执行**的证据来确认修复有效。

---

#### Round 4: 总结报告

**Thought（模型确认完成）**：

> 运行输出 Sum: 15 是正确的（1+2+3+4+5=15）。Bug 已修复并验证通过，任务完成。

**Action（无工具调用，返回最终总结）**：

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Bug 已修复并验证通过！\n\n问题：`calculate_sum` 函数中的 `numbers[i + 1]` 存在 off-by-one 越界错误。\n修复：将 `numbers[i + 1]` 改为 `numbers[i]`。\n验证：运行输出 `Sum: 15`（1+2+3+4+5=15），结果正确。"
    }
  ],
  "stop_reason": "end_turn"
}
```

> `stop_reason: "end_turn"` -- 客户端检测到模型认为任务已完成，退出 ReAct 循环。

### 3.3 闭环标注

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Agent 模式 = 闭环系统                              │
│                                                                      │
│  用户 ──(自然语言指令)──→ 模型                                       │
│                            ↓                                         │
│                     ┌──────────────────┐                             │
│                     │  ReAct 循环       │                             │
│                     │                  │                              │
│                     │  Round 1:        │                              │
│                     │  Thought → Read  │──→ 环境 ──→ 文件内容        │
│                     │     ↑            │           │                  │
│                     │     └────────────│───────────┘                  │
│                     │                  │                              │
│                     │  Round 2:        │                              │
│                     │  Thought → Edit  │──→ 环境 ──→ 编辑成功        │
│                     │     ↑            │           │                  │
│                     │     └────────────│───────────┘                  │
│                     │                  │                              │
│                     │  Round 3:        │                              │
│                     │  Thought → Bash  │──→ 环境 ──→ Sum: 15         │
│                     │     ↑            │           │                  │
│                     │     └────────────│───────────┘                  │
│                     │                  │                              │
│                     │  Round 4:        │                              │
│                     │  总结 → end_turn │                              │
│                     └──────────────────┘                             │
│                            ↓                                         │
│                     返回最终结果给用户                                 │
│                                                                      │
│  ● 模型自己读取文件（不需要用户复制粘贴）                              │
│  ● 模型自己修改文件（不是告诉用户怎么改，而是直接改）                   │
│  ● 模型自己运行验证（用 Bash 工具执行代码，确认结果正确）              │
│  ● 如果修复有误，它能从 Observation 中发现并重试                       │
│                                                                      │
│  每一步都有反馈回路：Action → Observation → 下一步 Thought             │
│  这就是「闭环」                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 四、对比总结

| 维度 | Chat 模式（开环） | Agent 模式（闭环） |
|------|-------------------|-------------------|
| **交互方式** | 用户贴代码 → 模型说文本 → 用户手动操作 | 用户说指令 → 模型自主操作 → 自动验证 |
| **请求结构** | 无 `tools` 字段，只有 `messages` | 有 `tools` 定义 + `messages` |
| **模型能力** | 只能「说」（生成文本） | 能「说」也能「做」（调用工具） |
| **stop_reason** | 永远是 `end_turn` | `tool_use`（继续循环）或 `end_turn`（结束） |
| **反馈回路** | 无。输出后就结束了 | 有。Observation 回传给模型作为下一步输入 |
| **错误发现** | 模型不知道自己的建议是否正确 | 模型能通过 Bash 运行代码发现错误 |
| **错误修复** | 需要用户发现错误、再次提问 | 模型自动在循环中重试修复 |
| **对应概念** | 单轮文本生成 | ReAct 循环（Thought-Action-Observation） |
| **类比** | 纸上谈兵的参谋 | 下场动手的工程师 |

---

## 五、教学要点

### 核心观点

> **Agent 的核心价值不是「更强的生成能力」，而是「能验证自己输出的能力」。**

### 展开解释

1. **同一个模型，不同的能力边界**

   Chat 模式和 Agent 模式背后可以是**完全相同的模型**。区别不在于模型本身"变聪明了"，而在于系统架构给了模型不同的能力：
   - Chat 模式：模型只能生成文本，没有任何与外部环境交互的手段
   - Agent 模式：模型可以通过工具读取文件、修改代码、执行命令

2. **开环系统的根本缺陷**

   Chat 模式是开环系统：模型输出后就结束了，没有任何反馈信号告诉它输出是否正确。这意味着：
   - 如果模型的分析有误（比如误判了 bug 的原因），它不会知道
   - 如果模型的修复建议有误（比如引入了新的 bug），它不会知道
   - 所有的验证工作都推给了人类用户

3. **闭环系统的关键机制：Observation**

   Agent 模式之所以是闭环，关键在于 **Observation（工具执行结果）会回传给模型**：
   - Round 1 的 Observation（文件内容）让模型真正「看到」了代码
   - Round 2 的 Observation（编辑成功）确认修改已落地
   - Round 3 的 Observation（运行结果 `Sum: 15`）提供了最终验证

   如果 Round 3 的结果是 `IndexError`，模型会从这个 Observation 中**意识到修复有问题**，然后在下一轮重新分析、修复、验证——这就是闭环的自我纠错能力。

4. **stop_reason 是循环的控制信号**

   在 `client.py` 的 `run()` 方法中，循环的退出条件是：
   ```python
   if response.get("stop_reason") != "tool_use":
       return None  # 模型认为任务完成，退出循环
   ```
   - `stop_reason: "tool_use"` → 模型还需要调用工具 → 继续循环
   - `stop_reason: "end_turn"` → 模型认为任务完成 → 退出循环

   **模型自己决定何时停止**——这是 Agent 自主性的体现。

5. **工程启示**

   从 Chat 到 Agent 的升级，核心改动其实很小：
   - 请求中加入 `tools` 定义
   - 客户端增加一个循环：检测 `tool_use` → 执行工具 → 回传 `tool_result`
   - 这就是 `client.py` 中 `run()` 方法的 `while` 循环

   但这个小改动带来的能力跃迁是巨大的：模型从「只能说」变成了「能做、能看、能验证」。

### 一句话总结

> **Chat = 模型说，人来做。Agent = 模型说了自己做，做完自己查，查出问题自己修。**

---

## 六、代码映射

本演示中的概念与代码库的对应关系：

| 概念 | 代码位置 | 关键函数/变量 |
|------|---------|-------------|
| 工具定义 | `mvp/src/client.py` | `get_tool_definitions()` |
| ReAct 循环 | `mvp/src/client.py` | `Client.run()` 中的 `while round_num < max_rounds` |
| 工具执行 | `mvp/src/client.py` | `Client._execute_tool()` |
| stop_reason 检测 | `mvp/src/client.py` | `response.get("stop_reason") != "tool_use"` |
| tool_result 回传 | `mvp/src/client.py` | `self.conversation.append({"role": "user", "content": tool_results})` |
| 协议适配 | `mvp/src/adapter.py` | `qwen_response_to_claude()` 将原始文本转为 content blocks |
| 测试用例 | `mvp/tests/buggy_code.py` | `calculate_sum()` 的 off-by-one bug |
