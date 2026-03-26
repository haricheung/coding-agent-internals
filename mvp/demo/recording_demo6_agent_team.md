# Demo 6 录制：Agent Team 协作模式

## 演示目标

展示多 Agent 协作的完整流程：**任务分解 -> 并行执行 -> 汇总报告**。

核心观点：
- 单 Agent 是「一个人干所有事」，Agent Team 是「项目经理 + 多个工程师」
- **TaskStore** 是协作的基础设施，解耦了主 Agent 和子 Agent 的通信
- 子 Agent 拥有**独立上下文 + 受限工具集**，实现安全的并行执行

模拟场景：用户说「修复 buggy_code.py 和 large_module.py 中的 bug，然后验证」

---

## Agent Team 架构图

```
                    用户指令：「修复两个文件的 bug」
                              |
                              v
 ┌──────────────────────────────────────────────────────────────────┐
 |                     主 Agent (Orchestrator)                      |
 |                                                                  |
 |  Step 1: 分析指令 -> 识别 3 个可追踪的子任务                      |
 |  Step 2: TaskCreate x 3 -> 写入 TaskStore                       |
 |  Step 3: Agent(prompt, task_id) x 3 -> 生成子 Agent 并行执行      |
 |  Step 4: TaskList() 轮询 -> 等待全部 completed                   |
 |  Step 5: 汇总子 Agent 结果 -> 向用户报告                          |
 └──────┬──────────────────┬──────────────────┬─────────────────────┘
        |                  |                  |
        |    并行执行       |                  |
        v                  v                  v
 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
 |  子 Agent 1  |  |  子 Agent 2  |  |  子 Agent 3  |
 |              |  |              |  |              |
 |  独立上下文   |  |  独立上下文   |  |  独立上下文   |
 |  受限工具集   |  |  受限工具集   |  |  受限工具集   |
 | (Read/Edit/  |  | (Read/Edit/  |  | (Read/Edit/  |
 |  Grep/Bash)  |  |  Grep/Bash)  |  |  Grep/Bash)  |
 |              |  |              |  |              |
 | 任务 #1:     |  | 任务 #2:     |  | 任务 #3:     |
 | 修 off-by-1  |  | 修 除零 bug  |  | 运行验证     |
 | TaskUpdate   |  | TaskUpdate   |  | TaskUpdate   |
 | -> completed |  | -> completed |  | -> completed |
 └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
        |                 |                  |
        v                 v                  v
 ┌──────────────────────────────────────────────────┐
 |              共享 TaskStore (线程安全)             |
 |  ┌────────┐   ┌────────┐   ┌────────┐           |
 |  | #1     |   | #2     |   | #3     |           |
 |  | done   |   | done   |   | done   |           |
 |  └────────┘   └────────┘   └────────┘           |
 |  主 Agent 通过 TaskList() 轮询，发现 3/3 完成     |
 └──────────────────────────────────────────────────┘
```

---

## Phase 1: 主 Agent 分析与任务分解

### 主 Agent 的思考过程

```
[主 Agent 内部推理]
用户要求修复 buggy_code.py 和 large_module.py 中的 bug。
分析：
  - buggy_code.py: calculate_sum 函数有 off-by-one bug
  - large_module.py: normalize 函数当所有值相同时除零
  - 两个文件修复完全独立，可以并行
  - 修复后需要统一验证
  -> 决策：分解为 3 个子任务（修复 x2 + 验证 x1）
```

### 初始化 TaskStore 和工具

```python
import sys
sys.path.insert(0, '/root/work/qlzhang/code/coding-agent-internals/mvp/src')
from task_tools import TaskStore, TaskCreateTool, TaskUpdateTool, TaskListTool

store = TaskStore()
create = TaskCreateTool(store)
update = TaskUpdateTool(store)
lst = TaskListTool(store)
```

### TaskCreate: 创建 3 个子任务

**TaskCreate #1:**

```python
>>> create.execute(description="修复 buggy_code.py 中的 off-by-one bug")
```

输出：
```
Created task #1: 修复 buggy_code.py 中的 off-by-one bug
Status: pending
```

**TaskCreate #2:**

```python
>>> create.execute(description="修复 large_module.py 的 normalize 除零 bug")
```

