# Demo 6: Agent Team 协作模式

## 演示目标

展示多 Agent 协作的完整流程：**分解 -> 并行 -> 汇总**。

核心观点：
- 单 Agent 是「一个人干所有事」，Agent Team 是「项目经理 + 多个工程师」
- TaskStore 是协作的基础设施，解耦了主 Agent 和子 Agent 的通信
- 子 Agent 独立上下文 + 受限工具集 = 安全的并行执行

模拟场景：用户说「修复 buggy_code.py 和 large_module.py 中的 bug」

---

## Agent Team 架构图

```
┌─────────────────────────────────────────────────────────────┐
│              主 Agent (Orchestrator)                         │
│                                                             │
│  1. 分析用户指令 -> 识别独立子任务                             │
│  2. TaskCreate x N -> 分解为可追踪的子任务                    │
│  3. Agent(prompt, task_id) x N -> 生成子 Agent               │
│  4. TaskList() 轮询 -> 等待子任务完成                         │
│  5. 汇总结果 -> 向用户报告                                    │
└───────┬─────────────────┬─────────────────┬─────────────────┘
        │                 │                 │
        │  并行执行        │                 │
        v                 v                 v
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  子 Agent 1   │ │  子 Agent 2   │ │  子 Agent 3   │
│               │ │               │ │               │
│  独立上下文    │ │  独立上下文    │ │  独立上下文    │
│  受限工具集    │ │  受限工具集    │ │  受限工具集    │
│  (Read/Edit/  │ │  (Read/Edit/  │ │  (Read/Edit/  │
│   Grep/Bash)  │ │   Grep/Bash)  │ │   Grep/Bash)  │
│               │ │               │ │               │
│  执行任务 #1  │ │  执行任务 #2  │ │  执行任务 #3  │
│  完成后:      │ │  完成后:      │ │  完成后:      │
│  TaskUpdate   │ │  TaskUpdate   │ │  TaskUpdate   │
│  -> completed │ │  -> completed │ │  -> completed │
└───────────────┘ └───────────────┘ └───────────────┘
        │                 │                 │
        └────────┬────────┘                 │
                 │                          │
        ┌────────v──────────────────────────v────────┐
        │           共享 TaskStore                    │
        │  ┌──────┐  ┌──────┐  ┌──────┐              │
        │  │ #1   │  │ #2   │  │ #3   │              │
        │  │ done │  │ done │  │ done │              │
        │  └──────┘  └──────┘  └──────┘              │
        │  主 Agent 通过 TaskList() 轮询状态           │
        └─────────────────────────────────────────────┘
```

---

## Phase 1: 主 Agent 分析与任务分解

### 主 Agent 的思考过程（模拟）

```
[主 Agent 思考]
用户要求修复 buggy_code.py 和 large_module.py 中的 bug。
分析：
  - buggy_code.py: 需要检查并修复其中的 bug
  - large_module.py: 已知 normalize 函数有除零 bug
  - 这是两个独立文件的修复，可以并行处理
  -> 决策：分解为 3 个子任务，通过 Agent 工具并行执行
```

### TaskCreate 实际调用和输出

调用代码：

```python
from task_tools import TaskStore, TaskCreateTool, TaskUpdateTool, TaskListTool

store = TaskStore()
create_tool = TaskCreateTool(store)
update_tool = TaskUpdateTool(store)
list_tool = TaskListTool(store)
```

**TaskCreate #1:**

```python
>>> create_tool.execute(description='修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑')
```

输出：
```
Created task #1: 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑
Status: pending
```

**TaskCreate #2:**

```python
>>> create_tool.execute(description='修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0')
```

输出：
```
Created task #2: 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0
Status: pending
```

**TaskCreate #3:**

```python
>>> create_tool.execute(description='验证所有修复：运行两个文件确认 bug 已修复且无新错误')
```

输出：
```
Created task #3: 验证所有修复：运行两个文件确认 bug 已修复且无新错误
Status: pending
```

### TaskList 初始状态（真实输出）

```python
>>> list_tool.execute()
```

```markdown
## Tasks
- [ ] #1: 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑 (pending)
- [ ] #2: 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0 (pending)
- [ ] #3: 验证所有修复：运行两个文件确认 bug 已修复且无新错误 (pending)

Summary: 0/3 completed, 3 pending
```

---

## Phase 2: 子 Agent 并行执行

> 在真实系统中，3 个子 Agent 在独立线程中并行运行。
> 这里我们按顺序模拟每个子 Agent 的执行过程，展示其独立的工具调用链。

### 子 Agent 1: 修复 buggy_code.py

**TaskUpdate: 标记为 in_progress**

```python
>>> update_tool.execute(task_id='1', status='in_progress')
```

