# Demo 3 录制：Bug 修复 L-R-V 完整流程

> **演示目标**：展示 Coding Agent 如何通过 **Localization → Repair → Validation** 三阶段循环，完成一次真实的 Bug 修复。每一步都对应 ReAct（Thought → Action → Observation）推理框架和 OODA（Observe → Orient → Decide → Act）决策循环。

**目标文件**：`mvp/tests/buggy_code.py`
**Bug 类型**：Off-by-one 越界索引错误
**预期修复**：`numbers[i + 1]` → `numbers[i]`

---

## 🔴 修复前的代码

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

---

## ══════ Round 1 ══════ 读取目标文件

**📍 L-R-V 阶段**：**Localization（定位）**
**📍 OODA 对应**：**Observe（观察）** — 获取原始信息

### 🧠 Thought

用户报告 `calculate_sum` 函数有 bug。第一步需要读取源文件，了解代码结构和逻辑，才能定位问题。

### 🔧 Action

```
工具: Read
参数: file_path = "mvp/tests/buggy_code.py"
```

### 📋 Observation

```
     1→"""
     2→A simple Python file with a bug for testing Day 1
     3→"""
     4→
     5→def calculate_sum(numbers):
     6→    """Calculate the sum of a list of numbers"""
     7→    total = 0
     8→    for i in range(len(numbers)):
     9→        total += numbers[i + 1]  # Bug: off-by-one error
    10→    return total
    11→
    12→
    13→def main():
    14→    nums = [1, 2, 3, 4, 5]
    15→    result = calculate_sum(nums)
    16→    print(f"Sum: {result}")
    17→
    18→
    19→if __name__ == "__main__":
    20→    main()
```

> **💡 重点解说**：Agent 的第一步是**读取文件全貌**。这是 Localization 阶段的起点——你不能修复你看不到的代码。Read 工具返回带行号的完整文件内容，为后续的模式搜索和精确编辑提供基础。注意第 9 行的 `numbers[i + 1]`，当 `i` 达到最后一个索引时，`i + 1` 会越界。

---

## ══════ Round 2 ══════ 搜索可疑模式 `i + 1`

**📍 L-R-V 阶段**：**Localization（定位）**
**📍 OODA 对应**：**Orient（定向）** — 识别可疑模式

### 🧠 Thought

文件已读取完毕。现在需要精确定位可疑的索引模式。`i + 1` 在循环中访问数组元素是常见的越界错误源，用 Grep 搜索确认。

### 🔧 Action

```
工具: Grep
参数: pattern = "i \+ 1"
      path = "mvp/tests/buggy_code.py"
      output_mode = "content"
```

### 📋 Observation

```
9:        total += numbers[i + 1]  # Bug: off-by-one error
```

> **💡 重点解说**：Grep 精确命中第 9 行。模式搜索 `i \+ 1` 快速定位了可疑的数组越界访问。在大型代码库中，Grep 可以在数千个文件中秒级找到所有匹配——这就是 ACI（Agent-Computer Interface）中 Grep 工具的核心价值。对比人类在 IDE 中手动搜索，Agent 的搜索是**可编程的、可重复的**。

---

## ══════ Round 3 ══════ 搜索循环边界模式 `range(len`

**📍 L-R-V 阶段**：**Localization（定位）**
**📍 OODA 对应**：**Orient（定向）** — 理解循环边界

### 🧠 Thought

确认了 `i + 1` 的位置后，还需要理解循环的边界条件。`range(len(numbers))` 会产生 `0, 1, ..., len-1`，当 `i = len-1` 时，`numbers[i+1]` 就是 `numbers[len]`，必然越界。

### 🔧 Action

```
工具: Grep
参数: pattern = "range\(len"
      path = "mvp/tests/buggy_code.py"
      output_mode = "content"
```

### 📋 Observation

```
8:    for i in range(len(numbers)):
```

> **💡 重点解说**：两次 Grep 搜索组合起来，构成了完整的 bug 定位推理链：
> - 第 8 行：`range(len(numbers))` → `i` 的范围是 `[0, len-1]`
> - 第 9 行：`numbers[i + 1]` → 当 `i = len-1` 时访问 `numbers[len]` → **IndexError**
>
> 这就是 Localization 的核心：不仅找到 **哪一行** 出错，还要理解 **为什么** 出错。

---

## ══════ Round 4 ══════ 运行代码复现错误

**📍 L-R-V 阶段**：**Localization（定位）**
**📍 OODA 对应**：**Observe（观察）** — 用执行结果确认假设

### 🧠 Thought

静态分析已经确定了 bug 的根因。现在通过实际运行来**复现错误**，用运行时证据验证我的分析。

### 🔧 Action

```
工具: Bash
命令: cd mvp/tests && python3 buggy_code.py
```

