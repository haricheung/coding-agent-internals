# 掀起 AI 编程智能体的引擎盖 v2.0

> **v2.0 变更说明：** 基于 Claude Code (Opus 4.6) 对 v1.0 的技术审校，修正了若干与 Claude Code 实际实现不符的描述，重写了模块三（Agent Team），新增了安全与权限控制章节。原始 v1.0 由 Gemini 协助生成。

---

# 一、论文阅读清单

按照 认知觉醒 → 确立战场 → 构建系统 → 架构反思 的认知递进排列：

---

### 第一阶段：认知觉醒（解决"如何让模型动起来"的问题）

**1. ReAct (智能体范式的鼻祖)**
*   **标题：** *ReAct: Synergizing Reasoning and Acting in Language Models*
*   **作者：** Shunyu Yao, et al. (Princeton University, Google Brain)
*   **时间：** 2022

**2. Toolformer (工具调用的底层原理)**
*   **标题：** *Toolformer: Language Models Can Teach Themselves to Use Tools*
*   **作者：** Timo Schick, et al. (Meta AI)
*   **时间：** 2023

**3. Reflexion (自我反思与纠错机制)**
*   **标题：** *Reflexion: Language Agents with Verbal Reinforcement Learning*
*   **作者：** Noah Shinn, et al. (Northeastern University, MIT)
*   **时间：** 2023

---

### 第二阶段：确立战场（解决"如何评价 AI 程序员"的问题）

**4. SWE-bench (行业公认的金标准测试集)**
*   **标题：** *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?*
*   **作者：** Carlos E. Jimenez, et al. (Princeton University)
*   **时间：** 2023

---

### 第三阶段：构建系统（解决"工程上如何复现 Claude Code"的问题）

**5. SWE-agent (ACI 接口设计的教科书)**
*   **标题：** *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering*
*   **作者：** John Yang, et al. (Princeton University)
*   **时间：** 2024

**6. AutoCodeRover (基于 AST 结构化检索的先驱)**
*   **标题：** *AutoCodeRover: Autonomous Program Improvement*
*   **作者：** Yuntong Zhang, et al. (National University of Singapore)
*   **时间：** 2024

**7. CodeAct (让模型直接执行 Bash/Python 的理念)**
*   **标题：** *Executable Code Actions Elicit Better LLM Agents*
*   **作者：** Xingyao Wang, et al. (UIUC, Google DeepMind)
*   **时间：** 2024

---

### 第四阶段：架构反思（解决"如何让系统更稳健、更低成本"的问题）

**8. Agentless (回归简洁流水线的深度思考)**
*   **标题：** *Agentless: Demystifying LLM-based Software Engineering Agents*
*   **作者：** Chunqiu Steven Xia, et al. (UIUC)
*   **时间：** 2024

---

### 补充阅读：多智能体协同（模块三参考）

**9. MetaGPT (多角色 SOP 协同)**
*   **标题：** *MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework*
*   **作者：** Sirui Hong, et al.
*   **时间：** 2023
*   **定位：** 学术参考，了解固定角色协同的思路。注意：Claude Code 的 Team 模式并未采用此方案。

**10. AutoGen (对话驱动的多智能体框架)**
*   **标题：** *AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation*
*   **作者：** Qingyun Wu, et al. (Microsoft Research)
*   **时间：** 2023
*   **定位：** 学术参考，了解对话式协同的通用框架设计。

**11. OpenHands (工业级开源实现)**
*   **标题：** *OpenHands: An Open Platform for AI Software Developers as Generalist Agents*
*   **作者：** Xingyao Wang, et al.
*   **时间：** 2025
*   **定位：** 最接近工业实践的开源参考实现，推荐重点阅读其 agent 调度与沙箱设计。

---

# 二、论文认知地图：两条主线

这 8+3 篇论文可以沿两条正交的主线来理解。

## 主线一：任务结构线 —— Localization → Repair → Validation

所有编程 agent（不论架构多复杂）本质上都在做三件事：

