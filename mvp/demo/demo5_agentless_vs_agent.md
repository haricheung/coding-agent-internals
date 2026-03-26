# Demo 5: Agentless vs Agent 架构对比

## 演示目标

通过同一个 bug 的两种修复路径，对比 **Agentless 流水线**和 **Agent 动态循环**两种架构的核心差异。

让观众直观理解：
- Agentless = 固定三阶段流水线（Localization → Repair → Validation），无反馈回路
- Agent = ReAct 动态循环（Thought → Action → Observation），有实时纠偏能力
- 简单问题两者殊途同归，复杂问题 Agent 的动态优势才显现

---

## Bug 场景描述

### Bug 1: off-by-one 错误（buggy_code.py）

**文件**: `mvp/tests/buggy_code.py`

```python
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total
```

**症状**: 当 `i` 到达最后一个索引时，`i + 1` 越界，抛出 `IndexError: list index out of range`。

**正确修复**: 将 `numbers[i + 1]` 改为 `numbers[i]`。

---

### Bug 2: ZeroDivisionError（large_module.py）

**文件**: `mvp/tests/large_module.py`，第 185-206 行，`DataTransformer.normalize()` 方法。

```python
@staticmethod
def normalize(dataset: DataSet) -> DataSet:
    valid = dataset.get_valid_records()
    if not valid:
        return dataset

    values = [r.value for r in valid]
    min_val = min(values)
    max_val = max(values)

    # BUG: 当所有值相同时，max_val == min_val，除以零！
    range_val = max_val - min_val

    new_records = []
    for record in dataset.records:
        if record.is_valid():
            normalized = (record.value - min_val) / range_val  # ZeroDivisionError!
            ...
```

**症状**: 当数据集中所有值相同时（如全部为 5.0），`max_val - min_val = 0`，除法触发 `ZeroDivisionError`。

**正确修复**: 在除法前检查 `range_val == 0` 的情况，返回 0.0 或 0.5（所有值相同意味着归一化后都在同一位置）。

---

## 一、Agentless 流水线详细模拟（以 Bug 1 为例）

Agentless 的核心思路来自论文 *"Agentless: Demystifying LLM-based Software Engineering Agents"*。
它将 bug 修复分解为三个**固定阶段**，每个阶段独立调用 LLM，阶段之间**无反馈回路**。

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  L: 定位      │ ──→ │  R: 修复      │ ──→ │  V: 验证      │
│  Localization │     │  Repair      │     │  Validation  │
│              │     │              │     │              │
│  2 次 API    │     │  5 次 API    │     │  5 次本地执行  │
│  调用        │     │  调用(采样)   │     │  (跑测试)     │
└──────────────┘     └──────────────┘     └──────────────┘
     单向流水线，不可回退
```

### 阶段 L: Localization（定位）

#### Step L1: 文件级定位

**Prompt 发送给模型：**

```
你是一个软件工程专家。以下是项目的文件列表：

mvp/
  src/
    client.py
    model_server.py
    parser.py
    tools.py
    task_tools.py
    agent_tool.py
  tests/
    buggy_code.py
    large_module.py
    fixed_code.py
  demo/
    demo2_curl_commands.sh

用户报告了以下 bug：
"运行 calculate_sum([1, 2, 3, 4, 5]) 时抛出 IndexError: list index out of range"

请回答：哪个文件最可能包含这个 bug？只返回文件路径，不要解释。
```

**模型预期回答：**

```
mvp/tests/buggy_code.py
```

> [1 次 API 调用]

---

#### Step L2: 行级定位

**Prompt 发送给模型：**

```
以下是文件 mvp/tests/buggy_code.py 的完整内容：

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

用户报告：调用 calculate_sum([1, 2, 3, 4, 5]) 时抛出 IndexError。

请指出有 bug 的具体行号和表达式，并解释 bug 的原因。
```

**模型预期回答：**

```
第 9 行：total += numbers[i + 1]

原因：循环 range(len(numbers)) 产生 i = 0, 1, 2, 3, 4。
当 i = 4 时，numbers[4 + 1] = numbers[5] 越界（列表只有 5 个元素，索引 0-4）。

这是一个 off-by-one 错误，应该改为 numbers[i]。
```

> [1 次 API 调用]
>
> **L 阶段合计：2 次 API 调用**

---

### 阶段 R: Repair（修复）

Agentless 的关键设计：**高温采样多个候选补丁**，靠数量覆盖正确答案。

#### Step R1: 生成 5 个候选补丁（temperature=0.8）

**Prompt 发送给模型（发 5 次，每次采样不同）：**

```
以下代码的第 9 行有 off-by-one 错误：

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total

