# 掀起 AI 编程的"引擎盖" — 机制、策略与工程实现

## 课程定位
- **受众**：有编程经验的工程师、算法工程师、技术管理者
- **前置要求**：有 LLM 使用经验，了解基本的 prompt engineering
- **目标**：学员能理解 AI 编程代理的完整机制，能评估/选择/定制工具，能基于原理构建自己的方案

## 课程结构

### 第一篇：原理篇 — 引擎是怎么转的
- [模块 0：核心机制 — AI 编程代理的"发动机"](part1-principles/module0-core-mechanism.md)
- [模块 1：Grounding — 感知的策略空间](part1-principles/module1-grounding.md)
- [模块 2：底层模型 — 引擎的"燃料"](part1-principles/module2-foundation-models.md)

### 第二篇：策略篇 — 每个环节怎么做
- [模块 3：Planning — 规划的策略空间](part2-strategies/module3-planning.md)
- [模块 4：Action — 执行的策略空间](part2-strategies/module4-action.md)
- [模块 5：Feedback — 评估与修正的策略空间](part2-strategies/module5-feedback.md)
- [模块 6：搜索策略 — 从贪心到 MCTS](part2-strategies/module6-search-strategies.md)

### 第三篇：实战篇 — 工程落地
- [模块 7：工程实战 — 两大工具深度使用](part3-practice/module7-engineering-practice.md)
- [模块 8：构建你自己的编程代理](part3-practice/module8-build-your-own.md)

### 附录
- [课程论文清单](appendix/paper-list.md)

## 课程形式
- **3 大篇章，9 个模块**
- 每模块 2-2.5 小时（共约 18-22 小时）
- 每模块结构：机制讲解（30%）+ 论文/算法解读（20%）+ 工程演示（20%）+ 动手实操（30%）
- 结业项目：从零构建一个领域特定的编程代理

## 核心一张图

```
        ┌──────────────────────────┐
        │     Intent（目标）        │
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐
   ┌───▶│  Grounding（感知现状）    │◀───┐
   │    │  [Grep/AST/LSP/RAG]     │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Planning（规划路径）      │    │
   │    │  [Flat/Tree/DAG/Multi]   │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Action（执行变更）       │    │
   │    │  [ToolUse/CodeAct/Gen]   │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Grounding（观察结果）     │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   └────│  Feedback（评估/修正）    │────┘
        │  [Test/Self/Reflect/Human]│
        └──────────────────────────┘
```
