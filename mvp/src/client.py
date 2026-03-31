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

    stop_reason 决定是否继续循环：
    - "tool_use"：模型想调用工具 → 执行工具 → 回传结果 → 继续循环
    - "end_turn"：模型认为任务完成 → 退出循环 → 返回最终回答

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
    - 基础工具（tools.py）：Read, Write, Edit, Grep, Bash
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

        # Day 1-2 基础工具：Read, Write, Edit, Grep, Bash
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

        限制 50 行是有意为之的 ACI 设计决策（课程 2.2 节内容）：
        - 给模型"刚好够定位"的信息量（粗粒度全景）
        - 模型需要精读时再用 Read 工具按需获取（细粒度局部）
        - 防止大项目的文件列表挤占有限的上下文窗口
        """
        lines = []
        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            depth = root.replace(self.working_dir, '').count(os.sep)
            indent = '  ' * depth
            basename = os.path.basename(root) or '.'
            lines.append(f"{indent}{basename}/")
            for f in sorted(files):
                if not f.startswith('.'):
                    lines.append(f"{indent}  {f}")
        return '\n'.join(lines[:50])

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
1. You MUST call a tool in your FIRST response. Never reply with only text.
2. To see file contents → call Read. NEVER make up or guess file contents.
3. To list files → call Bash("ls") or Bash("find ..."). NEVER list files from memory.
4. To modify a file → call Edit. To create a new file → call Write.
5. To run code → call Bash("python ...").
6. NEVER ask "which file?" or "could you provide?" or "please specify" — use the file tree above to find files yourself. If the user says "the code" without naming a file, read ALL .py files that are not test files.
7. Use absolute paths: {self.working_dir}/<relative_path>.
8. If a filename is partial (e.g., "buggy_code"), match it to the closest file in the tree.

PROACTIVE FILE DISCOVERY:
- When user mentions "the code" or "bugs" without specifying a file, you MUST immediately call Read on each non-test .py file ONE BY ONE. Start with buggy_code.py. Do NOT use wildcards or globs — Read only accepts a single file path.
- ALWAYS call Read FIRST before analyzing or explaining anything.

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
        # Day 3/4 升级：从 5 → 10，适应任务分解 + 多步执行的更长工作流
        max_rounds = 10
        round_num = 0

        while round_num < max_rounds:
            round_num += 1
            traj.start_round(round_num)
            trace(f"══ Round {round_num}/{max_rounds} ══",
                  conversation_len=len(self.conversation))

            # 构造请求：system prompt + tools + 对话历史
            # system prompt 作为对话的第一条消息
            messages = [{"role": "system", "content": self.get_system_prompt()}]
            messages.extend(self.conversation)

            # ── 发送请求，接收流式响应 ────────────────────────────
            print("\n🤖 ", end="", flush=True)
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
            if response.get("stop_reason") != "tool_use":
                # ── Issue 14 兜底：检测模型是否在文本中描述了工具调用 ──
                # 小模型有时会"假装调工具"——在文本中描述 Edit/Write 操作，
                # 但不发出 <tool_call> token。检测到时注入一次性纠正提示。
                full_text = " ".join(thought_parts)
                tool_names = [t for t in self.tools.keys()
                              if t in ("Edit", "Write", "Bash", "Grep")]
                mentioned_tools = [t for t in tool_names if t in full_text]

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
            # 提取所有 tool_use blocks，逐个执行
            tool_results = []
            for block in response.get("content", []):
                if block.get("type") != "tool_use":
                    continue

                tool_name = block["name"]
                tool_input = block["input"]
                tool_use_id = block["id"]

                trace(f"executing tool",
                      tool=tool_name,
                      params=str(tool_input)[:100])

                print(f"\n  🔧 Executing {tool_name}...", flush=True)
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
                    print(f"  ❌ {result}", flush=True)
                else:
                    preview = result[:80].replace('\n', ' ')
                    print(f"  ✅ {preview}{'...' if len(result) > 80 else ''}", flush=True)

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

            self.conversation.append({
                "role": "user",
                "content": tool_results + [intent_reminder] + extras
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

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            data = json.loads(line[6:])  # 去掉 "data: " 前缀

            if "token" in data:
                # 实时打印 token（流式输出的视觉效果）
                print(data["token"], end="", flush=True)

            elif data.get("done"):
                # 推理结束，获取结构化响应
                # 这是适配层的输出：Qwen 原始文本已被解析为 Claude content blocks
                claude_response = data.get("response")

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
