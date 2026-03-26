# Demo 5 录制：Agentless vs Agent 架构对比（实际执行版）

## 演示目标

通过修复同一个 bug（`mvp/tests/buggy_code.py` 中的 off-by-one 错误），**实际执行**两条修复路径，对比 **Agentless 三阶段流水线**和 **Agent ReAct 动态循环**的核心差异。

- Agentless = 固定三阶段流水线（Localization -> Repair -> Validation），无反馈回路
- Agent = ReAct 动态循环（Thought -> Action -> Observation），有实时纠偏能力

### Bug 描述

**文件**: `mvp/tests/buggy_code.py`

```python
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total
```

**症状**: `i` 到达最后一个索引时，`i + 1` 越界，抛出 `IndexError: list index out of range`。
**正确修复**: 将 `numbers[i + 1]` 改为 `numbers[i]`。

---

## 一、路径 A：Agentless 三阶段流水线模拟

> 以下模拟 Agentless 论文中的三阶段流水线。每个阶段独立调用 LLM，阶段之间**单向流转、不可回退**。

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  L: Localization │ --> │  R: Repair       │ --> │  V: Validation   │
│  定位             │     │  修复             │     │  验证             │
│                  │     │                  │     │                  │
│  L1: 文件级定位   │     │  采样 5 个候选补丁 │     │  逐个跑测试       │
│  L2: 行级定位    │     │  (temperature=0.8)│     │  投票选最优       │
│                  │     │                  │     │                  │
│  2 次 API 调用   │     │  5 次 API 调用    │     │  5 次本地执行     │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         单向流水线，不可回退，无反馈回路
```

---

### 阶段 L: Localization（定位）

#### Step L1 -- 文件级定位

**输入**: 项目文件列表 + bug 描述

我们先用 `find` 列出 `mvp/` 下所有文件（以下为真实执行结果）：

```
mvp/ISSUES.md
mvp/README.md
mvp/demo/demo1_chat_vs_agent.md
mvp/demo/demo2_curl_commands.sh
mvp/demo/demo2_protocol_teardown.md
mvp/demo/demo3_bug_fix_flow.md
mvp/demo/demo4_aci_granularity.md
mvp/demo/demo5_agentless_vs_agent.md
mvp/demo/demo6_agent_team.md
mvp/requirements.txt
mvp/src/adapter.py
mvp/src/agent_tool.py
mvp/src/client.py
mvp/src/main.py
mvp/src/model_server.py
mvp/src/parser.py
mvp/src/task_tools.py
mvp/src/tools.py
mvp/tests/buggy_code.py          <-- 目标文件
mvp/tests/large_module.py
mvp/tests/test_all.py
mvp/tests/test_components.py
mvp/tests/test_day1.py
mvp/tests/test_day1_features.py
mvp/tests/test_qwen3.py
mvp/tests/test_simple.py
```

**Prompt 发送给模型**:
```
你是一个软件工程专家。以下是项目的文件列表：
[上述文件列表]

用户报告了以下 bug：
"运行 calculate_sum([1, 2, 3, 4, 5]) 时抛出 IndexError: list index out of range"

请回答：哪个文件最可能包含这个 bug？只返回文件路径。
```

**模型输出**:
```
mvp/tests/buggy_code.py
```

> **[1 次 API 调用]**

**💡 重点解说**: Agentless 的 L1 阶段把完整的文件树交给 LLM，让模型"猜"目标文件。文件名 `buggy_code.py` 和函数名 `calculate_sum` 都是强信号，这一步对于简单场景几乎不会出错。但如果项目有上千个文件，这一步的 token 消耗会显著增加。

---

#### Step L2 -- 行级定位

**输入**: buggy_code.py 的完整内容

读取文件全文（以下为**真实文件内容**）：

```python
"""
A simple Python file with a bug for testing Day 1
"""

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error    <-- 第 9 行
    return total


def main():
    nums = [1, 2, 3, 4, 5]
    result = calculate_sum(nums)
    print(f"Sum: {result}")


