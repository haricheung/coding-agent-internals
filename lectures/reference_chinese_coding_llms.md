# 国内编程大模型能力点评（2026 年 4 月视角）

> 课程参考材料 — 面向高级研发工程师
> 聚焦 **2026 年发布**的模型；2025 年模型仅在对比表中保留。
> 所有 benchmark 均为模型方自报数据，不同 scaffold 下成绩差异显著，横向对比需谨慎。

---

## 一、MiniMax M2 系列 — SWE-bench SOTA，成本革命

### 1.1 MiniMax-M2.5（2026 年初）

MoE 架构，~228B 参数，Modified-MIT 开源。2025 年 10 月底至 2026 年初，3.5 个月内连续发布 M2 → M2.1 → M2.5。

**核心成绩（编码 Agent 场景）：**

| Benchmark | M2.5 | M2.1 | Claude Opus 4.6 | GPT-5.2 |
|-----------|------|------|-----------------|---------|
| **SWE-bench Verified** | **80.2%** | -- | 78.9% (Droid) | -- |
| Multi-SWE-Bench | **51.3%** | -- | -- | -- |
| SWE-bench (Droid scaffold) | **79.7%** | -- | 78.9% | -- |
| SWE-bench (OpenCode scaffold) | **76.1%** | -- | 75.9% | -- |

**点评：**
- **SWE-bench Verified 80.2%，当前全球最高**，超越 Claude Opus 4.6
- 在多个不同 scaffold（Droid / OpenCode）上均一致领先，泛化性强
- 成本革命：$0.3/M input + $2.4/M output（Lightning 版），**持续运行 1 小时仅 $1**（100 TPS），仅为 Opus 的 1/10~1/20
- 22.8 分钟完成 SWE-bench 一个任务（与 Opus 4.6 持平），比 M2.1 快 37%
- 10+ 语言（Go/C/C++/TS/Rust/Python/Java 等）200K+ 真实环境 RL 训练
- **Spec-writing 行为自发涌现**：先做架构规划再写代码

### 1.2 MiniMax-M2.7（最新）

GLM-5.1 benchmark 表中已出现 M2.7 作为对比模型，确认已发布：

| Benchmark | M2.7 | GLM-5.1 | Kimi K2.5 | Claude Opus 4.6 |
|-----------|------|---------|-----------|-----------------|
| SWE-Bench Pro | 56.2 | **58.4** | 53.8 | 57.3 |
| NL2Repo | 39.8 | 42.7 | 32.0 | **49.8** |
| HLE | 28.0 | 31.0 | 31.5 | 36.7 |

**点评：** M2.5 之后的又一次迭代，SWE-Bench Pro 56.2%，但具体架构和完整 benchmark 尚待 MiniMax 官方公布。

---

## 二、GLM-5 / GLM-5.1（智谱 AI / 清华）— 从 vibe coding 到 agentic engineering

### 2.1 GLM-5（2026 年 2 月，arXiv:2602.15763）

**架构：** MoE，**744B 总参 / 40B 激活**（较 GLM-4.5 的 355B/32B 大幅扩展），28.5T token 预训练，DeepSeek Sparse Attention (DSA)，MIT 开源。

自研 **slime** 异步 RL 基础设施，大幅提升 RL 训练效率。

| Benchmark | GLM-5 | DeepSeek-V3.2 | Kimi K2.5 | Claude Opus 4.5 | Gemini 3 Pro |
|-----------|-------|---------------|-----------|-----------------|-------------|
| **SWE-bench Verified** | **77.8%** | 73.1% | 76.8% | 80.9% | 76.2% |
| SWE-bench Multilingual | **73.3%** | 70.2% | 73.0% | 77.5% | 65.0% |
| Terminal-Bench 2.0 | 56.2 | 39.3 | 50.8 | 59.3 | 54.2 |
| CyberGym | 43.2 | 17.3 | 41.3 | 50.6 | 39.9 |
| BrowseComp | 62.0 | 51.4 | 60.6 | 37.0 | 37.8 |

**点评：**
- 开源模型 SWE-bench 77.8%，**开源最高**（发布时）
- BrowseComp 62.0 远超 Claude Opus 4.5（37.0），Agent 搜索能力突出
- 从 CodeGeeX4 的 ~71-82% HumanEval 到 SWE-bench 77.8%，智谱实现代际跨越