输出：
```
Created task #2: 修复 large_module.py 的 normalize 除零 bug
Status: pending
```

**TaskCreate #3:**

```python
>>> create.execute(description="验证所有修复：运行测试确认无错误")
```

输出：
```
Created task #3: 验证所有修复：运行测试确认无错误
Status: pending
```

### TaskList: 查看初始状态

```python
>>> lst.execute()
```

输出：
```markdown
## Tasks
- [ ] #1: 修复 buggy_code.py 中的 off-by-one bug (pending)
- [ ] #2: 修复 large_module.py 的 normalize 除零 bug (pending)
- [ ] #3: 验证所有修复：运行测试确认无错误 (pending)

Summary: 0/3 completed, 3 pending
```

> **💡 重点解说：任务分解的设计意图**
>
> 主 Agent 把一个模糊的用户指令分解成了 3 个**可追踪、可独立执行**的子任务。每个任务有唯一 ID，用于后续的状态更新和进度查询。这就是 Agent Team 中 Orchestrator 的核心能力：**将复合意图转化为结构化的执行计划**。
>
> 注意任务 #3（验证）依赖任务 #1 和 #2 的完成，因此会在前两个任务完成后才启动。这种依赖关系的识别也是 Orchestrator 的职责。

---

## Phase 2: 子 Agent 并行执行

> 在真实系统中，子 Agent 1 和子 Agent 2 在独立线程中**并行**运行。
> 这里按顺序模拟每个子 Agent 的执行过程，展示其独立的工具调用链。

---

### 子 Agent 1: 修复 buggy_code.py 的 off-by-one bug

**Step 1 - TaskUpdate: 标记任务为进行中**

```python
>>> update.execute(task_id="1", status="in_progress")
```

输出：
```
🔄 Task #1 updated to 'in_progress': 修复 buggy_code.py 中的 off-by-one bug
```

**Step 2 - Read: 读取目标文件**

子 Agent 1 使用 Read 工具读取 `buggy_code.py` 全文：

```python
# 子 Agent 1 调用: Read(file_path="mvp/tests/buggy_code.py")
```

真实输出：
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

**Step 3 - 分析 Bug:**

```
子 Agent 1 推理：
  第 8-9 行: for i in range(len(numbers)) 中 i 的范围是 [0, len-1]
  但第 9 行使用 numbers[i + 1]
  当 i = len(numbers) - 1 时，i + 1 = len(numbers)，越界！
  -> IndexError: list index out of range
  修复方案：将 numbers[i + 1] 改为 numbers[i]
```

**Step 4 - Edit: 执行修复**

```python
# 子 Agent 1 调用:
# Edit(file_path="mvp/tests/buggy_code.py",
#      old_string="total += numbers[i + 1]  # Bug: off-by-one error",
#      new_string="total += numbers[i]  # Fixed: use correct index")
```

**Step 5 - Bash: 验证修复**

```bash
$ python3 mvp/tests/buggy_code.py
```

修复后真实输出：
```
Sum: 15
EXIT_CODE=0
```

**Step 6 - TaskUpdate: 标记任务完成**

```python
>>> update.execute(task_id="1", status="completed")
```

输出：
```
✅ Task #1 updated to 'completed': 修复 buggy_code.py 中的 off-by-one bug
```

**TaskList: 查看进度**

```python
>>> lst.execute()
```

输出：
```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 off-by-one bug (completed)
- [ ] #2: 修复 large_module.py 的 normalize 除零 bug (pending)
- [ ] #3: 验证所有修复：运行测试确认无错误 (pending)

Summary: 1/3 completed, 2 pending
```

> **💡 重点解说：TaskStore 的状态流转**
>
> 任务 #1 经历了完整的状态机流转：`pending -> in_progress -> completed`。
> 注意此时任务 #2 和 #3 仍然是 `pending` 状态。在真实的并行场景中，
> 子 Agent 2 可能同时在执行，但 TaskStore 的线程安全锁（`threading.Lock`）
> 确保并发更新不会出现竞态条件。

---

### 子 Agent 2: 修复 large_module.py 的 normalize 除零 bug

**Step 1 - TaskUpdate: 标记任务为进行中**

```python
>>> update.execute(task_id="2", status="in_progress")
```