if __name__ == "__main__":
    main()
```

**Prompt 发送给模型**:
```
以下是文件 mvp/tests/buggy_code.py 的完整内容：
[上述文件全文]

用户报告：调用 calculate_sum([1, 2, 3, 4, 5]) 时抛出 IndexError。
请指出有 bug 的具体行号和表达式，并解释原因。
```

**模型输出**:
```
第 9 行：total += numbers[i + 1]

原因：循环 range(len(numbers)) 产生 i = 0, 1, 2, 3, 4。
当 i = 4 时，numbers[4 + 1] = numbers[5] 越界（列表只有 5 个元素，索引 0-4）。
这是一个 off-by-one 错误，应该改为 numbers[i]。
```

> **[1 次 API 调用]**
>
> **L 阶段合计：2 次 API 调用，0 次本地执行**

**💡 重点解说**: L2 将整个文件内容塞进 prompt。对于这个 20 行文件问题不大；但对于几百行的大文件，上下文消耗会很高，且模型在长文本中容易遗漏关键细节。

---

### 阶段 R: Repair（修复）

Agentless 的核心设计：**高温采样多个候选补丁**（temperature=0.8），靠数量覆盖正确答案。

#### Step R1 -- 生成 5 个候选补丁

**Prompt 发送给模型（重复 5 次，每次采样不同）**:
```
以下代码的第 9 行有 off-by-one 错误：

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total

请生成一个最小补丁来修复这个 bug，输出格式为 unified diff。
```

**5 次采样结果：**

---

**候选补丁 1** -- 直接修正索引（正确）:
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -6,7 +6,7 @@
     total = 0
     for i in range(len(numbers)):
-        total += numbers[i + 1]  # Bug: off-by-one error
+        total += numbers[i]
     return total
```

---

**候选补丁 2** -- 改用 for-each 循环（正确，风格不同）:
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -5,9 +5,8 @@
 def calculate_sum(numbers):
     """Calculate the sum of a list of numbers"""
     total = 0
-    for i in range(len(numbers)):
-        total += numbers[i + 1]  # Bug: off-by-one error
+    for num in numbers:
+        total += num
     return total
```

---

**候选补丁 3** -- 缩短循环范围（错误！漏掉 numbers[0]）:
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -6,7 +6,7 @@
     total = 0
-    for i in range(len(numbers)):
+    for i in range(len(numbers) - 1):
         total += numbers[i + 1]
     return total
```
> 此补丁只累加 numbers[1] 到 numbers[4]，漏掉了 numbers[0]，结果为 14 而非 15。

---

**候选补丁 4** -- 用内置 sum()（正确，Pythonic 风格）:
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -5,10 +5,7 @@
 def calculate_sum(numbers):
     """Calculate the sum of a list of numbers"""
-    total = 0
-    for i in range(len(numbers)):
-        total += numbers[i + 1]  # Bug: off-by-one error
-    return total
+    return sum(numbers)
```

---

**候选补丁 5** -- 改起始索引（错误！仍然越界）:
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -6,7 +6,7 @@
     total = 0
-    for i in range(len(numbers)):
-        total += numbers[i + 1]
+    for i in range(1, len(numbers) + 1):
+        total += numbers[i]
     return total
```
> 此补丁 `range(1, 6)` 最后访问 `numbers[5]`，仍然越界。

> **[5 次 API 调用]**
>
> **R 阶段合计：5 次 API 调用，0 次本地执行**

**💡 重点解说**: 5 个候选补丁中有 3 个正确、2 个错误，展示了高温采样的多样性。Agentless 不要求每次都对，而是靠后续验证过滤出正确的。这是"宽度优先"策略：多路并行采样 + 测试筛选。

---

### 阶段 V: Validation（验证）

对每个候选补丁逐个应用并运行测试。

#### Step V1 -- 逐个测试

**测试脚本**:
```python
from buggy_code import calculate_sum
assert calculate_sum([1, 2, 3, 4, 5]) == 15
assert calculate_sum([]) == 0
assert calculate_sum([10]) == 10
print("PASS")
```

