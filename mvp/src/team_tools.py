"""
Team 通信工具集 —— Agent 间消息传递

本模块实现了 Team 模式的核心通信原语，对应 Claude Code 的设计哲学：
「把所有协调原语都做成工具，让 LLM 自己编排」

三个工具：
    - TeamCreate: Lead 声明团队拓扑，创建消息队列基础设施
    - SendMessage: Agent 间消息传递（Worker → Lead 或 Lead → Worker）
    - ReadInbox: Lead 读取收到的消息

通信介质：
    文件系统消息队列（/tmp/team/{agent_id}/inbox.jsonl）。
    选择文件系统而非 socket/Redis 是教学设计决策——
    学生可以直接 `cat /tmp/team/lead/inbox.jsonl` 看到消息流，
    比抓包或 Redis CLI 直观得多。

与 Claude Code 的对应关系：
    CC 工具          │ MVP 工具         │ 差异
    SendMessage      │ SendMessage      │ CC 用进程间 IPC，我们用文件
    TeamCreate       │ TeamCreate       │ CC 有完整生命周期，我们只做 setup
    （无对应）        │ ReadInbox        │ CC 通过 tool_result 自动传递
"""

import os
import json
import shutil
import threading
from datetime import datetime
from typing import Dict, List, Any

from tools import Tool


# ===========================================================================
# 文件消息队列
# ===========================================================================