### 2.2 GLM-5.1（2026 年 Q1-Q2）

GLM-5 的快速迭代版，聚焦 **agentic engineering**——长时段 Agent 任务中持续优化能力。

**关键差异化：** 不同于前代模型"用完套路后停滞"，GLM-5.1 能在数百轮工具调用中**持续改进**：分解问题 → 实验 → 读取结果 → 定位阻塞 → 修正策略。

| Benchmark | GLM-5.1 | GLM-5 | Kimi K2.5 | Claude Opus 4.6 | Gemini 3.1 Pro | GPT-5.4 |
|-----------|---------|-------|-----------|-----------------|---------------|---------|
| **SWE-Bench Pro** | **58.4%** | 55.1% | 53.8% | 57.3% | 54.2% | 57.7% |
| NL2Repo | 42.7 | 35.9 | 32.0 | **49.8** | 33.4 | 41.3 |
| Terminal-Bench 2.0 | 63.5 | 56.2 | 50.8 | 65.4 | **68.5** | -- |
| **CyberGym** | **68.7** | 48.3 | 41.3 | 66.6 | -- | -- |
| BrowseComp | 68.0 | 62.0 | 60.6 | -- | -- | -- |
| BrowseComp (w/ Context) | 79.3 | 75.9 | 74.9 | 84.0 | **85.9** | 82.7 |

**点评：**
- SWE-Bench Pro **58.4%** 全球最高，超越 Claude Opus 4.6（57.3%）和 GPT-5.4（57.7%）
- CyberGym **68.7%**，安全攻防 Agent 能力全球前列
- 从 GLM-5 到 5.1 的每个 benchmark 都有显著提升，RL scaling 效果明显
- MIT 开源，支持 vLLM / SGLang / KTransformers 本地部署

---

## 三、Kimi K2.5（月之暗面）— 原生多模态 + Agent Swarm

**发布：** 2026 年 1 月（arXiv:2602.02276），基于 Kimi-K2-Base 续训约 15T 混合视觉 + 文本 token。

**架构：** MoE，**1T 总参 / 32B 激活**，384 专家选 8，MLA 注意力，256K 上下文，MoonViT 视觉编码器（400M），Modified-MIT 开源。

### 核心能力

- **原生多模态**：视觉 + 语言预训练，视觉知识 / 跨模态推理 / 视觉 Agent 工具调用
- **Coding with Vision**：从 UI 设计稿、视频流程图直接生成代码
- **Agent Swarm**：自动将复杂任务分解为并行子任务，动态实例化领域专用 Agent

### 编码 Benchmark（Thinking 模式）

| Benchmark | K2.5 | GPT-5.2 | Claude 4.5 Opus | Gemini 3 Pro | DeepSeek V3.2 |
|-----------|------|---------|-----------------|-------------|---------------|
| **SWE-bench Verified** | **76.8%** | 80.0% | 80.9% | 76.2% | 73.1% |
| SWE-bench Pro | 50.7% | 55.6% | 55.4% | -- | -- |
| SWE-bench Multilingual | **73.0%** | 72.0% | 77.5% | 65.0% | 70.2% |
| **LiveCodeBench (v6)** | **85.0** | -- | 82.2 | 87.4 | 83.3 |
| Terminal-Bench 2.0 | 50.8 | 54.0 | 59.3 | 54.2 | 46.4 |
| CyberGym | 41.3 | -- | 50.6 | 39.9 | 17.3 |
| PaperBench | 63.5 | 63.7 | **72.9** | -- | 47.1 |

**点评：**
- SWE-bench 76.8%，**超越 Gemini 3 Pro（76.2%）和 DeepSeek V3.2（73.1%）**
- LiveCodeBench v6 85.0，超越 Claude 4.5 Opus（82.2）和 DeepSeek V3.2（83.3）
- SWE-bench Multilingual 73.0% 超越 GPT-5.2（72.0%），多语言工程能力突出
- 1T/32B 架构与 K2 相同，但续训 15T 多模态数据后全面提升
- Agent Swarm 在 BrowseComp（78.4）和 WideSearch（79.0）上效果显著

---

## 四、DeepSeek-V3.2（深度求索）— 确认发布

从 GLM-5 和 Kimi K2.5 的 benchmark 表中多次作为对比模型出现，确认已发布。

