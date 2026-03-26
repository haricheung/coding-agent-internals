"""
任务管理工具集 —— Agent 的「计划与追踪」能力

本模块实现了 Agent 的任务管理系统，对应课程 Day 3 的核心交付物。
任务管理是 Agent 从「单步执行」升级到「多步规划」的关键能力。

为什么 Agent 需要任务管理？
    考虑用户指令：「重构这个模块：提取辅助函数，添加类型注解，编写测试」
    这是一个包含三个子任务的复合指令。没有任务管理，Agent 只能按顺序执行，
    中间如果某步失败，它不知道自己完成了多少、还剩多少。

    有了任务管理，Agent 可以：
    1. 先分解：创建三个任务（TaskCreate × 3）
    2. 逐个执行：每个任务标记 in_progress → completed
    3. 容错恢复：某个任务失败时，知道其他任务的状态，可以跳过或重试
    4. 向用户报告：通过 TaskList 展示整体进度

    这个模式在 Claude Code 中的对应物是 TodoWrite / TodoRead 工具。

设计决策：
    - 使用内存存储（非持久化）：Agent 的任务是会话级的，不需要跨会话保留
    - 状态机简化为三态：pending → in_progress → completed
      （真实系统会有 blocked、failed 等状态，这里为教学简化）
    - TaskList 返回 Markdown 格式：模型在训练数据中见过大量 Markdown，
      使用 Markdown 格式能让模型更好地理解和生成任务操作

任务管理与 Agent Team 的关系（Day 4 预铺垫）：
    Day 3：单 Agent + 任务管理 → Agent 自己创建任务、自己执行
    Day 4：多 Agent + 任务管理 → 主 Agent 创建任务、分派给子 Agent 执行
    任务系统是 Agent Team 协作的基础设施。

工具集：
    - TaskCreate(description): 创建新任务，返回 task_id
    - TaskUpdate(task_id, status): 更新任务状态
    - TaskList(): 列出所有任务及其状态
"""

import threading
from typing import Dict, Any, List, Optional

from tools import Tool


# ===========================================================================
# 任务存储 —— 全局任务仓库
# ===========================================================================

