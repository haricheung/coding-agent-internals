# 模块 10：真实世界工作流与工程落地

## 模块概述

> **核心问题：如何在真实团队和项目中落地 AI 编程代理？**

模块 7 展示了 Agent 驱动的 Bug 修复、功能开发和代码审查的基本场景。但从"个人在终端里用 Agent"到"团队级的生产力工具"，中间还有大量工程问题需要解决——CI/CD 集成、安全合规、成本控制、团队协作规范。

本模块聚焦这些**工程落地**问题。

| 主题 | 核心问题 | 你将学到 |
|------|---------|---------|
| 独立开发者工作流 | 日常开发的完整 Agent 化流程 | Issue→PR 全链路、Session 节奏、无头模式 |
| 团队集成 | 如何让 Agent 融入团队 CI/CD | GitHub Actions 集成、自动化 PR 审查、质量门禁 |
| Monorepo 策略 | 超大代码库怎么用 Agent | 多包依赖分析、跨团队治理、工作区感知 |
| 使用边界 | 组织层面的反模式 | 过度依赖风险、技能退化、组织反模式 |
| 安全与合规 | 企业环境的信任边界 | 数据流分析、SOC2/GDPR、离线部署、审计 |
| 成本控制 | 怎么用得起 Agent | Token 经济学、成本建模、模型路由、缓存 |

> **与模块 7 的关系**：模块 7 覆盖了 Agent 的基本使用场景和工具操作。本模块在此基础上，聚焦**规模化部署**的工程挑战——从"一个人用得好"到"一个团队用得好"。

---

## 10.1 独立开发者工作流

> 模块 7 已经展示了 Bug 修复、功能开发、代码审查的单个场景。本节关注这些场景如何串联成一个完整的日常工作流。

### 从 Issue 到 Merged PR：全链路 Agent 化

一个典型的独立开发者日常，Agent 可以参与每一个环节：

```
┌──────────────────────────────────────────────────────────┐
│                    开发者日常工作流                         │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│  阅读    │  分析    │  实现    │  测试    │  提交        │
│  Issue   │  代码库  │  功能    │  验证    │  PR          │
├──────────┼──────────┼──────────┼──────────┼──────────────┤
│ gh issue │ Agent    │ Agent    │ Agent    │ Agent        │
│ view     │ 探索     │ 编码    │ 运行    │ 生成 PR      │
│          │ 代码库   │ + 编辑  │ 测试    │ 描述 + 推送  │
└──────────┴──────────┴──────────┴──────────┴──────────────┘
     ↑                                           │
     │         人类：审查 + 决策 + 纠偏            │
     └────────────────────────────────────────────┘
```

**实战示例：从 GitHub Issue 到 Merged PR**

```bash
# 第一步：用 Agent 直接处理 Issue
claude "查看 GitHub Issue #42 的内容，分析问题原因，
       给出修复方案（先不要动手改）。"

# Agent 执行:
# → gh issue view 42
# → 分析错误描述和复现步骤
# → Glob + Grep 定位相关代码
# → 输出分析报告和修复方案

# 第二步：确认方案后让 Agent 实现
claude "方案 B 更好。请按照方案 B 实现修复。
       创建新分支 fix/issue-42，修复后跑测试。"

# Agent 执行:
# → git checkout -b fix/issue-42
# → 编辑代码
# → 运行测试
# → git add + commit

# 第三步：让 Agent 创建 PR
claude "为这个修复创建 PR。引用 Issue #42。
       PR 描述要包含：问题原因、修复方案、测试说明。"

# Agent 执行:
# → gh pr create --title "fix: ..." --body "..."
# → 输出 PR URL
```

### 开发者的 Session 节奏

高效使用 Agent 需要建立合理的"Session 节奏"——什么时候开新会话、什么时候在同一会话中继续：

