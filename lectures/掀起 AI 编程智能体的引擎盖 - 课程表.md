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
| | 10:00 - 10:40 | 工具调用机制：API 协议与结构化工具集 | **主线问题：模型如何通过工具调用操作真实的开发环境？**<br>〔OODA 定位：**Act 环节的基础设施** / 三阶段共用底层〕<br>1. 回到 ReAct 的 Action：turn 级工具调用协议（stop_reason / needsFollowUp），CC 源码实证——stop_reason 不可靠，工程实践检查 tool_use block 存在性〔Toolformer：token 级的学术路线，训练阶段自监督发现 + 推理阶段解码中断〕<br>2. Action Space 四个流派：SWE-agent ACI（消融数据：同模型 7 倍差距）、AutoCodeRover AST（CC 为何不选纯 LSP：工具智能 vs 模型智能）、CodeAct 代码即动作（CC 源码实证：~1500 行权限系统在 CodeAct 架构下无法实现）、Agentless 固定流水线（SWE-bench 27.3% 无 Agent 超早期 SWE-agent）→ 收敛为两条工业路线<br>3. CC 工具集精简设计（~9 核心 + 25+ ToolSearch 延迟加载，CC 源码实证）、Edit search/replace 行业共识（CC 额外实现引号规范化 + staleness 检查）、tool schema token 成本 trade-off<br>4. 协议三层对比（Claude / OpenAI / Qwen 原生）+ adapter 转换 + parser 四层 fallback<br>**〔Demo 2 · Live〕** 两段完整 curl 请求并排对比（普通 chat vs tool_use，含真实 tool schema）；adapter 协议转换链路演示；parser 三种格式鲁棒解析；可选：Qwen2.5 vs Qwen3 格式差异 + MoE 调试故障复现 |
| | 10:40 - 10:50 | | **课间休息** |
| | 10:50 - 11:20 | 修 Bug 实战剖析：多轮纠错与防死循环 | **主线问题：Agent 收到报错信息后，如何决定下一步行动？**<br>〔OODA 定位：**Orient 环节（从失败中学习）** / 完整走一遍 L→R→V 循环〕<br>1. 全流程演示：用 buggy_calc.py（两个独立 bug）展示多轮 L→R→V，**聚焦每次 Validation 失败后模型的 Thought——这条 Thought 就是 Orient**，决定了纠错还是死循环<br>2. Reflexion：用自然语言替代梯度。核心创新：失败经验 → 自然语言反思 → 存入记忆 → 下次参考。HumanEval 80.1%→91.0%（+10.9%，论文 Table 1）。消融实验：无自我反思则无提升。CC 映射：对话上下文 = 隐式 Memory，CLAUDE.md = 显式 Memory〔Reflexion：化失败为经验〕<br>3. 上下文压缩——模型如何管理自己的记忆：auto-compact 不是文本截断，而是**模型给自己写结构化摘要**。CC 源码实证：compact prompt 要求 9 个段落（`compact/prompt.ts`），其中 "Errors and fixes" 确保失败经验优先保留；模型先做 `<analysis>` 推理草稿再输出摘要（CoT 提升压缩质量）；6 层压缩策略从轻到重渐进降级（`autoCompact.ts` 阈值 = contextWindow - 33K）<br>4. 循环失灵与 Harness 兜底：Orient 失灵三种原因（推理不足 / 关键信息被压缩丢弃 / 信噪比过低）；三层防线（信息质量保障 → 行为检测纠正 → 强制终止止损）；CC 源码 max_output_tokens 恢复 + nudge + 熔断器<br>**〔Demo 3 · Live〕** 用 MVP + Qwen2.5-Coder-7B 现场修复 buggy_calc.py（两个 bug：除数错误 + 边界错误）；第一个 bug 修复后测试仍失败→**当场观察模型的 Orient 质量**；若模型出错则标注"OODA 哪个环节失灵"——失败即教材 |
| | 11:20 - 11:50 | ACI 设计哲学：在百万行代码中精准定位与安全修改 | **主线问题：Agent 如何在大规模代码库中高效定位目标、安全修改代码？**<br>〔OODA 定位：**Observe 环节（感知质量）** / 重点覆盖 Localization + Repair〕<br>1. RAG 在编程场景的局限性：自然语言描述 vs 代码符号的语义鸿沟〔SWE-bench：AI 程序员的试金石〕<br>2. 代码感知检索：AST 结构化搜索 + LSP 跳转定义，显著提升 Localization 阶段的精准度〔AutoCodeRover：结构化代码感知〕<br>3. 上下文保护机制：Read 的 offset+limit、Grep 的 head_limit —— 粗细粒度漏斗策略的工程化实现〔SWE-agent：信息粒度的精确控制〕<br>4. 写入协议的行业共识：Unified Diff（行号定位）的脆弱性 → 业界趋势转向 search/replace 范式（内容定位），Agentless 与 Claude Code 殊途同归〔Agentless：内容定位取代行号定位〕<br>**〔Demo 4 · Live〕** 对比演示：Bash `cat` 读取 200+ 行文件（上下文爆炸，后续推理质量下降）vs Read + offset/limit 精准读取；展示 system prompt 中文件树快照的 50 行上限 —— ACI 就是一组具体的工程决策 |
| | 11:50 - 12:00 | | **课间休息** |
| | 12:00 - 12:20 | 架构反思：Agentless 三阶段流水线 vs Agent 动态循环 | **主线问题：修复一个 Bug，一定需要完整的 Agent 循环吗？**<br>〔OODA 定位：**质疑循环本身** / L-R-V 三阶段的最简实现〕<br>1. Agentless 三阶段设计：Localization（分层漏斗定位）→ Repair（多候选采样）→ Validation（测试筛选）〔Agentless：最简实现的力量〕<br>2. 殊途同归：Agentless 与 Claude Code 在编辑格式上都采用 search/replace 范式，根本差异在整体架构与容错策略<br>3. 广度 vs 深度：Agentless 以并行采样多候选换取正确率（广度），Agent 以反馈驱动多轮迭代逼近正确解（深度）<br>4. 工程权衡：按任务难度匹配策略 —— 定义清晰的问题适合流水线（快速、可并行），需要动态探索的复杂问题适合 Agent（能处理意外）<br>**〔Demo 5 · Live+PPT〕** 白板并排画出同一个 bug 的两条修复路径：Agent 路线（复用 Demo 3 录像）vs Agentless 流水线（PPT 伪代码展示 L→R→V 三阶段各一次 API 调用），对比时间线和调用次数 |
| | 12:20 - 12:50 | Agent Team：从单体到协同编排 | **主线问题：单个 Agent 处理不了的大型任务，如何拆分给 Agent 团队协同完成？**<br>〔OODA 定位：**从单体 OODA 到编队 OODA / Boyd 推论三回归**〕<br>1. 什么时候需要 Agent Team？——三个场景，不是万能药。Anthropic 官方博客定调：多 Agent 消耗 3-10x token，总执行时间可能更长。只在三种场景下值得：**上下文污染**（子任务信息互相干扰，隔离比压缩更根本）、**并行探索**（覆盖更大搜索空间，彻底性而非加速——"The primary benefit of parallelization is thoroughness, not speed"）、**工具/领域专业化**（20+ 工具时选错概率上升，聚焦工具集提升可靠性）<br>2. 四种多 Agent 架构对比：MetaGPT（固定 SOP）vs AutoGen（对话驱动，O(N²) 协调开销）vs OpenHands（Controller 硬编码）vs CC（**协调原语工具化，LLM 运行时自主编排**）〔MetaGPT / AutoGen / OpenHands：三种多智能体范式〕。CC 核心创新：TeamCreate、TaskCreate、Agent、SendMessage 全部是工具，没有固定 DAG 和预设角色<br>3. CC Orchestrator-Worker 架构：三条 spawn 路径（Normal/Fork/Teammate），星型拓扑 O(N) 协调，文件级 mailbox + 文件锁 task 存储。CC 源码实证：`AgentTool/runAgent.ts`、`SendMessageTool.ts`、`tasks.ts`<br>4. 双层隔离机制：对话隔离（独立上下文，`createSubagentContext()`）+ **Git Worktree 文件隔离**（Worktree ≠ Branch：branch 是逻辑隔离管版本历史，worktree 是物理隔离管文件系统，并发写必须物理隔离）+ 权限冒泡（`bubble` 模式解决 N 个子 Agent 同时弹确认框的 UX 灾难）〔OpenHands：Docker 沙箱隔离实践〕<br>5. 编队 OODA：嵌套循环（Lead 慢循环粗粒度 + Worker 快循环细粒度）、层次化 L→R→V（Meta-L 拆解 → Worker 独立 L-R-V → Meta-V 集成测试）<br>**〔Demo 6 · 预录+Live 混合〕** 预录：用 MVP 之前成功跑通的 Todo 服务 trajectory——Lead 拆解→spawn backend-dev（Flask API）+ frontend-dev（原生 JS）→各自独立开发→Lead 汇总发现端口 mismatch（后端 5000 vs 前端 8000）→spawn Worker 修复→集成测试通过。教学要点：端口不一致正是 Meta-Validation 的价值——Worker 各自通过单元测试，但跨模块一致性问题只有 Lead 汇总时才能发现；Live：MVP + 7B 演示单个 backend-dev Worker；可选：7B 做 Lead 力不从心，引出"编排需要强模型，执行可以用弱模型" |
| | 12:50 - 13:00 | 安全与权限 + 课程总结 | **主线问题：如何确保 AI Agent 在代码库中的操作安全可控？**<br>1. 三道防线：工具级权限分级（读/写/执行）、破坏性操作强制确认、Bash 沙箱超时。CC 源码实证：~1500 行权限引擎（`permissions.ts`），8 个规则来源层级覆盖，支持内容级规则（如 `Bash(git *)`），甚至 AI 分类器 `auto` 模式——**结构化工具集是精细权限控制的前提**<br>2. Hook 系统与 CLAUDE.md：事件触发器实现自定义安全策略；5 层配置加载（managed → user → project → local → autoMem），自然语言"宪法"约束 Agent 行为边界<br>3. 双主线回顾：**主线一（L→R→V）** 贯穿修 Bug、写 Feature、Agentless 架构选择；**主线二（OODA）** 串联 ReAct（建立循环）→ Toolformer（增强 Act）→ Reflexion（增强 Orient）→ SWE-agent（优化 Observe）→ Agentless（质疑循环）→ Agent Team（编队 OODA）<br>4. 总结：**循环转速决定胜负，接口设计决定上限，协同架构决定规模，安全机制决定底线** |
| | 13:00+ | 〔加餐〕Meta-Harness：Agent 优化 Agent | 六讲手工拆解了 Agent 的引擎盖——system prompt、工具接口、上下文管理、循环控制。这些设计目前都是人类工程师手工调优的。Meta-Harness 论文用一个 coding agent 来搜索优化另一个 agent 的 harness code，在 TerminalBench-2 上击败了所有手工设计的 Haiku 4.5 方案。"Agent 优化 Agent" 的前沿方向。（选讲，视时间决定是否展开） |

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
9. **CC 源码作为实证**：Anthropic 已开源 Claude Code（1902 个 TypeScript 文件），课程中标注"CC 源码实证"的论点均可在源码中找到对应代码。详细的文件路径和行号索引见 `lectures/reference_cc_source_analysis.md`，可作为课后进阶阅读材料提供给学员。

