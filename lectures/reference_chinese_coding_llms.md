# 国内最新编程大模型能力点评（截至 2026 年 4 月）

> 课程参考材料 — 面向高级研发工程师

---

## 一、Qwen-Coder 系列（阿里通义千问）

### 1.1 Qwen2.5-Coder（2024 年 11 月）

**架构：** Dense，6 个尺寸（0.5B / 1.5B / 3B / 7B / 14B / 32B），5.5 万亿 token 代码语料，92+ 种语言，128K 上下文。

**Qwen2.5-Coder-32B-Instruct 核心数据：**

| Benchmark | 得分 | vs GPT-4o |
|-----------|------|-----------|
| HumanEval | **92.7** | 90.2 |
| HumanEval+ | **87.2** | 87.2（持平） |
| MBPP | **90.2** | 85.7 |
| MBPP+ | **78.8** | 73.5 |
| LiveCodeBench (2407-2409) | 34.3 | 43.2 |
| Aider Polyglot | 44.7% | 52.3% |

**点评：** 发布时开源编程模型天花板，HumanEval 匹配 GPT-4o。但 LiveCodeBench 和 Aider Polyglot 等实战 benchmark 上仍差 10-15 个百分点。作为可本地部署模型，性价比极高。

### 1.2 Qwen3（2025 年 4 月）

**架构：** 8 个模型，首次引入**混合思考模式**（深度推理 / 快速响应可切换）：

| 类型 | 模型 | 总参数 | 激活参数 |
|------|------|--------|---------|
| Dense | 0.6B / 1.7B / 4B / 8B / 14B / 32B | = 激活量 | 全量 |
| **MoE** | **Qwen3-30B-A3B** | 30B | ~3B |
| **MoE** | **Qwen3-235B-A22B**（旗舰） | 235B | ~22B |

**Qwen3-235B-A22B（Think 模式）核心数据：**

| Benchmark | Qwen3-235B | DeepSeek-R1 | GPT-4o |
|-----------|-----------|-------------|--------|
| LiveCodeBench | **~70.7%** | ~65.9% | ~50% |
| HumanEval | ~92.1% | ~90%+ | 90.2% |

**Aider 排行榜（2025 年 5 月）：**

| 排行榜 | Qwen3-235B (Think) | Qwen3-235B (非Think) | Qwen3-30B-A3B (Think) |
|--------|--------------------|--------------------|---------------------|
| Code Editing | **72.9%** | 62.7% | 71.1% |
| Polyglot (pass@2) | **60.4%** | -- | -- |

**点评：**
- 国产编程模型综合最强旗舰，LiveCodeBench 超越 DeepSeek-R1
- 235B 总参 / 22B 激活，推理效率远优于 DeepSeek-R1 的 37B 激活
- Think 模式对编码帮助显著（+10.2%），但格式合规率下降
- **Qwen3-30B-A3B 是极致性价比之选**：仅 3B 激活，Think 模式 71.1%，逼近旗舰
- 短板：vs Claude Sonnet 4（84.2%/78.4%）仍差 10-18 个百分点

---

## 二、DeepSeek-Coder 系列（深度求索）

### 2.1 DeepSeek-Coder-V2（2024 年中）

MoE 架构，16B / 236B（~21B 激活），MLA 注意力，338 种语言，128K 上下文。发布时超越 GPT-4 Turbo，但已被 V3/R1 全面超越，历史意义大于当前价值。

### 2.2 DeepSeek-V3（2024 年 12 月）及 V3-0324

**架构：** MoE，671B 总参 / 37B 激活。训练成本仅约 **560 万美元**。

| 版本 | Aider Code Editing | Aider Polyglot | SWE-bench Verified (Agentless) |
|------|-------------------|----------------|-------------------------------|
| V3 原版 | -- | **65.4%** | ~24-27% |
| **V3-0324** | **72.9%** | **64.0%** | **~42.1%** |

**点评：**
- V3 在 Aider Polyglot 上曾超越 Claude 3.5 Sonnet，开源模型首次在实用编码 benchmark 领先闭源
- V3-0324 不改架构大幅提升编码能力，展示后训练优化潜力
- 编辑格式合规率 98.8%，指令遵循出色

### 2.3 DeepSeek-R1（2025 年 1 月）及 R1-0528

基于 V3 架构加 RL 推理训练，类似 OpenAI o1/o3。

| Benchmark | R1 | R1-0528 |
|-----------|-----|---------|
| Aider Code Editing | **72.4%** | -- |
| Aider Polyglot | **60.4%** | -- |
| LiveCodeBench | ~53-54% | **~65.9%** |
| SWE-bench Verified | -- | **~49.2%** |

**点评：**
- 首个与 OpenAI o1 正面对标的开源推理模型
- R1-0528 大幅提升编码和数学推理
- **主要短板**：格式合规率偏低（80.3-88.4%），推理模型输出格式控制不如标准模型

---

## 三、其他国产编程模型

### 3.1 Kimi K2（月之暗面，2025 年 7 月）— 最大黑马

**架构：** MoE，**1T 总参 / 32B 激活**，Muon 优化器，Apache 2.0 完全开源。

| Benchmark | 得分 |
|-----------|------|
| SWE-bench Verified | **~65.5%** |
| Aider Polyglot | **~65.4%** |

**点评：** 2025 年最大黑马。1T 开源模型在 SWE-bench 达 65.5%，超越大量闭源方案。证明国产开源模型可在严格软件工程 benchmark 上与闭源前沿竞争。对企业私有化部署意义重大。

### 3.2 Yi-Coder（零一万物）

Dense，1.5B / 9B，128K 上下文，52 种语言。Yi-Coder-9B-Chat HumanEval ~85.4%。10B 以下级别佼佼者，定位轻量级 IDE 集成。