```
找到改哪里（Localization）──→ 生成修改（Repair）──→ 验证对不对（Validation）
```

这是 Agentless 论文显式提出的三阶段框架，但它抽象出的是一个**通用任务结构**，同样适用于 Claude Code：

| 阶段 | Agentless 实现 | Claude Code 实现 |
|---|---|---|
| Localization | 固定漏斗：文件 → 函数 → 行 | 动态探索：Glob → Grep → Read → LSP |
| Repair | 多候选采样 + search/replace | 单次生成 + Edit tool search/replace |
| Validation | 测试套件筛选最优候选 | Bash 跑测试，失败则回溯到 L 或 R |

区别只是 Agentless 的三阶段是**单向流水线**（不可回溯，靠广度采样兜底），而 Claude Code 的三阶段是**可回溯的循环**（靠深度迭代兜底）。骨架是同一个。

## 主线二：OODA 演进线 —— 每篇论文优化了循环的哪个环节

### OODA 与 TAO 的关系

OODA（Observe → Orient → Decide → Act）是军事战略家 John Boyd 提出的通用决策循环框架。ReAct 论文提出的 TAO（Thought → Action → Observation）是 OODA 在 LLM agent 领域的一个**特化投影**，将 Orient（理解）和 Decide（决策）压缩为一个 Thought 步骤——因为 LLM 在一次推理中天然地同时完成理解和决策：

```
OODA:   Observe ──→ Orient ──→ Decide ──→ Act ──→ (回到 Observe)
          感知        理解       决策       执行

TAO:    Observation ──→  Thought  ──→ Action ──→ (回到 Observation)
          感知         理解+决策      执行
```

### Boyd 的核心洞察：循环转速决定胜负

Boyd 的理论源自朝鲜战争空战。美军 F-86 对苏制 MiG-15 的击杀比高达 10:1，但 MiG-15 在纸面参数上全面占优（爬升更快、升限更高）。F-86 赢在两个"不起眼"的设计：气泡式座舱（360° 视野 = Observe 更快）和液压飞控（轻推即响应 = Act 更快）。

Boyd 由此得出的核心洞察是：**在动态环境中，快速的"足够好"决策胜过迟到的"完美"决策——因为完美决策做出时，它所针对的局面可能已经不存在了。** 循环更快的一方可以持续用最新信息纠偏，更慢的一方则在对过时的现实做反应——几轮下来，慢的一方彻底失去态势感知。

映射到 AI agent：模型的基础能力是门槛，但循环机制是放大器——一个中等能力的模型跑多轮 ReAct 迭代，往往胜过更强的模型做一次性开环生成。这正是 ReAct 胜过开环生成的根本原因。

### 8 篇论文在 OODA 循环上的演进

```
阶段一：建立循环
  ReAct ── 从开环到闭环，建立 Thought-Action-Observation 循环本身

阶段二：增强循环的各个环节
  Toolformer ── 增强 Act ── 让模型学会调用外部工具，从"只能生成文本"到"能操作环境"
  Reflexion ── 增强 Orient ── 在失败后显式生成经验总结，注入下一轮 Thought

阶段三：将循环搬进编程领域，优化各环节
  SWE-bench ── 定义目标函数 ── 用真实 GitHub Issue 衡量 agent 端到端能力
  SWE-agent ── 优化 Observe ── 设计 ACI 层控制模型感知的信息粒度
  AutoCodeRover ── 优化 Observe+Act ── 通过 AST 结构化感知和操作代码
  CodeAct ── 优化 Act 格式 ── 直接生成可执行代码，减少格式约束

阶段四：反思循环
  Agentless ── 质疑循环本身 ── 固定流水线+多候选采样也能解决大部分问题
```

每篇论文在 OODA 环节上的精确定位：

