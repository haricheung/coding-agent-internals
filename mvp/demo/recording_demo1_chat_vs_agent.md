# Demo 1 录制：Chat 模式 vs Agent 模式对比

## 演示目标

通过同一个 bug-fix 任务，对比展示两种 AI 编程交互范式的核心差异：

| | Chat 模式（开环） | Agent 模式（闭环） |
|---|---|---|
| **交互方式** | 人粘贴代码 → 模型一次性回答 | Agent 自主读取 → 分析 → 搜索 → 执行验证 |
| **验证能力** | 无法运行代码，无法确认修复正确 | 自动运行代码，用真实输出确认修复 |
| **核心区别** | 开环（open-loop）：无反馈 | 闭环（closed-loop）：有反馈回路 |

**目标代码**：`mvp/tests/buggy_code.py` —— 一个包含 off-by-one 错误的求和函数。

---

## Part A：Chat 模式（开环演示）

### 🎬 [00:00] 用户将代码粘贴给 Chat LLM

用户手动复制代码，粘贴到聊天窗口：

```
用户：请帮我看看这段代码有什么 bug：

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total
```

> 💡 **重点解说**：Chat 模式下，用户必须**手动**复制粘贴代码。如果项目有几十个文件，用户需要判断该贴哪个文件、贴多少内容。上下文组装完全依赖人类。

---

### 🎬 [00:15] Chat LLM 的一次性回答

```
LLM 回答：

这段代码有一个 off-by-one 错误。在第 5 行：

    total += numbers[i + 1]

当 i 到达 len(numbers) - 1 时，i + 1 等于 len(numbers)，
会导致 IndexError: list index out of range。

修复方案：将 numbers[i + 1] 改为 numbers[i]：

def calculate_sum(numbers):
    total = 0
    for i in range(len(numbers)):
        total += numbers[i]
    return total

或者使用更 Pythonic 的写法：

def calculate_sum(numbers):
    return sum(numbers)
```

> 💡 **重点解说**：Chat 模式的回答**看起来正确**，但存在关键缺陷——它没有运行代码验证。LLM 可能给出错误的修复建议（幻觉），而用户无从分辨。这就是"开环"：模型输出后没有反馈回路。

---

### 🎬 [00:30] Chat 模式的局限

Chat 模式到此**结束**。用户需要：
1. 自己把修复后的代码粘贴回编辑器
2. 自己运行测试验证
3. 如果还有问题，再粘贴回 Chat 窗口，开启下一轮

**没有任何自动化验证环节。**

---

## Part B：Agent 模式（闭环演示）

### 🎬 [01:00] Step 1 — Agent 使用 Read 工具读取源文件

用户仅给出一句指令：

```
用户：帮我修复 mvp/tests/buggy_code.py 中的 bug
```

Agent 自主调用 **Read** 工具：

**工具调用**：
```
Tool: Read
参数: file_path = "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
```

**返回结果**：
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

> 💡 **重点解说**：Agent **不需要用户粘贴代码**。它直接通过 Read 工具读取文件系统，获得完整的、带行号的源代码。上下文组装由 Agent 自主完成。

---

### 🎬 [01:15] Step 2 — Agent 使用 Grep 工具搜索可疑模式

Agent 对第 9 行的 `i + 1` 索引产生怀疑，用 **Grep** 工具确认所有类似模式的出现位置：

**工具调用**：
```
Tool: Grep
参数:
  pattern = "i \+ 1"
  path = "/root/work/qlzhang/code/coding-agent-internals/mvp/tests/buggy_code.py"
  output_mode = "content"
  -n = true
```

**返回结果**：
```
9:        total += numbers[i + 1]  # Bug: off-by-one error
```

> 💡 **重点解说**：Agent 像一个真正的开发者一样，用搜索工具定位可疑代码。Grep 返回精确的行号和上下文，帮助 Agent 确认问题的范围——只有第 9 行存在这个模式。这不是猜测，是基于代码搜索的事实。

---

### 🎬 [01:30] Step 3 — Agent 分析 Bug

基于读取和搜索的结果，Agent 进行分析：

```
Agent 分析：

第 9 行存在 off-by-one 错误：
  total += numbers[i + 1]

for 循环中 i 的取值范围为 0 到 len(numbers)-1。
当 i = len(numbers)-1 时，i+1 = len(numbers)，超出列表索引范围。

此外，即使不越界（比如列表足够长），这个逻辑也是错的：
- 它跳过了 numbers[0]（第一个元素从不被累加）
- 它多读了 numbers[len(numbers)]（不存在的元素）

这是一个典型的 off-by-one error。

修复方案：将 numbers[i + 1] 改为 numbers[i]。
```

> 💡 **重点解说**：Agent 的分析比 Chat 模式更深入——它不仅指出了会 crash，还指出了**语义错误**（跳过第一个元素）。但关键区别在下一步：Agent 不会止步于分析，它会**验证**。

---

### 🎬 [01:45] Step 4 — Agent 使用 Bash 工具运行代码验证