### 3.3 CodeGeeX4（智谱 AI / 清华）

基于 GLM-4-9B，~9B Dense。HumanEval ~71-82%。功能整合型编码助手，但与 Qwen/DeepSeek 存在明显代差。

---

## 四、SWE-bench Verified 排行榜（截至 2025 年中）

| 排名 | 系统 | 解决率 | 备注 |
|------|------|--------|------|
| 1 | MindForge AI | **77.4%** | 多 Agent 系统 |
| 2 | OpenAI Codex | ~72-75% | 云端编程 Agent |
| 3 | OpenHands + Codex | ~72.0% | 开源 Agent + OpenAI |
| 4 | DORA (Google) | ~71.7% | |
| 5 | Aide by Weco AI | 71.2% | |
| 6 | OpenAI o3 (High) | 69.8% | |
| 7 | **Kimi K2** | **~65.5%** | **国产开源最高** |
| 8 | Turing SWE Agent | 65.0% | |
| 9 | Google Gemini | ~63.8% | |
| 10 | **DeepSeek-R1-0528** | **~49.2%** | 国产 #2 |
| -- | **DeepSeek-V3-0324** | **~42.1%** | Agentless 模式 |

> SWE-bench 成绩高度依赖 Agent 脚手架（scaffolding），同一模型在不同框架下表现可能差异巨大。

---

## 五、Aider 排行榜综合对比（截至 2025 年 5 月）

### Code Editing（核心编辑能力）

| 模型 | 得分 | 归属 |
|------|------|------|
| **Claude Sonnet 4** | **84.2%** | Anthropic |
| o4-mini | 83.6% | OpenAI |
| Gemini 2.5 Pro | 81.3% | Google |
| Claude Sonnet 4 (Think) | 79.6% | Anthropic |
| Gemini 2.5 Flash | 79.6% | Google |
| o3 | 79.1% | OpenAI |
| **Qwen3-235B (Think)** | **72.9%** | 阿里 |
| **DeepSeek V3-0324** | **72.9%** | 深度求索 |
| **DeepSeek R1** | **72.4%** | 深度求索 |
| **Qwen3-30B-A3B (Think)** | **71.1%** | 阿里 |

### Polyglot（多语言实战，更难）

| 模型 | 得分 (pass@2) | 归属 |
|------|--------------|------|
| **Claude Sonnet 4** | **78.4%** | Anthropic |
| o4-mini | 72.4% | OpenAI |
| Gemini 2.5 Pro | 72.0% | Google |
| Claude Sonnet 4 (Think) | 71.1% | Anthropic |
| Gemini 2.5 Flash | 65.8% | Google |
| **DeepSeek V3-0324** | **64.0%** | 深度求索 |
| **Qwen3-235B (Think)** | **60.4%** | 阿里 |
| **DeepSeek R1** | **60.4%** | 深度求索 |

---

## 六、SWE-CI 论文

**SWE-CI: Evaluating AI Coding Agents in Continuous Integration Scenarios** (arXiv:2507.05285, 2025.07)

305 个任务，18 个 Java 开源仓库的真实 CI 失败场景。比 SWE-bench 更贴近真实 DevOps：修复 CI pipeline 失败而非 GitHub Issue，涉及构建系统导航、CI 日志解读、多文件 patch。

**课程教学价值：** 说明"编码 Agent 在真实 DevOps 流程中离成熟还有多远"。即使最强 Agent 也只能修复少量 CI 失败。

---

## 七、综合对比总结

| 模型 | 架构 | 总参/激活 | HumanEval | LiveCodeBench | Aider Edit | Aider Polyglot | SWE-bench |
|------|------|----------|-----------|---------------|------------|----------------|-----------|
| Qwen3-235B | MoE | 235B/22B | ~92% | **~70.7%** | 72.9% | 60.4% | -- |
| Qwen3-30B-A3B | MoE | 30B/3B | -- | -- | 71.1% | -- | -- |
| Qwen2.5-Coder-32B | Dense | 32B | **92.7%** | 34.3% | -- | 44.7% | -- |
| DeepSeek-V3-0324 | MoE | 671B/37B | -- | ~65.5% | 72.9% | 64.0% | ~42.1% |
| DeepSeek-R1-0528 | MoE | 671B/37B | -- | ~65.9% | -- | -- | ~49.2% |
| **Kimi K2** | MoE | 1T/32B | -- | -- | -- | ~65.4% | **~65.5%** |
| Yi-Coder-9B | Dense | 9B | ~85.4% | -- | -- | -- | -- |
| Claude Sonnet 4 | -- | -- | -- | -- | **84.2%** | **78.4%** | -- |
| o4-mini | -- | -- | -- | -- | 83.6% | 72.4% | -- |

---

## 八、核心结论

1. **国产模型已进入世界一流，但差距可见**：Aider 差 ~11 点，Polyglot 差 ~14 点，SWE-bench 差 ~12 点

2. **MoE 是主流路线**：Qwen3、DeepSeek、Kimi K2 均采用 MoE，算力限制下的务实选择

3. **Think 模式有明确帮助但非万能**：Qwen3 开启 Think +10%，但格式合规率下降

4. **格式合规率是 Agent 场景的隐藏杀手**：国产 81-89% vs Claude 97-99%，可能比 benchmark 分数更重要

5. **开源模型在 Agent 场景的价值正在被验证**：Kimi K2 开源 + SWE-bench 65.5%，可作 Agent 底座

---

*数据来源：Aider LLM Leaderboards, SWE-bench Verified Official, Qwen Blog, DeepSeek 技术报告, Composio SWE-bench Rankings*
