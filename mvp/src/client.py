"""
Agent 客户端 —— 说 Claude tool_use 协议

本模块实现了一个编程 Agent 的核心循环（ReAct loop），
客户端侧完全使用 Claude tool_use 协议——与 Claude Code 的真实架构对齐。

架构定位：
    本客户端只负责三件事：
    1. 构造请求（tools 定义 + 对话消息，Claude 格式）
    2. 处理响应（检测 tool_use blocks → 执行工具 → 回传 tool_result）
    3. 管理对话上下文（conversation history）

    所有格式转换（Claude ↔ Qwen）都在 model_server 的适配层完成。
    客户端不需要做任何文本解析——拿到的就是结构化的 content blocks。

    这与 Claude Code 的真实架构一致：
    Claude Code 客户端 → Anthropic API（返回 content blocks）→ 客户端处理
    MVP 客户端        → Model Server（适配层返回 content blocks）→ 客户端处理

ReAct 循环：
    用户输入 → [Thought → Action → Observation] × N → 最终回答

    其中：
    - Thought：模型的推理文本（text content block）
    - Action：模型请求调用工具（tool_use content block）
    - Observation：工具执行结果（tool_result content block）

    stop_reason 与 tool_use block 检测（学自 CC 源码）：
    - 主判断：检查 response content 中是否存在 tool_use block（CC 做法）
    - 辅助参考：stop_reason 字段（CC 源码注释: "stop_reason is unreliable"）
    - 存在 tool_use block → 执行工具 → 回传结果 → 继续循环
    - 不存在 tool_use block → 模型认为任务完成 → 退出循环

工具集演进（Day 1-4）：
    Day 1: Read, Write, Bash                     — 基础文件操作
    Day 2: + Edit, Grep                          — 精确编辑 + 代码搜索
    Day 3: + TaskCreate, TaskUpdate, TaskList     — 任务管理
    Day 4: + Agent                               — 子 Agent 生成

    客户端通过 get_tools() 和 get_task_tools() 加载工具，
    工具定义自动转为 Claude API 格式随请求发送。
"""

import os
import json
import time as _time
import requests
from typing import List, Dict, Any, Optional
from tools import get_tools
from task_tools import get_task_tools, task_store
from agent_tool import get_agent_tool
from trajectory import trace, Trajectory


# ---------------------------------------------------------------------------
# 工具定义：Claude 格式
# ---------------------------------------------------------------------------

def get_tool_definitions(tools: Dict) -> List[Dict[str, Any]]:
    """
    将内部工具对象转为 Claude API 格式的工具定义。

    Claude 格式的工具定义结构：
    {
        "name": "Read",
        "description": "Read the contents of a file",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string", ...}},
            "required": ["file_path"]
        }
    }

    这些定义会随每次请求发送给 model_server，
    由适配层转为 Qwen 的 function definition 格式后注入 chat template。

    Args:
        tools: get_tools() 返回的工具字典

    Returns:
        Claude 格式的工具定义列表
    """
    definitions = []
    for tool_name, tool in tools.items():
        definitions.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters
        })
    return definitions


# ---------------------------------------------------------------------------
# 客户端主类
# ---------------------------------------------------------------------------

