# Team-Mode Trajectory 采集任务集

> 目标：用 Claude Code 跑这些任务，采集高质量的 agent-team trajectory，用于 SFT 蒸馏到 Qwen。
> 每个任务标注了预期的 team 行为，方便后续筛选和质量评估。

---

## 一、任务分类

| 类别 | 数量 | 核心训练信号 |
|------|------|-------------|
| A. 并行探索 | 6 | spawn 时机 + 子任务分工 |
| B. 并行修改 | 6 | 文件分配 + 冲突避免 |
| C. 分治研究 | 4 | prompt 质量 + 结果汇总 |
| D. 流水线协作 | 4 | 顺序依赖 + SendMessage 传递 |
| E. 不该 spawn 的反例 | 5 | 学会判断"不拆" |

**共 25 个任务，预期采集 25 条 lead trajectory + 约 50-80 条 worker trajectory。**

---

## A. 并行探索（该 spawn，各自独立搜索）

### A1. 多目录 bug 定位
```
mvp/tests/ 下有 buggy_code.py 和 buggy_calc.py 两个文件都有 bug。
同时找出所有 bug 并汇总报告，不需要修复。
```
**预期行为：**
- TeamCreate(["analyst-1", "analyst-2"])
- spawn analyst-1 → 负责 buggy_code.py
- spawn analyst-2 → 负责 buggy_calc.py
- lead ReadInbox → 汇总两份报告

### A2. 代码风格审计
```
审计 mvp/src/ 下所有 Python 文件的代码风格问题（未使用的 import、
过长的函数、不一致的命名等），每个文件独立审计，最后汇总。
```
**预期行为：**
- spawn 2-3 个 worker，每人负责 3-4 个文件
- worker 用 Read 逐文件审查
- SendMessage 报告各自发现
- lead 汇总成统一报告

### A3. 依赖分析
```
分析 mvp/src/ 中各模块之间的 import 依赖关系。
一个 agent 分析 client.py 的依赖，另一个分析 model_server.py 的依赖。
最后画出依赖图。
```
**预期行为：**
- spawn 2 个 worker，各自 Grep import 语句
- lead 合并结果，输出依赖关系

### A4. 测试覆盖率审查
```
检查 mvp/tests/ 中的测试文件，对照 mvp/src/ 中的源文件，
找出哪些源文件/函数没有被测试覆盖到。并行检查不同的源文件。
```
**预期行为：**
- spawn worker 分别检查不同的 src 文件对应的测试
- 每个 worker Grep 函数名在测试文件中是否出现
- lead 汇总缺失覆盖的函数列表

### A5. API 接口文档提取
```
从 model_server.py 中提取所有 HTTP 接口（路由、方法、参数、返回值），
同时从 client.py 中提取所有对 model_server 的调用点。
对比两边，看是否有未使用或未文档化的接口。
```
**预期行为：**
- spawn worker-server → 分析 model_server.py 的路由
- spawn worker-client → 分析 client.py 的 HTTP 调用
- lead 对比两份报告

### A6. 多文件搜索特定模式
```
在整个 mvp/ 目录中搜索所有的错误处理模式：
1) try/except 块
2) 返回 "Error" 开头字符串的函数
3) is_error 标志的使用
三个方向并行搜索，汇总错误处理策略。
```
**预期行为：**
- spawn 3 个 worker，各负责一个搜索方向
- 各自用 Grep 搜索对应模式
- lead 汇总成错误处理策略文档

---

## B. 并行修改（该 spawn，各改各的文件）

### B1. 双 bug 并行修复
```
buggy_code.py 有 off-by-one bug，buggy_calc.py 有统计计算 bug。
两个都修复，并分别运行测试验证。
```
**预期行为：**
- TaskCreate("修复 buggy_code.py") + TaskCreate("修复 buggy_calc.py")
- spawn worker-1 → Read + Edit buggy_code.py + Bash 运行验证
- spawn worker-2 → Read + Edit buggy_calc.py + Bash pytest test_buggy_calc.py
- lead ReadInbox 确认两边都修复成功

### B2. 多文件添加 docstring
```
给 mvp/src/ 中的 tools.py、parser.py、adapter.py 的所有 public 函数
添加 docstring。三个文件并行处理。
```
**预期行为：**
- spawn 3 个 worker，各负责一个文件
- worker 用 Read 读文件 → 用 Edit 添加 docstring
- 不同 worker 改不同文件，无冲突

### B3. 多文件添加类型注解
```
给 task_tools.py、agent_tool.py、team_tools.py 中的函数添加
完整的类型注解（参数类型 + 返回值类型）。并行处理。
```
**预期行为：**
- spawn 3 个 worker，各负责一个文件
- 各自 Read → Edit，互不干扰