请生成一个最小补丁来修复这个 bug。
输出格式为 unified diff。
```

**5 次采样的预期输出：**

**候选补丁 1** (正确):
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -6,7 +6,7 @@
     total = 0
     for i in range(len(numbers)):
-        total += numbers[i + 1]
+        total += numbers[i]
     return total
```

**候选补丁 2** (正确，但风格不同):
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -5,8 +5,7 @@
 def calculate_sum(numbers):
     """Calculate the sum of a list of numbers"""
     total = 0
-    for i in range(len(numbers)):
-        total += numbers[i + 1]
+    for num in numbers:
+        total += num
     return total
```

**候选补丁 3** (错误 -- 改了循环范围但引入新 bug):
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
> 此补丁只累加 numbers[1] 到 numbers[4]，漏掉了 numbers[0]，结果错误。

**候选补丁 4** (正确，Pythonic 风格):
```diff
--- a/mvp/tests/buggy_code.py
+++ b/mvp/tests/buggy_code.py
@@ -5,9 +5,7 @@
 def calculate_sum(numbers):
     """Calculate the sum of a list of numbers"""
-    total = 0
-    for i in range(len(numbers)):
-        total += numbers[i + 1]
-    return total
+    return sum(numbers)
```

**候选补丁 5** (错误 -- 改了索引但越界方向不同):
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
> 此补丁 `range(1, 6)` 最后 `numbers[5]` 仍然越界。

> [5 次 API 调用]
>
> **R 阶段合计：5 次 API 调用**

---

### 阶段 V: Validation（验证）

对每个候选补丁，应用到代码上并运行测试，选择通过测试的那个。

#### Step V1: 逐个测试候选补丁

```
对每个补丁执行：
  1. git apply patch_N.diff
  2. python -c "
from buggy_code import calculate_sum
assert calculate_sum([1,2,3,4,5]) == 15
assert calculate_sum([]) == 0
assert calculate_sum([10]) == 10
print('PASS')
"
  3. git checkout -- buggy_code.py  (还原)
```

**测试结果：**

| 补丁 | 测试结果 | 原因 |
|------|---------|------|
| 补丁 1 | PASS | `numbers[i]` 正确遍历所有元素 |
| 补丁 2 | PASS | `for num in numbers` 正确遍历 |
| 补丁 3 | FAIL | `calculate_sum([1,2,3,4,5])` 返回 14 而非 15（漏加 numbers[0]） |
| 补丁 4 | PASS | `sum(numbers)` 内置函数，正确 |
| 补丁 5 | FAIL | `IndexError: list index out of range`（仍然越界） |

**投票选择**：补丁 1、2、4 均通过，选择其中出现频率最高的修复模式（索引修正），最终采用**补丁 1**。

> [5 次本地测试执行]

---

### Agentless 总计

| 指标 | 数量 |
|------|------|
| API 调用 | 7 次（L1 + L2 + R1 x 5） |
| 本地执行 | 5 次（V1 x 5） |
| 总交互 | 12 次 |
| 是否有反馈回路 | 无 -- 每个阶段单向流转，不可回退 |

---

## 二、Agent 动态循环详细模拟（以 Bug 1 为例）

Agent 使用 ReAct 循环（参见 `mvp/src/client.py` 中的 `Client.run()` 方法），每一轮由 Thought-Action-Observation 三元组驱动。

```
┌─────────────────────────────────────────────────────┐
│                  ReAct Loop                         │
│                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│   │ Thought  │───→│ Action   │───→│ Observation  │  │
│   │ (推理)   │    │ (工具调用)│    │ (工具结果)   │  │
│   └──────────┘    └──────────┘    └──────┬───────┘  │
│        ↑                                 │          │
│        └─────────────────────────────────┘          │
│                  动态反馈回路                        │
│                                                     │
│   stop_reason == "tool_use"  → 继续循环             │
│   stop_reason == "end_turn"  → 退出                 │
└─────────────────────────────────────────────────────┘
```

### Round 1: 读取代码

**模型 Thought：**
```
用户说 calculate_sum 有 IndexError。我需要先看一下代码。
从文件树中可以看到 tests/buggy_code.py，应该就是这个文件。
```

**模型 Action：**
```json
{
  "type": "tool_use",
  "name": "Read",
  "input": {"file_path": "/root/work/project/mvp/tests/buggy_code.py"}
}
```

**Observation（工具返回）：**
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
12  def main():
13      nums = [1, 2, 3, 4, 5]
14      result = calculate_sum(nums)
15      print(f"Sum: {result}")
```

