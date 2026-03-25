# 《掀开 AI 程序员的引擎盖：Claude Code 与 AI Agent 的底层架构与控制流》

**课程受众：** 高级研发工程师、架构师、效能团队
**课程时长：** 3 小时
**演示模型：** Qwen2.5-Coder-7B-Instruct（Dense 架构，tool calling 格式稳定，失败模式可控可解释）
**演示平台：** MVP 代码库（`mvp/`：model_server + client + parser + tools）

**课程双主线：**
- **主线一（任务结构）：** Localization → Repair → Validation —— Agent 在做什么
- **主线二（OODA 演进）：** 每篇论文优化了决策循环的哪个环节 —— 如何做得更好

---

| 时间 | 时段 | 主题模块 | 内容 |
|:---:|:---:|:---|:---|
| | 09:30 - 10:00 | 破冰与愿景：AI 编程从"文本接龙"到"闭环控制" | **主线问题：从 Chat 到 Agent，AI 编程发生了什么质变？**<br>1. 对比演示：同一个 Bug，纯 Chat 一次性生成 vs Agent 多轮闭环修复<br>2. Boyd 的 OODA 循环理论：F-86 vs MiG-15 的 10:1 击杀比 —— 在动态环境中，快速的"足够好"决策胜过迟到的"完美"决策；基础能力是门槛，循环机制是放大器〔ReAct：从开环到闭环的范式革命〕<br>3. 课程双主线：所有编程 Agent 的通用任务结构（Localization → Repair → Validation），以及 8 篇论文在 OODA 循环各环节上的演进关系<br>4. 二维认知地图：横轴任务结构（L-R-V）× 纵轴 OODA 环节（Observe/Orient/Act），11 篇论文的定位总览<br>**〔Demo 1 · 预录+Live〕** 预录：Chat 模式粘贴 buggy_code.py 后一次性生成修复；Live：Agent 模式仅给一句"buggy_code.py 有 bug，帮我修"，观众看 agent 自主 Read→分析→Write→Bash 验证 |
| | 10:00 - 10:40 | 工具调用机制：API 协议与结构化工具集 | **主线问题：模型如何通过工具调用操作真实的开发环境？**<br>〔OODA 定位：**Act 环节的基础设施** / 三阶段共用底层〕<br>1. 机制澄清：工具调用是应用层 `tool_use` 协议，而非 Tokenizer 层的 Special Token 拦截〔Toolformer：赋予模型工具使用能力〕<br>2. 协议详解：并排展示普通 `chat completion` 请求 vs 带 `tools` 定义的请求，逐字段对比<br>3. 两条技术路线对比：结构化工具集（Claude Code: Read/Edit/Grep/Bash...）vs 直接生成可执行代码（OpenHands）〔CodeAct：代码即动作〕<br>4. 结构化路线的工程优势分析：权限控制、格式鲁棒性、可审计性<br>**〔Demo 2 · Live〕** 用 MVP 的 model_server 作为后端，并排展示两段 curl 请求（普通 chat vs tool_use）；展示 parser.py 的三种解析策略（XML / 代码块 / 裸 JSON），说明小模型为何需要宽容解析 |
| | 10:40 - 10:50 | | **课间休息** |
| | 10:50 - 11:20 | 修 Bug 实战剖析：多轮纠错与防死循环 | **主线问题：Agent 收到报错信息后，如何决定下一步行动？**<br>〔OODA 定位：**Orient 环节（从失败中学习）** / 完整走一遍 L→R→V 循环〕<br>1. 全流程演示：一个真实的修 Bug 流程，逐步展示 L→R→V 三阶段在 ReAct 循环中的动态执行<br>2. 双层循环模型：内层 TAO 循环 + 外层经验积累循环；失败信号（负反馈）经 Reflection 转化为结构化经验总结（正向指导），注入下一轮 Thought〔Reflexion：化失败为经验〕<br>3. 循环失灵与恢复机制：Orient 环节停滞时表现为重复执行相同错误命令；工程上通过 max retries、上下文压缩、prompt 指令三重手段强制恢复循环<br>4. 对比分析：一次成功纠错 vs 一次陷入死循环的完整日志，定位关键分叉点<br>**〔Demo 3 · Live〕** 用 MVP + Qwen2.5-Coder-7B 现场修复 buggy_code.py（off-by-one bug）；每步暂停标注 L/R/V 阶段；若模型出错则当场讲解"这是 OODA 哪个环节失灵"，失败即教材 |
| | 11:20 - 11:50 | ACI 设计哲学：在百万行代码中精准定位与安全修改 | **主线问题：Agent 如何在大规模代码库中高效定位目标、安全修改代码？**<br>〔OODA 定位：**Observe 环节（感知质量）** / 重点覆盖 Localization + Repair〕<br>1. RAG 在编程场景的局限性：自然语言描述 vs 代码符号的语义鸿沟〔SWE-bench：AI 程序员的试金石〕<br>2. 代码感知检索：AST 结构化搜索 + LSP 跳转定义，显著提升 Localization 阶段的精准度〔AutoCodeRover：结构化代码感知〕<br>3. 上下文保护机制：Read 的 offset+limit、Grep 的 head_limit —— 粗细粒度漏斗策略的工程化实现〔SWE-agent：信息粒度的精确控制〕<br>4. 写入协议的行业共识：Unified Diff（行号定位）的脆弱性 → 业界趋势转向 search/replace 范式（内容定位），Agentless 与 Claude Code 殊途同归〔Agentless：内容定位取代行号定位〕<br>**〔Demo 4 · Live〕** 对比演示：Bash `cat` 读取 200+ 行文件（上下文爆炸，后续推理质量下降）vs Read + offset/limit 精准读取；展示 system prompt 中文件树快照的 50 行上限 —— ACI 就是一组具体的工程决策 |
| | 11:50 - 12:00 | | **课间休息** |
| | 12:00 - 12:20 | 架构反思：Agentless 三阶段流水线 vs Agent 动态循环 | **主线问题：修复一个 Bug，一定需要完整的 Agent 循环吗？**<br>〔OODA 定位：**质疑循环本身** / L-R-V 三阶段的最简实现〕<br>1. Agentless 三阶段设计：Localization（分层漏斗定位）→ Repair（多候选采样）→ Validation（测试筛选）〔Agentless：最简实现的力量〕<br>2. 殊途同归：Agentless 与 Claude Code 在编辑格式上都采用 search/replace 范式，根本差异在整体架构与容错策略<br>3. 广度 vs 深度：Agentless 以并行采样多候选换取正确率（广度），Agent 以反馈驱动多轮迭代逼近正确解（深度）<br>4. 工程权衡：按任务难度匹配策略 —— 定义清晰的问题适合流水线（快速、可并行），需要动态探索的复杂问题适合 Agent（能处理意外）<br>**〔Demo 5 · Live+PPT〕** 白板并排画出同一个 bug 的两条修复路径：Agent 路线（复用 Demo 3 录像）vs Agentless 流水线（PPT 伪代码展示 L→R→V 三阶段各一次 API 调用），对比时间线和调用次数 |
| | 12:20 - 12:50 | Agent Team：从单体到协同编排 | **主线问题：单个 Agent 处理不了的大型任务，如何拆分给 Agent 团队协同完成？**<br>〔OODA 定位：**从单体 OODA 到编队 OODA**〕<br>1. 上下文污染问题：单 Agent 执行数十步后对话历史膨胀，早期关键信息被稀释，分治成为工程必然<br>2. Orchestrator-Worker 架构：主 agent 通过 `Agent` tool 动态 spawn 子 agent，星型拓扑通信以最小化协调开销〔MetaGPT / AutoGen：两种多智能体学术范式对比〕<br>3. 隔离机制：对话隔离（独立上下文）+ Git Worktree 文件隔离（独立分支+文件副本），从根本上解决并发写冲突〔OpenHands：沙箱隔离实践〕<br>4. 全流程演示：TaskCreate 拆解任务 → 并发 spawn 子 agent → 独立执行 → 汇总 merge → 集成测试 → 交付<br>**〔Demo 6 · 预录+Live 混合〕** 预录：Claude Code 完整 Agent Team 交付过程（主 agent 拆解→spawn 3 个子 agent→并发执行→merge→测试）；Live：用 MVP + 7B 演示单个 worker 执行子任务；可选：现场展示 7B 作为 orchestrator 的力不从心，引出"为什么 Team 模式需要强模型" |
| | 12:50 - 13:00 | 安全与权限 + 课程总结 | **主线问题：如何确保 AI Agent 在代码库中的操作安全可控？**<br>1. 三道防线：工具级权限分级（读/写/执行）、破坏性操作强制确认、Bash 沙箱超时<br>2. Hook 系统与 CLAUDE.md：事件触发器实现自定义安全策略；自然语言"宪法"约束 Agent 行为边界<br>3. 双主线回顾：**主线一（L→R→V）** 贯穿修 Bug、写 Feature、Agentless 架构选择；**主线二（OODA）** 串联 ReAct（建立循环）→ Toolformer（增强 Act）→ Reflexion（增强 Orient）→ SWE-agent（优化 Observe）→ Agentless（质疑循环）→ Agent Team（编队 OODA）<br>4. 总结：**循环转速决定胜负，接口设计决定上限，协同架构决定规模，安全机制决定底线** |