输出：
```
🔄 Task #1 updated to 'in_progress': 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑
```

**Step 1 - Read: 读取文件**

```python
# 子 Agent 1 使用 Read 工具读取 buggy_code.py
```

读取内容：
```python
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers"""
    total = 0
    for i in range(len(numbers)):
        total += numbers[i + 1]  # Bug: off-by-one error
    return total
```

**Step 2 - 分析 Bug:**

```
子 Agent 1 分析：
  numbers[i + 1] 导致越界访问。当 i = len(numbers) - 1 时，
  i + 1 = len(numbers)，超出索引范围，触发 IndexError。
  修复：将 numbers[i + 1] 改为 numbers[i]。
```

**Step 3 - Edit: 修复**

```python
# Edit 工具调用
old_string: "total += numbers[i + 1]  # Bug: off-by-one error"
new_string: "total += numbers[i]  # Fixed: use correct index"
```

**Step 4 - Bash: 验证**

```bash
$ python tests/buggy_code.py
Sum: 15
```

**TaskUpdate: 标记为 completed**

```python
>>> update_tool.execute(task_id='1', status='completed')
```

输出：
```
✅ Task #1 updated to 'completed': 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑
```

---

### 子 Agent 2: 修复 large_module.py 的 normalize 除零 bug

**TaskUpdate: 标记为 in_progress**

```python
>>> update_tool.execute(task_id='2', status='in_progress')
```

输出：
```
🔄 Task #2 updated to 'in_progress': 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0
```

**Step 1 - Grep: 定位 bug**

```bash
$ grep -n "range_val" large_module.py
201:        range_val = max_val - min_val
206:                normalized = (record.value - min_val) / range_val
```

**Step 2 - Read: 精读第 195-210 行**

```python
195:         values = [r.value for r in valid]
196:         min_val = min(values)
197:         max_val = max(values)
198:
199:         # BUG: 当所有值相同时，max_val == min_val，除以零！
200:         # 这是故意留下的 bug，用于 Demo 3 的 bug 修复演示
201:         range_val = max_val - min_val
202:
203:         new_records = []
204:         for record in dataset.records:
205:             if record.is_valid():
206:                 normalized = (record.value - min_val) / range_val
207:                 new_records.append(DataRecord(
208:                     value=normalized,
209:                     timestamp=record.timestamp,
210:                     label=record.label,
```

**Step 3 - 分析 Bug:**

```
子 Agent 2 分析：
  Bug 位置: 第 201 行 range_val = max_val - min_val
  问题: 当所有值相同时 range_val = 0，第 206 行除以 range_val 触发 ZeroDivisionError
  修复: 添加 range_val == 0 的检查，此时所有值相同，归一化结果应为 0.0
```

**Step 4 - Edit: 修复**

```python
# Edit 工具调用
old_string: "range_val = max_val - min_val"
new_string: "range_val = max_val - min_val\n        if range_val == 0:\n            range_val = 1.0  # 所有值相同时避免除零，归一化结果为 0.0"
```

**Step 5 - Bash: 验证**

```bash
$ python tests/large_module.py
Created: DataSet(name='sample', size=100)
Sample records: [DataRecord(value=-2.48, label='A'), ...]

Validation passed: False
Outliers at indices: []
Statistics: {'count': 100, 'mean': 24.81, ...}

Testing normalize on uniform data...
  Result: [0.0, 0.0, 0.0]    # <-- 修复成功！不再抛 ZeroDivisionError
```

返回码: 0

**TaskUpdate: 标记为 completed**

```python
>>> update_tool.execute(task_id='2', status='completed')
```

输出：
```
✅ Task #2 updated to 'completed': 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0
```

---

### TaskList 进度更新（子 Agent 1 和 2 完成后，真实输出）

```python
>>> list_tool.execute()
```

```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑 (completed)
- [x] #2: 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0 (completed)
- [ ] #3: 验证所有修复：运行两个文件确认 bug 已修复且无新错误 (pending)

Summary: 2/3 completed, 1 pending
```

---

### 子 Agent 3: 验证所有修复

**TaskUpdate: 标记为 in_progress**

```python
>>> update_tool.execute(task_id='3', status='in_progress')
```

输出：
```
🔄 Task #3 updated to 'in_progress': 验证所有修复：运行两个文件确认 bug 已修复且无新错误
```

**验证 buggy_code.py:**

```bash
$ python tests/buggy_code.py
Sum: 15
状态: PASS
```

**验证 large_module.py:**

```bash
$ python tests/large_module.py
Created: DataSet(name='sample', size=100)
...
Testing normalize on uniform data...
  Result: [0.0, 0.0, 0.0]
状态: PASS
```

**TaskUpdate: 标记为 completed**

```python
>>> update_tool.execute(task_id='3', status='completed')
```

