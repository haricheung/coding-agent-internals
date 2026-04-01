# Demo 3: 完整 Bug 修复流程 -- L-R-V 循环实战

## 演示目标

完整展示一个编程 Agent 如何通过 **Localization -> Repair -> Validation (L-R-V)** 循环自动修复代码中的 bug。每一步都使用项目中实现的真实工具（ReadTool / GrepTool / EditTool / BashTool），所有 Observation 均为真实运行结果。

本演示对应课程模块三（多轮纠错与防死循环）的核心内容，重点展示 **Orient 环节**——Agent 如何从测试报错中学习并做出正确判断。

---

## v2 演示文件（Lecture 3 主用）

**目标文件**: `mvp/tests/buggy_calc.py` + `mvp/tests/test_buggy_calc.py`

一个成绩统计函数，包含**两个独立的 bug**：
- Bug 1: `avg = sum(scores) / (len(scores) - 1)` — 除数错误
- Bug 2: `s > 60` — 及格线边界错误（应为 `>= 60`）

**两阶段失败模式**：
1. 初始运行：3 个测试失败（average + pass_rate + all_pass）
2. 修 Bug 1 后：average 通过，但 pass_rate 仍然失败 → **这是 Orient 时刻**
3. 修 Bug 2 后：全部 6 个测试通过

**演示指令**: `"buggy_calc.py 有 bug，帮我修"`

**教学重点**: 每次 Validation 失败后，暂停标注模型的 Thought——这条 Thought 就是 Orient，它决定了 Agent 是走向修复还是走向死循环。

---

## v1 演示记录（Lecture 1 原始 Demo，保留作为参考）

**目标文件**: `mvp/tests/buggy_code.py`

```python
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total
```

**Bug 类型**: Off-by-one 错误（数组越界）

**症状**: 当 `i` 到达最后一个索引时，`i + 1` 超出数组边界，抛出 `IndexError: list index out of range`

**预期行为**: `calculate_sum([1, 2, 3, 4, 5])` 应返回 `15`

---

## 完整 ReAct 循环记录

### ══════ Round 1 ══════

**Phase: Localization (定位阶段)**