---

### 授课建议

1. **以 Boyd 故事破冰**：09:30 以 F-86 vs MiG-15 的空战案例开场，从军事决策理论引出 OODA，再自然过渡到 ReAct，迅速建立课程的理论纵深感。
2. **二维认知地图常驻可见**：建议将 L-R-V × OODA 的论文定位图打印或常驻屏幕一角，每讲完一节在图上标记当前位置，帮助听众保持全局感。
3. **每节先展示失败场景**：先演示模型在该环节的典型错误（幻觉代码、死循环、上下文丢失），再讲工程上的应对方案，建立可信度。
4. **API 请求对比是核心教具**：10:00 时段的 `chat completion` vs `tool_use` 并排展示，建议提前准备可运行的 curl 示例。
5. **优先使用 Live Demo**：模块一二全部 Live 演示（Qwen2.5-Coder-7B + MVP），模块三采用 Live + 预录混合（7B 演示 worker，预录视频展示 Claude Code 完整 Team 流程）。
6. **失败即教材**：7B 模型的 demo 出错时不要重启，当场标注"这是 OODA 循环的哪个环节失灵"，把事故变成教学素材。这是选择 7B 而非更强模型的核心原因。
7. **论文引用点到为止**：每个知识点已以题注形式标注对应论文，授课时一句话带过出处即可，重心放在实际工程实现。
8. **课前预热 model_server**：模型加载需要数分钟，务必在 09:30 前完成 `model_server.py` 启动和 GPU 预热，避免 Live Demo 等待冷启动。

---

*v3.0 | 2026-03-25 | 新增 Demo 策略：选型 Qwen2.5-Coder-7B，各时段标注〔Demo N · 形式〕，授课建议增加 Live Demo 操作要点*
*v2.4 | 2025-03-25 | 论文引用改为题注式标注，统一为〔论文名：核心贡献〕格式*
*v2.3 | 2025-03-25 | 统一内容语气，保持专业性与节奏感平衡*
*v2.2 | 2025-03-25 | 引入 OODA 演进线与双主线框架，各时段加挂 OODA 定位标注*
*v2.1 | 2025-03-25 | 新增 Agentless 专题时段，修正表述语气*
*v2.0 | 2025-03-25 | 基于 Claude Code (Opus 4.6) 审校设计*