### 📋 Observation

```
Traceback (most recent call last):
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 20, in <module>
    main()
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 15, in main
    result = calculate_sum(nums)
  File "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py", line 9, in calculate_sum
    total += numbers[i + 1]  # Bug: off-by-one error
IndexError: list index out of range
```

> **💡 重点解说**：**运行时确认**是 Localization 阶段的关键闭环。静态分析说"这里可能有 bug"，运行时的 `IndexError: list index out of range` 在第 9 行确认了"这里确实有 bug"。注意 traceback 精确指向了第 9 行——和我们 Grep 搜索的结果完全一致。Localization 阶段至此完成，Agent 可以自信地进入 Repair 阶段。

---

## ══════ Round 5 ══════ 修复 Bug

**📍 L-R-V 阶段**：**Repair（修复）**
**📍 OODA 对应**：**Decide + Act（决策 + 行动）** — 执行精确修复

### 🧠 Thought

Bug 已精确定位：第 9 行 `numbers[i + 1]` 应该是 `numbers[i]`。使用 Edit 工具进行精确的字符串替换——只改这一行，不碰其他代码。

### 🔧 Action

```
工具: Edit
参数:
  file_path = "mvp/tests/buggy_code.py"
  old_string = "        total += numbers[i + 1]  # Bug: off-by-one error"
  new_string = "        total += numbers[i]  # Fixed: use correct index"
```

### 📋 Observation

```
The file mvp/tests/buggy_code.py has been updated successfully.
```

> **💡 重点解说**：Edit 工具执行了**精确的字符串替换**，而不是重写整个文件。这是 ACI 设计的精髓：
> - `old_string` 必须在文件中唯一匹配——防止误改
> - 只替换目标行——最小化 diff，减少引入新 bug 的风险
> - 保留缩进和周围代码——不破坏文件结构
>
> 对比"用 sed 正则替换"或"重写整个文件"，Edit 工具提供了**手术刀级别的精度**。

---

## ══════ Round 6 ══════ 读取修复后的文件确认

**📍 L-R-V 阶段**：**Repair（修复）**
**📍 OODA 对应**：**Observe（观察）** — 确认修复正确应用

### 🧠 Thought

修复已执行，但需要再次读取文件确认修改确实生效，且没有意外的副作用。

### 🔧 Action

```
工具: Read
参数: file_path = "mvp/tests/buggy_code.py"
```

### 📋 Observation

```
     1→"""
     2→A simple Python file with a bug for testing Day 1
     3→"""
     4→
     5→def calculate_sum(numbers):
     6→    """Calculate the sum of a list of numbers"""
     7→    total = 0
     8→    for i in range(len(numbers)):
     9→        total += numbers[i]  # Fixed: use correct index
    10→    return total
    11→
    12→
    13→def main():
    14→    nums = [1, 2, 3, 4, 5]
    15→    result = calculate_sum(nums)
    16→    print(f"Sum: {result}")
    17→
    18→
    19→if __name__ == "__main__":
    20→    main()
```

> **💡 重点解说**：Read 确认了**只有第 9 行被修改**，其余 19 行代码完全不变。这体现了 Repair 阶段的**最小修改原则**：改得越少，引入新问题的可能性越低。Agent 现在可以自信地进入 Validation 阶段。

---

## ══════ Round 7 ══════ 运行修复后的代码

**📍 L-R-V 阶段**：**Validation（验证）**
**📍 OODA 对应**：**Observe（观察）** — 验证修复有效

### 🧠 Thought

修复已确认。现在运行修复后的代码，验证 IndexError 是否消失，输出是否正确。`[1,2,3,4,5]` 的和应该是 `15`。

### 🔧 Action

```
工具: Bash
命令: cd mvp/tests && python3 buggy_code.py
```

### 📋 Observation

```
Sum: 15
```

> **💡 重点解说**：修复前是 `IndexError: list index out of range`，修复后是 `Sum: 15`——**从崩溃到正确输出**，一行代码的修改。这是 Validation 阶段第一步：确认程序不再崩溃，且主路径输出正确。但一个测试用例不够，还需要更多验证。

---

## ══════ Round 8 ══════ 运行额外断言测试

**📍 L-R-V 阶段**：**Validation（验证）**
**📍 OODA 对应**：**Observe + Orient（观察 + 定向）** — 边界情况验证

### 🧠 Thought

主路径验证通过，但需要测试边界情况。特别是空列表 `[]` 的情况——修复不应该破坏空输入的处理。

### 🔧 Action

```
工具: Bash
命令: cd mvp/tests && python3 -c "from buggy_code import calculate_sum; assert calculate_sum([1,2,3,4,5]) == 15; assert calculate_sum([]) == 0; print('ALL TESTS PASSED')"
```