class Client:
    """
    Agent 客户端：管理对话上下文，驱动 ReAct 循环。

    核心设计：
    - 对话历史（self.conversation）存储 Claude 格式的消息（含 content blocks）
    - 每轮请求携带完整对话历史 + 工具定义发送给 model_server
    - model_server 返回结构化响应（content blocks），客户端直接处理
    - 客户端不做任何文本解析，所有格式转换在 model_server 适配层完成

    工具集构成：
    - 基础工具（tools.py）：Read, Write, Edit, Glob, Grep, Bash
    - 任务工具（task_tools.py）：TaskCreate, TaskUpdate, TaskList
    - Agent 工具（agent_tool.py）：Agent（子 Agent 生成）
    所有工具通过统一的 self.tools 字典管理，execute 接口一致。
    """

    def __init__(self, server_url: str = "http://localhost:9981", working_dir: str = None,
                 parent_session_id: str = None):
        """
        初始化客户端。

        初始化流程：
        1. 加载所有工具（基础 + 任务 + Agent）
        2. 生成 Claude 格式的工具定义
        3. 扫描工作目录文件树
        4. 健康检查（确认 model_server 可达）

        Args:
            server_url: model_server 的地址
            working_dir: 工作目录，Agent 将在此目录中操作文件
        """
        self.server_url = server_url.rstrip("/")
        self.working_dir = working_dir or os.getcwd()
        self._parent_session_id = parent_session_id

        # ── 加载工具集 ────────────────────────────────────────────────
        # 合并三类工具到统一字典：基础工具 + 任务工具 + Agent 工具
        # 这使得 _execute_tool() 只需一次字典查找即可调用任何工具
        self.tools: Dict[str, Any] = {}

        # Day 1-2 基础工具：Read, Write, Edit, Glob, Grep, Bash
        self.tools.update(get_tools(working_dir=self.working_dir))

        # Day 3 任务管理工具：TaskCreate, TaskUpdate, TaskList
        # 共享全局 task_store 实例，确保所有工具操作同一份任务数据
        self.tools.update(get_task_tools(task_store))

        # Day 4+ Team 通信工具（仅 Lead 加载完整工具集）
        # 子 Agent 的 SendMessage 由 SubAgentRunner 注入，不在这里加载
        self._message_queue = None
        self._team_worker_name = None  # Worker 身份标识（由 SubAgentRunner 设置）
        if parent_session_id is None:
            # 顶层 Lead：创建消息队列，加载 TeamCreate + SendMessage + ReadInbox
            from team_tools import MessageQueue, get_team_tools
            self._message_queue = MessageQueue()
            self.tools.update(get_team_tools(self._message_queue, agent_id="lead"))

        # Day 4 Agent 工具：Agent（子 Agent 生成）
        # 传入 server_url 和 working_dir，子 Agent 将复用同一个 model_server
        # 传入 message_queue，使子 Agent 在 Team 模式下能获得 SendMessage
        self.tools.update(get_agent_tool(
            self.server_url, self.working_dir, task_store,
            message_queue=self._message_queue
        ))

        # 生成 Claude 格式的工具定义（随请求发送给 model_server）
        self.tool_definitions = get_tool_definitions(self.tools)

        # 对话历史：存储 Claude 格式的消息（含 content blocks）
        self.conversation: List[Dict[str, Any]] = []

        # Issue 14 兜底：一次性纠正标志，防止无限 nudge 循环
        self._already_nudged = False

        # ── 扫描文件树 ───────────────────────────────────────────────
        # ACI 设计：给模型一个项目全景，帮助它定位文件
        # 50 行上限是信息粒度控制——防止大项目的文件树撑爆上下文
        self._file_tree = self._scan_files()

        # ── 健康检查 ─────────────────────────────────────────────────
        # 确认 model_server 已启动，否则后续所有请求都会失败
        try:
            resp = requests.get(f"{self.server_url}/health", timeout=3)
            resp.raise_for_status()
            print(f"Connected to model server at {self.server_url}")
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to model server at {self.server_url}\n"
                f"Start it first: python model_server.py <model_path>"
            )

    def _scan_files(self) -> str:
        """
        扫描工作目录，生成文件树快照。

        ACI 信息粒度控制（Agentless 第一层：看文件树）：
        - 小项目（< 50 行输出）：显示完整文件树（目录 + 文件）
        - 大项目（> 50 行）：只显示前两层目录结构（深层只显示目录名）
          → 让模型看到项目的"骨架"（哪些模块存在），足够定位搜索范围
          → 模型需要看具体文件时再用 Glob 或 Grep
        - 上限 80 行，防止大项目的文件列表挤占上下文窗口
        """
        MAX_LINES = 80
        SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}

        # 先尝试完整文件树（目录 + 文件）
        lines = []
        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
            depth = root.replace(self.working_dir, '').count(os.sep)
            indent = '  ' * depth
            basename = os.path.basename(root) or '.'
            lines.append(f"{indent}{basename}/")
            for f in sorted(files):
                if not f.startswith('.'):
                    lines.append(f"{indent}  {f}")

        if len(lines) <= MAX_LINES:
            return '\n'.join(lines)

        # 大项目：两层深度的目录 + 文件混合视图
        # 深度 0-1 显示文件，深度 2+ 只显示目录名
        dir_lines = []
        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
            depth = root.replace(self.working_dir, '').count(os.sep)
            indent = '  ' * depth
            basename = os.path.basename(root) or '.'

            if depth <= 2:
                # 浅层：显示目录名 + 文件数
                visible_files = [f for f in files if not f.startswith('.')]
                file_count = len(visible_files)
                dir_lines.append(f"{indent}{basename}/  ({file_count} files)")
                # 深度 0-1 列出文件名
                if depth <= 1:
                    for f in sorted(visible_files):
                        dir_lines.append(f"{indent}  {f}")
            else:
                # 深层：只在父目录的行里汇总（不单独列出）
                pass

        return '\n'.join(dir_lines[:MAX_LINES])

    def get_system_prompt(self) -> str:
        """
        生成系统提示词。

        系统提示词的设计哲学（ACI 行为引导层）：
        - 不包含工具定义（由 chat template 的 tools 参数注入，与训练分布对齐）
        - 不包含格式说明（模型使用其训练时的原生 <tool_call> 格式）
        - 只包含行为指令：做什么、怎么做、不做什么

        v2 升级（Day 3-4 新增内容）：
        - 新增任务管理指令：收到复合任务时，先分解再执行
        - 新增 Edit 优先原则：修改已有文件优先用 Edit 而非 Write
        - 新增 Grep 工作流：用 Grep 定位 → Read 精读 → Edit 修复
        - 新增 Agent Team 指令：独立子任务可通过 Agent 工具并行执行

        这使得 system prompt 既是行为指南，也是课程 ACI 设计的活教材。
        """
        # Worker 模式：精简的系统提示词 + team 通信指令
        if self._team_worker_name:
            return f"""You are a coding agent worker named '{self._team_worker_name}'. Complete the assigned task using your tools.

Working directory: {self.working_dir}

OUTPUT DIRECTORY (CRITICAL):
- You MUST write ALL generated files to /tmp/team/workspace/
- NEVER write files to the working directory above — it contains source code, not your output.
- Create subdirectories under /tmp/team/workspace/ as needed.
- Example: Write("/tmp/team/workspace/app.py", ...) or Write("/tmp/team/workspace/index.html", ...)

Files in this project (READ-ONLY reference):
{self._file_tree}

RULES:
1. Use tools for ALL file operations. NEVER guess file contents.
2. Use absolute paths.
3. PREFER Edit over Write for modifying existing files.

EFFICIENCY (IMPORTANT):
- Focus ONLY on the core deliverable. Do NOT create README, docs, requirements.txt, or other auxiliary files.
- Do NOT spend rounds on redundant verification (e.g. grep for keywords you just wrote).
- Budget: you have ~10 rounds total. Plan: 1-3 rounds to build, 1 round to verify, 1 round to SendMessage.

TEAM COMMUNICATION (CRITICAL):
- You are worker '{self._team_worker_name}' in a team led by 'lead'.
- When you finish your task, call SendMessage(to="lead", content="<your results>") EXACTLY ONCE.
- Include: what you did, file paths created/modified, any issues found.
- Do NOT call SendMessage more than once — one clear report is enough.
- Do NOT finish without calling SendMessage — the lead is waiting for your report.

Keep responses short. Act first, explain after."""

        # Lead 模式：完整的系统提示词
        return f"""You are a coding agent. You MUST use tools for ALL file operations. You can NEVER output file contents from memory — you MUST call Read to see any file.

Working directory: {self.working_dir}

Files in this project:
{self._file_tree}

CRITICAL RULES:
1. ALWAYS explain your reasoning BEFORE calling a tool: what you observed, what you think the problem is, and what you plan to do. Then call the tool.
2. To see file contents → call Read. NEVER make up or guess file contents.
3. To find files by name → call Glob(pattern="**/*keyword*"). To list directory contents → call Glob(pattern="dir/*"). NEVER use Bash("ls") or Bash("find") — always use Glob.
4. To modify a file → call Edit. To create a new file → call Write.
5. To run code → call Bash("python ...").
6. NEVER ask "which file?" or "could you provide?" or "please specify" — use the file tree above to find files yourself. If the user says "the code" without naming a file, read ALL .py files that are not test files.
7. Use absolute paths: {self.working_dir}/<relative_path>.
8. If a filename is partial (e.g., "buggy_code"), match it to the closest file in the tree.
9. NEVER use Bash for file searching. Use Glob for finding files and Grep for searching content. Bash is ONLY for running programs (python, npm, git, etc.).

PROACTIVE FILE DISCOVERY:
- When user mentions "the code" or "bugs" without specifying a file, first call Glob(pattern="**/*.py") to find all Python files, then Read each non-test file ONE BY ONE. Start with buggy_code.py.
- ALWAYS call Read FIRST before analyzing or explaining anything.

SEARCH STRATEGY FOR LARGE CODEBASES (CRITICAL):
- When working with a large codebase (many files), use a FUNNEL approach:
  Step 1: Glob(pattern="**/*keyword*") or Glob(pattern="**/*.ext") to find relevant files by name
  Step 2: Grep(pattern="keyword", path="<dir>") to search file contents
  Step 3: Read(file_path="<file>", offset=N, limit=50) to read ONLY the specific section you need
- IMPORTANT: ALWAYS start with Glob to find files. NEVER use Bash("find") or Bash("ls") for file discovery. Glob is faster and returns better results.
- NEVER paginate through a large file with Read — if you need to find something in a 500+ line file, use Grep(pattern="...", path="<file>") to locate the exact lines first, then Read only those lines.
- When Read returns "File too large" error, ALWAYS use Grep next (not Read with offset/limit). The error message shows a suggested Grep pattern — use it.
- After 2-3 Grep calls, you should have enough context to answer. Do NOT read entire files.
- You have a LIMITED budget of ~10 tool calls. After gathering enough information (usually 5-8 calls), STOP searching and WRITE YOUR ANSWER. Do not keep reading more code — synthesize what you have.

FOLLOW USER INTENT — do exactly what is asked, nothing more, nothing less:
- "显示/show/read X" → Read, present result. STOP. Do NOT analyze, fix, or run.
- "找/找找/find/分析/analyze + bug/错误/问题" → Read files, explain bugs. Do NOT call Edit. Do NOT fix.
- "修/fix/修复/改 + bug/错误" → Read → Edit → Bash. Full L-R-V cycle.
- CRITICAL: "找" (find) ≠ "修" (fix). If user says 找/find, you MUST NOT call Edit or Write. Only Read and explain.
- If the task is done, STOP immediately. Do NOT do extra work the user didn't ask for.

BUG FIX WORKFLOW (ONLY when user explicitly says 修/fix/修复/改):
- Localize: Use Grep/Read to find the bug.
- Repair: Use Edit (not Write) for precise changes.
- Validate: Use Bash to run the code and verify.
- If user did NOT say fix, do NOT enter this workflow.

EDITING RULES:
- PREFER Edit over Write for modifying existing files.
- Only use Write for creating new files.

TASK MANAGEMENT (for complex, multi-step requests):
- Use TaskCreate/TaskUpdate/TaskList to break down and track multi-step work.
- For independent sub-tasks, use the Agent tool to spawn sub-agents.

AGENT TEAM MODE (IMPORTANT):
- When the user says "in parallel", "each one", "for each file", or requests multiple independent reviews/tasks, you MUST use the Agent tool to spawn one sub-agent per task.
- Do NOT do the work yourself sequentially — spawn sub-agents instead.
- Example: "Review each Python file for bugs in parallel" → spawn one Agent per .py file, each with prompt "Read <file> and report any bugs found."
- Each sub-agent runs in its own context with Read/Write/Edit/Grep/Bash tools.
- Wait for all sub-agents to complete, then summarize their findings.

TEAM COMMUNICATION:
- To set up a team: call TeamCreate(members=["backend-dev", "frontend-dev", "test-dev"]).
- To spawn a named worker: call Agent(prompt="...", agent_name="backend-dev"). The worker gets a SendMessage tool.
- Workers will SendMessage their results to your inbox before they return.
- After workers complete, call ReadInbox() to read all their messages at once.
- Workers write output files to /tmp/team/workspace/ (not the working directory).
- Workflow: TeamCreate → Agent(worker1) → Agent(worker2) → ReadInbox → review results → Agent(worker3) → ReadInbox → final summary.

Keep text responses short. Always act first, explain after."""

    def run(self, user_input: str) -> Optional[str]:
        """
        处理用户输入，驱动 ReAct 循环直至任务完成。

        这是 Agent 的核心循环，对应课程模块一的 TAO（Thought-Action-Observation）：

        循环流程：
        1. 将用户输入加入对话历史
        2. 发送请求（tools + system prompt + 对话历史）给 model_server
        3. 接收 Claude 格式的结构化响应
        4. 检查 stop_reason：
           - "tool_use"：提取 tool_use blocks → 执行工具 → 构造 tool_result → 继续循环
           - "end_turn"：任务完成，退出循环

        防死循环机制（Circuit Breaker）：
        max_rounds 限制最大循环次数。对应课程中"OODA 循环卡死"的工程兜底——
        当模型的 Orient 环节失灵（无法从重复的 Observation 中提取新信息）时，
        强制终止循环，避免无限消耗 token。

        Day 3/4 升级：轮数从 5 提升到 10。
        原因：引入任务管理后，一个复合任务可能需要：
        TaskCreate × 3 + (Read + Edit + Bash) × 3 = 12 轮工具调用。
        5 轮不够用了，10 轮是新的合理上限。

        Args:
            user_input: 用户的自然语言指令

        Returns:
            None（所有输出已通过 print 实时展示）
        """
        self.conversation.append({"role": "user", "content": user_input})

        # 重置 nudge 标志（每次 run() 只允许一次纠正）
        self._already_nudged = False

        # 创建轨迹记录器
        traj = Trajectory(user_input, save_dir=os.path.join(self.working_dir, "trajectories"),
                          parent_session_id=self._parent_session_id)
        self._traj_session_id = traj.session_id

        # Circuit Breaker：最大循环轮数
        # CC 没有默认轮次上限（靠模型自己 end_turn），但 30B MoE 缺乏自主停止能力，
        # 需要外部限制。15 轮给 Localization 漏斗（~5 轮）+ 修复验证（~5 轮）留够空间。
        max_rounds = 15
        round_num = 0

        while round_num < max_rounds:
            round_num += 1
            traj.start_round(round_num)
            trace(f"══ Round {round_num}/{max_rounds} ══",
                  conversation_len=len(self.conversation))

            # ── Micro Compact（对齐 CC 的 microCompact.ts）──────────
            # CC 在每轮 API 调用前清理旧工具结果，保护上下文窗口：
            #   旧的 tool_result → "[Old tool result content cleared]"
            # 只保留最近 KEEP_RECENT 条消息的完整工具结果。
            # 这是 CC 七层上下文防线的第 4 层。
            self._microcompact()

            # 构造请求：system prompt + tools + 对话历史
            # system prompt 作为对话的第一条消息
            messages = [{"role": "system", "content": self.get_system_prompt()}]
            messages.extend(self.conversation)

            # 预算警告：倒数第2轮注入合成提示，迫使模型输出答案而非继续搜索
            # CC 靠模型自己 end_turn，但 30B MoE 需要外部信号触发模式切换
            if round_num >= max_rounds - 1:
                messages.append({
                    "role": "user",
                    "content": "IMPORTANT: You are running out of rounds. STOP searching and WRITE YOUR FINAL ANSWER NOW based on what you have found so far. Do NOT call any more tools — just summarize your findings in detail."
                })

            # ── 发送请求，接收流式响应 ────────────────────────────
            print(f"\n── Round {round_num}/{max_rounds} ──", flush=True)
            print("🤖 ", end="", flush=True)
            t0 = _time.time()
            response = self._generate(messages)
            t1 = _time.time()

            if response is None:
                trace("round result: no response")
                print("\n  ⚠️ No response from server.", flush=True)
                traj.end_round()
                traj.finish()
                return None

            # ── 轨迹：记录本轮响应结构 ────────────────────────────
            content_types = [b.get("type") for b in response.get("content", [])]
            trace(f"round {round_num} response",
                  gen_time=f"{t1-t0:.1f}s",
                  stop_reason=response.get("stop_reason"),
                  content_blocks=content_types)

            # ── 提取思考文本用于轨迹记录 ─────────────────────────
            thought_parts = []
            for block in response.get("content", []):
                if block.get("type") == "text":
                    thought_parts.append(block.get("text", ""))
            if thought_parts:
                traj.record_thought(" ".join(thought_parts))

            # ── 将 assistant 响应加入对话历史 ─────────────────────
            # 存储完整的 content blocks，保持对话历史的结构化
            self.conversation.append(response)

            # ── 检查是否需要执行工具 ──────────────────────────────
            # 【学自 CC 源码】CC 的 query.ts 不信任 stop_reason（注释: "stop_reason
            # === 'tool_use' is unreliable"），而是直接检查 response 中是否存在
            # tool_use block。我们采用相同策略：以 tool_use block 的实际存在性为准，
            # stop_reason 仅作辅助参考。
            tool_use_blocks = [b for b in response.get("content", [])
                               if b.get("type") == "tool_use"]
            has_tool_use = len(tool_use_blocks) > 0

            if not has_tool_use:
                # ── Budget warning round: accept text as final answer ────
                # On budget-warning rounds, model is explicitly told to write
                # its answer without tools. Skip nudge — tool names in text
                # are descriptions (e.g. "CC's Edit tool"), not failed calls.
                if round_num >= max_rounds - 1:
                    if thought_parts:
                        traj.record_response(" ".join(thought_parts))
                    trace(f"loop exit: budget round final answer")
                    traj.end_round()
                    traj.finish()
                    return None

                # ── Issue 14 兜底：检测模型是否在文本中描述了工具调用 ──
                # 小模型有时会"假装调工具"——在文本中描述 Edit/Write 操作，
                # 但不发出 <tool_call> token。检测到时注入一次性纠正提示。
                # 使用更严格的匹配：要求工具名后跟 ( 或前有动词 call/use/invoke，
                # 避免 "CC's Edit tool" 之类的描述触发误报。
                full_text = " ".join(thought_parts)
                tool_names = [t for t in self.tools.keys()
                              if t in ("Edit", "Write", "Bash", "Grep")]
                mentioned_tools = []
                for t in tool_names:
                    # Match patterns like "Edit(" or "call Edit" or "use Edit" — not "Edit tool"
                    import re as _re
                    if _re.search(rf'\b{t}\s*\(', full_text) or _re.search(rf'(?:call|use|invoke|run)\s+{t}\b', full_text):
                        mentioned_tools.append(t)

                if mentioned_tools and not self._already_nudged:
                    self._already_nudged = True
                    nudge = (
                        f"You described using {', '.join(mentioned_tools)} "
                        f"but did not actually call the tool. "
                        f"Do NOT describe tool calls in text. "
                        f"You MUST invoke the tool directly. Try again."
                    )
                    trace("nudge: model described tool without calling",
                          mentioned=mentioned_tools)
                    traj.record_thought(f"[NUDGE] {nudge}")
                    traj.end_round()

                    self.conversation.append({"role": "user", "content": nudge})
                    continue  # retry the round

                # 模型认为任务完成（stop_reason: "end_turn"）
                # 记录最终回答
                if thought_parts:
                    traj.record_response(" ".join(thought_parts))
                trace(f"loop exit: stop_reason={response.get('stop_reason')}")
                traj.end_round()
                traj.finish()
                return None

            # ── 执行工具调用 ──────────────────────────────────────
            # 使用上面已提取的 tool_use_blocks（与 CC 对齐：基于 block 存在性）
            tool_results = []
            for block in tool_use_blocks:

                tool_name = block["name"]
                tool_input = block["input"]
                tool_use_id = block["id"]

                trace(f"executing tool",
                      tool=tool_name,
                      params=str(tool_input)[:100])

                print(f"\n  🔧 {tool_name}", flush=True)
                # 打印工具参数（完整显示，方便 demo 观察）
                for k, v in tool_input.items():
                    v_str = str(v)
                    if len(v_str) > 200:
                        v_str = v_str[:200] + "..."
                    print(f"     {k}: {v_str}", flush=True)
                t_tool_0 = _time.time()
                # Agent 工具需要额外传递 parent_session_id
                if tool_name == "Agent":
                    tool_input["parent_session_id"] = traj.session_id
                result = self._execute_tool(tool_name, tool_input)
                t_tool_1 = _time.time()

                # 判断执行是否出错
                is_error = result.startswith("Error")

                # 捕获子 Agent 的 session_id（用于轨迹关联）
                sub_session_id = None
                if tool_name == "Agent":
                    agent_tool = self.tools.get("Agent")
                    sub_session_id = getattr(agent_tool, '_last_sub_session_id', None)

                trace(f"tool result",
                      tool=tool_name,
                      is_error=is_error,
                      result_len=len(result),
                      time=f"{t_tool_1-t_tool_0:.2f}s")

                # 轨迹记录
                traj.record_action(tool_name, tool_input, result,
                                   t_tool_1 - t_tool_0, is_error,
                                   sub_session_id=sub_session_id)

                if is_error:
                    print(f"  ❌ {result[:500]}", flush=True)
                else:
                    # 显示更完整的结果（多行保留前 5 行，单行显示 200 字符）
                    lines = result.split('\n')
                    if len(lines) <= 5:
                        for line in lines:
                            print(f"     {line}", flush=True)
                    else:
                        for line in lines[:5]:
                            print(f"     {line}", flush=True)
                        print(f"     ... ({len(lines)} lines total)", flush=True)

                # 构造 tool_result block
                # tool_use_id 关联确保多工具并发时结果不会错配
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                    "is_error": is_error
                })

            traj.end_round()

            # 将所有 tool_result 作为一条 user 消息回传
            # Claude API 的约定：tool_result 放在 user role 的 content blocks 中
            #
            # 同时注入用户意图提醒（Issue 15 结构性兜底）：
            # 小模型在看到工具结果后容易"发散"——读了文件就想分析，
            # 分析完就想修复。在 tool_result 旁边放一条简短提醒，
            # 比在 system prompt 里写长段规则有效得多（距离近 = 注意力强）。
            intent_reminder = {
                "type": "text",
                "text": f"[Reminder: user's original request was: \"{user_input}\". "
                        f"Do ONLY what was asked. "
                        f"If user asked to find/show/analyze, do NOT call Edit or Write. "
                        f"If user asked to fix/repair, do Read → Edit → Bash then STOP.]"
            }

            # ── Reflexion: 测试失败后注入反思提示 ────────────────
            # Reflexion (Shinn et al., 2023) 的核心机制：
            # 看到测试失败后，强制模型产生结构化分析（CoT），
            # 而不是跳过推理直接行动。
            # 两种触发场景：
            #   1. 首次失败：分析错误信息，形成修复假设
            #   2. 修复后仍失败：反思上次修复为什么没用
            reflection_prompt = None
            has_prior_edit = any(
                b.get("name") == "Edit"
                for msg in self.conversation
                if msg.get("role") == "assistant"
                for b in msg.get("content", [])
                if isinstance(b, dict) and b.get("type") == "tool_use"
            )
            for tr in tool_results:
                output = tr.get("content", "")
                if "FAILED" in output:
                    if has_prior_edit:
                        reflection_prompt = {
                            "type": "text",
                            "text": "[REFLECT] Your previous fix did NOT solve all failures. "
                                    "Before editing again: "
                                    "1) Which test STILL fails and what is the exact error value? "
                                    "2) Why didn't your last edit fix it? "
                                    "3) What is the REAL root cause? "
                                    "Read the file if needed, then Edit the correct line."
                        }
                    else:
                        reflection_prompt = {
                            "type": "text",
                            "text": "[ANALYZE] Before fixing, analyze the errors: "
                                    "1) What are the exact wrong values vs expected values? "
                                    "2) Work backwards: what calculation could produce the wrong value? "
                                    "3) Form a hypothesis for each failing test. "
                                    "Then Read the code and Edit to fix."
                        }
                    break

            # ── Last-round nudge ──────────────────────────────────
            # Worker 快到轮次上限时，注入紧急提醒让它调 SendMessage。
            # 这比纯靠 system prompt 有效——距离近、时机准、模型注意力集中。
            # 三层防线的中间层：prompt 预防 → nudge 催促 → auto-send 兜底。
            extras = []
            if self._team_worker_name and round_num == max_rounds - 1:
                extras.append({
                    "type": "text",
                    "text": f"[URGENT: You have 1 round left. You MUST call SendMessage(to=\"lead\") NOW to report your results. Do NOT call any other tool.]"
                })

            # ── 可视化 Reflexion 注入（演示用）──────────────────
            if reflection_prompt:
                tag = "[REFLECT]" if has_prior_edit else "[ANALYZE]"
                print(f"\n  💡 Reflexion injected: {tag}", flush=True)
                traj.record_reflexion(tag, reflection_prompt["text"])

            self.conversation.append({
                "role": "user",
                "content": tool_results + [intent_reminder]
                           + ([reflection_prompt] if reflection_prompt else [])
                           + extras
            })

        trace("loop exit: max_rounds reached", rounds=max_rounds)
        print("\n  ⚠️ Reached maximum rounds. Stopping.", flush=True)
        traj.finish()
        return None

    def _generate(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        调用 model_server 进行推理，实时打印 token 流，返回结构化响应。

        通信协议（SSE）：
        - 推理中：收到 {"token": "Let"} → 直接打印到终端
        - 结束时：收到 {"done": true, "response": {...}} → 返回 Claude 格式响应

        实时打印 token 是 Live Demo 的关键视觉效果——
        观众能看到模型"逐字思考"的过程，而不是等几秒后突然蹦出一大段文字。

        Args:
            messages: 完整的对话消息列表（含 system prompt）

        Returns:
            Claude 格式的结构化响应字典，或 None（请求失败时）
        """
        try:
            resp = requests.post(
                f"{self.server_url}/generate",
                json={
                    "tools": self.tool_definitions,
                    "messages": messages,
                },
                stream=True,
                timeout=300
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"\n  ❌ Request failed: {e}", flush=True)
            return None

        claude_response = None
        # 用于过滤流式输出中的工具调用 JSON（fallback 路径下会出现在 content 中）
        # 标记：<tool_call>, <function=, ```json 开头的代码块
        _stream_buf = ""
        _in_tool_block = False
        # 工具调用开始标记列表
        _tool_markers = ["<tool_call>", "<function=", "```json", "```\n{"]
        # Thinking mode 状态
        _in_thinking = False
        # 服务端错误
        _server_error = None

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            data = json.loads(line[6:])  # 去掉 "data: " 前缀

            # 处理服务端错误（如 vLLM context overflow）
            if "error" in data:
                _server_error = data["error"]
                print(f"\n  ❌ Server error: {_server_error}", flush=True)
                continue

            if "thinking" in data:
                token = data["thinking"]
                if not _in_thinking:
                    _in_thinking = True
                    print("\n  💭 Thinking: ", end="", flush=True)
                print(token, end="", flush=True)
                continue

            if "token" in data:
                if _in_thinking:
                    _in_thinking = False
                    print("\n  ── End thinking ──\n  ", end="", flush=True)
                token = data["token"]
                # 过滤 Qwen 特殊 token
                token = token.replace("<|im_start|>", "").replace("<|im_end|>", "")
                if not token:
                    continue
                _stream_buf += token

                if not _in_tool_block:
                    # 检查是否进入工具调用块
                    marker_pos = -1
                    for marker in _tool_markers:
                        pos = _stream_buf.find(marker)
                        if pos >= 0:
                            marker_pos = pos
                            break
                    if marker_pos >= 0:
                        # 打印标记之前的文本
                        before = _stream_buf[:marker_pos]
                        if before:
                            print(before, end="", flush=True)
                        _stream_buf = _stream_buf[marker_pos:]
                        _in_tool_block = True
                    else:
                        # 保留缓冲以检测跨 token 的标记（最长标记约 12 字符）
                        safe = _stream_buf[:-15] if len(_stream_buf) > 15 else ""
                        if safe:
                            print(safe, end="", flush=True)
                            _stream_buf = _stream_buf[len(safe):]

                if _in_tool_block:
                    # 检查工具调用块结束
                    for end_tag in ["</tool_call>", "</function>"]:
                        if end_tag in _stream_buf:
                            after = _stream_buf[_stream_buf.index(end_tag) + len(end_tag):]
                            _stream_buf = after
                            _in_tool_block = False
                            break
                    # ```json ... ``` 块：检测末尾的 ```
                    if _in_tool_block and _stream_buf.startswith("```"):
                        # 找闭合的 ```（跳过开头）
                        close = _stream_buf.find("```", 3)
                        if close >= 0:
                            after = _stream_buf[close + 3:]
                            _stream_buf = after
                            _in_tool_block = False

            elif data.get("done"):
                # 推理结束，获取结构化响应
                # 这是适配层的输出：Qwen 原始文本已被解析为 Claude content blocks
                claude_response = data.get("response")

        # 刷新缓冲区中剩余的非工具调用文本
        if _stream_buf and not _in_tool_block:
            print(_stream_buf, end="", flush=True)

        # 服务端报错且无有效响应时，构造一个包含错误信息的 fallback 响应
        # 这让 ReAct 循环能继续运转——模型看到错误信息后可以调整策略
        # （如用 offset/limit 读取大文件的局部），而非直接终止会话
        if claude_response is None and _server_error:
            claude_response = {
                "role": "assistant",
                "content": [{"type": "text", "text":
                    f"I encountered an error: {_server_error}. "
                    f"This may be due to the conversation context being too long. "
                    f"I should try using more targeted tool calls "
                    f"(e.g., Read with offset/limit for large files)."}],
                "stop_reason": "end_turn"
            }

        return claude_response

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        """
        执行单个工具调用。

        统一的工具执行入口：根据 tool_name 从 self.tools 查找工具对象，
        然后调用其 execute() 方法。所有工具（基础/任务/Agent）的执行接口一致。

        Args:
            tool_name: 工具名（Read / Write / Edit / Grep / Bash /
                       TaskCreate / TaskUpdate / TaskList / Agent）
            parameters: 工具参数字典

        Returns:
            执行结果文本（成功或错误信息）
        """
        if tool_name not in self.tools:
            return f"Error: Unknown tool '{tool_name}'"

        tool = self.tools[tool_name]
        try:
            return tool.execute(**parameters)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    # ── Micro Compact（对齐 CC 的 microCompact.ts）───────────────────
    # 保留最近 N 条消息的完整工具结果，清理更早的
    KEEP_RECENT_MESSAGES = 3

    def _microcompact(self):
        """
        清理旧的工具结果，保护上下文窗口。

        对齐 CC 的 microCompact.ts：
            CC 在每轮 API 调用前，将旧的 tool_result 内容替换为
            "[Old tool result content cleared]"，只保留最近 N 条消息的
            完整工具结果。这是 CC 七层上下文防线的第 4 层。

        为什么这有效？
            工具结果（尤其是 Read 和 Bash 的输出）是上下文中最大的消费者。
            模型在前几轮读取的文件内容对后续推理的价值递减——
            它已经从中提取了 Thought，不需要原始内容了。
            清理旧结果释放上下文空间，让后续推理不会因 token 溢出而崩溃。

        设计决策：
            - 只清理 tool_result block 的 content 字段（保留 block 结构）
            - 保留 assistant 的 text（Thought）和 tool_use block（Action 记录）
            - 保留 user 的 text block（intent reminder 等）
            - 保留最近 KEEP_RECENT_MESSAGES 条消息不动
        """
        if len(self.conversation) <= self.KEEP_RECENT_MESSAGES:
            return

        compacted = 0
        # 只清理前面的消息，保留最近 N 条不动
        cutoff = len(self.conversation) - self.KEEP_RECENT_MESSAGES
        for msg in self.conversation[:cutoff]:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and isinstance(block.get("content"), str)
                        and len(block["content"]) > 200):
                    block["content"] = "[Old tool result content cleared]"
                    compacted += 1

        if compacted > 0:
            trace(f"microcompact: cleared {compacted} old tool results",
                  conversation_len=len(self.conversation),
                  cutoff=cutoff)

    def reset(self):
        """
        重置会话状态，开始新的对话。

        清理内容：
        1. 对话历史（conversation）：清空所有消息
        2. 任务存储（task_store）：清空所有任务
        3. 消息队列（message_queue）：清理 /tmp/team/ 目录

        为什么要同时清空任务？
        任务是会话级状态——上一轮对话创建的任务对新对话没有意义。
        如果不清空，模型可能会看到陈旧的任务列表，产生混乱。
        """
        self.conversation = []
        task_store.reset()
        if self._message_queue:
            self._message_queue.cleanup()
