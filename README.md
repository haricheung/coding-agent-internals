# 掀起 AI 编程智能体的引擎盖

> Claude Code 与 AI Agent 的底层架构与控制流

## 课程定位

- **受众**：高级研发工程师、架构师、效能团队
- **时长**：4 小时（14:00 - 18:00）
- **演示模型**：Qwen3-30B-A3B（MoE，30B 总参 / 3B 激活）
- **演示平台**：MVP 代码库（`mvp/`）
- **目标**：理解 AI 编程代理的完整机制，能评估/选择/定制工具，能基于原理构建自己的方案

## 课程双主线

- **任务结构线**：Localization → Repair → Validation — Agent 在做什么
- **OODA 演进线**：每篇论文优化了决策循环的哪个环节 — 如何做得更好

## 课程结构

| # | 主题 | 核心问题 |
|---|------|---------|
| 1 | [破冰：从"文本接龙"到"闭环控制"](lectures/lecture1_opening.md) | Chat → Agent，质变在哪？ |
| 2 | [工具调用：模型如何"伸出手"](lectures/lecture2_tool_use.md) | 模型怎样从"只会说"变成"能操作"？ |
| 3 | [修 Bug 实战：多轮纠错与防死循环](lectures/lecture3_feedback_and_orient.md) | 测试报错后，纠错还是死循环？ |
| 4 | [ACI 设计：百万行代码中精准定位](lectures/lecture4_observe_and_localization.md) | 如何用"刚好够"的信息量找到目标？ |
| 5 | [架构反思：流水线 vs Agent 循环](lectures/lecture5_pipeline_vs_agent.md) | 修一个 Bug，一定需要完整的 Agent 循环吗？ |
| 6 | [Agent Team：从单体到协同编排](lectures/lecture6_agent_team.md) | 一个 Agent 搞不定的任务，怎么拆？ |
| 7 | [安全与权限：Agent 的行为边界](lectures/lecture7_safety_and_permissions.md) | 能力越大，边界越重要 |
| 8 | [Meta-Harness + 课程总结](lectures/lecture8_meta_harness_and_summary.md) | Agent 优化 Agent — 终点即起点 |

## 参考材料

### 核心讲义

- [掀起 AI 编程智能体的引擎盖 v3.4](lectures/掀起%20AI%20编程智能体的引擎盖%20v2.md) — 完整讲义（含论文清单、认知地图、协议详解）
- [课程表](lectures/掀起%20AI%20编程智能体的引擎盖%20-%20课程表.md) — 4 小时授课时间表与 Demo 策略

### 深度参考

- [Claude Code 开源代码深度解读](lectures/reference_cc_source_analysis.md) — 基于 1902 个 TypeScript 文件的源码实证
- [国内编程大模型能力点评（2026 年 4 月）](lectures/reference_chinese_coding_llms.md) — MiniMax M2.5、Qwen3-Coder、DeepSeek 等最新模型分析
- [蒸馏路线做编码大模型的可行性分析](lectures/reference_distillation_for_coding.md) — DeepSeek-R1 蒸馏实验与工程路径
- [Claude Code ↔ Opus 4.6 交互协议](claude-message-protocol.md) — content block 类型、tool_use 协议、并行调用、Team 消息格式

### 论文清单

- [附录：课程论文清单](appendix/paper-list.md) — 18 篇核心论文 + 15+ 篇扩展阅读，按 6 层技术栈组织

## 代码库结构

```
.
├── lectures/              # 8 讲讲义 + 参考材料
│   ├── lecture1_opening.md
│   ├── lecture2_tool_use.md
│   ├── lecture3_feedback_and_orient.md
│   ├── lecture4_observe_and_localization.md
│   ├── lecture5_pipeline_vs_agent.md
│   ├── lecture6_agent_team.md
│   ├── lecture7_safety_and_permissions.md
│   ├── lecture8_meta_harness_and_summary.md
│   ├── reference_cc_source_analysis.md
│   ├── reference_chinese_coding_llms.md
│   └── reference_distillation_for_coding.md
│
├── mvp/                   # 编程代理 MVP 实现
│   ├── src/              # 核心实现（model_server, client, parser, tools）
│   ├── demo/             # Demo 脚本与演示文档
│   ├── tests/            # 测试与 benchmark
│   └── README.md         # MVP 架构说明
│
├── pdf/                   # 所有讲义的 PDF 版本
│   ├── lecture1_opening.pdf
│   ├── lecture2_tool_use.pdf
│   ├── ...
│   └── README.pdf
│
├── appendix/              # 附录材料
│   └── paper-list.md     # 论文清单（18 篇核心 + 15+ 扩展）
│
├── trajectories/          # Agent 执行轨迹记录
└── CLAUDE.md             # Claude Code 项目指引
```

## 核心一张图

```
        ┌──────────────────────────┐
        │     Intent（目标）        │
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐
   ┌───▶│  Observe（感知现状）      │◀───┐
   │    │  [Grep/AST/LSP/RAG]     │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Orient（理解/规划）       │    │
   │    │  [Reasoning/Planning]    │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Decide（决策）           │    │
   │    │  [Tool Selection]        │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   │    │  Act（执行变更）          │    │
   │    │  [ToolUse/CodeAct]       │    │
   │    └────────────┬─────────────┘    │
   │                 ▼                  │
   │    ┌──────────────────────────┐    │
   └────│  Observe（观察结果）       │────┘
        │  + Feedback（评估/修正）  │
        └──────────────────────────┘
```

## 课程特色

1. **双线并进**：任务结构（L-R-V）+ OODA 演进，建立二维认知地图
2. **源码实证**：所有关于 Claude Code 的论断均可在开源代码中找到对应
3. **失败即教材**：用小模型演示，让失效模式可见、可分析、可修复
4. **工程视角**：LLM vs Harness 分工表 — Agent 超半数关键工作由工程代码完成
5. **可复现**：MVP 代码库提供完整实现，可直接运行和修改

## 授课建议

1. **以 Boyd 故事破冰**：F-86 vs MiG-15 的空战案例开场，从军事决策理论自然过渡到 ReAct
2. **认知地图常驻**：L-R-V × OODA 的论文定位图打印或常驻屏幕一角
3. **先展示失败**：先演示模型在该环节的典型错误，再讲工程应对
4. **API 对比是核心教具**：`chat completion` vs `tool_use` 并排 curl，提前准备可运行示例
5. **失败即教材**：小模型 Demo 出错时不要重启，当场标注"OODA 哪个环节失灵"
6. **课前预热**：模型加载需数分钟，14:00 前完成 `model_server.py` 启动和 GPU 预热

## 版本历史

- **v3.7** (2026-04-07) — 全面精简课程表，删除预录标注，内容列压缩为要点式
- **v3.6** (2026-04-07) — Agent Team 新增模型路由（三层金字塔、opusplan、sub-agent inherit）
- **v3.5** (2026-04-02) — 演示模型更换为 Qwen3-30B-A3B（MoE），授课时间调整为 14:00-18:00
- **v3.4** (2026-04-02) — 安全权限模块 + Meta-Harness 加餐 + 四句总结
- **v3.3** (2026-04-02) — Agent Team 重构：Anthropic 官方三场景框架，四种架构对比
- **v3.0** (2026-03-25) — 新增 Demo 策略，选型 Qwen2.5-Coder-7B
- **v2.0** — 基于 Claude Code (Opus 4.6) 技术审校，修正实现细节
- **v1.0** — 初版（Gemini 协助生成）

---

**四句总结**：
- 循环转速决定胜负
- Harness 工程决定上限
- 协同架构决定规模
- 安全机制决定底线