> [1 次 API 调用 + 1 次本地执行]

---

### Round 2: 诊断并修复

**模型 Thought：**
```
看到了！第 9 行 numbers[i + 1] 是 off-by-one 错误。
当 i = len(numbers) - 1 时，i + 1 越界。
应该改成 numbers[i]。我用 Edit 工具做精确修改。
```

**模型 Action：**
```json
{
  "type": "tool_use",
  "name": "Edit",
  "input": {
    "file_path": "/root/work/project/mvp/tests/buggy_code.py",
    "old_string": "        total += numbers[i + 1]  # Bug: off-by-one error",
    "new_string": "        total += numbers[i]"
  }
}
```

**Observation（工具返回）：**
```
Successfully edited file.
```

> [1 次 API 调用 + 1 次本地执行]

---

### Round 3: 验证修复

**模型 Thought：**
```
修改已完成。我需要运行代码来验证修复是否正确。
```

**模型 Action：**
```json
{
  "type": "tool_use",
  "name": "Bash",
  "input": {
    "command": "cd /root/work/project/mvp/tests && python -c \"from buggy_code import calculate_sum; print(calculate_sum([1,2,3,4,5]))\""
  }
}
```

**Observation（工具返回）：**
```
15
```

> [1 次 API 调用 + 1 次本地执行]

---

### Round 4: 完成

**模型 Thought：**
```
calculate_sum([1,2,3,4,5]) 返回 15，正确！bug 已修复。
```

**模型 Response（stop_reason: "end_turn"）：**
```
已修复 buggy_code.py 中的 off-by-one 错误：
- 第 9 行: numbers[i + 1] → numbers[i]
- 原因: 循环索引 i 已经覆盖所有位置，+1 导致越界
- 验证: calculate_sum([1,2,3,4,5]) = 15 ✓
```

> [1 次 API 调用，无本地执行]

---

### Agent 总计

| 指标 | 数量 |
|------|------|
| API 调用 | 4 次（Round 1-4 各 1 次） |
| 本地执行 | 3 次（Read + Edit + Bash） |
| 总交互 | 7 次 |
| 是否有反馈回路 | 有 -- 每轮 Observation 影响下轮 Thought |

---

## 三、对比分析

### 核心维度对比表

| 维度 | Agentless | Agent |
|------|-----------|-------|
| API 调用数 | 7 次（固定） | 3-5 次（动态） |
| 修复策略 | 多候选投票（采样 5 个补丁，选最优） | 单路径 + 验证（一次修对就停） |
| 错误恢复 | 无（靠采样多样性覆盖正确答案） | 有（Reflexion 双循环：观察错误 → 调整策略） |
| 复杂问题 | 劣势（3 阶段固定，无法中途调整搜索方向） | 优势（动态调整，可回溯重试） |
| 简单问题 | 两者趋近一致 | 两者趋近一致 |
| 延迟 | 高（必须跑完所有阶段，即使第 1 个补丁就对了） | 低（可能 2 轮就完成） |
| 可复现性 | 高（流水线固定，结果确定性强） | 低（循环路径依赖中间结果，每次可能不同） |
| 批量能力 | 强（可并行处理多个 bug，互不干扰） | 弱（每个 bug 占用一个 Agent 会话） |
| 卡死风险 | 无（没有循环，不会死循环） | 有（需要 Circuit Breaker 兜底，如 max_rounds=10） |
| 实现复杂度 | 低（3 个 prompt 模板 + 测试脚本） | 高（需要 ReAct 框架 + 工具系统 + 上下文管理） |

---

## 四、两种路径的时间线对比图