| 论文 | 优化的 OODA 环节 | 核心贡献 |
|---|---|---|
| **ReAct** | 建立循环本身 | 革命性：将 LLM 从开环生成带入闭环控制 |
| **Toolformer** | Act（行动能力） | 让模型学会调用外部工具，解决"手"的问题 |
| **Reflexion** | Orient（理解反馈） | 将失败信号转化为结构化经验总结，解决"从错误中学习"的问题 |
| **SWE-bench** | （定义战场） | 建立编程领域的标准评测基准 |
| **SWE-agent** | Observe（感知质量） | 设计 ACI 控制信息粒度，解决"眼睛"的问题 |
| **AutoCodeRover** | Observe + Act | 通过 AST 给模型装上"代码 X 光"，结构化感知+操作 |
| **CodeAct** | Act（行动格式） | 用可执行代码替代 JSON 工具调用，简化动作表达 |
| **Agentless** | 质疑循环本身 | 证明流水线也能达到 agent 70-80% 的效果，倒逼 agent 证明额外复杂度的价值 |

### Reflexion 的双层循环模型

Reflexion 在 TAO 循环的基础上增加了一个**外层循环**。内层是标准的 TAO（一个 Episode 内的多步操作），外层是 Episode 之间的学习循环：

```
外层循环（Reflexion 层，跨 Episode）：
  Episode 1: [T → A → O → T → A → O → ...] → 失败 → 生成 Reflection
                                                            ↓
  Episode 2: [T(+Reflection) → A → O → ...] → 失败 → 生成 Reflection
                                                            ↓
  Episode 3: [T(+Reflections 1&2) → A → O → ...] → 成功 → 结束
```

触发 Reflection 的信号是**失败**（负反馈），但 Reflection 的输出是结构化的经验总结（"我错在哪、为什么错、下次应该怎么做"），这段总结作为**正向指导**注入下一轮 Thought。所以 Reflexion 本质上是一个**负反馈到正向指导的转化器**。

在 Claude Code 的实际实现中，这两层循环被摊平为一个连续对话：stderr 直接进入上下文，模型下一个 Thought 自然参考。但 Reflexion 论文的贡献在于证明了**显式生成经验总结**比"把错误信息扔进上下文让模型自己领悟"更有效。

## 两条主线的交汇：二维认知地图

两条主线构成一个二维空间：横轴是任务结构（L → R → V），纵轴是 OODA 环节。11 篇论文散布在这个空间中：

```
          │  Localization    Repair      Validation
  ────────┼──────────────────────────────────────────
  Observe │  SWE-agent
          │  AutoCodeRover
  ────────┼──────────────────────────────────────────
  Orient  │                  Reflexion
  ────────┼──────────────────────────────────────────
  Act     │  Toolformer      CodeAct
          │                  Agentless*
  ────────┼──────────────────────────────────────────
  全循环  │  ReAct (建立 T-A-O 循环本身)
  ────────┼──────────────────────────────────────────
  评测    │  SWE-bench (定义端到端评测基准)
  ────────┼──────────────────────────────────────────
  多Agent │  MetaGPT / AutoGen / OpenHands
  ────────┴──────────────────────────────────────────
  * Agentless 同时覆盖 L-R-V 三阶段，但作为固定流水线而非循环
```

这张图就是课程开场"论文全景图"要展示的内容——让听众在第一时间拿到认知地图，后续每个模块都能定位到图上的具体区域。

---

# 三、论文够不够？

**对于前两个议题（修 Bug、写 Feature）绝对够了**，这 8 篇覆盖了单体智能（Single Agent）的核心理论。

**对于"Agent Team（多智能体协同）"不够。** 上述 8 篇主要讲模型如何与"环境（Terminal）"交互，没有讲模型如何与"其他模型（Peers）"交互。补充的 3 篇（MetaGPT、AutoGen、OpenHands）提供了理论底座。

**v2.0 额外建议：** 多智能体部分，学术论文与工业实现的差距很大。建议同时参考 Anthropic 官方的 agent 文档和 Claude Code 的实际行为，而非仅依赖论文。

---

# 四、3小时高阶课程大纲