输出：
```
🔄 Task #2 updated to 'in_progress': 修复 large_module.py 的 normalize 除零 bug
```

**Step 2 - Grep: 粗粒度定位 bug**

子 Agent 2 面对一个 442 行的大文件，先用 Grep 工具定位关键变量 `range_val`：

```python
# 子 Agent 2 调用: Grep(pattern="range_val", path="mvp/tests/large_module.py")
```

真实输出：
```
/root/work/qlzhang/code/coding-agent-internals/mvp/tests/large_module.py:201:         range_val = max_val - min_val
/root/work/qlzhang/code/coding-agent-internals/mvp/tests/large_module.py:206:                 normalized = (record.value - min_val) / range_val

[2 matches found]
```

> **💡 重点解说：Grep -> Read 的漏斗策略**
>
> 442 行的文件，Grep 只返回了 2 行匹配。子 Agent 现在知道 bug 在第 201 行和第 206 行附近，
> 接下来只需精读这一小段代码，而不是把整个文件塞入上下文。
> 这就是 ACI 的「**粗粒度定位 -> 细粒度精读**」漏斗策略。

**Step 3 - Read: 精读第 195-210 行**

```python
# 子 Agent 2 调用: Read(file_path="mvp/tests/large_module.py", offset=194, limit=16)
```

真实输出：
```
195 |         values = [r.value for r in valid]
196 |         min_val = min(values)
197 |         max_val = max(values)
198 |
199 |         # BUG: 当所有值相同时，max_val == min_val，除以零！
200 |         # 这是故意留下的 bug，用于 Demo 3 的 bug 修复演示
201 |         range_val = max_val - min_val
202 |
203 |         new_records = []
204 |         for record in dataset.records:
205 |             if record.is_valid():
206 |                 normalized = (record.value - min_val) / range_val
207 |                 new_records.append(DataRecord(
208 |                     value=normalized,
209 |                     timestamp=record.timestamp,
210 |                     label=record.label,

[Showing lines 195-210 of 442 total]
```

**Step 4 - 分析 Bug:**

```
子 Agent 2 推理：
  第 201 行: range_val = max_val - min_val
  第 206 行: normalized = (record.value - min_val) / range_val

  当所有值相同时: max_val == min_val -> range_val = 0
  第 206 行除以 range_val -> ZeroDivisionError!

  修复方案: 在第 201 行后添加 range_val == 0 的检查
  当 range_val == 0 时设为 1.0，归一化结果为 0.0（所有值相同，偏差为 0）
```

**Step 5 - Edit: 执行修复**

```python
# 子 Agent 2 调用:
# Edit(file_path="mvp/tests/large_module.py",
#      old_string="range_val = max_val - min_val",
#      new_string="range_val = max_val - min_val\n        if range_val == 0:\n            range_val = 1.0  # 避免除零")
```

**Step 6 - Bash: 验证修复**

```bash
$ python3 -c "... 模拟 normalize 修复后运行 ..."
```

修复后真实输出：
```
Testing normalize on uniform data (after fix)...
  Result: [0.0, 0.0, 0.0]
  Status: PASS (no ZeroDivisionError)
EXIT_CODE=0
```

**Step 7 - TaskUpdate: 标记任务完成**

```python
>>> update.execute(task_id="2", status="completed")
```

输出：
```
✅ Task #2 updated to 'completed': 修复 large_module.py 的 normalize 除零 bug
```

**TaskList: 查看进度（子 Agent 1 & 2 完成后）**

```python
>>> lst.execute()
```

输出：
```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 off-by-one bug (completed)
- [x] #2: 修复 large_module.py 的 normalize 除零 bug (completed)
- [ ] #3: 验证所有修复：运行测试确认无错误 (pending)

Summary: 2/3 completed, 1 pending
```

> **💡 重点解说：主 Agent 的轮询决策点**
>
> 此时主 Agent 通过 `TaskList()` 发现任务 #1 和 #2 已完成，#3 仍为 `pending`。
> 由于 #3（验证）依赖 #1 和 #2 的完成，现在是启动子 Agent 3 的正确时机。
> 这就是 TaskStore 作为「看板」的价值：主 Agent 不需要直接持有子 Agent 引用，
> 只需要查看 TaskStore 就能掌握全局进度。