```
时间轴 ──────────────────────────────────────────────────────────→

Agentless 流水线：
  ┌─────┐  ┌─────┐  ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐  ┌────┐┌────┐┌────┐┌────┐┌────┐
  │ L1  │→│ L2  │→│ R1-a ││ R1-b ││ R1-c ││ R1-d ││ R1-e │→│ V-a ││ V-b ││ V-c ││ V-d ││ V-e │
  │ 选文件│ │ 选行 │  │补丁1 ││补丁2 ││补丁3 ││补丁4 ││补丁5 │  │测试1││测试2││测试3││测试4││测试5│
  │ API │  │ API │  │ API  ││ API  ││ API  ││ API  ││ API  │  │本地 ││本地 ││本地 ││本地 ││本地 │
  └─────┘  └─────┘  └──────┘└──────┘└──────┘└──────┘└──────┘  └────┘└────┘└────┘└────┘└────┘
  │←── 定位 ──→│    │←──────── 修复（5路采样）────────→│     │←──── 验证 ────→│
                                                                              ↓ 选 PASS 的补丁
  总计: 7 API + 5 本地 = 12 步                                              最终输出补丁

──────────────────────────────────────────────────────────────────────────

Agent ReAct 循环：
  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌──────────┐
  │ Round 1         │→│ Round 2         │→│ Round 3         │→│ Round 4  │
  │ T: 需要看代码   │  │ T: 发现bug      │  │ T: 需要验证     │  │ T: 通过了 │
  │ A: Read(file)   │  │ A: Edit(fix)    │  │ A: Bash(test)   │  │ end_turn │
  │ O: 文件内容     │  │ O: 修改成功     │  │ O: 输出15      │  │ 完成！   │
  │ [API + 本地]    │  │ [API + 本地]    │  │ [API + 本地]    │  │ [API]    │
  └─────────────────┘  └─────────────────┘  └─────────────────┘  └──────────┘
       ↑                     ↑                     ↑
       └──── 反馈 ───────────┴──── 反馈 ───────────┘

  总计: 4 API + 3 本地 = 7 步                      比 Agentless 少 5 步！

──────────────────────────────────────────────────────────────────────────

Agent（遇到错误时的 Reflexion 路径）：
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Round 1  │→│ Round 2  │→│ Round 3  │→│ Round 4  │→│ Round 5  │→│ Round 6  │
  │ Read     │  │ Edit     │  │ Bash     │  │ 分析错误  │  │ Edit     │  │ Bash     │
  │ (看代码) │  │ (首次修) │  │ (测试)   │  │ (反思)   │  │ (再修)   │  │ (再验证) │
  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
                                   ↓ FAIL        ↓                           ↓ PASS
                              发现输出不对  →  重新分析  →  换一种修法  →  验证通过！

  总计: 6 API + 4 本地 = 10 步                     错误恢复是 Agent 独有的能力
```

---

## 五、复杂场景对比：large_module.py 的 ZeroDivisionError

这个 bug 嵌在一个 200+ 行的数据处理模块中，难度更高：
- 文件大，定位成本高
- Bug 只在特定输入条件（所有值相同）下触发
- 修复需要理解归一化的数学语义

### Agentless 处理此 Bug

#### 阶段 L: 定位

**Step L1 Prompt（文件级定位）：**
```
以下是项目文件列表：
mvp/
  src/
    client.py, model_server.py, parser.py, tools.py, ...
  tests/
    buggy_code.py, large_module.py, fixed_code.py

用户报告：调用 DataTransformer.normalize() 处理全部值相同的数据集时，
抛出 ZeroDivisionError。

哪个文件包含这个 bug？
```

**模型回答：** `mvp/tests/large_module.py`

> [1 次 API 调用]

**Step L2 Prompt（行级定位）：**
```
以下是 large_module.py 的完整内容（443 行）：

[... 完整文件内容 ...]

用户报告：DataTransformer.normalize() 在所有值相同时抛出 ZeroDivisionError。
请指出 bug 所在的具体行号和表达式。
```

**模型回答：**
```
第 201 行：range_val = max_val - min_val
第 206 行：normalized = (record.value - min_val) / range_val

当所有值相同时 max_val == min_val，range_val = 0，第 206 行除以零。
```

> [1 次 API 调用]

**问题：L2 需要将 443 行完整文件塞入 prompt，消耗大量 token，且模型在长上下文中可能遗漏细节。**

#### 阶段 R: 修复（5 路采样）

**候选补丁 1** (正确):
```diff
@@ -198,6 +198,9 @@
     range_val = max_val - min_val

+    if range_val == 0:
+        range_val = 1.0  # 所有值相同，归一化为 0.0
+
     new_records = []
```

**候选补丁 2** (正确，另一种语义):
```diff
@@ -198,6 +198,10 @@
     range_val = max_val - min_val

+    if range_val == 0:
+        # 所有值相同，归一化为 0.5（区间中点）
+        return DataSet(name=f"{dataset.name}_normalized")
+
     new_records = []
```
> 但此补丁返回空数据集，虽然不报错但逻辑有问题。

