"""
@author:alex
@date:2025/9/30
@time:05:06
"""

__author__ = "alex"

import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from oldman.logging import logger


class TaskType(StrEnum):
    PERSISTENT = "persistent"  # 持久任务，异常时重启
    ONE_TIME = "one_time"  # 一次性任务，完成后自动销毁


class TaskStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    RESTARTING = "restarting"
    COMPLETED = "completed"


class BaseTask(ABC):
    """简化的任务基类 - 只包含核心功能"""

    def __init__(self, task_id: str, **kwargs):
        self.task_id = task_id
        self.created_at = time.time()
        self.status = TaskStatus.STOPPED

    @abstractmethod
    async def execute(self) -> Any:
        """执行任务的抽象方法"""
        pass

    def get_running_status(self) -> dict:
        return {}

    async def cleanup(self) -> None:
        """任务清理（默认实现，子类可重写）"""
        logger.debug(f"任务 {self.task_id} 清理完成")

    def update_status(self, status: TaskStatus) -> None:
        """更新任务状态"""
        self.status = status
