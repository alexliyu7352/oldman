from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

import msgspec

from oldman.serializers import MsgspecModel
from oldman.tasks.base import TaskType


class MessageType(StrEnum):
    # 任务控制消息
    TASK_START = "task_start"
    TASK_STOP = "task_stop"
    # 系统控制消息
    SHUTDOWN = "shutdown"


class TaskMessage(MsgspecModel, kw_only=True):
    """统一的任务消息 - 简化版本"""

    type: MessageType
    task_id: str
    timestamp: float = msgspec.field(default_factory=time.time)
    message_id: str = msgspec.field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")

    # 任务相关字段
    worker_id: int = -1
    task_data: dict[str, Any] | None = None
    error: str | None = None

    # 使用统一枚举，不再硬编码字符串
    task_type: TaskType = TaskType.PERSISTENT
    restart_delay: int = 30
    max_restarts: int = 3
    auto_remove_on_complete: bool = False