```
推荐的 Session 节奏:

Session 1 (早晨): 代码审查 + Bug 分诊
  → 审查昨晚的 PR
  → 分析新增的 Bug 报告
  → 确定今天的工作优先级
  ⏱ 典型时长: 30-60 分钟

Session 2 (上午): 功能实现 A
  → 聚焦一个功能的完整实现
  → 从分析到编码到测试
  ⏱ 典型时长: 1-2 小时

--- /compact 或 新 Session ---

Session 3 (下午): 功能实现 B 或 Bug 修复
  → 切换到不同的任务
  → 新 Session 避免上下文污染
  ⏱ 典型时长: 1-2 小时

Session 4 (收尾): 提交 + PR + 文档
  → 整理当天的变更
  → 创建/更新 PR
  → 补充文档
  ⏱ 典型时长: 30 分钟
```

**关键原则**：**一个 Session 聚焦一个主题**。当切换到不相关的任务时，开新 Session 比在旧 Session 中继续更好——避免上下文窗口被无关信息占据。

### 无头模式（Headless Mode）

Claude Code 支持非交互式的无头模式，适合自动化场景：

```bash
# 非交互式执行单个任务
claude -p "修复 src/api/users.ts 中的类型错误并运行测试" \
       --allowedTools "Read,Edit,Bash(npm test)"

# 从文件读取提示词
claude -p "$(cat task-description.md)" \
       --output-format json

# 管道式使用
gh issue view 42 --json body -q .body | \
  claude -p "分析这个 Issue 并给出修复建议，不要修改文件"
```

**无头模式的应用场景**：

| 场景 | 命令示例 |
|------|---------|
| CI 中的自动修复 | `claude -p "修复 lint 错误" --allowedTools "Read,Edit"` |
| 批量代码审查 | `for pr in $(gh pr list -q .number); do claude -p "审查 PR #$pr"; done` |
| 自动生成 changelog | `claude -p "基于最近 10 个 commit 生成 changelog"` |
| Issue 自动分诊 | `claude -p "分析 Issue 的严重程度和影响范围"` |

### Session 链接：跨会话的复杂任务

对于跨越多天的大型任务，通过 Session 链接保持连续性：

```bash
# 第一天：分析和计划
claude --session "refactor-auth"
> "分析认证模块的现状，制定重构计划"
# 输出计划，保存到 CLAUDE.md 的"当前进度"区块

# 第二天：继续实现
claude --resume
> "继续认证模块重构，接着完成计划中的第 3-4 步"
# Agent 可以看到之前的对话历史

# 或者使用新 Session + 手动上下文注入
claude
> "我在重构认证模块。进度见 CLAUDE.md '当前进度'部分。
>  今天请完成第 3-4 步。"
```

---

## 10.2 团队集成

### GitHub Actions 集成

将 Agent 集成到 CI/CD 流程中，实现自动化的代码质量保障。

**场景 1：PR 自动审查**

```yaml
# .github/workflows/agent-review.yml
name: Agent Code Review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  agent-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # 获取完整历史以便 diff

      - name: Install Claude Code
        run: npm install -g @anthropic-ai/claude-code

      - name: Get PR diff
        id: diff
        run: |
          echo "diff<<EOF" >> $GITHUB_OUTPUT
          gh pr diff ${{ github.event.pull_request.number }} >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Agent Review
        run: |
          claude -p "$(cat <<'PROMPT'
          审查以下 PR 的代码变更。检查：
          1. 逻辑正确性
          2. 潜在的安全问题
          3. 性能影响
          4. 测试覆盖
          只输出发现的问题，格式为：
          - [严重程度] 文件:行号 — 问题描述
          如果没有问题，输出"LGTM"。
          PROMPT
          )" --output-format json > review.json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Post Review Comment
        run: |
          REVIEW=$(cat review.json | jq -r '.result')
          gh pr comment ${{ github.event.pull_request.number }} \
            --body "## 🤖 Agent Code Review

          $REVIEW

          ---
          *Automated review by Claude Code*"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**场景 2：自动修复 Lint 错误**

```yaml
# .github/workflows/agent-autofix.yml
name: Agent Auto-fix
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  autofix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
          token: ${{ secrets.PAT_TOKEN }}  # 需要 push 权限

      - name: Run Lint
        id: lint
        run: |
          npm ci
          npm run lint 2>&1 | tee lint-output.txt || true

      - name: Check for errors
        id: check
        run: |
          if grep -q "error" lint-output.txt; then
            echo "has_errors=true" >> $GITHUB_OUTPUT
          fi

      - name: Agent Fix
        if: steps.check.outputs.has_errors == 'true'
        run: |
          npm install -g @anthropic-ai/claude-code
          claude -p "修复以下 lint 错误。只修改有错误的文件，
                     不要做额外的重构。
                     $(cat lint-output.txt)" \
                 --allowedTools "Read,Edit"
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Commit fixes
        if: steps.check.outputs.has_errors == 'true'
        run: |
          git config user.name "claude-bot"
          git config user.email "claude-bot@noreply.github.com"
          git add -A
          git diff --staged --quiet || \
            git commit -m "fix: auto-fix lint errors [claude-bot]"
          git push