**测试结果汇总：**

| 补丁编号 | 修复策略 | 测试结果 | 原因 |
|---------|---------|---------|------|
| 补丁 1 | `numbers[i]` 直接修正索引 | **PASS** | 正确遍历所有元素 |
| 补丁 2 | `for num in numbers` | **PASS** | for-each 正确遍历 |
| 补丁 3 | `range(len(numbers) - 1)` | **FAIL** | `calculate_sum([1,2,3,4,5])` 返回 14（漏掉 numbers[0]） |
| 补丁 4 | `return sum(numbers)` | **PASS** | 内置函数正确 |
| 补丁 5 | `range(1, len(numbers) + 1)` | **FAIL** | `IndexError: list index out of range`（仍越界） |

**投票选择**: 补丁 1、2、4 均通过。按最小修改原则（最接近原始代码结构），最终采用**补丁 1**。

> **[5 次本地测试执行]**
>
> **V 阶段合计：0 次 API 调用，5 次本地执行**

**💡 重点解说**: 验证阶段**完全在本地执行**，不消耗 API 调用。这是 Agentless 的一个优点：验证成本为零（仅本地计算）。最终通过投票从 3 个正确补丁中选出最优。

---

### Agentless 路径 A 总结

| 阶段 | API 调用 | 本地执行 | 说明 |
|------|---------|---------|------|
| L1 文件级定位 | 1 | 0 | 从文件列表选目标文件 |
| L2 行级定位 | 1 | 0 | 从文件内容选目标行 |
| R1 生成候选补丁 | 5 | 0 | 高温采样 5 个补丁 |
| V1 逐个测试 | 0 | 5 | 本地跑测试 |
| **合计** | **7** | **5** | **共 12 步** |

---

## 二、路径 B：Agent ReAct 循环（实际执行）

> 以下每一轮的 Action 和 Observation 均为**真实工具调用结果**。

```
┌─────────────────────────────────────────────────────┐
│                  ReAct Loop                         │
│                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│   │ Thought  │--->│ Action   │--->│ Observation  │  │
│   │ (推理)   │    │ (工具调用)│    │ (工具结果)   │  │
│   └──────────┘    └──────────┘    └──────┬───────┘  │
│        ^                                 │          │
│        └─────────────────────────────────┘          │
│                  动态反馈回路                        │
└─────────────────────────────────────────────────────┘
```

---

### Round 1: 读取代码

🧠 **Thought**:
用户说 `calculate_sum` 有 `IndexError`。我需要先看一下代码。文件树中可以看到 `tests/buggy_code.py`，应该就是这个文件。

🔧 **Action**: `Read("mvp/tests/buggy_code.py")`

📋 **Observation**（真实输出）:
```
     1  """
     2  A simple Python file with a bug for testing Day 1
     3  """
     4
     5  def calculate_sum(numbers):
     6      """Calculate the sum of a list of numbers"""
     7      total = 0
     8      for i in range(len(numbers)):
     9          total += numbers[i + 1]  # Bug: off-by-one error
    10      return total
    11
    12
    13  def main():
    14      nums = [1, 2, 3, 4, 5]
    15      result = calculate_sum(nums)
    16      print(f"Sum: {result}")
    17
    18
    19  if __name__ == "__main__":
    20      main()
```

> **[1 次 API 调用 + 1 次本地执行]**

**💡 重点解说**: Agent 的第一步和 Agentless 的 L2 类似，但 Agent 是**按需读取**的 -- 先有"需要看代码"的推理，再执行读取。而 Agentless 是预定义流程，无论是否需要都会执行每个阶段。

---

### Round 2: 搜索 bug 模式

🧠 **Thought**:
看到第 9 行有 `numbers[i + 1]`，这很可能是 off-by-one。让我用 Grep 确认一下这个模式在文件中只出现一次。

🔧 **Action**: `Grep(pattern="i \\+ 1", path="mvp/tests/buggy_code.py")`