## 课程名称：《掀开 AI 程序员的引擎盖：Claude Code 与 AI Agent 的底层架构与控制流》

**课程受众：** 高级研发工程师、架构师、效能团队
**课程时长：** 3 小时（每个模块 45 分钟讲解 + 15 分钟 QA 互动）

---

## 模块一：破除"文本接龙"迷信 —— 智能体控制论与 Bug 修复原理 (1小时)

**场景目标：** 剖析 `cc` 是如何在完全未知的代码库中，通过试错修复一个 Bug 的。
**核心引用论文：** *ReAct*, *Toolformer*, *Reflexion*

### 1.1 从开环生成到闭环控制：OODA 与 TAO

*   **传统大模型的死穴：** 开环生成（Open-loop）与错误累积（Error Accumulation）。一次性生成代码补丁，没有验证环节，错误无从纠正。
*   **Boyd 的启示：** 朝鲜战争中 F-86 以 10:1 击杀比碾压纸面参数更优的 MiG-15，靠的不是更强的火力，而是更快的决策-反馈循环（OODA: Observe → Orient → Decide → Act）。在动态环境中，快速的"足够好"决策胜过迟到的"完美"决策——因为完美决策做出来的时候，它所针对的局面可能已经不存在了。映射到 AI agent：模型基础能力是门槛，循环机制是放大器。
*   **ReAct 范式〔ReAct：从开环到闭环的范式革命〕：** 交替执行"推理（Thought）→ 动作（Action）→ 观察（Observation）"，形成闭环。TAO 是 OODA 在 LLM agent 领域的特化投影——将 Orient（理解）和 Decide（决策）压缩为一个 Thought 步骤，因为 LLM 在一次推理中天然地同时完成理解和决策。
*   **两条主线的起点：** ReAct 同时开启了本课程的两条主线——任务结构线（Localization → Repair → Validation 的循环执行）和 OODA 演进线（后续论文分别优化循环的各个环节）。

### 1.2 工具调用的真实机制：API 层协议而非 Tokenizer 魔法

*   **工具调用的本质〔Toolformer：赋予模型工具使用能力〕：** 模型通过 API 的 `tool_use` 协议返回结构化的工具调用请求（JSON schema），客户端解析后执行对应操作，再将结果作为 `tool_result` 回传。这是**应用层协议**，不是 tokenizer 层的 special token hack。
*   **常见误区澄清：** 网上流传的"special token 劫持"说法具有误导性。实际的 Claude API 工具调用流程是：模型输出 → API 返回 `tool_use` content block → 客户端执行 → 将结果封装为 `tool_result` 回传。整个过程在应用层完成。
*   **Claude Code 的工具集设计：** `cc` 并非让模型直接输出裸 bash 命令（这是 CodeAct/OpenHands 的路线），而是提供了**结构化的专用工具集**（Read、Edit、Grep、Glob、Bash、Agent...），每个工具有明确的参数 schema。这降低了格式出错的概率，也让权限控制成为可能。
*   **对比〔CodeAct：代码即动作〕：** CodeAct 论文主张让模型直接生成可执行代码作为动作，减少格式约束。这是另一条可行路线（OpenHands 采用），各有优劣。Claude Code 选择了结构化工具调用 + 丰富工具集的路线。

### 1.2a Action Space 设计：少即是多

各论文的 Action Space 看似简单，实则是反复试错后的极简完备集：

| 系统 | Action Space 规模 | 设计哲学 |
|---|---|---|
| SWE-agent | ~12 个命令（open, scroll, search_file, edit...） | 模拟人类在编辑器中的最小操作集 |
| AutoCodeRover | AST 工具（search_class, search_method...） | 按代码结构而非文本组织动作 |
| CodeAct | 仅 Python + Bash | 极致简化：代码本身就是动作语言 |
| Claude Code | ~10 个工具（Read, Edit, Glob, Grep, Bash, LSP, Agent...） | 每个工具职责单一，参数 schema 严格约束 |