**候选补丁 3** (错误 -- 只加了注释没改代码):
```diff
@@ -198,6 +198,7 @@
     range_val = max_val - min_val
+    # TODO: handle range_val == 0

     new_records = []
```

**候选补丁 4** (正确):
```diff
@@ -198,7 +198,10 @@
     range_val = max_val - min_val

     new_records = []
     for record in dataset.records:
         if record.is_valid():
-            normalized = (record.value - min_val) / range_val
+            if range_val == 0:
+                normalized = 0.0
+            else:
+                normalized = (record.value - min_val) / range_val
```

**候选补丁 5** (错误 -- 用 try/except 掩盖问题):
```diff
@@ -204,7 +204,11 @@
     for record in dataset.records:
         if record.is_valid():
-            normalized = (record.value - min_val) / range_val
+            try:
+                normalized = (record.value - min_val) / range_val
+            except ZeroDivisionError:
+                normalized = 0.0
```
> 虽然功能上"能用"，但 try/except 掩盖除零错误是反模式。

> [5 次 API 调用]

#### 阶段 V: 验证

```python
# 测试脚本
from large_module import DataTransformer, DataSet, DataRecord
from datetime import datetime

ts = datetime(2024, 1, 1)
uniform_ds = DataSet(name="uniform")
uniform_ds.add_many([DataRecord(value=5.0, timestamp=ts) for _ in range(10)])

result = DataTransformer.normalize(uniform_ds)
assert all(r.value == 0.0 for r in result.records), "归一化值应为 0.0"

# 正常情况也不能破坏
normal_ds = DataSet(name="normal")
normal_ds.add_many([DataRecord(value=float(i), timestamp=ts) for i in range(5)])
result2 = DataTransformer.normalize(normal_ds)
assert result2.records[0].value == 0.0  # min
assert result2.records[4].value == 1.0  # max
print("PASS")
```

| 补丁 | 测试结果 | 原因 |
|------|---------|------|
| 补丁 1 | PASS | range_val=1.0 时 (5.0-5.0)/1.0=0.0 |
| 补丁 2 | FAIL | 返回空数据集，assertion 失败 |
| 补丁 3 | FAIL | 没改代码，仍然 ZeroDivisionError |
| 补丁 4 | PASS | 显式检查 range_val==0，归一化为 0.0 |
| 补丁 5 | PASS | try/except 绕过了错误（但属于反模式） |

**投票**：补丁 1 和 4 通过且语义正确，最终采用**补丁 4**（更显式的条件检查）。

> **Agentless 总计：7 API + 5 本地 = 12 步**

---

### Agent 处理此 Bug

#### Round 1: 定位文件

**Thought：** 用户说 normalize 方法有 ZeroDivisionError。我先用 Grep 搜索 normalize 在哪。

**Action：**
```json
{"name": "Grep", "input": {"pattern": "def normalize", "path": "/root/work/project/mvp"}}
```

**Observation：**
```
mvp/tests/large_module.py:185:    def normalize(dataset: DataSet) -> DataSet:
```

> [1 次 API 调用 + 1 次本地执行]

#### Round 2: 精读 bug 位置

**Thought：** 找到了，在 large_module.py 第 185 行。我不需要读整个 443 行文件，只读 normalize 方法附近即可。

**Action：**
```json
{"name": "Read", "input": {"file_path": "/root/work/project/mvp/tests/large_module.py", "offset": 184, "limit": 35}}
```

**Observation：**
```
185      @staticmethod
186      def normalize(dataset: DataSet) -> DataSet:
...
199          # BUG: 当所有值相同时，max_val == min_val，除以零！
200          range_val = max_val - min_val
201
202          new_records = []
203          for record in dataset.records:
204              if record.is_valid():
205                  normalized = (record.value - min_val) / range_val
```

> [1 次 API 调用 + 1 次本地执行]

**关键差异：Agent 只读了 35 行（L-R-V 漏斗策略），Agentless L2 读了 443 行全文。**

#### Round 3: 修复

**Thought：** 第 205 行除以 `range_val`，当所有值相同时 `range_val=0`。需要加一个零值检查。

**Action：**
```json
{
  "name": "Edit",
  "input": {
    "file_path": "/root/work/project/mvp/tests/large_module.py",
    "old_string": "            if record.is_valid():\n                normalized = (record.value - min_val) / range_val",
    "new_string": "            if record.is_valid():\n                if range_val == 0:\n                    normalized = 0.0\n                else:\n                    normalized = (record.value - min_val) / range_val"
  }
}
```