class MessageQueue:
    """
    基于文件系统的消息队列。

    每个 agent 有一个 inbox 文件（JSONL 格式，一行一条消息）。
    发消息 = 往对方的 inbox 文件追加一行 JSON。
    读消息 = 读取自己的 inbox 文件全部内容，然后清空。

    为什么用 JSONL 而不是 JSON 数组？
    因为 JSONL 支持 append-only 写入（追加一行），
    而 JSON 数组需要先读再写（读全文 → 解析 → 追加 → 重写）。
    在并发场景下，append-only 更安全也更高效。

    目录结构：
        /tmp/team/
        ├── lead/
        │   └── inbox.jsonl
        ├── backend-dev/
        │   └── inbox.jsonl
        └── frontend-dev/
            └── inbox.jsonl
    """

    BASE_DIR = "/tmp/team"

    def __init__(self):
        self._lock = threading.Lock()

    def setup_team(self, member_names: List[str]) -> Dict[str, str]:
        """
        创建团队消息基础设施。

        为每个成员创建 inbox 目录和空的 JSONL 文件。
        幂等操作——重复调用安全。

        Args:
            member_names: 成员名称列表

        Returns:
            {成员名: inbox路径} 字典
        """
        with self._lock:
            paths = {}
            for name in member_names:
                inbox_dir = os.path.join(self.BASE_DIR, name)
                os.makedirs(inbox_dir, exist_ok=True)
                inbox_path = os.path.join(inbox_dir, "inbox.jsonl")
                # 创建空文件（如果不存在）
                if not os.path.exists(inbox_path):
                    open(inbox_path, 'w').close()
                paths[name] = inbox_path
            return paths

    def send(self, from_id: str, to_id: str, content: str) -> bool:
        """
        发送消息到目标 agent 的 inbox。

        Args:
            from_id: 发送者名称
            to_id: 接收者名称
            content: 消息内容

        Returns:
            True 成功，False 失败（inbox 不存在）
        """
        inbox_path = os.path.join(self.BASE_DIR, to_id, "inbox.jsonl")
        if not os.path.exists(inbox_path):
            return False

        message = {
            "from": from_id,
            "to": to_id,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        with self._lock:
            with open(inbox_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(message, ensure_ascii=False) + '\n')

        return True

    def read_inbox(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        读取 agent 的所有未读消息，然后清空 inbox。

        Args:
            agent_id: 读取者名称

        Returns:
            消息列表（可能为空）
        """
        inbox_path = os.path.join(self.BASE_DIR, agent_id, "inbox.jsonl")
        if not os.path.exists(inbox_path):
            return []

        with self._lock:
            messages = []
            with open(inbox_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

            # 清空 inbox（已读即删）
            with open(inbox_path, 'w') as f:
                pass

        return messages

    def cleanup(self):
        """删除整个 /tmp/team/ 目录树。"""
        if os.path.exists(self.BASE_DIR):
            shutil.rmtree(self.BASE_DIR, ignore_errors=True)


# ===========================================================================
# TeamCreate 工具 —— 声明团队拓扑
# ===========================================================================

class TeamCreateTool(Tool):
    """
    创建团队，建立消息队列基础设施。

    这是 Team 模式的第一步：Lead 声明"我要一个团队"，
    系统为每个成员创建 inbox。之后 Lead 用 Agent 工具 spawn workers。

    对应 CC 的 TeamCreate 工具，但大幅简化：
    - 不做角色分配（CC 有 role/capabilities）
    - 不做生命周期管理（CC 有 TeamDelete + shutdown 协议）
    - 只做消息基础设施搭建
    """

    def __init__(self, queue: MessageQueue):
        super().__init__(
            name="TeamCreate",
            description=(
                "Create a team of named agents with file-based message inboxes. "
                "Call this BEFORE spawning worker agents with the Agent tool. "
                "Returns team member list and inbox paths."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "members": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of worker agent names, e.g. "
                            "['backend-dev', 'frontend-dev', 'test-dev']. "
                            "'lead' is always included automatically."
                        )
                    }
                },
                "required": ["members"]
            }
        )
        self._queue = queue

    def execute(self, members) -> str:
        """
        创建团队消息基础设施。

        Args:
            members: 成员名称列表（可能是 list 或 JSON 字符串，Qwen 有时传字符串）

        Returns:
            团队信息（成员列表 + inbox 路径）
        """
        # 鲁棒解析：Qwen 有时把 array 序列化为 JSON 字符串传过来
        # 例如 members='["backend-dev", "frontend-dev"]' 而不是 ["backend-dev", "frontend-dev"]
        if isinstance(members, str):
            import json as _json
            try:
                members = _json.loads(members)
            except _json.JSONDecodeError:
                # 尝试逗号分隔: "backend-dev, frontend-dev"
                members = [m.strip().strip("'\"") for m in members.split(",") if m.strip()]

        if not isinstance(members, list) or not members:
            return "Error: members must be a list of agent names, e.g. ['backend-dev', 'frontend-dev']"

        # 确保 lead 在成员列表中
        if "lead" not in members:
            members = ["lead"] + list(members)

        paths = self._queue.setup_team(members)

        lines = [f"Team created with {len(members)} members:"]
        for name in members:
            lines.append(f"  - {name}: {paths[name]}")
        lines.append("")
        lines.append("Workers can use SendMessage(to='lead', content='...') to report results.")
        lines.append("Lead can use ReadInbox() to check messages from workers.")

        return "\n".join(lines)


# ===========================================================================
# SendMessage 工具 —— Agent 间消息传递
# ===========================================================================

class SendMessageTool(Tool):
    """
    发送消息给其他团队成员。

    这是 Team 模式的核心通信原语。对应 CC 的 SendMessage 工具。

    使用模式：
    - Worker 完成任务后: SendMessage(to="lead", content="API ready. Files: ...")
    - Lead 给 Worker 指示: SendMessage(to="backend-dev", content="Fix the API...")

    在我们的 MVP 中，由于 Agent 调用是同步的（Lead 等待 Worker 完成），
    Worker 的 SendMessage 实际上在 Worker 返回前执行，Lead 在下一步才读取。
    消息的价值不在于实时性，而在于：
    1. 消息持久化在文件系统，可被审计/检查
    2. 多个 Worker 的消息会累积在 Lead 的 inbox，一次性读取
    3. 演示了"通信即工具"的设计哲学
    """

    def __init__(self, queue: MessageQueue, agent_id: str):
        super().__init__(
            name="SendMessage",
            description=(
                "Send a message to another team member. "
                "Workers MUST use this to report results back to the lead. "
                "The message is written to the recipient's file-based inbox."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": (
                            "Recipient agent name (e.g. 'lead')"
                        )
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Message content: your results summary, "
                            "file paths created/modified, status report"
                        )
                    }
                },
                "required": ["to", "content"]
            }
        )
        self._queue = queue
        self._agent_id = agent_id

    def execute(self, to: str, content: str) -> str:
        """
        发送消息。

        Args:
            to: 接收者名称
            content: 消息内容

        Returns:
            发送确认或错误信息
        """
        success = self._queue.send(
            from_id=self._agent_id,
            to_id=to,
            content=content
        )

        if success:
            return (
                f"Message sent from '{self._agent_id}' to '{to}' "
                f"({len(content)} chars)"
            )
        else:
            return (
                f"Error: Cannot send message to '{to}'. "
                f"Inbox not found. Did you call TeamCreate first?"
            )


# ===========================================================================
# ReadInbox 工具 —— 读取收件箱
# ===========================================================================

class ReadInboxTool(Tool):
    """
    读取 inbox 中的所有消息。

    CC 没有显式的 ReadInbox 工具——worker 的结果通过 tool_result 自动传回 lead。
    我们加这个工具是为了让消息流更可见：
    - Lead 主动调用 ReadInbox，而不是被动收到
    - 输出中包含发送者、时间戳、消息内容
    - 教学时可以对比"工具返回值传递"和"消息队列传递"两种模式
    """

    def __init__(self, queue: MessageQueue, agent_id: str):
        super().__init__(
            name="ReadInbox",
            description=(
                "Read all messages in your inbox from other team members. "
                "Returns messages and clears the inbox. "
                "Use this after worker agents complete to see their results."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self._queue = queue
        self._agent_id = agent_id

    def execute(self) -> str:
        """
        读取并清空 inbox。

        Returns:
            格式化的消息列表，或 "No new messages"
        """
        messages = self._queue.read_inbox(self._agent_id)

        if not messages:
            return "No new messages in inbox."

        lines = [f"{len(messages)} new message(s):"]
        for i, msg in enumerate(messages, 1):
            from_id = msg.get("from", "unknown")
            timestamp = msg.get("timestamp", "")
            content = msg.get("content", "")
            # 截取时间到秒
            if "T" in timestamp:
                timestamp = timestamp.split("T")[1][:8]
            lines.append(f"\n[{i}] From: {from_id} ({timestamp})")
            lines.append(content)

        return "\n".join(lines)


# ===========================================================================
# 工具注册函数
# ===========================================================================

def get_team_tools(queue: MessageQueue, agent_id: str = "lead") -> Dict[str, Tool]:
    """
    返回 Team 通信工具字典。

    工具可见性由 agent 角色决定：
    - Lead: TeamCreate + SendMessage + ReadInbox（完整工具集）
    - Worker: 只有 SendMessage（只能发消息给 lead）

    这个角色约束不是提示词层面的"请不要用"，
    而是架构层面的"工具不存在"——Worker 的工具列表里
    根本没有 TeamCreate 和 ReadInbox。
    这就是 harness 约束的体现。

    Args:
        queue: 共享的消息队列实例
        agent_id: 当前 agent 的名称（"lead" 或 worker 名）

    Returns:
        {工具名: 工具对象} 字典
    """
    tools: Dict[str, Tool] = {
        "SendMessage": SendMessageTool(queue, agent_id),
    }
    if agent_id == "lead":
        tools["TeamCreate"] = TeamCreateTool(queue)
        tools["ReadInbox"] = ReadInboxTool(queue, agent_id)
    return tools