### B4. 创建多个测试文件
```
为以下三个模块分别创建独立的单元测试文件：
1) test_task_tools_new.py — 测试 TaskStore 的边界条件
2) test_agent_tool_new.py — 测试 SubAgentRunner 的参数校验
3) test_team_tools_new.py — 测试 MessageQueue 的并发安全
```
**预期行为：**
- spawn 3 个 worker
- 各自 Read 源文件理解接口 → Write 测试文件
- lead 最后 Bash pytest 运行所有新测试

### B5. large_module.py 拆分重构
```
large_module.py 有 443 行，包含 5 个类。把它拆分成独立的模块文件：
data_record.py、data_set.py、data_validator.py、data_transformer.py、
statistics_calculator.py。每个 worker 负责提取一个类。
```
**预期行为：**
- lead 先 Read large_module.py 了解结构
- spawn 多个 worker，各提取一个类到新文件
- lead 最后创建 __init__.py 把它们重新 export

### B6. 配置抽取
```
mvp/src/ 中有很多硬编码的配置值（端口号、超时时间、最大行数等）。
找出 client.py 和 model_server.py 中所有硬编码常量，
提取到一个统一的 config.py 中，并更新引用。
```
**预期行为：**
- spawn worker-client → 扫描 client.py 的硬编码值
- spawn worker-server → 扫描 model_server.py 的硬编码值
- lead 汇总后创建 config.py，再分别更新两个文件

---

## C. 分治研究（该 spawn，各自研究后汇总）

### C1. 协议对比分析
```
对比 Claude API 格式和 OpenAI API 格式在以下维度的差异：
1) 工具定义格式
2) 消息中的工具调用格式
3) 响应中的工具调用格式
从 adapter.py 的代码中提取具体差异，给出对照表。
```
**预期行为：**
- spawn worker-inbound → 分析 claude_tools_to_qwen / claude_messages_to_openai
- spawn worker-outbound → 分析 qwen_response_to_claude
- lead 合并成对照表

### C2. 解析器能力矩阵
```
parser.py 支持多种 tool call 解析策略。分析每种策略：
1) 能处理什么格式的输入
2) 边界条件和失败模式
3) 在 test_all.py 中对应哪些测试用例
给出一个能力矩阵。
```
**预期行为：**
- spawn worker-xml → 分析 XML 解析路径
- spawn worker-json → 分析 code block / bare JSON / function call 路径
- lead 汇总成矩阵

### C3. 系统提示词对比
```
对比 client.py 中 lead mode 和 worker mode 的系统提示词差异。
分析每种模式：包含哪些指令、工具列表差异、行为约束差异。
输出一份对比文档。
```
**预期行为：**
- spawn 2 个 worker，各自 Read client.py 中对应部分
- lead 合并对比

### C4. 错误恢复机制全景
```
分析 MVP 中所有的错误恢复机制：
1) client.py 中的 Reflexion 注入
2) client.py 中的 nudge 机制
3) tools.py 中的错误返回约定
4) model_server.py 中的 fallback 解析
每个机制独立分析，最后汇总。
```
**预期行为：**
- spawn 2-3 个 worker，按机制分工
- 各自 Read + Grep 分析代码
- lead 汇总成全景文档

---

## D. 流水线协作（该 spawn，但有顺序依赖）

### D1. 读取-分析-修复流水线
```
对 buggy_calc.py 执行以下流水线：
1) 第一阶段：读取文件和测试，分析所有 bug
2) 第二阶段：根据分析结果修复所有 bug
3) 第三阶段：运行测试验证修复
阶段之间需要传递信息。
```
**预期行为：**
- spawn analyst → Read + 分析 → SendMessage 给 lead 报告 bug 列表
- lead ReadInbox 收到 bug 列表
- spawn fixer → 根据 lead 转发的 bug 列表 Edit 修复
- lead 最后 Bash pytest 验证

### D2. 设计-实现-测试流水线
```
为 MVP 添加一个新功能：在 trajectory.py 中添加一个 export_markdown() 方法，
将 trajectory JSON 导出为可读的 Markdown 格式。
阶段：1) 设计接口 2) 实现 3) 写测试
```
**预期行为：**
- spawn designer → 读 trajectory.py 结构 → SendMessage 接口设计
- lead 审核设计 → spawn implementer → 实现代码
- spawn tester → 写测试
- 有明确的阶段依赖

### D3. 数据流追踪
```
追踪一次完整的工具调用请求从 client.py 发出到返回的完整路径：
1) 先分析 client.py 的请求构造
2) 然后分析 model_server.py 的请求处理
3) 最后分析响应的解析和返回
按顺序，每步的输出是下一步的输入。
```
**预期行为：**
- spawn worker-1 → 分析 client._generate() 的请求构造
- worker-1 SendMessage 结果 → lead 转发给 worker-2
- spawn worker-2 → 从 worker-1 的结论出发分析 model_server
- 体现信息传递的链式协作

