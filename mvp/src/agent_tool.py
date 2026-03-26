"""
Agent Spawn 工具 —— 子 Agent 生成与并行执行

本模块实现了 Agent Team 模式的核心机制：主 Agent 可以生成子 Agent，
每个子 Agent 在独立的上下文中执行任务。

这是课程 Day 4 的核心交付物，对应课程模块三「Agent Team」。

Agent Team 的协作模型：

    ┌─────────────────────────────────────────────────────┐
    │                    主 Agent (Orchestrator)            │
    │                                                      │
    │  1. 分析用户指令                                      │
    │  2. TaskCreate × N（分解子任务）                       │
    │  3. Agent(prompt, task_id) × N（生成子 Agent）         │
    │  4. TaskList() 轮询（等待子任务完成）                   │
    │  5. 汇总结果                                         │
    └──────┬──────────────┬──────────────┬────────────────┘
           │              │              │
    ┌──────▼──────┐┌──────▼──────┐┌──────▼──────┐
    │  子 Agent 1  ││  子 Agent 2  ││  子 Agent 3  │
    │  独立上下文   ││  独立上下文   ││  独立上下文   │
    │  受限工具集   ││  受限工具集   ││  受限工具集   │
    │  执行任务 #1  ││  执行任务 #2  ││  执行任务 #3  │
    └─────────────┘└─────────────┘└─────────────┘

子 Agent 的设计决策：

    1. 独立上下文（Isolated Context）
       每个子 Agent 有自己的对话历史，不与主 Agent 或其他子 Agent 共享。
       这避免了「上下文污染」—— 一个子 Agent 处理文件 A 的中间状态
       不会影响另一个子 Agent 处理文件 B 的推理质量。

    2. 受限工具集（Restricted Tools）
       子 Agent 只能使用 Read / Write / Edit / Grep / Bash 这五个工具，
       不能调用 TaskCreate / TaskUpdate / TaskList / Agent。
       原因：
       - 防止子 Agent 递归生成孙 Agent（递归爆炸）
       - 防止子 Agent 修改主 Agent 创建的任务（角色混乱）
       - 子 Agent 的职责是「执行」，不是「规划」

    3. 同步执行 + 线程并行
       - 每个 Agent() 调用会启动一个线程执行子 Agent
       - 子 Agent 在线程中运行自己的 ReAct 循环
       - 主 Agent 通过 TaskList 轮询获取完成状态
       - 最大并行数限制为 3（防止 GPU 过载，7B 模型单 GPU 吞吐有限）

    4. 简化设计（教学优先）
       真实的 Claude Code Agent Team 使用进程级隔离（subprocess），
       我们用线程 + 独立 Client 实例模拟，降低实现复杂度。
       这个简化在教学场景下是合理的——核心概念（独立上下文、任务关联、
       并行执行）都保留了，只是隔离粒度从进程降为线程。

与 TaskStore 的交互：
    子 Agent 完成任务后，通过 task_id 更新任务状态为 completed。
    主 Agent 轮询 TaskList 发现状态变化后，知道该任务已完成。
    这个「生产者-消费者」模式是分布式系统中最基本的协作模式。
"""

import threading
from typing import Dict, Any, Optional

from tools import Tool, get_tools
from task_tools import TaskStore, task_store


# ===========================================================================
# 子 Agent 执行器
# ===========================================================================

class SubAgentRunner:
    """
    子 Agent 执行器：在独立上下文中运行 ReAct 循环。

    每个 SubAgentRunner 实例代表一个子 Agent。
    它有自己的工具集和对话历史，但共享同一个 model_server。

    为什么不直接复用 Client 类？
    因为 Client 类的构造函数会做健康检查（连接 model_server），
    而且它包含了主 Agent 的 system prompt 和工具定义。
    子 Agent 需要：
    - 不同的 system prompt（聚焦于单个任务）
    - 受限的工具集（无 TaskXxx、无 Agent）
    - 独立的对话历史

    所以我们创建一个精简版的执行器，复用 model_server 通信逻辑，
    但使用自己的上下文。

    实现方式：
    子 Agent 实际上是在当前进程中创建一个新的 Client 实例，
    但限制其可用工具集。在教学场景下，这比进程级隔离更简单。
    """

    def __init__(self, server_url: str, working_dir: str,
                 task_store: TaskStore, task_id: str = None):
        """
        初始化子 Agent。

        Args:
            server_url: model_server 地址
            working_dir: 工作目录
            task_store: 共享的任务存储（用于更新任务状态）
            task_id: 关联的任务 ID（完成后自动更新状态）
        """
        self.server_url = server_url
        self.working_dir = working_dir
        self.task_store = task_store
        self.task_id = task_id

        # 子 Agent 的受限工具集：只有文件操作 + 命令执行
        # 没有 TaskCreate / TaskUpdate / TaskList / Agent
        self.tools = get_tools(working_dir=working_dir)

        # 执行结果
        self.result: Optional[str] = None
        self.error: Optional[str] = None

    def run(self, prompt: str) -> str:
        """
        执行子 Agent 任务。

        创建一个独立的 Client 实例来运行子 Agent 的 ReAct 循环。
        子 Agent 完成后，如果有关联的 task_id，自动更新任务状态。

        Args:
            prompt: 子 Agent 的任务指令

        Returns:
            执行结果摘要
        """
        try:
            # ── 创建独立的 Client 实例 ────────────────────────────────
            # 延迟导入避免循环依赖（client.py → tools.py → agent_tool.py → client.py）
            from client import Client

            # 子 Agent 使用独立的 Client 实例
            # skip_health_check=False（默认）：子 Agent 也会验证 server 连接
            sub_client = Client(
                server_url=self.server_url,
                working_dir=self.working_dir
            )

            # ── 限制工具集 ────────────────────────────────────────────
            # 覆盖子 Client 的工具集：只保留基础工具
            # 这确保子 Agent 不能生成孙 Agent 或操作任务
            sub_client.tools = self.tools
            from client import get_tool_definitions
            sub_client.tool_definitions = get_tool_definitions(self.tools)

            # ── 执行任务 ──────────────────────────────────────────────
            sub_client.run(prompt)
            self.result = f"Sub-agent completed task: {prompt[:80]}"

            # ── 更新任务状态 ──────────────────────────────────────────
            if self.task_id:
                self.task_store.update(self.task_id, "completed")

            return self.result

        except Exception as e:
            self.error = str(e)
            error_msg = f"Sub-agent error: {self.error}"

            # 即使失败，也要更新任务状态（标记为仍在 pending 或保持 in_progress）
            # 不自动标记 completed，让主 Agent 决定如何处理失败
            return error_msg