```

**场景 3：质量门禁（Quality Gate）**

```yaml
# .github/workflows/quality-gate.yml
name: Quality Gate
on:
  pull_request:
    types: [opened, synchronize, ready_for_review]

jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Complexity Analysis
        run: |
          npm install -g @anthropic-ai/claude-code

          # 获取变更文件
          CHANGED_FILES=$(gh pr diff ${{ github.event.pull_request.number }} \
            --name-only | grep -E '\.(ts|tsx|js|jsx)$' | head -20)

          claude -p "$(cat <<PROMPT
          分析以下变更文件的代码质量：
          $CHANGED_FILES

          评估维度（每项 1-5 分）：
          1. 可读性：命名、结构、注释
          2. 可维护性：耦合度、单一职责
          3. 测试覆盖：是否有对应测试
          4. 安全性：输入校验、注入风险

          输出 JSON 格式：
          { "scores": {...}, "total": N, "pass": true/false, "issues": [...] }
          总分 >= 12 为 pass。
          PROMPT
          )" --output-format json > quality.json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Check Quality Gate
        run: |
          PASS=$(cat quality.json | jq -r '.result' | jq -r '.pass')
          if [ "$PASS" != "true" ]; then
            echo "Quality gate failed"
            exit 1
          fi
```

### GitLab CI 集成

GitLab 环境下的类似配置：

```yaml
# .gitlab-ci.yml
agent-review:
  stage: review
  image: node:20
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - npm install -g @anthropic-ai/claude-code
    - |
      DIFF=$(git diff $CI_MERGE_REQUEST_DIFF_BASE_SHA...$CI_COMMIT_SHA)
      claude -p "审查以下代码变更：$DIFF" \
             --output-format json > review.json
    - |
      # 通过 GitLab API 发布评论
      REVIEW=$(cat review.json | jq -r '.result')
      curl --request POST \
        --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        --data-urlencode "body=$REVIEW" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

### 团队级 CLAUDE.md 治理

当团队多人使用 Agent 时，CLAUDE.md 需要统一管理：

```
团队 CLAUDE.md 治理模型:

1. CLAUDE.md 纳入代码审查
   → 修改 CLAUDE.md 和修改生产代码一样需要 PR + Review
   → 避免个别成员添加与团队规范冲突的规则

2. 定期审计
   → 每月检查 CLAUDE.md 是否与项目实际情况一致
   → 移除过时的规则（如已删除的目录路径）
   → 补充新的约定（如新增的 CI 流程）

3. 分层管理
   项目根目录/CLAUDE.md         ← Tech Lead 维护（团队共识）
   packages/api/CLAUDE.md       ← 后端 TL 维护（模块规范）
   packages/web/CLAUDE.md       ← 前端 TL 维护（模块规范）
   ~/.claude/CLAUDE.md          ← 个人偏好（不影响团队）
```

---

## 10.3 Monorepo 与大型代码库策略

> 模块 7 已经介绍了 CLAUDE.md 架构地图、Glob+Grep 定向搜索、分层感知和 .claudeignore 四种基本策略。本节在此基础上深入 Monorepo 特有的挑战。

### 多包依赖分析

Monorepo 中最常见的 Agent 陷阱：修改了 Package A，却不知道会影响依赖它的 Package B、C、D。

```
典型的 Monorepo 依赖图:

packages/shared          ← 被所有包引用
  │
  ├── packages/api       ← 后端服务
  │     │
  │     └── packages/admin  ← 管理后台（依赖 API 的类型）
  │
  ├── packages/web       ← 前端应用
  │
  └── packages/mobile    ← 移动端应用

风险: 修改 shared 中的一个类型定义 →
      所有下游包可能编译失败
```