📋 **Observation**（真实输出）:
```
9:        total += numbers[i + 1]  # Bug: off-by-one error
```

> **[1 次 API 调用 + 1 次本地执行]**

**💡 重点解说**: Agent 用 Grep 精确定位 `i + 1` 模式，确认只在第 9 行出现一次。这是 Agent 的"主动搜索"策略：不是被动读全文让模型找，而是用工具精确匹配。

---

### Round 3: 运行代码看错误

🧠 **Thought**:
第 9 行确实是 `numbers[i + 1]`。在 `range(len(numbers))` 下，当 `i = 4` 时 `numbers[5]` 越界。让我先运行代码确认错误现象。

🔧 **Action**: `Bash("python mvp/tests/buggy_code.py")`

📋 **Observation**（真实输出）:
```
Traceback (most recent call last):
  File "mvp/tests/buggy_code.py", line 20, in <module>
    main()
  File "mvp/tests/buggy_code.py", line 15, in main
    result = calculate_sum(nums)
  File "mvp/tests/buggy_code.py", line 9, in calculate_sum
    total += numbers[i + 1]  # Bug: off-by-one error
IndexError: list index out of range
```

> **[1 次 API 调用 + 1 次本地执行]**

**💡 重点解说**: Agent 在修改前先运行代码**确认错误现象**。这是 Agentless 完全没有的步骤 -- Agentless 的 L 阶段只做静态分析，不运行代码。Agent 拿到了真实的 traceback，可以精确确认 bug 位置。

---

### Round 4: 修复 bug

🧠 **Thought**:
确认了：第 9 行 `numbers[i + 1]` 导致 `IndexError`。修复方案是把 `i + 1` 改为 `i`。用 Edit 工具做精确替换。

🔧 **Action**: `Edit(file_path="mvp/tests/buggy_code.py", old_string="total += numbers[i + 1]  # Bug: off-by-one error", new_string="total += numbers[i]  # Fixed: use correct index")`

📋 **Observation**（真实输出）:
```
The file mvp/tests/buggy_code.py has been updated successfully.
```

> **[1 次 API 调用 + 1 次本地执行]**

**💡 重点解说**: Agent 只生成了 **1 个补丁**并直接应用，而 Agentless 生成了 5 个候选补丁再筛选。Agent 的策略是"先修再验"：如果修错了，后面的 Observation 会告诉它，它可以再修。

---

### Round 5: 运行验证

🧠 **Thought**:
修改完成。运行代码验证 `calculate_sum([1, 2, 3, 4, 5])` 是否返回 15。

🔧 **Action**: `Bash("python mvp/tests/buggy_code.py")`

📋 **Observation**（真实输出）:
```
Sum: 15
```

> **[1 次 API 调用 + 1 次本地执行]**

**💡 重点解说**: 输出 `Sum: 15`，即 `1+2+3+4+5=15`，正确！Agent 只用了**一次验证**就确认修复成功。而 Agentless 需要对所有 5 个候选补丁逐一验证。这就是"深度优先"（单路径 + 验证）vs"宽度优先"（多路径 + 筛选）的效率差异。

---

### Round 6: 报告完成

🧠 **Thought**:
`calculate_sum([1,2,3,4,5])` 返回 15，bug 已修复。向用户报告。

🔧 **Action**: 无（`stop_reason: end_turn`）

📋 **最终报告**:
```
已修复 mvp/tests/buggy_code.py 中的 off-by-one 错误：
- 第 9 行: numbers[i + 1] -> numbers[i]
- 原因: 循环索引 i 已覆盖所有位置（0 到 len-1），+1 导致越界
- 验证: calculate_sum([1, 2, 3, 4, 5]) = 15，正确
```

> **[1 次 API 调用，0 次本地执行]**

---

### 收尾：恢复原始 bug

Agent 执行后，将文件恢复为原始版本，确保 buggy_code.py 不变：

🔧 **Action**: `Edit(old_string="total += numbers[i]  # Fixed: use correct index", new_string="total += numbers[i + 1]  # Bug: off-by-one error")`