class TaskStore:
    """
    任务存储：管理所有任务的生命周期。

    这是一个线程安全的内存存储，所有 TaskXxx 工具共享同一个实例。
    线程安全是为 Day 4 的 Agent Team 预留的——多个子 Agent 可能并发更新任务状态。

    数据模型（每个任务）：
        {
            "id": "1",                    # 自增 ID，字符串类型（方便拼接输出）
            "description": "提取辅助函数",  # 任务描述
            "status": "pending"            # 状态：pending / in_progress / completed
        }

    状态机：
        pending ──→ in_progress ──→ completed
          │                            ↑
          └────────────────────────────┘  （也允许直接 pending → completed）

    为什么用自增 ID 而不是 UUID？
        因为模型需要在后续对话中引用任务 ID，短整数（"1", "2", "3"）
        比长 UUID 更容易记忆和生成。这是 ACI 设计中「减少模型认知负担」的体现。
    """

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._next_id: int = 1
        self._lock = threading.Lock()  # 线程安全锁（为 Day 4 多 Agent 预留）

    def create(self, description: str) -> Dict[str, Any]:
        """
        创建新任务。

        Args:
            description: 任务描述

        Returns:
            新创建的任务字典（含自动分配的 ID）
        """
        with self._lock:
            task_id = str(self._next_id)
            self._next_id += 1
            task = {
                "id": task_id,
                "description": description,
                "status": "pending"
            }
            self._tasks[task_id] = task
            return task.copy()

    def update(self, task_id: str, status: str) -> Optional[Dict[str, Any]]:
        """
        更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态（pending / in_progress / completed）

        Returns:
            更新后的任务字典，或 None（如果任务不存在）
        """
        valid_statuses = {"pending", "in_progress", "completed"}
        if status not in valid_statuses:
            return None

        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task["status"] = status
            return task.copy()

    def list_all(self) -> List[Dict[str, Any]]:
        """
        列出所有任务。

        Returns:
            所有任务的列表（按 ID 排序）
        """
        with self._lock:
            return [
                task.copy()
                for task in sorted(
                    self._tasks.values(),
                    key=lambda t: int(t["id"])
                )
            ]

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个任务。

        Args:
            task_id: 任务 ID

        Returns:
            任务字典，或 None
        """
        with self._lock:
            task = self._tasks.get(task_id)
            return task.copy() if task else None

    def reset(self) -> None:
        """清空所有任务（用于会话重置）。"""
        with self._lock:
            self._tasks.clear()
            self._next_id = 1


# ===========================================================================
# 全局任务存储实例
# ===========================================================================

# 所有 TaskXxx 工具共享同一个 TaskStore 实例。
# 这个实例在模块加载时创建，随进程生命周期存在。
# Client.reset() 时应调用 task_store.reset() 同步清理。
task_store = TaskStore()


# ===========================================================================
# TaskCreate 工具
# ===========================================================================

class TaskCreateTool(Tool):
    """
    创建新任务。

    使用场景：
    当 Agent 收到复合指令时，先用 TaskCreate 分解为多个子任务，
    然后逐个执行。这个「先分解、再执行」的模式对应课程中的
    「Plan → Execute」两阶段策略。

    在 Agent Team 模式（Day 4）中：
    主 Agent 用 TaskCreate 创建任务，然后用 Agent 工具生成子 Agent 来执行。
    task_id 是主 Agent 和子 Agent 之间的关联纽带。

    示例对话：
        用户：重构这个模块：提取辅助函数，添加类型注解，编写测试
        Agent：
          → TaskCreate("提取辅助函数到 helpers.py")  → id: 1
          → TaskCreate("为核心函数添加类型注解")       → id: 2
          → TaskCreate("编写单元测试")               → id: 3
          → TaskUpdate("1", "in_progress")
          → (执行提取辅助函数...)
          → TaskUpdate("1", "completed")
          → TaskUpdate("2", "in_progress")
          → ...
    """

    def __init__(self, store: TaskStore):
        super().__init__(
            name="TaskCreate",
            description=(
                "Create a new task for tracking multi-step work. "
                "Returns the task ID. Use this to break down complex "
                "instructions into smaller, trackable sub-tasks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": (
                            "A clear description of what needs to be done. "
                            "Be specific enough that you can later determine "
                            "if the task is completed."
                        )
                    }
                },
                "required": ["description"]
            }
        )
        self._store = store

    def execute(self, description: str) -> str:
        """
        创建任务并返回任务信息。

        Args:
            description: 任务描述

        Returns:
            包含任务 ID 和状态的确认信息
        """
        task = self._store.create(description)
        return (
            f"Created task #{task['id']}: {task['description']}\n"
            f"Status: {task['status']}"
        )


# ===========================================================================
# TaskUpdate 工具
# ===========================================================================

class TaskUpdateTool(Tool):
    """
    更新任务状态。

    状态流转：
        pending → in_progress → completed

    使用时机：
    - 开始执行任务时：TaskUpdate(id, "in_progress")
    - 完成任务时：TaskUpdate(id, "completed")
    - 需要回退时：TaskUpdate(id, "pending")（少见，但允许）

    在 Agent Team 模式中：
    子 Agent 完成工作后，通过 TaskUpdate 将任务标记为 completed，
    主 Agent 轮询 TaskList 发现任务已完成，即可继续下一步。

    这个模式类似于消息队列中的「任务完成回调」，
    但简化为「轮询 + 状态机」的实现。
    """

    def __init__(self, store: TaskStore):
        super().__init__(
            name="TaskUpdate",
            description=(
                "Update the status of a task. "
                "Valid statuses: 'pending', 'in_progress', 'completed'. "
                "Use 'in_progress' when starting a task, "
                "'completed' when finished."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The ID of the task to update"
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "New status: 'pending', 'in_progress', or 'completed'"
                        ),
                        "enum": ["pending", "in_progress", "completed"]
                    }
                },
                "required": ["task_id", "status"]
            }
        )
        self._store = store

    def execute(self, task_id: str, status: str) -> str:
        """
        更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态

        Returns:
            更新确认信息，或错误信息
        """
        # 验证状态值
        valid_statuses = {"pending", "in_progress", "completed"}
        if status not in valid_statuses:
            return (
                f"Error: Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(valid_statuses))}"
            )

        task = self._store.update(task_id, status)
        if task is None:
            return f"Error: Task #{task_id} not found"

        # 状态对应的 emoji，让输出更直观
        status_icons = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅"
        }
        icon = status_icons.get(status, "")
        return f"{icon} Task #{task['id']} updated to '{status}': {task['description']}"


# ===========================================================================
# TaskList 工具
# ===========================================================================

class TaskListTool(Tool):
    """
    列出所有任务及其当前状态。

    返回 Markdown 格式的任务列表，包含统计摘要。
    Markdown 格式是有意选择的——模型在训练数据中见过大量 Markdown，
    使用这种格式能让模型更好地理解任务状态。

    在 Agent Team 模式中：
    主 Agent 定期调用 TaskList 检查所有子任务的状态，
    就像项目经理查看看板（Kanban Board）一样。
    当所有任务都 completed 时，主 Agent 知道可以开始汇总了。

    输出示例：
        ## Tasks
        - [x] #1: 提取辅助函数到 helpers.py (completed)
        - [ ] #2: 为核心函数添加类型注解 (in_progress)
        - [ ] #3: 编写单元测试 (pending)

        Summary: 1/3 completed, 1 in progress, 1 pending
    """

    def __init__(self, store: TaskStore):
        super().__init__(
            name="TaskList",
            description=(
                "List all tasks with their current status. "
                "Returns a Markdown-formatted task list with "
                "a progress summary. Use this to check overall progress."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self._store = store

    def execute(self) -> str:
        """
        列出所有任务。

        Returns:
            Markdown 格式的任务列表和统计摘要
        """
        tasks = self._store.list_all()

        if not tasks:
            return "No tasks created yet."

        # ── 构造 Markdown 列表 ────────────────────────────────────────
        lines = ["## Tasks"]
        for task in tasks:
            # Markdown checkbox：[x] 表示已完成，[ ] 表示未完成
            checkbox = "[x]" if task["status"] == "completed" else "[ ]"
            lines.append(
                f"- {checkbox} #{task['id']}: {task['description']} "
                f"({task['status']})"
            )

        # ── 统计摘要 ─────────────────────────────────────────────────
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        pending = sum(1 for t in tasks if t["status"] == "pending")

        lines.append("")
        lines.append(
            f"Summary: {completed}/{total} completed"
            f"{f', {in_progress} in progress' if in_progress else ''}"
            f"{f', {pending} pending' if pending else ''}"
        )

        return "\n".join(lines)


# ===========================================================================
# 工具注册函数
# ===========================================================================

def get_task_tools(store: TaskStore = None) -> Dict[str, Tool]:
    """
    返回任务管理工具字典。

    Args:
        store: 任务存储实例。如果为 None，使用全局实例。
               允许传入自定义实例是为了测试隔离。

    Returns:
        {工具名: 工具对象} 字典
    """
    if store is None:
        store = task_store

    return {
        "TaskCreate": TaskCreateTool(store),
        "TaskUpdate": TaskUpdateTool(store),
        "TaskList": TaskListTool(store),
    }