**在 CLAUDE.md 中表达依赖关系**：

```markdown
# CLAUDE.md

## 包依赖关系（修改时注意影响范围）
- packages/shared → 被 api, web, mobile, admin 引用
  ⚠️ 修改 shared 中的导出类型后，必须检查所有下游包的编译
- packages/api → 被 admin 引用（类型定义）
  修改 API 路由后，检查 admin 中对应的 API 调用
- packages/web 和 packages/mobile 互不依赖

## 跨包修改的检查命令
修改 packages/shared 后运行: pnpm --filter "...{packages/shared}" build
修改 packages/api 后运行: pnpm --filter "...{packages/api}" test
```

### 工作区感知的 Agent 策略

```
大型 Monorepo 中的 Agent 使用策略:

策略 1: 限定工作区
────────────────
> "这个任务只涉及 packages/web。
>  不要搜索或修改其他 package 的代码。
>  如果需要修改 shared 中的类型，先告诉我。"

策略 2: Agent Teams 分工
────────────────────────
Agent A (worktree) → 修改 packages/api
Agent B (worktree) → 修改 packages/web
Agent C (主分支)   → 修改 packages/shared（需要协调）

策略 3: 分层修改
────────────────
Session 1: 修改 shared 中的类型定义（基础层）
           → 运行 pnpm build 确认所有包编译通过
Session 2: 基于新类型修改 api（应用层）
           → 运行 pnpm --filter api test
Session 3: 修改 web 前端（消费层）
           → 运行 pnpm --filter web test
```

### 超大代码库的搜索优化

当代码库超过 50 万行时，搜索效率成为瓶颈：

```
搜索优化策略:

1. 分区搜索（缩小搜索范围）
   ❌ Grep("handleAuth")                    ← 搜索整个代码库
   ✓  Grep("handleAuth", path="src/auth/")  ← 限定目录

2. 类型过滤（减少噪声）
   ❌ Glob("**/*user*")                      ← 包含测试、文档、配置
   ✓  Glob("src/**/*user*.ts")              ← 只看源代码

3. .claudeignore 排除
   排除: dist/, node_modules/, .next/, coverage/,
         *.generated.ts, *.d.ts（除非专门处理类型）

4. 入口文件策略
   不要让 Agent 自己找入口——在任务中直接给出:
   > "从 packages/api/src/routes/index.ts 开始，
   >  追踪 /api/users 路由的完整调用链。"
```

---

## 10.4 何时"不"该用智能体

> 模块 7 讨论了 Agent 在技术层面的局限性（创造性设计、性能优化、安全代码、并发逻辑）。本节聚焦**组织层面**的反模式。

### 组织反模式

**反模式 1：Agent 作为"万能工具"**

```
症状: 团队把所有编程任务都丢给 Agent，包括不适合的任务
后果:
  - 低质量代码逐渐积累
  - 团队对代码库的理解能力下降
  - 技术债务隐性增长

根因: 管理层把 Agent 等同于"自动编程机"，忽略了人类
      判断在软件工程中的不可替代性
```

**反模式 2：跳过 Code Review**

```
症状: "反正是 Agent 写的，肯定没问题"
后果:
  - Agent 的细微错误（边界条件、竞态条件）无人发现
  - 代码库中出现风格不一致的"Agent 味"代码
  - 安全漏洞无人捕获

修正: Agent 生成的代码必须和人类代码一样经过 Review
```

**反模式 3：过度依赖导致技能退化**

```
症状: 工程师逐渐忘记底层实现细节
      "我不知道认证怎么工作的，每次都是 Agent 写的"
后果:
  - 无法在 Agent 出错时纠正
  - 技术面试能力下降（如果这对你重要的话）
  - 系统出现问题时缺乏 debug 能力

修正:
  - 定期进行"无 Agent 编码"练习
  - 要求工程师能解释 Agent 生成的每一行代码
  - 关键系统的代码由人类手写，Agent 辅助
```

### 健康的 Agent 使用文化