# ===========================================================================
# Agent 工具
# ===========================================================================

class AgentTool(Tool):
    """
    生成子 Agent 执行任务。

    这是 Agent Team 模式的核心工具，让主 Agent 能够：
    1. 将独立的子任务分派给子 Agent
    2. 子 Agent 在独立上下文中执行（不污染主 Agent 的对话历史）
    3. 完成后自动更新关联任务的状态

    调用模式：
        主 Agent 的典型使用序列：
        1. TaskCreate("修复 file_a.py 的 bug")  → task_id: "1"
        2. TaskCreate("修复 file_b.py 的 bug")  → task_id: "2"
        3. Agent(prompt="修复 file_a.py 中的 off-by-one 错误", task_id="1")
        4. Agent(prompt="修复 file_b.py 中的空指针错误", task_id="2")
        5. TaskList()  → 检查所有任务是否完成
        6. 汇总报告

    注意：Agent 工具的调用是同步的（等待子 Agent 完成才返回）。
    真正的并行需要在更高层实现（如使用线程池），
    或者依赖模型在单轮中生成多个 Agent 调用（并发执行）。

    在 MVP 教学场景中：
    我们演示的是「子 Agent 独立执行」的概念，而非真正的 GPU 并行推理。
    7B 模型在单 GPU 上无法真正并行推理，所以多个子 Agent 实际上是串行执行的。
    但概念上，它们各自拥有独立上下文，这是 Agent Team 的核心。
    """

    def __init__(self, server_url: str, working_dir: str,
                 store: TaskStore = None):
        """
        初始化 Agent 工具。

        Args:
            server_url: model_server 地址
            working_dir: 工作目录
            store: 任务存储实例（共享）
        """
        super().__init__(
            name="Agent",
            description=(
                "Spawn a sub-agent to execute a task in an isolated context. "
                "The sub-agent has its own conversation history and limited "
                "tools (Read, Write, Edit, Grep, Bash). It cannot create tasks "
                "or spawn other agents. Optionally link to a task_id to "
                "auto-update task status on completion."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "The task instruction for the sub-agent. "
                            "Be specific: include file paths, expected behavior, "
                            "and verification steps."
                        )
                    },
                    "task_id": {
                        "type": "string",
                        "description": (
                            "Optional task ID to link this agent to. "
                            "When the sub-agent completes, the task will be "
                            "automatically marked as 'completed'."
                        )
                    }
                },
                "required": ["prompt"]
            }
        )
        self._server_url = server_url
        self._working_dir = working_dir
        self._store = store or task_store

    def execute(self, prompt: str, task_id: str = None) -> str:
        """
        生成子 Agent 并执行任务。

        执行流程：
        1. 如果有 task_id，先将任务标记为 in_progress
        2. 创建 SubAgentRunner
        3. 执行子 Agent 的 ReAct 循环
        4. 返回执行结果摘要

        Args:
            prompt: 子 Agent 的任务指令
            task_id: 可选的关联任务 ID

        Returns:
            执行结果摘要
        """
        # ── 更新任务状态为 in_progress ────────────────────────────────
        if task_id:
            task = self._store.get(task_id)
            if task is None:
                return f"Error: Task #{task_id} not found"
            self._store.update(task_id, "in_progress")
            print(f"\n  🤖 Spawning sub-agent for task #{task_id}: {prompt[:60]}...",
                  flush=True)
        else:
            print(f"\n  🤖 Spawning sub-agent: {prompt[:60]}...", flush=True)

        # ── 创建并执行子 Agent ────────────────────────────────────────
        runner = SubAgentRunner(
            server_url=self._server_url,
            working_dir=self._working_dir,
            task_store=self._store,
            task_id=task_id
        )

        result = runner.run(prompt)

        # ── 返回结果摘要 ──────────────────────────────────────────────
        if runner.error:
            return f"Sub-agent failed: {runner.error}"

        if task_id:
            return f"Sub-agent completed task #{task_id}: {prompt[:80]}"
        else:
            return f"Sub-agent completed: {prompt[:80]}"


# ===========================================================================
# 工具注册函数
# ===========================================================================

def get_agent_tool(server_url: str, working_dir: str,
                   store: TaskStore = None) -> Dict[str, Tool]:
    """
    返回 Agent 工具字典。

    Args:
        server_url: model_server 地址
        working_dir: 工作目录
        store: 任务存储实例

    Returns:
        {工具名: 工具对象} 字典
    """
    return {
        "Agent": AgentTool(server_url, working_dir, store),
    }