---

### 子 Agent 3: 验证所有修复

**Step 1 - TaskUpdate: 标记任务为进行中**

```python
>>> update.execute(task_id="3", status="in_progress")
```

输出：
```
🔄 Task #3 updated to 'in_progress': 验证所有修复：运行测试确认无错误
```

**TaskList: 查看执行中状态**

```python
>>> lst.execute()
```

输出：
```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 off-by-one bug (completed)
- [x] #2: 修复 large_module.py 的 normalize 除零 bug (completed)
- [ ] #3: 验证所有修复：运行测试确认无错误 (in_progress)

Summary: 2/3 completed, 1 in progress
```

**Step 2 - Bash: 验证 buggy_code.py（修复前 vs 修复后）**

修复前运行（真实输出 -- 展示原始 bug）：
```bash
$ python3 mvp/tests/buggy_code.py
```
```
Traceback (most recent call last):
  File "mvp/tests/buggy_code.py", line 20, in <module>
    main()
  File "mvp/tests/buggy_code.py", line 15, in main
    result = calculate_sum(nums)
  File "mvp/tests/buggy_code.py", line 9, in calculate_sum
    total += numbers[i + 1]  # Bug: off-by-one error
IndexError: list index out of range
EXIT_CODE=1
```

修复后运行（真实输出）：
```bash
$ python3 mvp/tests/fixed_code.py
```
```
Sum: 15
EXIT_CODE=0
```

验证结论：`calculate_sum([1,2,3,4,5])` 返回 15，正确。

**Step 3 - Bash: 验证 large_module.py（修复前 vs 修复后）**

修复前运行（真实输出 -- 展示原始 bug）：
```bash
$ python3 mvp/tests/large_module.py
```
```
Created: DataSet(name='sample', size=100)
Sample records: [DataRecord(value=-2.4765482515740556, label='A'), DataRecord(value=-3.618749545681931, label='B'), DataRecord(value=1.7728119836591207, label='C')]

Validation passed: False
Outliers at indices: []
Statistics: {'count': 100, 'mean': 24.814797650478965, 'min': -3.618749545681931, 'max': 52.787312080102815, 'median': 24.358461623629196, 'std': 14.8445828014903, 'q25': 13.24555446003693, 'q75': 36.71513687102477}

Testing normalize on uniform data...
  BUG: ZeroDivisionError when all values are the same!
EXIT_CODE=0
```

修复后运行（真实输出）：
```
Testing normalize on uniform data (after fix)...
  Result: [0.0, 0.0, 0.0]
  Status: PASS (no ZeroDivisionError)
EXIT_CODE=0
```

验证结论：均匀数据归一化不再报错，结果全为 0.0，符合预期。

**Step 4 - TaskUpdate: 标记任务完成**

```python
>>> update.execute(task_id="3", status="completed")
```

输出：
```
✅ Task #3 updated to 'completed': 验证所有修复：运行测试确认无错误
```

---

## Phase 3: 主 Agent 汇总

### TaskList 最终状态（3/3 completed）

```python
>>> lst.execute()
```

真实输出：
```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 off-by-one bug (completed)
- [x] #2: 修复 large_module.py 的 normalize 除零 bug (completed)
- [x] #3: 验证所有修复：运行测试确认无错误 (completed)

Summary: 3/3 completed
```

> **💡 重点解说：3/3 completed 的意义**
>
> 当主 Agent 轮询 `TaskList()` 发现 `Summary: 3/3 completed` 时，
> 它知道所有子任务都已完成，可以进入汇总阶段。
> 这就是 TaskStore 的「看板」模式：不需要复杂的回调机制或事件系统，
> 简单的轮询 + 状态检查就足够了。

### 主 Agent 生成汇总报告