🧠 **Thought (模型推理)**:
用户报告代码运行时出错。我需要先读取目标文件，了解代码结构和可能的 bug 位置。让我用 ReadTool 读取 `buggy_code.py` 的完整内容。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Read",
  "input": {
    "file_path": "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
 1 | """
 2 | A simple Python file with a bug for testing Day 1
 3 | """
 4 |
 5 | def calculate_sum(numbers):
 6 |     """Calculate the sum of a list of numbers"""
 7 |     total = 0
 8 |     for i in range(len(numbers)):
 9 |         total += numbers[i + 1]  # Bug: off-by-one error
10 |     return total
11 |
12 |
13 | def main():
14 |     nums = [1, 2, 3, 4, 5]
15 |     result = calculate_sum(nums)
16 |     print(f"Sum: {result}")
17 |
18 |
19 | if __name__ == "__main__":
20 |     main()

[20 lines total]
```

📍 **L-R-V 阶段**: Localization（粗粒度定位 -- 读取全文建立代码地图）
📍 **OODA 对应**: Observe（观察 -- 收集原始信息）

---

### ══════ Round 2 ══════

**Phase: Localization (精确定位)**

🧠 **Thought (模型推理)**:
文件不大，我已读取全文。第 9 行的注释暗示有 bug。但在真实场景中，Agent 不会依赖注释，它需要通过模式搜索来定位可疑代码。让我用 GrepTool 搜索 `i + 1` 模式 -- 这是一个典型的 off-by-one 嫌疑模式。同时搜索 `range(len` 模式，这种写法本身就是 code smell。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Grep",
  "input": {
    "pattern": "i \\+ 1",
    "path": "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py:9:         total += numbers[i + 1]  # Bug: off-by-one error

[1 matches found]
```

🔧 **Action (补充搜索)**:
```json
{
  "tool": "Grep",
  "input": {
    "pattern": "range\\(len",
    "path": "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py:8:     for i in range(len(numbers)):

[1 matches found]
```

📍 **L-R-V 阶段**: Localization（细粒度定位 -- 精确到行号）
📍 **OODA 对应**: Orient（定向 -- 分析信息，形成假设）

---

### ══════ Round 3 ══════

**Phase: Localization (确认错误)**

🧠 **Thought (模型推理)**:
让我先运行这段代码，确认错误现象。这样我可以明确知道 bug 的表现是什么。这对应 L-R-V 中的 "确认重现" 步骤。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Bash",
  "input": {
    "command": "python3 buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
STDERR: Traceback (most recent call last):
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 20, in <module>
    main()
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 15, in main
    result = calculate_sum(nums)
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 9, in calculate_sum
    total += numbers[i + 1]  # Bug: off-by-one error
IndexError: list index out of range

Return code: 1
```

📍 **L-R-V 阶段**: Localization（错误确认 -- 重现问题，确认假设）
📍 **OODA 对应**: Orient（定向 -- Traceback 确认了第 9 行是 bug 源头）

---

### ══════ Round 4 ══════

**Phase: Repair (修复阶段)**

🧠 **Thought (模型推理)**:
现在我完全理解了这个 bug：

- 第 8 行：`for i in range(len(numbers))` -- `i` 的范围是 `0` 到 `len(numbers)-1`
- 第 9 行：`numbers[i + 1]` -- 当 `i = len(numbers)-1` 时，`i+1 = len(numbers)`，越界！
- 修复方案：将 `numbers[i + 1]` 改为 `numbers[i]`

这是经典的 off-by-one 错误。让我用 EditTool 精确替换。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Edit",
  "input": {
    "file_path": "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py",
    "old_string": "        total += numbers[i + 1]  # Bug: off-by-one error",
    "new_string": "        total += numbers[i]  # Fixed: use correct index"
  }
}
```

📋 **Observation (执行结果)**:
```
Successfully edited /root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py
Replaced: "        total += numbers[i + 1]  # Bug: off-by-one error"
    With: "        total += numbers[i]  # Fixed: use correct index"
```

📍 **L-R-V 阶段**: Repair（修复 -- 应用代码变更）
📍 **OODA 对应**: Decide + Act（决策 + 行动 -- 选择修复方案并执行）

---

### ══════ Round 5 ══════

**Phase: Validation (验证阶段)**

🧠 **Thought (模型推理)**:
修复已应用。现在我需要验证两件事：(1) 代码语法正确，(2) 运行结果符合预期。让我先用 ReadTool 确认修改内容，然后运行代码验证。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Read",
  "input": {
    "file_path": "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
 1 | """
 2 | A simple Python file with a bug for testing Day 1
 3 | """
 4 |
 5 | def calculate_sum(numbers):
 6 |     """Calculate the sum of a list of numbers"""
 7 |     total = 0
 8 |     for i in range(len(numbers)):
 9 |         total += numbers[i]  # Fixed: use correct index
10 |     return total
11 |
12 |
13 | def main():
14 |     nums = [1, 2, 3, 4, 5]
15 |     result = calculate_sum(nums)
16 |     print(f"Sum: {result}")
17 |
18 |
19 | if __name__ == "__main__":
20 |     main()

[20 lines total]
```

📍 **L-R-V 阶段**: Validation（验证 -- 检查修改内容）
📍 **OODA 对应**: Observe（观察 -- 确认代码变更正确写入）

---

### ══════ Round 6 ══════

**Phase: Validation (运行验证)**

🧠 **Thought (模型推理)**:
代码修改看起来正确。让我运行它验证输出是否为预期的 `Sum: 15`（1+2+3+4+5=15）。

🔧 **Action (工具调用)**:
```json
{
  "tool": "Bash",
  "input": {
    "command": "python3 buggy_code.py"
  }
}
```

📋 **Observation (执行结果)**:
```
Sum: 15
```

✅ **验证通过！** 输出 `Sum: 15`，与预期一致。Bug 修复成功。

📍 **L-R-V 阶段**: Validation（验证通过 -- 循环结束）
📍 **OODA 对应**: Observe（观察运行结果） -> 确认修复有效，退出循环

---

## 修复前后代码对比 (diff)

```diff
--- buggy_code.py (修复前)
+++ buggy_code.py (修复后)
@@ -6,7 +6,7 @@
     """Calculate the sum of a list of numbers"""
     total = 0
     for i in range(len(numbers)):
-        total += numbers[i + 1]  # Bug: off-by-one error
+        total += numbers[i]  # Fixed: use correct index
     return total
```

**变更分析**：
- 仅修改 1 行代码
- 移除了错误的 `+ 1` 偏移
- 修改量极小，精确命中 bug

---

## 验证结果汇总

| 测试项 | 修复前 | 修复后 |
|--------|--------|--------|
| 运行 `calculate_sum([1,2,3,4,5])` | `IndexError: list index out of range` | `Sum: 15` |
| 退出码 | 1（失败） | 0（成功） |
| 是否抛异常 | 是（IndexError） | 否 |

---

## 教学要点

### 1. L-R-V 三阶段如何映射到 ReAct 循环

L-R-V 不是独立于 ReAct 的另一套框架，而是 ReAct 在 bug 修复场景下的**具体实例化**：

```
ReAct 循环:    Thought  ->  Action  ->  Observation  ->  Thought  -> ...
                  |            |            |
L-R-V 阶段:      |            |            |
                  |            |            |
  Localization:   "代码可能     Read/Grep    "第9行有
                   有越界问题"   读取代码      i+1 的写法"

  Repair:         "应该把       Edit         "替换成功"
                   i+1改成i"    替换代码

  Validation:     "需要运行     Bash         "Sum: 15
                   确认修复"    执行代码       验证通过"
```

**映射关系**：
- **Localization = 多轮 Thought+Action(Read/Grep)+Observation** -- 定位阶段可能需要多次工具调用
- **Repair = 一轮 Thought+Action(Edit)+Observation** -- 修复通常是单次精确操作
- **Validation = 一轮 Thought+Action(Bash)+Observation** -- 运行测试确认结果

### 2. Circuit Breaker（断路器）的作用

在本演示中，Agent 一次修复就成功了。但如果 Agent 进入了错误的修复方向怎么办？

**Circuit Breaker 机制**：
```
设定最大循环次数（例如 max_rounds = 10）

while round < max_rounds:
    result = execute_one_round()
    if validation_passed(result):
        return SUCCESS
    round += 1

return FAILURE  # Circuit Breaker 触发：超过最大轮次，停止尝试
```

**为什么需要 Circuit Breaker**：
- **防止无限循环**: 模型可能反复尝试错误的修复方案，永远通不过验证
- **防止 token 浪费**: 每一轮都消耗 API tokens，无限循环会烧钱
- **及时止损**: 超过阈值后应该返回失败，由人类介入

**我们 MVP 的实现**: 在 `client.py` 中通过 `max_rounds` 参数控制，默认值为 10。

### 3. 如果模型第一次修复失败会怎样（Reflexion 双循环）

假设模型在 Round 4 做了一个错误的修复：

```
══════ Round 4 (错误修复) ══════

🧠 Thought: 也许应该把 range(len(numbers)) 改成 range(len(numbers)-1)

🔧 Action: Edit -- 修改循环范围

📋 Observation: 修改成功

══════ Round 5 (验证失败) ══════

🧠 Thought: 让我运行验证

🔧 Action: Bash -- python3 buggy_code.py

📋 Observation: Sum: 10  （预期 15，少了最后一个元素！）

══════ Round 6 (反思 + 重新定位) ══════  <-- Reflexion 内循环

🧠 Thought: 验证失败了！输出 10 而非 15。分析：
   - 修改循环范围导致少遍历了一个元素
   - 问题不在循环范围，而在索引偏移
   - 应该把 numbers[i+1] 改成 numbers[i]，保持 range 不变

   （这就是 Reflexion 的核心：从失败中学习，调整策略）

🔧 Action: Edit -- 恢复循环范围 + 修正索引

📋 Observation: 修改成功

══════ Round 7 (重新验证) ══════

🔧 Action: Bash -- python3 buggy_code.py

📋 Observation: Sum: 15 ✅
```

**Reflexion 双循环结构**：

```
┌─────────────────────────────────────────────────────────┐
│                    外循环 (Task Loop)                      │
│                                                           │
│   接收任务 -> 执行 L-R-V -> 返回结果                        │
│                                                           │
│   ┌───────────────────────────────────────────────────┐   │
│   │              内循环 (Reflexion Loop)                │   │
│   │                                                     │   │
│   │   Localization -> Repair -> Validation              │   │
│   │        ^                        |                   │   │
│   │        |    失败？反思错误原因     |                   │   │
│   │        +------------------------+                   │   │
│   │                                                     │   │
│   │   成功？ -> 退出内循环                                │   │
│   └───────────────────────────────────────────────────┘   │
│                                                           │
│   Circuit Breaker: 内循环超过 N 轮 -> 强制退出              │
└─────────────────────────────────────────────────────────┘
```

**关键区别**：
- **单循环 ReAct**: 线性执行，不从失败中学习
- **Reflexion 双循环**: 验证失败时，分析失败原因，更新修复策略，重新进入 L-R-V

**这正是 Reflexion 论文 (Shinn et al., 2023) 的核心贡献**：通过语言化的自我反思（verbal self-reflection），让 Agent 在同一个任务上越做越好，而不是每次都从零开始。

---

## 工具调用统计

| 工具 | 调用次数 | 阶段 | 用途 |
|------|---------|------|------|
| ReadTool | 2 | Localization + Validation | 读取代码、确认修改 |
| GrepTool | 2 | Localization | 搜索 bug 模式 |
| EditTool | 1 | Repair | 精确替换修复 |
| BashTool | 2 | Localization + Validation | 重现错误、运行验证 |
| **合计** | **7** | -- | **6 轮 ReAct 循环** |

---

## 附录：OODA 循环对照

OODA (Observe-Orient-Decide-Act) 是军事决策框架，与 L-R-V 的对应关系：

| OODA | L-R-V | 本次演示 |
|------|-------|---------|
| **Observe** (观察) | Localization 前半段 | Read 读取代码，Bash 重现错误 |
| **Orient** (定向) | Localization 后半段 | Grep 精确定位，分析 bug 原因 |
| **Decide** (决策) | Repair 的 Thought | 决定将 `i+1` 改为 `i` |
| **Act** (行动) | Repair 的 Action + Validation | Edit 修改代码，Bash 运行验证 |

---

*本演示记录由实际工具调用生成，所有 Observation 均为真实运行结果。*
*日期: 2026-03-26*