```
健康的使用模式:
├── Agent 做探索 — 快速理解不熟悉的代码库
├── Agent 做模板 — 生成重复性的样板代码
├── Agent 做检查 — 审查代码、发现潜在问题
├── 人类做决策 — 架构选择、技术方案、权衡取舍
├── 人类做审查 — 所有 Agent 输出必须经人类审查
└── 人类做关键路径 — 安全、支付、核心业务逻辑

一句话总结: Agent 是"高级实习生"，不是"高级工程师"。
你可以让它快速完成 80% 的工作，
但最终的质量控制和决策权在你手里。
```

---

## 10.5 安全、隐私与企业级考量

### 数据流分析

使用 AI 编程代理时，代码数据会经过以下路径：

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ 本地代码库    │────▶│ Agent 进程    │────▶│ LLM API      │
│             │     │ (本地)        │     │ (云端)        │
│ 源代码       │     │              │     │              │
│ 配置文件     │     │ 发送:         │     │ 处理:         │
│ 环境变量     │     │ · 文件内容    │     │ · 推理        │
│ 测试数据     │     │ · 搜索结果    │     │ · 生成响应    │
│             │     │ · 命令输出    │     │              │
└─────────────┘     └──────────────┘     └──────────────┘
                                               │
                    发送了什么？              │ 保留了什么？
                    ─────────               ─────────────
                    · Read 读取的文件内容      · Anthropic: 不训练
                    · Grep 的搜索结果          · OpenAI: 可选退出
                    · Bash 的命令输出          · 本地模型: 不出网
                    · 对话历史
```

**关键问题**：当 Agent 执行 `Read("config/database.yml")` 或 `Bash("env | grep API")` 时，这些内容会被发送到云端 API。

### 敏感信息防护

**策略 1：.claudeignore 排除敏感文件**

```
# .claudeignore
.env
.env.*
config/secrets/
credentials.json
*.pem
*.key
id_rsa*
```

**策略 2：环境变量间接引用**

```markdown
# CLAUDE.md
## 安全规则
- 不要直接读取 .env 文件
- 需要知道环境变量名时，参考 .env.example
- 不要在代码中硬编码 API Key、密码、Token
- 不要执行 `env | grep` 或 `printenv` 命令
```

**策略 3：Hooks 实现安全网关**

```json
// .claude/settings.json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "python3 scripts/check-sensitive.py $CLAUDE_FILE_PATH"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 scripts/check-command.py \"$CLAUDE_COMMAND\""
          }
        ]
      }
    ]
  }
}
```

```python
# scripts/check-sensitive.py
import sys
import os

BLOCKED_PATTERNS = [
    '.env', 'credentials', 'secret', '.pem', '.key',
    'id_rsa', 'password', 'token'
]

file_path = sys.argv[1] if len(sys.argv) > 1 else ""
file_lower = file_path.lower()

for pattern in BLOCKED_PATTERNS:
    if pattern in file_lower:
        print(f"BLOCKED: 不允许读取敏感文件 {file_path}")
        sys.exit(1)

sys.exit(0)
```

### 企业合规要求

**SOC 2 合规考量**：

| SOC 2 原则 | Agent 使用的影响 | 应对措施 |
|-----------|-----------------|---------|
| 安全性 | 代码数据传输到第三方 API | TLS 加密、API Key 轮换、访问控制 |
| 可用性 | 依赖外部 API 的可用性 | 本地模型备用方案、限速处理 |
| 处理完整性 | Agent 可能引入错误代码 | Code Review 流程、自动化测试门禁 |
| 机密性 | 敏感数据可能发送到云端 | .claudeignore、Hooks 安全网关 |
| 隐私 | 用户数据可能在代码中出现 | 测试数据脱敏、禁止读取生产配置 |

**GDPR 注意事项**：

```
如果代码库中包含欧盟用户的个人数据（即使是测试数据），
通过 Agent 发送到美国的 API 服务器可能构成跨境数据传输。

应对措施:
1. 测试数据使用合成数据（faker），不使用真实用户数据
2. .claudeignore 排除包含真实数据的目录
3. 考虑使用本地模型处理涉及个人数据的代码
4. 与法务团队确认数据处理协议（DPA）
```

### API Key 管理

```
API Key 安全管理最佳实践:

1. 分离：每个环境使用不同的 Key
   ────────────────────────────
   开发环境: ANTHROPIC_API_KEY_DEV
   CI 环境:  ANTHROPIC_API_KEY_CI   (存入 GitHub Secrets)
   生产环境: 不部署 Agent

2. 轮换：定期更换 Key
   ────────────────────
   频率: 至少每 90 天
   流程: 生成新 Key → 更新所有引用 → 废弃旧 Key

3. 监控：跟踪 Key 的使用情况
   ────────────────────────
   Anthropic Console → Usage 页面
   设置用量告警阈值

4. 最小权限：CI 中的 Key 只授予必要权限
   ─────────────────────────────────────
   --allowedTools "Read,Grep,Glob"  ← 只读审查不需要写权限
```

### 审计日志

企业环境需要记录 Agent 的所有操作：

```bash
# 启用 Agent 操作日志
# Claude Code 的操作记录在 ~/.claude/projects/ 下的 session 文件中

# 自定义审计日志（通过 Hooks）
# .claude/settings.json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"timestamp\":\"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\",\"tool\":\"'$CLAUDE_TOOL_NAME'\",\"user\":\"'$USER'\"}' >> /var/log/agent-audit.jsonl"
          }
        ]
      }
    ]
  }
}
```

### 离线 / 私有部署方案

对于对数据安全有极高要求的场景：

```
方案 1: 本地模型（完全离线）
──────────────────────────
工具: OpenCode + Ollama
模型: deepseek-coder-v2、codellama、qwen-coder
优势: 数据完全不出内网
劣势: 模型能力显著低于 Claude/GPT-4o

方案 2: 私有云部署
──────────────────
工具: Claude API (AWS Bedrock / GCP Vertex AI)
优势: 数据在企业自己的云环境中处理
劣势: 需要企业级合同，成本较高

方案 3: 混合方案
────────────────
敏感代码 → 本地模型（Ollama）
非敏感代码 → 云端 API（Claude/GPT-4o）
判断依据: 文件路径 + .claudeignore 规则
```

---

## 10.6 成本控制

### Token 经济学

理解 AI 编程代理的成本结构：

```
单次 Agent 交互的 Token 消耗:

┌─────────────────────────────────────────┐
│ System Prompt + CLAUDE.md    ~3K tokens │
│ 用户输入                     ~500 tokens │
│ Grounding (Read/Grep)      ~5-30K tokens │  ← 主要消耗
│ Agent 思考 (extended think) ~2-10K tokens │
│ Agent 输出                 ~1-5K tokens  │
│ 工具调用开销               ~1-3K tokens  │
├─────────────────────────────────────────┤
│ 单次交互合计              ~12-50K tokens │
└─────────────────────────────────────────┘

一个典型的 Bug 修复 Session（10-15 轮）:
  → 消耗 ~150K-500K tokens
  → 按 Claude Sonnet 4 定价 ≈ $0.45-$1.50

一个复杂功能开发 Session（20-40 轮）:
  → 消耗 ~500K-2M tokens
  → 按 Claude Sonnet 4 定价 ≈ $1.50-$6.00
```

### 成本建模

为团队建立成本预测模型：

```python
# 团队 Agent 成本估算
def estimate_monthly_cost(
    team_size: int,
    sessions_per_day: float,         # 每人每天几个 Session
    avg_tokens_per_session: int,     # 每 Session 平均 Token
    model: str = "sonnet"
):
    pricing = {
        "opus":   {"input": 15.0, "output": 75.0},   # $/M tokens
        "sonnet": {"input": 3.0,  "output": 15.0},
        "haiku":  {"input": 0.80, "output": 4.0},
    }

    price = pricing[model]
    # 假设 input:output = 4:1（Agent 读取多、输出少）
    input_tokens = avg_tokens_per_session * 0.8
    output_tokens = avg_tokens_per_session * 0.2

    cost_per_session = (
        input_tokens * price["input"] / 1_000_000 +
        output_tokens * price["output"] / 1_000_000
    )

    working_days = 22
    monthly = team_size * sessions_per_day * cost_per_session * working_days
    return monthly

# 示例: 10 人团队，每人每天 5 个 Session，每 Session 200K tokens
print(estimate_monthly_cost(10, 5, 200_000, "sonnet"))
# → ~$528/月