共同的设计原则：**动作空间越精简，模型选错工具的概率越低；参数 schema 越严格，格式出错的概率越低。** 这对应 OODA 的 Act 环节——关键不是"能做的事情越多越好"，而是"精简的动作空间降低决策复杂度，从而提升循环转速"。

每个系统都在精简性与表达力之间做取舍：CodeAct 走极简路线（只要会写代码就什么都能做），但牺牲了权限控制和格式安全；Claude Code 多做了一层抽象（每个工具有明确 schema），换来了可审计性和鲁棒性。

### 1.3 真实演练剖析：`cc` 的修 Bug 状态机

*   **触发失败：** 运行 `pytest` 看到满屏红字。
*   **多轮上下文纠错〔Reflexion：化失败为经验〕：** 模型将 `stderr` 输出纳入对话上下文，在下一轮推理中参考错误信息进行修正。Reflexion 论文揭示了这个过程的本质——它在 TAO 循环外部套了一层**经验积累循环**：失败触发 Reflection（负反馈），Reflection 生成结构化经验总结（正向指导），总结注入下一轮 Thought。在 Claude Code 的实际实现中，这两层循环被摊平为连续对话，但"显式总结经验"比"把错误信息扔进上下文让模型自己领悟"更有效。
*   **防死循环机制（Circuit Breaker）：** 模型可能陷入"重复执行同一个错误命令"的怪圈。用 Boyd 的框架理解：这是 OODA 循环卡死——模型的 Orient 环节失灵，无法从重复的 Observation 中提取新信息。工程上通过 max retries、上下文压缩（context compaction）、以及在 system prompt 中注入"如果连续失败请换一种方法"的指令来强制打破循环。

---

## 模块二：突破上下文重力法则 —— ACI 协议与新功能开发 (1小时)

**场景目标：** 剖析 `cc` 是如何在百万行代码中不迷失，并从零实现一个跨文件 Feature 的。
**核心引用论文：** *SWE-bench*, *SWE-agent*, *AutoCodeRover*, *Agentless*

### 2.1 为什么传统的 RAG 检索在编程中常常失效？〔SWE-bench：AI 程序员的试金石〕

*   **词汇鸿沟与依赖幽灵：** Issue 描述用自然语言，代码用变量名和函数签名，BM25/向量检索难以跨越这道语义鸿沟，找不到真实的 Bug 发生地。
*   **AST 与代码感知〔AutoCodeRover：结构化代码感知〕：** `cc` 需要具备跳转定义（Go to Definition）、查看类签名（LSP hover）的能力，通过代码结构而非纯文本相似度来定位目标。这比把整个文件塞给模型高效得多。

### 2.2 核心科技：ACI（智能体-计算机接口）设计哲学〔SWE-agent：信息粒度的精确控制〕

*   **不是裸 Terminal，而是精心设计的工具层：** `cc` 在模型与操作系统之间插入了一层精心设计的工具接口，控制信息的粒度和格式。
*   **防爆窗机制：** 为什么 `cc` 的 Read 工具支持 `offset` + `limit` 参数？为什么 Grep 有 `head_limit`？因为必须保护 Token Budget——一个 `cat` 大文件就能把整个上下文窗口撑爆。这是 SWE-agent 论文中"粗细粒度漏斗策略（Coarse-to-fine）"的工程化实现。
*   **安全的写入协议：** 让模型输出 Unified Diff (`@@ -10,5 +10,6 @@`) 极易出错（行号偏移、上下文不匹配），根本原因在于 diff 依赖**行号定位**，而模型对数字天然不敏感。业界的共识趋势是转向 **search/replace 范式（内容定位）**——用代码原文本身做锚点，而非行号。Agentless 自创的 `<<<< SEARCH / REPLACE >>>>` 格式和 Claude Code 的 `old_string → new_string` 在精神上完全一致，都属于这一范式，只是各自独立得出了相同结论。Claude Code 在此基础上增加了一层硬约束：如果 `old_string` 在文件中匹配到多处，直接拒绝执行，强制模型提供更多上下文来消歧——宁可报错重试，也不悄悄改错地方。

