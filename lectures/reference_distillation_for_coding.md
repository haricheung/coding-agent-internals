# 蒸馏路线做编码大模型的可行性分析

> 课程参考材料 — 面向高级研发工程师

---

## 一、为什么关注蒸馏？

从零预训练编码大模型的成本在数百万到数千万美元量级，对绝大多数团队不现实。蒸馏提供了"站在巨人肩膀上"的路径：从强模型输出中学习，用远低于预训练的成本获得接近的能力。

2025 年 DeepSeek-R1 的蒸馏实验是这条路线最有说服力的证据。

---

## 二、关键论文与项目

### 2.1 DeepSeek-R1 蒸馏（2025.01）— 最重要参考

**论文：** DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning (arXiv:2501.12948)

**做法：** 从 DeepSeek-R1（671B MoE）生成约 **80 万条高质量样本**（数学、代码、科学、逻辑），质量过滤后 SFT 蒸馏到 Qwen2.5 和 Llama3 系列。

| 模型 | HumanEval | LiveCodeBench | Codeforces Elo |
|------|-----------|---------------|----------------|
| DeepSeek-R1 (671B) | ~92% | 65.9% | 2,029 (96.3%) |
| Distill-Qwen-32B | ~90.2% | ~57.2% | ~1,691 |
| Distill-Qwen-14B | ~86.6% | ~53.1% | -- |
| Distill-Qwen-7B | ~79.9% | ~37.6% | -- |
| Distill-Llama-70B | ~90%+ | ~57%+ | -- |
| Distill-Llama-8B | ~80%+ | ~39%+ | -- |
| OpenAI o1-mini (对比) | ~92% | ~53.8% | 1,820 (93.4%) |

**最关键发现：小模型上纯蒸馏 > 纯 RL。** Distill-Qwen-32B 在多个基准上超过 o1-mini。蒸馏+RL 组合可进一步提升。

### 2.2 WizardCoder / Evol-Instruct（微软，2023-2024）

用 Evol-Instruct 让 GPT-4 迭代进化编码问题，再微调 StarCoder/Code Llama。WizardCoder-33B-V1.1 HumanEval 79.9%，一度超越 GPT-3.5-turbo。证明**数据质量 > 数据数量**。

### 2.3 Qwen2.5-Coder（阿里，2024）

5.5 万亿 token 代码预训练，多阶段流水线（通用预训练 → 代码继续预训练 → 指令微调）。小模型利用大模型蒸馏。Qwen2.5-Coder-1.5B 超过许多更大模型，是当前蒸馏实验最合适的 base model 之一。

### 2.4 OpenCoder（2024 末）

1.5B / 8B，完全公开训练数据、处理流水线、训练协议。为可复现的代码 LLM 训练树立标杆，可作蒸馏实验 baseline 对照。

### 2.5 StarCoder2（BigCode / HuggingFace / NVIDIA，2024）

3B / 7B / 15B，The Stack v2（619 种语言，4T+ tokens），15B 约 72,000 A100 GPU 小时。OpenRAIL-M 许可。

---

## 三、轨迹蒸馏 — 编码智能体最核心的方向

### 3.1 为什么必须是轨迹蒸馏？

传统蒸馏关注"给定输入，模仿 teacher 输出"。轨迹蒸馏捕获**完整 agent 行为序列**：

```
思考 → 工具调用 → 观察结果 → 下一步决策 → ... → 最终结果
```

编码不是单步任务。要做真正的编码智能体而不是代码补全器，必须做轨迹级蒸馏。

### 3.2 关键论文

**FireAct (Chen et al., Princeton, 2023)**
- 用 GPT-4 生成 ReAct/CoT/Reflexion 三种推理轨迹，过滤成功样本，微调 Llama-2-13B
- 核心发现：
  - 微调后 Llama-2-13B 匹敌甚至超过 GPT-3.5 prompting
  - **多方法混合轨迹** > 单一方法
  - 模型学会"何时用工具、何时直接回答"
  - **几百条轨迹就能显著提升性能**（sample efficiency 极高）

**Agent LUMOS (AI2, ACL 2024)**
- 将 agent 任务分解为 Planning / Grounding / Execution 三模块
- 统一数据格式：不同来源轨迹转统一格式训练
- LLaMA-2-7B 达到与 GPT-4 agent 竞争水平
- **启示：模块化设计 + 统一轨迹格式是小模型 agent 蒸馏的有效策略**

**AgentTrek（2025）**
- 通过引导重放 Web 教程合成 agent 轨迹，方法论可迁移至编码 agent

### 3.3 轨迹格式对比

| 格式 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| 完整轨迹 | 保留中间推理，信号最丰富 | 可能传播错误步骤 | 中 |
| 仅结果 | 简洁，只保留成功案例 | 丢失中间推理过程 | 低 |
| **过滤轨迹** | **兼顾质量和信号丰富度** | 需额外过滤管道 | **最推荐** |
| 模块化轨迹 | 独立训练规划/执行，便于调试 | 设计更复杂 | 中高 |