print(estimate_monthly_cost(10, 5, 200_000, "opus"))
# → ~$2,640/月
```

### 模型路由策略

不是所有任务都需要最强的模型。智能路由可以大幅降低成本：

```
任务类型              推荐模型      成本比
──────────          ──────────   ──────
简单问答/解释         Haiku        1x
Lint 错误修复         Haiku        1x
模板代码生成          Sonnet       4x
Bug 修复             Sonnet       4x
复杂重构             Sonnet       4x
架构设计             Opus         19x
多文件协调修改        Opus         19x

路由策略:
┌──────────────────────────────────────┐
│                                      │
│  用户请求 ──→ 复杂度评估             │
│                  │                   │
│          ┌───────┼───────┐           │
│          ▼       ▼       ▼           │
│        简单    中等     复杂          │
│        Haiku  Sonnet   Opus          │
│                                      │
│  人工切换: /model sonnet             │
│  自动路由: Claude Code 内置降级策略   │
│                                      │
└──────────────────────────────────────┘
```

**实用的切换时机**：

```bash
# Claude Code 中手动切换模型
/model          # 查看当前模型
/model haiku    # 切换到 Haiku（快速/低成本任务）
/model sonnet   # 切换到 Sonnet（日常开发）
/model opus     # 切换到 Opus（复杂任务）

# 推荐的使用模式:
# 1. 默认用 Sonnet（性价比最优）
# 2. 探索代码库、简单修改 → 切 Haiku
# 3. 复杂架构分析、多文件重构 → 切 Opus
# 4. 完成后切回 Sonnet
```

### Prompt Caching（提示缓存）

Anthropic API 支持 Prompt Caching，对 Agent 场景效果显著：

```
Prompt Caching 的工作原理:

无缓存时:
  每轮对话都完整发送 System Prompt + 对话历史
  → System Prompt (~3K tokens) 每次都计费

有缓存时:
  首次发送 System Prompt → 缓存 5 分钟
  后续请求复用缓存 → 缓存 token 按 90% 折扣计费

Agent 场景的收益:
  一个 20 轮的 Session:
  - 无缓存: 3K × 20 = 60K tokens 的 System Prompt 消耗
  - 有缓存: 3K + 3K × 0.1 × 19 ≈ 8.7K tokens
  → 节省 ~85% 的 System Prompt 成本

Claude Code 已默认启用 Prompt Caching，无需额外配置。
```

### Token 消耗监控

```bash
# 查看当前 Session 的成本
/cost

# 输出示例:
# Session cost: $1.23
# Input tokens: 245,000
# Output tokens: 42,000
# Cache read tokens: 180,000
# Duration: 35 minutes
```

**团队级监控**：

```
监控维度:
├── 每人每天的 Token 消耗
├── 每个项目的月度成本
├── 模型使用分布（Opus/Sonnet/Haiku 各占多少）
├── 成本趋势（是否在增长？增长率是否合理？）
└── 异常检测（某天某人消耗突然翻倍 → 可能在循环浪费）

数据来源:
├── Anthropic Console → Usage Dashboard
├── API 响应中的 usage 字段
└── Hooks 自定义日志 → 聚合分析
```

### 成本优化清单

```
立即可做的优化:
├── ✅ 日常任务用 Sonnet 而不是 Opus
├── ✅ 简单查询用 Haiku
├── ✅ 配置 .claudeignore 排除无关文件（减少 Grounding token）
├── ✅ 任务中提供精确的文件路径（避免全局搜索）
├── ✅ 在上下文溢出前 /compact（避免低效的长对话）
└── ✅ 识别死循环并及时中断（避免无效 token 浪费）