### 2.3 真实演练剖析：`cc` 的 Feature 建造流

*   **探索期：** `Glob`（按模式找文件）→ `Grep`（按内容搜代码）→ `Read`（精读关键文件）→ `LSP`（跳转定义、查引用）。
*   **修改期：** `Edit`（精确替换）→ `Bash` 运行 lint/test → 根据结果迭代修正。

### 2.4 架构反思：Agentless 三阶段流水线 vs Agent 动态循环〔Agentless：最简实现的力量〕

Agentless 论文提出了一条与 ReAct Agent 截然不同的技术路线——**固定三阶段流水线**：

```
Localization（定位）→ Repair（修复）→ Patch Validation（验证）
```

**阶段一：分层定位漏斗（Localization）**

Localization 内部还有一个层级细化过程：**文件级 → 类/函数级 → 行级**。每一层只给模型看"刚好够做决策"的信息量——先看文件列表选文件，再看代码骨架（skeleton）选函数，最后看具体代码选行号。这个粗到细（Coarse-to-fine）的信息控制策略是全文最具工程洞察力的设计，与 Claude Code 的实际行为（Glob → Grep → Read）高度同构，区别在于 agent 是在 ReAct 循环中动态执行的，而 Agentless 是预设好的固定流水线。

**阶段二：多候选采样修复（Repair）**

Agentless 在修复阶段不是只生成一个 patch，而是用高 temperature 采样生成多个候选 patch。这暗含一个关键洞察：模型单次生成正确修复的概率可能只有 20%，但生成 10 个候选中有一个正确的概率可以到 80%+。这是用**推理时计算（inference-time compute）换准确率**的策略，与 best-of-N 采样、self-consistency 同源。Agent 方案则是通过多轮试错达到类似效果——跑测试、看报错、再改，本质上也是在搜索正确解，只是搜索策略不同。

**阶段三：测试驱动验证（Patch Validation）**

用测试套件对所有候选 patch 做筛选，选出通过率最高的作为最终输出。

**两条路线的核心对比：**

需要注意的是，Agentless 和 Claude Code 在**编辑格式**上殊途同归——都采用了 search/replace 范式（用内容定位，而非行号），真正的对立面是 unified diff（行号定位）。它们的根本差异不在编辑格式，而在**整体架构和容错策略**：

| | Agentless（流水线） | Agent（Claude Code） |
|---|---|---|
| 编辑格式 | search/replace（自创语法） | search/replace（old_string → new_string） |
| 唯一性校验 | 无，生成后直接 apply | 有，old_string 不唯一则拒绝执行 |
| 搜索策略 | 并行采样 + 测试筛选 | 串行试错 + 反馈修正 |
| 容错机制 | 多候选中选一个能过测试的 | 严格校验 + 模型看到错误后多轮重试 |
| 优势 | 无状态，可大规模并行，成本可控 | 能利用中间反馈，适应意外情况 |
| 劣势 | 不可回溯，定位错则全盘皆输 | 可能陷入死循环，上下文会膨胀 |

**关键局限：固定流水线的"脆性"。** Agentless 的三阶段严格串行、不可回溯。如果 Localization 阶段定位错了文件，后续 Repair 和 Validation 全部白费。而 Agent 在实际工作中可以根据中间观察动态调整搜索方向（发现改错地方 → 退回重新定位），这种动态纠偏能力是 ReAct agent 的核心优势。

**工程权衡结论：** Agentless 用简单流水线达到了 agent 方案约 70-80% 的效果，证明了大量问题不需要复杂的 agent 循环。正确的选择不是非此即彼，而是**按任务难度匹配策略**：定义清晰、范围有限的问题适合流水线（快、便宜、可并行）；需要跨文件追踪、动态探索的复杂任务适合 agent（慢、贵、但能处理意外）。

---

## 模块三：从单兵到正规军 —— Agent Team 模式与协同编排 (1小时)