📋 **Observation**:
```
The file mvp/tests/buggy_code.py has been updated successfully.
```

🔧 **验证恢复**: `Bash("python mvp/tests/buggy_code.py")`

📋 **Observation**:
```
IndexError: list index out of range
```

原始 bug 已恢复，文件状态不变。

---

### Agent 路径 B 总结

| 轮次 | 动作 | API 调用 | 本地执行 | 说明 |
|------|------|---------|---------|------|
| Round 1 | Read | 1 | 1 | 读取文件内容 |
| Round 2 | Grep | 1 | 1 | 搜索 `i + 1` 模式 |
| Round 3 | Bash | 1 | 1 | 运行代码确认错误 |
| Round 4 | Edit | 1 | 1 | 修复 off-by-one |
| Round 5 | Bash | 1 | 1 | 运行验证修复结果 |
| Round 6 | end_turn | 1 | 0 | 报告完成 |
| **合计** | | **6** | **5** | **共 11 步** |

---

## 三、并排时间线对比图

```
时间轴 =================================================================>

Agentless 流水线（固定三阶段，单向，无反馈）：

  ┌──────┐  ┌──────┐  ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐  ┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
  │  L1  │->│  L2  │->│ R1-a ││ R1-b ││ R1-c ││ R1-d ││ R1-e │->│ V-a ││ V-b ││ V-c ││ V-d ││ V-e │
  │选文件│  │选行号│  │补丁1 ││补丁2 ││补丁3 ││补丁4 ││补丁5 │  │测试1││测试2││测试3││测试4││测试5│
  │ API  │  │ API  │  │ API  ││ API  ││ API  ││ API  ││ API  │  │本地 ││本地 ││本地 ││本地 ││本地 │
  └──────┘  └──────┘  └──────┘└──────┘└──────┘└──────┘└──────┘  └─────┘└─────┘└─────┘└─────┘└─────┘
  |<- 定位(2 API) ->|  |<----- 修复(5 API, 采样) ----->|        |<---- 验证(5 本地) ---->|
                                                                                          |
                                                                                    投票选 PASS
                                                                                      的补丁

  合计: 7 API + 5 本地 = 12 步                              无反馈回路，不可回退

========================================================================

Agent ReAct 循环（动态，有反馈回路）：

  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
  │   Round 1     │->│   Round 2     │->│   Round 3     │->
  │ T: 需要看代码 │  │ T: 搜索模式   │  │ T: 运行看错误 │
  │ A: Read(file) │  │ A: Grep(i+1)  │  │ A: Bash(run)  │
  │ O: 文件内容   │  │ O: 第9行匹配  │  │ O: IndexError │
  │ [API+本地]    │  │ [API+本地]    │  │ [API+本地]    │
  └───────────────┘  └───────────────┘  └───────────────┘
         |                  ^                   |
         +--- 反馈 ---------+---- 反馈 ---------+

  ┌───────────────┐  ┌───────────────┐  ┌──────────┐
  │   Round 4     │->│   Round 5     │->│ Round 6  │
  │ T: 确认bug    │  │ T: 验证修复   │  │ T: 通过! │
  │ A: Edit(fix)  │  │ A: Bash(run)  │  │ end_turn │
  │ O: 修改成功   │  │ O: Sum: 15    │  │ 完成报告 │
  │ [API+本地]    │  │ [API+本地]    │  │ [API]    │
  └───────────────┘  └───────────────┘  └──────────┘
         |                  ^
         +--- 反馈 ---------+

  合计: 6 API + 5 本地 = 11 步                   有反馈回路，可动态纠偏

========================================================================

Agent 遇到错误时的 Reflexion 路径（假设首次修错）：

  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Round 1  │->│ Round 2  │->│ Round 3  │->│ Round 4  │->│ Round 5  │->│ Round 6  │
  │ Read     │  │ Edit     │  │ Bash     │  │ 分析错误  │  │ Edit     │  │ Bash     │
  │ (看代码) │  │ (首次修) │  │ (测试)   │  │ (反思)   │  │ (再修)   │  │ (再验证) │
  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
                                   | FAIL       |                           | PASS
                              发现输出不对 -> 重新分析 -> 换一种修法 -> 验证通过!

  错误恢复是 Agent 独有的能力，Agentless 没有这种反馈回路
```