### 3.4 开源轨迹数据集

- **OpenHands SWE-bench 轨迹**：`xingyaoww/openhands-swe-bench-trajectories` (HuggingFace)
- **SWE-bench / Verified / Lite**：`princeton-nlp/SWE-bench`
- **Agentless / AutoCodeRover / Moatless Tools** 均有轨迹数据发布

### 3.5 工具使用能力能否蒸馏？

| 能力层次 | 蒸馏效果 | 备注 |
|---------|---------|------|
| 代码生成 | 好（teacher 的 85-95%） | 最容易迁移 |
| 工具调用 / API 选择 | 可以 | 需足够多样的工具使用样本 |
| 多步 agent 行为 | **难度最大** | 7B 与 frontier 仍有明显差距 |

**关键瓶颈：** 小模型上下文理解和长程规划有限，训练分布外泛化不足。

---

## 四、蒸馏 vs SFT vs RL 对比

### 4.1 定量对比（基于 DeepSeek-R1 论文）

| 维度 | 蒸馏 (KD) | SFT | RL (GRPO/PPO) | 蒸馏 + RL |
|------|----------|-----|--------------|----------|
| 数据需求 | 中 (10K-800K) | 高 | 低（只需 reward） | 中 |
| 训练稳定性 | 高 | 高 | 低 | 中 |
| 上限 | 受 teacher 约束 | 受数据约束 | 可超越 teacher | **最高** |
| 代码编写 | 好 | 好 | 很好 | 最好 |
| Agent 行为 | 中等 | 取决于数据 | 好 | 最好 |
| 成本 | 中低 | 中 | 高 | 最高 |
| **小模型效果** | **最佳** | 中 | 差（不稳定） | 好 |

### 4.2 蒸馏何时有效 / 失效？

**有效：**
- student >= 7B，足以表达 teacher 知识
- 任务在训练分布内（标准代码补全、常见 bug 修复）
- teacher 数据质量高、多样性好
- 有明确模式需要学习（如 ReAct 格式工具调用）

**失效：**
- 需要超越 teacher（蒸馏有天花板）
- 长程推理和复杂规划（大型仓库级 bug 修复）
- student 太小（1.5B 在 agent 任务上能力不足）
- 训练数据过于单一
- 未见过的编程语言或框架

### 4.3 数据量需求

| 任务类型 | 所需样本量 |
|---------|----------|
| 代码补全/生成 | 10K-50K |
| 推理增强（CoT 蒸馏） | 50K-200K |
| Agent 轨迹蒸馏 | 1K-10K 条轨迹 |
| 工具使用 | 5K-20K 条含工具调用 |

---

## 五、四种路线全面对比

| 维度 | 从零预训练 | 继续预训练+SFT | 纯蒸馏 | 轨迹 SFT |
|------|----------|--------------|-------|---------|
| **成本 (7B)** | $500K-$2M | $50K-$200K | $5K-$50K | **$2K-$20K** |
| **GPU 需求** | 数百张 A100，数月 | 8-32 张，数周 | 1-4 张，数天 | **1-2 张，数小时~天** |
| **数据需求** | 万亿 token | 千亿 token | 10K-800K 样本 | **100-10K 轨迹** |
| **HumanEval** | 取决于规模 | 7B ~70-80% | 7B ~80% | 取决于 base+轨迹 |
| **SWE-bench** | -- | 低 | 低 | **最适合** |
| **Agent 能力** | 无 | 无 | 弱 | **强** |
| **工具使用** | 无 | 无 | 可教会 | **原生支持** |
| **技术门槛** | 极高 | 高 | 中 | **中低** |
| **天花板** | 理论最高 | 受 base 限制 | 受 teacher 限制 | 受 teacher+base 限制 |
| **适合谁** | 大公司 | 中型团队 | 小团队 | **高级工程师/小团队** |
| **训练周期** | 3-12 个月 | 2-8 周 | 1-7 天 | **数小时~天** |

---

## 六、实操考量

### 6.1 硬件需求与成本（QLoRA 微调，最经济路线）

| 模型规模 | GPU 显存 | 推荐硬件 | 典型训练成本 |
|---------|--------|---------|------------|
| 7B (LoRA) | 16-24 GB | 1x A100 40GB | **$2-5** |
| 7B (全参数) | 60-80 GB | 2-4x A100 80GB | $50-200 |
| 14B (LoRA) | 24-40 GB | 1x A100 80GB | $5-15 |
| 32B (LoRA) | 40-80 GB | 1-2x A100 80GB | $15-50 |
| 32B (全参数) | 200+ GB | 8x A100 80GB | $500-2000 |

> QLoRA（4-bit 量化 + LoRA）可以把 7B 训练放到单张 RTX 4090 (24GB) 上。