---

*v3.3 | 2026-04-02 | Agent Team 模块重构：动机改用 Anthropic 官方三场景框架（context pollution / thoroughness not speed / specialization），架构对比扩展为四种（+OpenHands），Worktree vs Branch 区分，Demo 改用 Todo 服务（Flask+JS+端口 mismatch），新增 Meta-Harness 加餐时段*
*v3.2 | 2026-04-01 | 修 Bug 模块重构：聚焦 Orient 环节，新增 buggy_calc.py 两阶段 Demo，Reflexion 数据改用论文原始数据（HumanEval 80.1%→91.0%），新增上下文压缩专题（CC compact prompt 9 段结构、模型自摘要原理、6 层渐进降级），删除双层循环模型图和对比分析节，精简为三段式（Orient 时刻→Reflexion+压缩→死循环诊断）*
*v3.1 | 2026-04-01 | 基于 CC 开源代码审查：工具调用机制增加 CC 源码实证（stop_reason 不可靠、ToolSearch 延迟加载、~1500 行权限系统），修 Bug 模块衔接 Reflexion 最小实例与 harness 兜底机制，Team 模块增加三条 spawn 路径和 6 层 context 压缩，安全模块增加 8 源权限引擎和 CLAUDE.md 5 层加载*
*v3.0 | 2026-03-25 | 新增 Demo 策略：选型 Qwen2.5-Coder-7B，各时段标注〔Demo N · 形式〕，授课建议增加 Live Demo 操作要点*
*v2.4 | 2025-03-25 | 论文引用改为题注式标注，统一为〔论文名：核心贡献〕格式*
*v2.3 | 2025-03-25 | 统一内容语气，保持专业性与节奏感平衡*
*v2.2 | 2025-03-25 | 引入 OODA 演进线与双主线框架，各时段加挂 OODA 定位标注*
*v2.1 | 2025-03-25 | 新增 Agentless 专题时段，修正表述语气*
*v2.0 | 2025-03-25 | 基于 Claude Code (Opus 4.6) 审校设计*