```
所有 3 个子任务已完成：

  1. buggy_code.py: calculate_sum 函数的 off-by-one bug 已修复
     - 原因: numbers[i + 1] 在 i = len-1 时越界
     - 修复: numbers[i + 1] -> numbers[i]
     - 验证: calculate_sum([1,2,3,4,5]) = 15 ✓

  2. large_module.py: normalize 函数的除零 bug 已修复
     - 原因: 所有值相同时 range_val = max - min = 0，除以 0 触发 ZeroDivisionError
     - 修复: 添加 range_val == 0 检查，设为 1.0 避免除零
     - 验证: uniform data normalize 返回 [0.0, 0.0, 0.0] ✓

  3. 验证通过: 两个文件均可正常运行，无错误

修复摘要：
  - 文件修改: 2 个
  - Bug 类型: IndexError (off-by-one) + ZeroDivisionError (边界条件)
  - 测试状态: 全部通过
```

---

## 📊 关键设计决策解析

### 决策 1: 为什么子 Agent 需要独立上下文？（防止上下文污染）

```
场景：子 Agent 1 正在修复 buggy_code.py，读取了大量代码和错误堆栈。
如果这些信息泄露到子 Agent 2 的上下文中：

子 Agent 2（处理 large_module.py）会看到：
  - buggy_code.py 的代码片段
  - "IndexError: list index out of range" 的讨论
  - numbers[i+1] 的修复方案

这些无关信息会：
  1. 占用宝贵的上下文窗口（7B 模型只有 4K-8K 上下文）
  2. 干扰模型推理（可能混淆两个完全不同的 bug）
  3. 降低输出质量（注意力被分散到不相关的信息上）

独立上下文 = 每个子 Agent 只看到自己任务相关的信息
就像现实中的工程师各自在自己的 IDE 中工作，互不干扰。

     ┌─────────────────────┐    ┌─────────────────────┐
     |   子 Agent 1 上下文   |    |   子 Agent 2 上下文   |
     |                     |    |                     |
     |  buggy_code.py      |    |  large_module.py    |
     |  IndexError         |    |  ZeroDivisionError  |
     |  numbers[i+1]       |    |  range_val = 0      |
     |                     |    |                     |
     |  互不可见 ←──────────|────|──→ 互不可见         |
     └─────────────────────┘    └─────────────────────┘
```

### 决策 2: 为什么子 Agent 有受限工具集？（防止递归爆炸）

```
子 Agent 的工具集：Read, Write, Edit, Grep, Bash（5 个执行工具）
子 Agent 不能使用：TaskCreate, TaskUpdate, TaskList, Agent（4 个管理工具）

如果子 Agent 能调用 Agent 工具（递归爆炸）：
  主 Agent
    -> 子 Agent 1
       -> 孙 Agent 1.1
          -> 曾孙 Agent 1.1.1
             -> ...（指数级膨胀！）

如果子 Agent 能调用 TaskCreate（角色越界）：
  子 Agent 1 创建了 Task #4, #5, #6
  主 Agent 不知道这些任务从哪来，规划混乱
  子 Agent 的职责是「执行」，不是「规划」

受限工具集 = 明确的职责边界

  ┌─────────────────────────────────────────────┐
  |              职责分离原则                      |
  |                                             |
  |  主 Agent:  规划 (TaskCreate)               |
  |            分派 (Agent)                     |
  |            监控 (TaskList)                  |
  |                                             |
  |  子 Agent: 执行 (Read/Edit/Grep/Bash)       |
  |            汇报 (TaskUpdate -> completed)   |
  └─────────────────────────────────────────────┘
```

### 决策 3: 为什么用 TaskStore 协调而非直接通信？（松耦合）

```
方案 A（直接通信 -- 紧耦合）：
  主 Agent 持有子 Agent 引用，直接调用 sub_agent.get_result()
  问题：主 Agent 必须知道每个子 Agent 的内部状态

方案 B（TaskStore 协调 -- 松耦合）：
  子 Agent 完成后更新 TaskStore
  主 Agent 轮询 TaskStore 发现完成

TaskStore 充当「消息队列」的角色：

┌──────────┐     write      ┌───────────┐     read      ┌──────────┐
| 子 Agent  | ────────────> | TaskStore  | <──────────── | 主 Agent  |
| (生产者)  |  TaskUpdate   | (消息队列)  |   TaskList    | (消费者)  |
└──────────┘               └───────────┘               └──────────┘

优势：
  - 松耦合：主 Agent 不需要持有子 Agent 引用
  - 可观测性：TaskList 提供全局视图，像看板一样
  - 容错性：子 Agent 崩溃了，任务状态仍保留（stuck in_progress）
  - 可扩展：未来可替换为 Redis/RabbitMQ 等真正的消息队列
```