### D4. 渐进式重构
```
将 parser.py 中的 4 种解析策略从 if-else 链重构为策略模式：
1) 先分析当前结构
2) 设计新的类结构
3) 逐个迁移每种策略
4) 运行现有测试确保不 break
```
**预期行为：**
- spawn analyst → 分析现状 → SendMessage 设计方案
- lead 审核 → spawn refactorer → 实现重构
- lead Bash pytest 验证

---

## E. 不该 spawn 的反例（训练模型学会"不拆"）

### E1. 单文件简单 bug
```
修复 buggy_code.py 中的 off-by-one bug。
```
**预期行为：** 不 spawn，直接 Read → Edit → Bash 验证，3 步搞定。

### E2. 读一个文件并解释
```
读取 parser.py 并解释它的主要功能和设计思路。
```
**预期行为：** 不 spawn，直接 Read → 输出解释。

### E3. 运行测试
```
运行 mvp/tests/test_all.py 并报告结果。
```
**预期行为：** 不 spawn，直接 Bash pytest → 报告。

### E4. 小范围 grep
```
在 client.py 中搜索所有使用 micro_compact 的地方。
```
**预期行为：** 不 spawn，直接 Grep → 报告。

### E5. 简单文件创建
```
创建一个 mvp/src/config.py，定义 DEFAULT_PORT=9981 和 MAX_ROUNDS=15。
```
**预期行为：** 不 spawn，直接 Write 一个文件。

---

## 二、采集流程

### Step 1: 环境准备
```bash
# 确保 trajectory 采集开启
export TRACE=1
cd /root/work/qlzhang/code/coding-agent-internals

# 创建干净的采集目录
mkdir -p mvp/team_trajectories
```

### Step 2: 逐任务采集
```bash
# 用 Claude Code 跑每个任务
# trajectory.py 会自动保存到 trajectories/ 目录
# 子 agent 的 trajectory 也会自动关联（parent_session_id）
```

### Step 3: 质量筛选

每条 trajectory 按以下标准打分（0-3 分）：

| 维度 | 0 分 | 1 分 | 2 分 | 3 分 |
|------|------|------|------|------|
| spawn 决策 | 该拆没拆 / 不该拆却拆了 | 拆了但分工不合理 | 拆分合理 | 拆分合理且粒度恰到好处 |
| prompt 质量 | 子 agent prompt 模糊 | 有目标但缺上下文 | 目标+上下文清晰 | 包含成功标准和约束 |
| 协调能力 | 无 SendMessage | 有但信息不完整 | 信息完整 | 有阶段性汇报+最终汇总 |
| 任务管理 | 无 TaskCreate | 创建了但不更新 | 创建+更新状态 | 完整生命周期管理 |

**只保留总分 >= 8 的 trajectory 用于训练。**

### Step 4: 格式转换
```
Claude trajectory (JSON)
  → adapter.py 反向转换
  → Qwen chat template (SFT 训练格式)
```

关键转换点：
- `tool_use` content block → `<tool_call>` XML 标签
- `tool_result` block → assistant 上下文中的观察结果
- system prompt 中的工具定义 → `<tools>` XML 注入

---

## 三、评估 Benchmark

训练完成后，用以下 10 个任务评估（5 个该拆 + 5 个不该拆）：

| # | 任务 | 正确行为 | 评估指标 |
|---|------|----------|----------|
| 1 | 并行修复 buggy_code + buggy_calc | spawn 2 worker | spawn 决策 + 完成率 |
| 2 | 审计 3 个文件的代码风格 | spawn 2-3 worker | 分工合理性 |
| 3 | 分析 adapter.py 的 inbound + outbound | spawn 2 worker | 报告质量 |
| 4 | 读-分析-修复流水线 | 有序 spawn | 阶段依赖正确性 |
| 5 | 5 个文件提取配置到 config.py | spawn + 汇总 | 端到端成功率 |
| 6 | 修复单个 bug | 不 spawn | 正确"不拆" |
| 7 | 读文件并解释 | 不 spawn | 正确"不拆" |
| 8 | 运行一个测试 | 不 spawn | 正确"不拆" |
| 9 | grep 搜索 | 不 spawn | 正确"不拆" |
| 10 | 创建单个文件 | 不 spawn | 正确"不拆" |

**核心指标：**
- **spawn 决策准确率** = (正确 spawn + 正确不 spawn) / 10
- **子任务完成率** = 成功完成的子任务 / 总 spawn 的子任务
- **端到端成功率** = 整体任务目标达成 / 总任务数