输出：
```
✅ Task #3 updated to 'completed': 验证所有修复：运行两个文件确认 bug 已修复且无新错误
```

---

## Phase 3: 主 Agent 汇总

### TaskList 最终状态（全部 completed，真实输出）

```python
>>> list_tool.execute()
```

```markdown
## Tasks
- [x] #1: 修复 buggy_code.py 中的 bug：检查 calculate_sum 函数的索引逻辑 (completed)
- [x] #2: 修复 large_module.py 的 normalize 函数除零 bug：当所有值相同时 range_val=0 (completed)
- [x] #3: 验证所有修复：运行两个文件确认 bug 已修复且无新错误 (completed)

Summary: 3/3 completed
```

### 主 Agent 汇总报告

```
所有 3 个子任务已完成：
  1. buggy_code.py: calculate_sum 函数的 off-by-one bug 已修复
     - numbers[i + 1] -> numbers[i]
  2. large_module.py: normalize 函数的除零 bug 已修复
     - 添加 range_val == 0 检查，避免 ZeroDivisionError
  3. 验证通过: 两个文件均可正常运行，无错误

修复摘要：
  - 文件修改: 2 个
  - 新增代码: 3 行
  - 测试状态: 全部通过
```

---

## 关键设计决策解析

### 1. 为什么子 Agent 需要独立上下文？（防止上下文污染）

```
场景：子 Agent 1 正在修复 buggy_code.py，中间读取了大量代码和错误信息。
如果这些信息泄露到子 Agent 2 的上下文中：

子 Agent 2（处理 large_module.py）会看到：
  - buggy_code.py 的代码片段
  - "IndexError" 相关的讨论
  - numbers[i+1] 的修复方案

这些无关信息会：
  1. 占用宝贵的上下文窗口（7B 模型只有 4K-8K 上下文）
  2. 干扰模型的推理（模型可能混淆两个 bug 的修复方案）
  3. 降低输出质量（注意力被分散到不相关的信息上）

独立上下文 = 每个子 Agent 只看到自己任务相关的信息
这就像现实中的工程师各自在自己的 IDE 中工作，互不干扰。
```

### 2. 为什么子 Agent 有受限工具集？（防止递归爆炸）

```
子 Agent 的工具集：Read, Write, Edit, Grep, Bash（5 个）
子 Agent 不能使用：TaskCreate, TaskUpdate, TaskList, Agent（4 个）

如果子 Agent 能调用 Agent 工具：
  主 Agent -> 子 Agent 1 -> 孙 Agent 1.1 -> 曾孙 Agent 1.1.1 -> ...
  指数级爆炸！每层都创建新的 Client 实例、新的对话历史。

如果子 Agent 能调用 TaskCreate：
  子 Agent 1 创建了 Task #4, #5, #6
  主 Agent 不知道这些任务从哪来，规划完全混乱
  角色越界：子 Agent 的职责是「执行」，不是「规划」

受限工具集 = 明确的职责边界
  主 Agent：规划（TaskCreate）+ 分派（Agent）+ 监控（TaskList）
  子 Agent：执行（Read/Edit/Bash）
```

### 3. 为什么用 TaskStore 协调而非直接通信？（解耦）

```
方案 A（直接通信）：
  主 Agent 持有子 Agent 的引用，直接调用 sub_agent.get_result()
  问题：紧耦合，主 Agent 必须知道每个子 Agent 的内部状态

方案 B（TaskStore 协调）：
  主 Agent 和子 Agent 通过共享的 TaskStore 通信
  子 Agent 完成后更新 TaskStore -> 主 Agent 轮询 TaskStore 发现完成

  TaskStore 充当「消息队列」的角色：
  ┌──────────┐     write      ┌───────────┐     read      ┌──────────┐
  │ 子 Agent  │ ────────────> │ TaskStore  │ <──────────── │ 主 Agent  │
  │ (生产者)  │  TaskUpdate   │ (队列)     │   TaskList    │ (消费者)  │
  └──────────┘               └───────────┘               └──────────┘

优势：
  - 松耦合：主 Agent 不需要持有子 Agent 引用
  - 可观测性：TaskList 提供全局视图，像看板一样
  - 容错性：子 Agent 崩溃了，任务状态仍然保留（pending/in_progress）
  - 可扩展：未来可以替换为真正的消息队列（Redis/RabbitMQ）
```

### 4. 7B 模型作为 Orchestrator 的局限性（规划能力不足）