---

## 完整执行时间线

```
时间   事件                                              TaskStore 状态
─────  ─────────────────────────────────────────────     ──────────────────
t=0    [主 Agent] 接收用户指令                             (空)
t=1    [主 Agent] TaskCreate #1                           #1:pending
t=2    [主 Agent] TaskCreate #2                           #1:pending #2:pending
t=3    [主 Agent] TaskCreate #3                           #1:pending #2:pending #3:pending
t=4    [主 Agent] 启动子 Agent 1 和 2（并行）
       ┌─────────────────────────────┬─────────────────────────────┐
t=5    | [子Agent1] #1->in_progress  | [子Agent2] #2->in_progress  |
t=6    | [子Agent1] Read buggy_code  | [子Agent2] Grep range_val   |
t=7    | [子Agent1] 分析: i+1 越界   | [子Agent2] Read 195-210行   |
t=8    | [子Agent1] Edit: 修复       | [子Agent2] 分析: 除零       |
t=9    | [子Agent1] Bash: 验证 PASS  | [子Agent2] Edit: 修复       |
t=10   | [子Agent1] #1->completed    | [子Agent2] Bash: 验证 PASS  |
       |                             | [子Agent2] #2->completed    |
       └─────────────────────────────┴─────────────────────────────┘
t=11   [主 Agent] TaskList() -> 2/3 completed, 1 pending
t=12   [主 Agent] 启动子 Agent 3（验证任务）
       ┌─────────────────────────────┐
t=13   | [子Agent3] #3->in_progress  |
t=14   | [子Agent3] Bash: 验证 #1    |
t=15   | [子Agent3] Bash: 验证 #2    |
t=16   | [子Agent3] #3->completed    |
       └─────────────────────────────┘
t=17   [主 Agent] TaskList() -> 3/3 completed
t=18   [主 Agent] 生成汇总报告，返回给用户
```

---

## 教学要点总结

### 1. 子 Agent 执行可标准化（7B 模型够用）

子 Agent 的工作模式是高度结构化的 L-R-V 流程：

```
Grep(关键词) -> Read(文件) -> Edit(修复) -> Bash(验证)
   定位           精读          修复          验证
```

每一步的输入输出都是明确的，不需要高级推理能力，7B 模型完全胜任。
就像流水线上的工人：给他操作手册（prompt），他就能正确执行。

### 2. Orchestrator 规划是瓶颈（需要强模型）

「修复这两个文件的 bug」这句话包含了多少隐含判断？
- 哪些文件？（需要从上下文推断）
- 什么 bug？（需要先读代码才知道）
- 怎么分解？（需要判断任务独立性）
- 什么顺序？（需要识别依赖关系）
- 怎么验证？（需要理解预期行为）

这些判断需要「世界知识 + 推理能力」，是 7B 模型的短板。
现实选择：Orchestrator 用强模型（70B+ / Claude），子 Agent 可用弱模型。

### 3. Agent Team 是放大器，不是万能药

```
Agent Team 的放大效果：
  + 并行执行，提升吞吐
  + 独立上下文，保护推理质量
  + 任务追踪，提供可观测性

但如果基础能力不够：
  - Orchestrator 分解错了 -> 所有子 Agent 白忙活
  - 子 Agent 理解不了 prompt -> 修复方向错误

类比：
  10 个实习生 + 好的项目经理 = 高效团队
  10 个实习生 + 实习生当经理 = 混乱
  1 个高级工程师独自工作 = 也许比上面两种都好

结论：先确保单 Agent 能力达标，再引入 Agent Team。
```

---

## 附录：关键源文件

| 文件 | 作用 | 行数 |
|------|------|------|
| `mvp/src/task_tools.py` | TaskStore + TaskCreate/Update/List 工具 | 428 行 |
| `mvp/src/tools.py` | Read/Write/Edit/Grep/Bash 基础工具 | 740 行 |
| `mvp/tests/buggy_code.py` | 演示用 bug 文件 (off-by-one IndexError) | 20 行 |
| `mvp/tests/large_module.py` | 演示用 bug 文件 (ZeroDivisionError) | 442 行 |