### 📋 Observation

```
ALL TESTS PASSED
```

> **💡 重点解说**：两个断言全部通过：
> - `calculate_sum([1,2,3,4,5]) == 15` — 正常输入 ✅
> - `calculate_sum([]) == 0` — 边界情况（空列表）✅
>
> 这就是 Validation 阶段的完整性：不仅测试"修复是否解决了原来的问题"，还测试"修复是否引入了新问题"。在真实的 Coding Agent（如 SWE-bench）中，这一步会运行完整的测试套件。

---

## ══════ Round 9 ══════ 恢复原始文件

**📍 L-R-V 阶段**：**收尾（演示清理）**
**📍 OODA 对应**：**Act（行动）** — 恢复现场

### 🧠 Thought

演示完成，需要将文件恢复到原始状态，确保不影响其他演示或测试。

### 🔧 Action

```
工具: Edit
参数:
  file_path = "mvp/tests/buggy_code.py"
  old_string = "        total += numbers[i]  # Fixed: use correct index"
  new_string = "        total += numbers[i + 1]  # Bug: off-by-one error"
```

### 📋 Observation

```
The file mvp/tests/buggy_code.py has been updated successfully.
```

恢复后文件确认：

```
     1→"""
     2→A simple Python file with a bug for testing Day 1
     3→"""
     4→
     5→def calculate_sum(numbers):
     6→    """Calculate the sum of a list of numbers"""
     7→    total = 0
     8→    for i in range(len(numbers)):
     9→        total += numbers[i + 1]  # Bug: off-by-one error
    10→    return total
    11→
    12→
    13→def main():
    14→    nums = [1, 2, 3, 4, 5]
    15→    result = calculate_sum(nums)
    16→    print(f"Sum: {result}")
    17→
    18→
    19→if __name__ == "__main__":
    20→    main()
```

> **💡 重点解说**：文件已恢复原样。演示结束后清理现场是好习惯——特别是在共享代码库中，你不希望演示的副作用影响到其他人的工作。

---

## 📊 修复前后 Diff 对比

```diff
--- a/mvp/tests/buggy_code.py (修复前)
+++ b/mvp/tests/buggy_code.py (修复后)
@@ -6,7 +6,7 @@
     """Calculate the sum of a list of numbers"""
     total = 0
     for i in range(len(numbers)):
-        total += numbers[i + 1]  # Bug: off-by-one error
+        total += numbers[i]  # Fixed: use correct index
     return total
```

**改动量**：1 行修改，0 行新增，0 行删除

---

## ✅ 验证结果表格

| 测试用例 | 修复前结果 | 修复后结果 | 状态 |
|---------|-----------|-----------|------|
| `calculate_sum([1,2,3,4,5])` | `IndexError: list index out of range` | `15` | ✅ 通过 |
| `calculate_sum([])` | `0`（空循环不触发 bug） | `0` | ✅ 通过 |
| 主程序 `python3 buggy_code.py` | 崩溃退出 (exit code 1) | 输出 `Sum: 15` (exit code 0) | ✅ 通过 |

---

## 🔄 L-R-V 流程总结

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCALIZATION 定位                         │
│                                                             │
│  Round 1: Read 读取文件          ← OODA: Observe            │
│  Round 2: Grep "i + 1" 搜索     ← OODA: Orient             │
│  Round 3: Grep "range(len" 搜索 ← OODA: Orient             │
│  Round 4: Bash 运行复现错误      ← OODA: Observe            │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                      REPAIR 修复                            │
│                                                             │
│  Round 5: Edit 精确替换一行      ← OODA: Decide + Act       │
│  Round 6: Read 确认修改正确      ← OODA: Observe            │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    VALIDATION 验证                           │
│                                                             │
│  Round 7: Bash 运行验证输出      ← OODA: Observe            │
│  Round 8: Bash 断言测试边界      ← OODA: Observe + Orient   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📌 关键教学点

1. **Localization 占了 4/8 轮**（50%）——定位比修复更重要。找到 bug 的准确位置和根因，修复通常是 trivial 的。

2. **工具组合的威力**：Read（全局视野）→ Grep（精确搜索）→ Bash（运行验证），三种工具配合完成定位。

3. **Edit 的精确性**：只改 1 行，old_string 必须唯一匹配。这比 `sed` 或重写文件安全得多。

4. **Validation 不只是"跑通"**：不仅要测试修复的 case，还要测试边界 case（空列表），确保没有引入回归。

5. **OODA 循环嵌套在 L-R-V 中**：每个阶段内部都有自己的 Observe-Orient-Decide-Act 小循环，形成多层决策结构。

---

*录制时间：2026-03-26 | 所有工具输出均为真实执行结果*