**场景目标：** 剖析 `cc` 的 Agent Team 模式是如何实际工作的：一个主 agent 规划拆解，spawn 子 agent 并行执行，然后汇总交付。
**核心引用论文：** *MetaGPT* (学术对比), *AutoGen* (学术对比), *OpenHands* (工业参考)
**核心参考：** Claude Code 实际行为与 Anthropic Agent 文档

### 3.1 为什么我们需要 Agent Team？（物理极限与分治策略）

*   **上下文污染（Context Pollution）：** 单个 Agent 在执行了几十步操作后，对话历史膨胀，早期的关键信息被稀释甚至被压缩丢弃，导致模型"迷失"。
*   **分治法的天然适配：** 软件工程任务本身就是可分解的（前端/后端/测试/文档），将子任务分发给独立的 agent，每个 agent 拥有干净的上下文，效果远好于一个 agent 扛所有。
*   **与学术方案的区别〔MetaGPT：固定角色与 SOP 流程〕：** MetaGPT 预定义了 PM、Architect、SWE 等固定角色和 SOP 流程。Claude Code 的实际做法更灵活——**主 agent 根据任务动态决定要 spawn 几个子 agent、每个做什么**，没有固定角色约束。

### 3.2 Claude Code 的 Orchestrator-Worker 架构

*   **Agent Tool 机制：** 主 agent 通过调用 `Agent` 工具 spawn 子 agent，传入一段自然语言 prompt 描述任务。子 agent 在独立的对话上下文中执行，完成后返回结果摘要给主 agent。
*   **任务追踪系统：** 主 agent 使用 `TaskCreate` / `TaskUpdate` / `TaskList` 管理任务状态（pending → in_progress → completed），实现类似看板（Kanban）的协调。这是自然语言驱动的调度，而非预先生成的 DAG。
*   **并发执行：** 主 agent 可以在一次响应中同时发起多个 Agent 调用，实现真正的并行执行。独立的子任务并发跑，有依赖关系的串行等待。
*   **对比〔AutoGen：对话驱动的多智能体框架〕：** AutoGen 的"对话驱动"多 agent 模式让 agent 之间直接对话。Claude Code 选择了更简单的星型拓扑——所有子 agent 只与主 agent 通信，不互相对话，降低了协调复杂度。

### 3.3 隔离与共享：子 agent 的执行环境

*   **对话隔离，环境共享：** 子 agent 的对话历史是独立的（干净上下文），但继承了工作目录、git 状态、CLAUDE.md 项目指令等环境上下文。这意味着子 agent 能直接读写项目文件。
*   **Git Worktree 隔离模式〔OpenHands：沙箱隔离实践〕：** 对于可能产生文件冲突的并行任务，可以设置 `isolation: "worktree"`，让子 agent 在独立的 git worktree 中工作。每个 worktree 是一个独立的文件系统副本 + 独立分支，从根本上避免了并发写冲突。
*   **冲突解决：** 当多个子 agent 在各自 worktree 完成工作后，主 agent 负责 review 和 merge。如果有冲突，主 agent 可以手动解决或再 spawn 一个子 agent 处理。

### 3.4 Team 模式下的双主线：嵌套的 OODA 与 L-R-V

多智能体论文（MetaGPT、AutoGen、OpenHands）并未显式提出类似 OODA 或 L-R-V 的统一框架，但从 Claude Code 的实际行为中可以投影出嵌套结构：

**L-R-V 在 Team 模式下变成分层执行：**

```
Meta-Localization：主 agent 分析需求，识别需要修改的子系统，拆解为子任务
  └→ 每个子 agent 在自己的范围内独立执行完整的 L → R → V 循环
Meta-Repair：    并发分发 worker，各自执行
Meta-Validation：worker 完成后，主 agent 执行集成测试
```

**OODA 在 Team 模式下变成嵌套循环：**