---

## 四、最终对比表

| 维度 | Agentless 流水线 | Agent ReAct 循环 |
|------|-----------------|-----------------|
| **API 调用数** | 7 次（固定：L1+L2+R*5） | 6 次（动态：按需调用） |
| **本地执行数** | 5 次（V 阶段测试 5 个补丁） | 5 次（Read+Grep+Bash+Edit+Bash） |
| **总步骤数** | 12 步 | 11 步 |
| **Token 消耗（估算）** | ~3000（L2 全文 + R*5 重复 prompt） | ~1500（按需读取，无重复 prompt） |
| **反馈回路** | 无 -- 三阶段单向流转，不可回退 | 有 -- 每轮 Observation 驱动下一轮 Thought |
| **错误恢复能力** | 无 -- 靠采样多样性覆盖正确答案 | 有 -- Reflexion：观察失败 -> 反思 -> 重试 |
| **修复策略** | 宽度优先：采样 5 个补丁，投票选最优 | 深度优先：单路径修改 + 运行时验证 |
| **运行前确认** | 无 -- 不运行代码确认错误 | 有 -- Round 3 先运行看 traceback |
| **搜索策略** | 被动 -- 把全文交给 LLM 分析 | 主动 -- Grep 精确搜索 + 按需精读 |
| **可复现性** | 高 -- 流水线固定，输入输出确定 | 低 -- 循环路径依赖中间结果 |
| **批量处理** | 强 -- 100 个 bug 并行跑 100 条流水线 | 弱 -- 每个 bug 占一个 Agent 会话 |
| **卡死风险** | 无 -- 没有循环，不会死循环 | 有 -- 需要 Circuit Breaker（如 max_rounds） |
| **实现复杂度** | 低 -- 3 个 prompt 模板 + 测试脚本 | 高 -- ReAct 框架 + 工具系统 + 上下文管理 |
| **适用场景** | 批量标准 bug、CI/CD 自动修复 | 探索性调试、交互式编程助手 |

---

## 五、关键洞察

### 1. 简单问题殊途同归
对于 `buggy_code.py` 这种 20 行代码、单一 bug 的简单场景，Agentless 和 Agent **都能正确修复**。差异主要在效率层面（12 步 vs 11 步），结果一致。

### 2. Agent 的独有优势：运行时反馈
Agent 在 Round 3 **先运行代码看到真实 traceback**，然后再修改。这种"观察驱动"的方式让 Agent 对 bug 的理解更扎实。Agentless 的 L 阶段完全是静态分析，不运行代码。

### 3. Agent 的独有优势：错误恢复
如果 Agent 第一次修错了，Round 5 的验证结果会告诉它"还是不对"，它可以在 Round 6-7 反思并重试。Agentless 没有这种回退机制，只能靠前面 5 个采样中"碰巧有正确的"。

### 4. Agentless 的独有优势：可预测性
Agentless 的流水线是固定的：永远是 L1->L2->R*5->V*5。不会卡死、不会死循环、容易调试和审计。Agent 的 ReAct 循环可能走不同路径，需要 max_rounds 兜底。

### 5. 工程选择取决于场景

| 场景 | 推荐方案 | 原因 |
|------|---------|------|
| 大批量标准 bug 修复 | Agentless | 并行效率高，结果稳定 |
| 探索性调试 | Agent | 动态搜索，按需深入 |
| CI/CD 集成 | Agentless | 流水线化，可预测 |
| 交互式编程助手 | Agent | 实时反馈，灵活应答 |
| 安全关键系统 | Agentless | 无循环卡死风险，可审计 |

**结论：Agentless 和 Agent 不是非此即彼，而是互补的两种架构范式。**