**Observation：** `Successfully edited file.`

> [1 次 API 调用 + 1 次本地执行]

#### Round 4: 验证

**Thought：** 修改完成，我需要运行模块自带的自检来验证。

**Action：**
```json
{
  "name": "Bash",
  "input": {
    "command": "cd /root/work/project/mvp/tests && python large_module.py"
  }
}
```

**Observation：**
```
Created: DataSet(name='sample', size=100)
Sample records: [DataRecord(value=...), ...]

Validation passed: True
Outliers at indices: [...]
Statistics: {...}

Testing normalize on uniform data...
  Result: [0.0, 0.0, 0.0]
```

> [1 次 API 调用 + 1 次本地执行]

#### Round 5: 完成

**Thought：** 自检通过了！uniform data 的 normalize 不再报 ZeroDivisionError，输出 [0.0, 0.0, 0.0] 符合预期。

**Response (end_turn)：**
```
已修复 large_module.py 的 ZeroDivisionError：
- 位置: DataTransformer.normalize(), 第 205 行
- 原因: 当所有值相同时 max_val == min_val, range_val = 0, 除零报错
- 修复: 在除法前加 if range_val == 0 检查，相同值归一化为 0.0
- 验证: 模块自检通过，uniform data normalize 输出 [0.0, 0.0, 0.0] ✓
```

> **Agent 总计：5 API + 4 本地 = 9 步**

---

### 复杂场景对比小结

| 维度 | Agentless | Agent |
|------|-----------|-------|
| 上下文消耗 | L2 阶段塞入 443 行全文 | Grep 定位 + Read 35 行精读 |
| API 调用 | 7 次（固定流程） | 5 次（按需调用） |
| Token 消耗 | 高（大量冗余上下文） | 低（精准读取） |
| 搜索策略 | 被动（等模型在全文中找 bug） | 主动（Grep 先搜再精读） |
| 如果首次修复失败？ | 没有回退机制，只能靠 5 个候选中有正确的 | 分析失败原因，Round 5-6 再修 |

---

## 六、教学要点

### 1. 简单问题两种方法殊途同归

对于 `buggy_code.py` 这种 10 行代码、单一 bug 的简单场景：
- Agentless 的 7 次 API 调用能搞定
- Agent 的 4 次 API 调用也能搞定
- **结果都是正确的**，只是效率不同

这说明 Agentless 不是"弱"，而是用更多计算量换取确定性。

### 2. 复杂问题 Agent 的动态纠偏优势才显现

当 bug 藏在 200+ 行的大文件中（`large_module.py`），且触发条件是边界情况（全部值相同）时：
- Agentless 必须把全文塞入上下文，模型容易遗漏
- Agent 可以 Grep 精确定位，只读关键 35 行
- 如果 Agent 第一次修错了，它能看到测试失败的输出，**反思**并重新修复

**这就是 ReAct 循环的核心价值：观察驱动的动态纠偏。**

### 3. Agentless 的优点不可忽视

- **可复现**：相同输入 → 相同流水线 → 相同输出（温度采样除外）
- **可批量**：100 个 bug 可以并行跑 100 条流水线，互不干扰
- **无卡死风险**：没有循环，不存在死循环的可能
- **易调试**：每个阶段的输入输出都是确定的，出了问题容易定位
- **论文数据**：在 SWE-bench Lite 上，Agentless 的成本效率比许多 Agent 更优

### 4. Agent 的优点在于灵活和高效

- **灵活**：遇到未知问题能动态探索（不需要预定义流水线）
- **高效**：简单 bug 可能 2 轮就完成，不浪费计算
- **能处理未知问题**：不受固定阶段的限制，可以自由组合工具
- **错误恢复**：Reflexion 双循环 -- 外层 ReAct 循环 + 内层失败反思

### 5. 工程实践的最佳选择

| 场景 | 推荐方案 |
|------|---------|
| 大批量标准化 bug 修复 | Agentless（并行效率高，结果稳定） |
| 探索性调试（不确定 bug 在哪） | Agent（动态搜索，按需深入） |
| CI/CD 集成自动修复 | Agentless（流水线化，可预测） |
| 交互式编程助手 | Agent（实时反馈，灵活应答） |
| 安全关键系统 | Agentless（无循环卡死风险，可审计） |

**结论：Agentless 和 Agent 不是非此即彼，而是互补的两种架构范式。理解两者的权衡取舍，才能在工程实践中做出正确选择。**