### 6.2 数据许可合规（红线）

| 数据来源 | 许可状态 | 可否蒸馏 |
|---------|---------|---------|
| OpenAI (GPT-4/o1) | ToS 禁止训练竞争模型 | **不可以** |
| Anthropic (Claude) | 使用政策限制 | **不可以** |
| Google (Gemini) | 类似限制 | **不可以** |
| **DeepSeek-R1** | **MIT 许可** | **可以** |
| **Llama 3.1 (Meta)** | 社区许可证，鼓励蒸馏 | **可以** |
| **Qwen 系列** | **Apache 2.0** | **可以** |
| StarCoder2 | OpenRAIL-M | **可以** |

> 2025 年起 AI 公司开始部署水印和指纹技术检测蒸馏行为。

### 6.3 蒸馏 vs API 调用：何时值得？

| 场景 | 蒸馏成本 | 月度 API | 盈亏平衡 |
|------|--------|---------|---------|
| 个人/小团队 | $50-500 一次性 | $50-200/月 | 1-3 个月 |
| 中型团队 | $500-5000 一次性 | $2K-20K/月 | 1 个月内 |
| 离线/隐私部署 | $500-5000 一次性 | 不可用 | 立即 |

---

## 七、2025-2026 年重要进展

1. **DeepSeek-R1 蒸馏的里程碑意义**：首次大规模证明蒸馏在小模型上优于 RL。800K 样本 SFT "菜谱"已被广泛复制。

2. **RLCEF 的兴起**：代码执行反馈作为 RL 奖励信号，比 RLHF 更客观。趋势是蒸馏 SFT 作 warm-up，再用 RLCEF 优化。

3. **混合流水线成为主流**：SFT (warm-up) → 蒸馏 (teacher knowledge) → RL (push frontier)

4. **开源生态爆发**：HuggingFace agent 轨迹数据集快速增长；SmolAgents、OpenHands 支持小模型 agent；TRL、LLaMA-Factory、Axolotl 支持 LoRA + 蒸馏。

---

## 八、推荐蒸馏实操路线

### 第一层：快速验证（1-2 天，< $10）

1. Base: Qwen2.5-Coder-7B-Instruct
2. 收集 50-100 条编码 agent 轨迹（OpenHands 开源数据或自行用开源强模型生成）
3. QLoRA (4-bit) 单张 A100 微调
4. 评估：对比微调前后简单工具调用任务表现

### 第二层：Agent 行为蒸馏（3-5 天，$50-200）

1. Base: Qwen2.5-Coder-14B 或 32B
2. 从 DeepSeek-R1 或 Qwen-72B 生成 1K-5K 条 team mode 轨迹
3. 格式：过滤后完整轨迹，含 Agent spawn 时机、SendMessage、多阶段编排
4. 全参数或 LoRA rank=64+
5. 评估：自定义 team mode benchmark

### 第三层：蒸馏 + RL（进阶，$500+）

1. 第二层基础上，GRPO/PPO + 代码执行反馈
2. 需搭建代码执行沙箱
3. 可能突破蒸馏天花板

### 轨迹数据格式建议

```
[System] You are a coding agent with tools: Read, Edit, Bash, Agent...
[User] Fix the bug in authentication module...
[Assistant] <thinking>分析问题...</thinking>
[Tool Call] Read(file="auth.py")
[Tool Result] ...file contents...
[Assistant] <thinking>发现问题在第42行...</thinking>
[Tool Call] Agent(task="Write unit test for auth fix", tools=["Read","Edit","Bash"])
...subagent trajectory...
[Tool Call] Edit(file="auth.py", old="...", new="...")
[Tool Call] Bash(command="pytest tests/test_auth.py")
[Tool Result] All tests passed
[Assistant] Bug fixed. The issue was...
```

---

## 九、核心结论

1. **蒸馏可行**，且是小团队构建编码 agent 最现实的路径
2. **必须做轨迹蒸馏**，不是问答蒸馏 — 代码补全能力可预训练获得，agent 行为必须通过轨迹学习
3. **推荐路线**：Qwen2.5-Coder 7B/14B + 开源轨迹 + QLoRA，成本 < $10
4. **合规红线**：不能用 Claude/GPT 输出做商用蒸馏。DeepSeek-R1 (MIT) 和 Qwen (Apache 2.0) 安全
5. **蒸馏不是终点**：最强方案是"蒸馏 SFT + RL"混合流水线，但纯蒸馏 SFT 足以展示核心概念

**一句话：** 80 万条样本 SFT 就能让 32B 模型超越 o1-mini（DeepSeek-R1 已证明），但要做编码智能体而不是补全器，必须做轨迹级蒸馏。

---

*核心参考：DeepSeek-R1 技术报告 (arXiv:2501.12948), FireAct (Chen et al., 2023), Agent LUMOS (ACL 2024), Qwen2.5-Coder 技术报告*