```
Agent Team 模式对 Orchestrator（主 Agent）的要求很高：
  1. 理解复合指令，拆分为合理的子任务
  2. 识别任务间的依赖关系（哪些可以并行，哪些必须串行）
  3. 为每个子 Agent 写出精确的任务指令
  4. 在子 Agent 失败时做出正确的重试/跳过决策

7B 模型（如 Qwen2.5-Coder-7B）的局限：
  - 规划能力弱：容易漏掉子任务或错误分解
  - 指令生成不精确：子 Agent 的 prompt 可能模糊、遗漏关键信息
  - 容错判断差：子 Agent 失败时，不知道是重试还是跳过
  - 上下文利用率低：TaskList 返回的状态信息可能被忽略

现实选择：
  - Orchestrator 需要强模型（70B+ 或 API 模型如 Claude/GPT-4）
  - 子 Agent 执行可以用弱模型（7B 足够做 Read/Edit/Bash）
  - 这就是「混合模型架构」的价值所在
```

---

## 教学要点

### 1. 子 Agent 执行可标准化（7B 够用）

```
子 Agent 的工作模式是高度结构化的：
  Grep(关键词) -> Read(文件) -> Edit(修复) -> Bash(验证)

这个 L-R-V（Localize-Repair-Validate）流程：
  - 每一步的输入输出都是明确的
  - 不需要高级推理能力
  - 7B 模型完全可以胜任

就像工厂流水线上的工人：
  给他明确的操作手册（prompt），他就能正确执行。
  不需要他理解整个产品的设计理念。
```

### 2. Orchestrator 规划是瓶颈（需要强模型）

```
规划 = 将模糊的用户意图转化为精确的执行计划

「修复这两个文件的 bug」 这句话包含了多少隐含信息？
  - 哪些文件？（需要从上下文推断）
  - 什么 bug？（需要先读代码才知道）
  - 怎么分解？（需要判断任务独立性）
  - 什么顺序？（需要识别依赖关系）
  - 怎么验证？（需要理解预期行为）

这些判断需要「世界知识 + 推理能力」，是 7B 模型的短板。
Orchestrator 的质量直接决定了整个 Agent Team 的成功率。
```

### 3. 这呼应了「循环机制是放大器，但基础能力是阈值」

```
Agent Team 是一个强大的「放大器」：
  - 并行执行，提升吞吐
  - 独立上下文，保护推理质量
  - 任务追踪，提供可观测性

但如果基础能力不够：
  - Orchestrator 分解错了 -> 所有子 Agent 白忙活
  - 子 Agent 理解不了 prompt -> 修复方向错误
  - 循环再多次也得不到正确结果

类比：
  10 个实习生 + 1 个好的项目经理 = 高效团队
  10 个实习生 + 1 个实习生当经理 = 混乱
  1 个高级工程师独自工作 = 也许比上面两种都好

结论：
  在引入 Agent Team 之前，先确保单 Agent 的能力达到阈值。
  Agent Team 是锦上添花，不是雪中送炭。
```

---

## 完整执行时间线

```
t=0   [主 Agent] 接收用户指令
t=1   [主 Agent] TaskCreate #1 -> pending
t=2   [主 Agent] TaskCreate #2 -> pending
t=3   [主 Agent] TaskCreate #3 -> pending
t=4   [主 Agent] Agent(task_id=1) -> 启动子 Agent 1
t=4   [主 Agent] Agent(task_id=2) -> 启动子 Agent 2  (并行)
      ┌─────────────────────────┬─────────────────────────┐
t=5   │ [子 Agent 1] Read       │ [子 Agent 2] Grep       │
t=6   │ [子 Agent 1] Edit       │ [子 Agent 2] Read       │
t=7   │ [子 Agent 1] Bash       │ [子 Agent 2] Edit       │
t=8   │ [子 Agent 1] DONE #1    │ [子 Agent 2] Bash       │
      │                         │ [子 Agent 2] DONE #2    │
      └─────────────────────────┴─────────────────────────┘
t=9   [主 Agent] TaskList -> 2/3 completed
t=10  [主 Agent] Agent(task_id=3) -> 启动子 Agent 3
t=11  [子 Agent 3] Bash(buggy_code.py) -> PASS
t=12  [子 Agent 3] Bash(large_module.py) -> PASS
t=13  [子 Agent 3] DONE #3
t=14  [主 Agent] TaskList -> 3/3 completed
t=15  [主 Agent] 生成汇总报告
```

---

## 附录：关键源文件

| 文件 | 作用 |
|------|------|
| `mvp/src/task_tools.py` | TaskStore + TaskCreate/Update/List 工具 |
| `mvp/src/agent_tool.py` | SubAgentRunner + AgentTool |
| `mvp/src/client.py` | 主 Agent 的 ReAct 循环 |
| `mvp/tests/buggy_code.py` | 演示用 bug 文件 (off-by-one) |
| `mvp/tests/large_module.py` | 演示用 bug 文件 (ZeroDivisionError) |