| Benchmark | V3.2 | GLM-5 | Kimi K2.5 | Claude Opus 4.5 |
|-----------|------|-------|-----------|-----------------|
| SWE-bench Verified | 73.1% | 77.8% | 76.8% | 80.9% |
| SWE-bench Multilingual | 70.2% | 73.3% | 73.0% | 77.5% |
| Terminal-Bench 2.0 | 39.3 | 56.2 | 50.8 | 59.3 |
| LiveCodeBench (v6) | 83.3 | -- | 85.0 | 82.2 |
| CyberGym | 17.3 | 43.2 | 41.3 | 50.6 |
| BrowseComp | 51.4 | 62.0 | 60.6 | 37.0 |

**点评：**
- SWE-bench 73.1%，相比 V3-0324 的 ~42% 有巨大飞跃
- LiveCodeBench v6 83.3，竞争力强
- 但 Terminal-Bench（39.3）和 CyberGym（17.3）明显落后，**Agent 长程任务能力仍是短板**
- 具体架构参数和技术报告尚未看到完整公开

---

## 五、Qwen 系列（阿里通义千问）

### 5.1 Qwen3.6-Plus（最新）

GLM-5.1 benchmark 表中出现 Qwen3.6-Plus 作为对比模型：

| Benchmark | Qwen3.6-Plus | GLM-5.1 | Kimi K2.5 | Claude Opus 4.6 |
|-----------|-------------|---------|-----------|-----------------|
| SWE-Bench Pro | 56.6% | **58.4%** | 53.8% | 57.3% |
| Terminal-Bench 2.0 | 61.6 | 63.5 | 50.8 | 65.4 |
| HLE | 28.8 | 31.0 | 31.5 | 36.7 |
| AIME 2026 | 95.1 | 95.3 | 94.5 | 95.6 |

**点评：** Qwen 系列最新迭代，SWE-Bench Pro 56.6%，Terminal-Bench 61.6，表现稳健。具体架构细节待官方公布。

### 5.2 Qwen3-Coder（2025 年 7 月，背景参考）

MoE，480B/36B 激活，Apache 2.0。SWE-bench Verified 70.0%（已被 2026 年模型全面超越），Aider Polyglot 64.4%。

---

## 六、字节跳动（ByteDance）

### 6.1 Doubao-Coder-o1（豆包编程推理模型，2025 年）

SWE-bench Verified ~62.8%，驱动 TRAE AI IDE。

### 6.2 Seed-Coder-8B（2025 年中）

Dense 8B，MIT 开源，HumanEval+ ~85.4%。8B 级别 SOTA。"LLMs4LLMs" 数据筛选方法。

> 字节 2026 年新模型数据暂未在 HF 上找到，如有新发布请补充。

---

## 七、SWE-bench Verified 排行榜（2026 年 4 月最新）

| 排名 | 模型/系统 | 解决率 | 备注 |
|------|----------|--------|------|
| **1** | **MiniMax-M2.5** | **80.2%** | **国产 #1，全球 SOTA** |
| 2 | Claude Opus 4.5/4.6 | ~80.9%/78.9% | Anthropic（scaffold 差异） |
| 3 | GPT-5.2 | 80.0% | OpenAI |
| **4** | **GLM-5** | **77.8%** | **国产 #2，MIT 开源** |
| **5** | **Kimi K2.5** | **76.8%** | **国产 #3，多模态 Agent** |
| 6 | Gemini 3 Pro | 76.2% | Google |
| **7** | **DeepSeek-V3.2** | **73.1%** | **国产 #4** |
| -- | Qwen3-Coder (2025) | 70.0% | 已被 2026 模型超越 |

> 注意：SWE-bench 成绩极度依赖 Agent scaffold。MiniMax M2.5 使用 Claude Code 为 scaffold，其他模型使用各自内部框架。同模型换框架可差 5-10 个百分点。

---

## 八、SWE-Bench Pro 排行榜（更难的下一代 benchmark）

| 排名 | 模型 | 解决率 |
|------|------|--------|
| **1** | **GLM-5.1** | **58.4%** |
| 2 | GPT-5.4 | 57.7% |
| 3 | Claude Opus 4.6 | 57.3% |
| **4** | **Qwen3.6-Plus** | **56.6%** |
| **5** | **MiniMax M2.7** | **56.2%** |
| 6 | GLM-5 | 55.1% |
| **7** | **Kimi K2.5** | **53.8%** |