需要团队协调的优化:
├── 📋 制定模型使用指南（什么任务用什么模型）
├── 📋 设置月度 Token 预算和告警阈值
├── 📋 定期分析 Token 消耗模式，识别浪费
└── 📋 评估 Prompt Caching 的实际节省效果
```

---

## 实操环节

### 练习 1：搭建 Agent 驱动的 CI/CD 流程

**目标**：为一个 GitHub 仓库配置 Agent 自动 PR 审查。

**步骤**：

1. Fork 一个示例项目（或使用自己的项目）

2. 创建 `.github/workflows/agent-review.yml`，参考本模块 10.2 中的配置

3. 在 GitHub 仓库的 Settings → Secrets 中添加 `ANTHROPIC_API_KEY`

4. 创建一个测试 PR（故意包含一些问题），观察 Agent 的审查评论

5. 迭代优化审查提示词，使审查意见更精准

**记录**：
- Agent 发现了哪些真实问题？
- Agent 产生了哪些误报？
- 提示词的哪些调整最有效？

### 练习 2：团队成本估算与优化

**目标**：为你的团队建立 Agent 使用的成本模型并制定优化方案。

**步骤**：

1. 收集数据（使用 1 周）：
   - 每天使用几个 Session
   - 每个 Session 的 `/cost` 输出
   - 使用的模型分布

2. 用 10.6 中的成本估算公式计算月度预测成本

3. 分析优化空间：
   - 哪些 Session 可以用更便宜的模型？
   - 哪些 Session 存在 Token 浪费（死循环、过度搜索）？
   - .claudeignore 是否配置合理？

4. 制定优化方案和月度预算

---

## 本模块小结

### 核心要点回顾

```
独立开发者工作流
├── Issue → 分析 → 实现 → 测试 → PR 全链路
├── Session 节奏 — 一个 Session 聚焦一个主题
├── 无头模式 — claude -p 用于自动化场景
└── Session 链接 — 跨天任务的上下文传递

团队集成
├── GitHub Actions — PR 审查、自动修复、质量门禁
├── GitLab CI — 类似的集成方式
└── CLAUDE.md 治理 — 纳入 Code Review、定期审计

Monorepo 策略
├── 依赖关系声明 — 在 CLAUDE.md 中表达包间依赖
├── 工作区限定 — 限制 Agent 的操作范围
├── 分层修改 — 基础层 → 应用层 → 消费层
└── 搜索优化 — 分区搜索、类型过滤、入口文件

组织层面的使用边界
├── 反模式 — 万能工具、跳过 Review、过度依赖
├── 技能退化风险 — 定期无 Agent 练习
└── 健康文化 — Agent 是高级实习生，不是高级工程师

安全与合规
├── 数据流分析 — 理解什么数据会发送到云端
├── 敏感信息防护 — .claudeignore + Hooks 安全网关
├── 合规要求 — SOC2/GDPR 的应对措施
├── API Key 管理 — 分离、轮换、监控、最小权限
└── 离线方案 — 本地模型 / 私有云 / 混合部署

成本控制
├── Token 经济学 — 理解成本结构
├── 成本建模 — 预测团队月度开销
├── 模型路由 — 简单任务用 Haiku，复杂任务用 Opus
├── Prompt Caching — 自动节省 System Prompt 成本
└── 监控与优化 — /cost + 团队级 Dashboard
```

### 思考题

**基础理解**

1. 在 GitHub Actions 中集成 Agent 进行 PR 审查时，如何确保审查质量的一致性？考虑提示词漂移（不同 PR 可能触发不同的审查深度）和误报率控制。

2. 解释为什么"一个 Session 聚焦一个主题"是高效的 Agent 使用策略。从上下文窗口利用率和注意力分布的角度分析。

**深度思考**

3. 某公司有 50 名工程师，每人每天使用 Agent 5 次，平均每次 300K tokens。目前使用 Opus。设计一个模型路由策略，将月度 API 成本从当前水平降低 60%，同时保证代码质量不显著下降。你需要：定义"代码质量不显著下降"的度量方式、设计路由规则、预测优化后的成本。

4. 一家金融科技公司需要使用 AI 编程代理，但必须满足 SOC 2 Type II 合规要求。设计一套完整的 Agent 使用策略，覆盖：数据流控制、访问权限管理、操作审计、应急响应。

**实践应用**

5. 为你的团队制定一份"AI 编程代理使用规范"文档，包含：适用场景和限制场景、模型选择指南、安全红线（绝对不能做的事）、成本预算和监控方式、Code Review 要求。

---

> **下一模块预告**：模块 11（即模块 8 "构建你自己的编程代理"）将带你从零实现一个完整的编程代理——从 API 调用到工具集成到反馈循环，将前面所有模块的理论知识融会贯通为一个可运行的系统。