```
主 agent 的 OODA（慢循环，粗粒度决策）：
  Observe：接收各 worker 的完成报告
  Orient： 判断整体进度，识别阻塞点
  Decide： 决定是否追加 worker、重新分配任务
  Act：    spawn 新 worker 或执行 merge

子 agent 的 OODA（快循环，细粒度决策）：
  标准的 T → A → O 单体循环，在独立上下文中执行
```

Boyd 将 OODA 从单机空战扩展到编队作战时的核心发现：**编队的整体 OODA 转速取决于协调开销。** Claude Code 选择星型拓扑（子 agent 不互相通信）正是在最小化协调开销，保持整体循环速度。

### 3.5 真实演练剖析：一次完整的 Team 级交付

*   用户输入复杂需求 → 主 agent 分析并拆解为若干子任务（TaskCreate）→ 并发 spawn 多个子 agent（Agent tool，可选 worktree 隔离）→ 各子 agent 在独立上下文中完成代码修改 → 返回结果摘要给主 agent → 主 agent review、合并、运行集成测试 → 标记任务完成 → 向用户汇报交付结果。

---

## 模块四（加餐）：安全与权限控制 —— 给 AI 装上刹车 (15分钟)

**场景目标：** 高阶开发者最关心的问题——如何确保 AI agent 不会搞出灾难？

### 4.1 权限分级机制

*   **工具级权限控制：** 每个工具调用都经过权限检查，用户可以配置自动允许的操作范围（如"允许读文件但写文件需确认"）。
*   **破坏性操作保护：** `git push --force`、`rm -rf`、删除分支等高风险操作即使在 agent 自主模式下也需要用户确认。

### 4.2 沙箱与 Hook 机制

*   **Bash 沙箱：** 命令执行有超时限制（默认 2 分钟），防止 agent 启动失控的长时间进程。
*   **Hook 系统：** 用户可以配置在特定事件（如工具调用前/后）自动执行的 shell 命令，实现自定义的安全策略和自动化流程。

### 4.3 CLAUDE.md：人类对 AI 的"宪法"

*   项目根目录的 `CLAUDE.md` 文件作为 agent 的行为准则，每次对话都会加载。这是人类控制 agent 行为边界的关键机制——相当于用自然语言写的"宪法"。

---

## 授课建议

1.  **Boyd 故事是全场破冰利器：** 用 F-86 vs MiG-15 的故事开场，高阶开发者会立刻意识到这不是一堂 AI 营销课。从空战引出 OODA，再从 OODA 落到 ReAct，自然过渡。
2.  **二维认知地图要常驻屏幕：** 横轴 L-R-V × 纵轴 OODA 的论文定位图，建议打印或常驻屏幕一角，每讲完一节就标记当前位置，帮助听众始终知道"我在哪"。
3.  **准备 API 请求对比 Demo：** 在大屏幕上对比普通的 `chat completion` 请求和包含 `tools` 定义的请求，展示 `tool_use` / `tool_result` 的完整交互流程。
4.  **永远先讲失败：** 高阶开发者不相信魔法。讲每个模块时，先展示"模型在这里会犯什么错"（幻觉代码、死循环、上下文丢失），再讲工程上如何兜底。
5.  **用 MVP 代码做 Live Demo：** 手头的 MVP 代码可以直接演示 ReAct 循环、工具调用、错误恢复的全过程，比论文截图有说服力 10 倍。
6.  **双主线收束：** 结语用一句话总结——**"循环转速决定胜负，接口设计决定上限，协同架构决定规模，安全机制决定底线。"**

---

*v2.3 | 2025-03-25 | 引用格式统一为题注式，新增 Action Space 设计分析，新增 Team 模式嵌套 OODA/L-R-V 框架*
*v2.2 | 2025-03-25 | 引入 OODA 演进线与双主线框架、Boyd 理论、TAO 与 OODA 关系、Reflexion 双层循环*
*v2.0 | 2025-03-25 | 基于 Claude Code (Opus 4.6) 审校修订*
*v1.0 | 原始版本 by Gemini 协助生成*