---

## 九、综合对比矩阵（2026 年模型）

| 模型 | 架构 | 总参/激活 | SWE-bench Verified | SWE-Bench Pro | LiveCodeBench v6 | Terminal-Bench 2.0 | CyberGym |
|------|------|----------|-------------------|---------------|------------------|-------------------|----------|
| **MiniMax-M2.5** | MoE | ~228B | **80.2%** | -- | -- | -- | -- |
| **GLM-5.1** | MoE | 754B/40B | -- | **58.4%** | -- | 63.5 | **68.7** |
| **GLM-5** | MoE | 744B/40B | **77.8%** | 55.1% | -- | 56.2 | 48.3 |
| **Kimi K2.5** | MoE | 1T/32B | 76.8% | 50.7% | **85.0** | 50.8 | 41.3 |
| **DeepSeek-V3.2** | MoE | -- | 73.1% | -- | 83.3 | 39.3 | 17.3 |
| **Qwen3.6-Plus** | -- | -- | -- | 56.6% | -- | 61.6 | -- |
| MiniMax-M2.7 | MoE | -- | -- | 56.2% | -- | -- | -- |
| Claude Opus 4.6 | -- | -- | ~78.9% | 57.3% | -- | 65.4 | 66.6 |
| Gemini 3.1 Pro | -- | -- | -- | 54.2% | -- | **68.5** | -- |
| GPT-5.4 | -- | -- | -- | 57.7% | -- | -- | -- |

---

## 十、已退出/停更的国产编程模型

| 模型 | 状态 | 说明 |
|------|------|------|
| Yi-Coder（零一万物） | 已停更 | 公司转向 AI 应用，大模型训练团队裁撤 |
| CodeGeeX4（智谱旧版） | 已被 GLM-5/5.1 取代 | 从 ~71-82% HumanEval 到 77.8% SWE-bench，代际跨越 |
| Qwen3-Coder | 仍可用但已被超越 | SWE-bench 70.0% 在 2026 格局中不再领先 |

---

## 十一、核心结论

1. **国产模型已全面达到世界前沿**：MiniMax M2.5 SWE-bench 80.2% 全球 SOTA；GLM-5.1 SWE-Bench Pro 58.4% 全球 SOTA；国产模型在多个 benchmark 上首次超越所有闭源模型

2. **2026 年竞争格局彻底重塑**：五强并立 — MiniMax（SWE-bench SOTA）、智谱 GLM（SWE-Bench Pro SOTA + 安全攻防）、月之暗面 Kimi（多模态 Agent + LiveCodeBench）、DeepSeek（通用编码）、阿里 Qwen（稳健全面）

3. **MoE 仍是统一路线**：GLM-5（744B/40B）、Kimi K2.5（1T/32B）、MiniMax M2.5（~228B MoE）、DeepSeek V3.2 — 无一例外

4. **Agentic 能力成为核心分水岭**：2026 的 benchmark 从 HumanEval/MBPP 全面转向 SWE-bench Pro / Terminal-Bench / CyberGym / NL2Repo，测的是**长时段多轮 Agent 工程能力**，不是单次代码生成

5. **成本断崖式下降**：MiniMax M2.5 持续运行 1 小时仅 $1，是 Claude Opus 的 1/10~1/20。"Intelligence too cheap to meter"正在成为现实

6. **RL scaling 是关键引擎**：GLM-5 用 slime 异步 RL，MiniMax 用 Forge Agent-native RL + CISPO 算法，Kimi K2.5 用 Agent Swarm RL — 都在 Agent 环境中做大规模 RL，这是 2026 年的技术主线

7. **Scaffold 依赖是隐忧**：同一模型在不同 scaffold 下 SWE-bench 可差 5-10 个百分点（MiniMax M2.5 Droid 79.7% vs OpenCode 76.1%），自报 benchmark 需谨慎解读

---

*数据来源：HuggingFace 模型卡（moonshotai/Kimi-K2.5, MiniMaxAI/MiniMax-M2.5, zai-org/GLM-5, zai-org/GLM-5.1），各模型方技术报告*
*注：MiniMax M2.7、Qwen3.6-Plus 的完整数据来自 GLM-5.1 benchmark 表中的对比列，待各自官方补充完整信息*