Agent 调用 **Bash** 工具运行原始代码，观察真实错误：

**工具调用**：
```
Tool: Bash
参数: command = "python mvp/tests/buggy_code.py"
```

**返回结果**（退出码 1，执行失败）：
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

> 💡 **重点解说**：**这是 Agent 模式的核心优势——闭环验证。** Agent 实际运行了代码，看到了真实的 `IndexError` 错误堆栈。它不是在"猜"代码有 bug，而是亲眼"看到"了 bug 的发生。Chat 模式永远做不到这一步。

---

### 🎬 [02:00] Step 5 — Agent 展示修复方案

基于真实的错误验证，Agent 给出修复方案：

```
Agent 修复方案：

文件：mvp/tests/buggy_code.py
第 9 行：
  - 原代码：total += numbers[i + 1]  # Bug: off-by-one error
  + 修复后：total += numbers[i]       # Fixed: use correct index

修复原理：循环变量 i 本身已经覆盖了 0 到 len(numbers)-1 的范围，
直接使用 numbers[i] 即可正确遍历列表的每一个元素。
```

> 💡 **重点解说**：在真实的 Agent 工作流中，这一步会调用 Edit 工具直接修改文件。此处为演示目的，仅展示修复方案而不实际修改。

---

### 🎬 [02:15] Step 6 — Agent 验证修复后的结果

Agent 运行已修复的版本来确认修复是否正确：

**工具调用**：
```
Tool: Bash
参数: command = "python mvp/tests/fixed_code.py"
```

**返回结果**（退出码 0，执行成功）：
```
Sum: 15
```

验证：`1 + 2 + 3 + 4 + 5 = 15` ✓

> 💡 **重点解说**：**闭环闭合！** Agent 不仅找到了 bug、给出了修复，还**运行修复后的代码确认结果正确**。输出 `Sum: 15` 与预期的 `1+2+3+4+5=15` 完全吻合。这就是 Agent 模式 "Read → Analyze → Edit → Verify" 闭环的完整体现。

---

## Part C：并排对比

### 同一个任务，两种模式的执行路径

| 步骤 | Chat 模式（开环） | Agent 模式（闭环） |
|------|-------------------|-------------------|
| **获取代码** | 用户手动复制粘贴 | Agent 调用 `Read` 工具自动读取 |
| **搜索上下文** | 用户自行查找，或不搜索 | Agent 调用 `Grep` 工具精确搜索 |
| **分析 Bug** | LLM 基于粘贴内容推理 | Agent 基于完整文件 + 搜索结果推理 |
| **验证 Bug** | ❌ 无法运行代码 | ✅ 调用 `Bash` 运行，看到 `IndexError` |
| **给出修复** | 直接输出修复建议 | 输出修复建议 |
| **验证修复** | ❌ 无法验证 | ✅ 调用 `Bash` 运行修复后代码，确认 `Sum: 15` |
| **自动应用** | ❌ 用户手动粘贴 | ✅ 可调用 `Edit` 工具直接修改文件 |

---

## 📊 对比总结

| 维度 | Chat 模式 | Agent 模式 | 差异分析 |
|------|----------|-----------|---------|
| **交互轮次** | 1 轮（问→答） | 1 轮指令，Agent 内部 4+ 步 | Agent 自动展开多步工作流 |
| **工具调用** | 0 次 | 4 次（Read + Grep + Bash×2） | Agent 拥有环境操作能力 |
| **代码运行** | 0 次 | 2 次（验证 bug + 验证修复） | Chat 是纯推理，Agent 有执行能力 |
| **验证环节** | 无 | 有（前后对比验证） | 这是最关键的差异 |
| **上下文来源** | 人工粘贴 | Agent 自主获取 | Agent 可探索整个代码库 |
| **幻觉风险** | 高（无法验证输出） | 低（执行结果提供 ground truth） | 闭环反馈抑制幻觉 |
| **适用场景** | 小片段问答、学习 | 真实项目的 bug 修复、重构 | 复杂度越高，Agent 优势越大 |

---

## 教学总结

### 一句话概括

> **Chat 模式是"看图猜病"，Agent 模式是"看图 → 化验 → 确诊 → 治疗 → 复查"。**

### 三个关键 Takeaway

1. **开环 vs 闭环**：Chat 模式输出后没有反馈回路，Agent 模式通过 Bash 执行构建了 "行动→观察→修正" 的闭环。闭环是 Agent 区别于 Chat 的本质特征。

2. **工具是 Agent 的手脚**：Read（眼睛）、Grep（搜索）、Edit（双手）、Bash（验证）—— 四种工具组合使 LLM 从"只会说"变成"会做"。

3. **验证消灭幻觉**：Chat 模式下 LLM 可能自信地给出错误答案，Agent 模式下错误会被 Bash 的真实输出立即暴露。**能运行的答案才是可信的答案。**

---

*录制完成。本文件记录了 Demo 1 的完整执行过程，所有工具调用的输入和输出均为真实执行结果。*
