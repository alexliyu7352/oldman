import multiprocessing as mp
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from oldman.logging import logger
from oldman.tasks.base import BaseTask, TaskStatus
from oldman.tasks.communication import CommunicationManager
from oldman.tasks.messages import MessageType, TaskMessage
from oldman.tasks.simple import BackgroundTaskManager

TaskCreator = Callable[[str, dict[str, Any]], BaseTask]


class BaseWorker(ABC):
    """简洁的Worker基类 - 只负责进程间通信和任务执行"""

    def __init__(self, worker_id: int, task_queue: mp.Queue):
        self.worker_id = worker_id
        self.comm_manager = CommunicationManager()
        self.running = False

        # 内置任务管理器。注意 BackgroundTaskManager 是进程级单例（`@singleton_adv`）：
        # Worker 今天跑在独立进程里，所以和 Web 进程的那个互不干扰；哪天有人在 Web 进程
        # 内创建 Worker，两者就会共享同一个管理器，包括它的停机状态。
        self.task_manager = BackgroundTaskManager()

        # 任务创建器注册表 - 简化类型
        self.task_creators: dict[str, TaskCreator] = {}
        # 任务实例
        self.tasks: dict[str, BaseTask] = {}
        # 设置通信
        self.comm_manager.register_queue(task_queue)
        self._register_handlers()

    def register_task_creator(self, task_type: str, creator: TaskCreator):
        """注册任务创建器 - 不再是async"""
        self.task_creators[task_type] = creator
        logger.debug(f"Worker {self.worker_id} 注册任务创建器: {task_type}")

    def _register_handlers(self):
        """注册消息处理器"""
        self.comm_manager.register_handler(MessageType.TASK_START, self._handle_task_start)
        self.comm_manager.register_handler(MessageType.TASK_STOP, self._handle_task_stop)
        self.comm_manager.register_handler(MessageType.SHUTDOWN, self._handle_shutdown)

    async def start(self):
        """启动worker"""
        self.running = True
        logger.info(f"Worker {self.worker_id} 启动，PID: {mp.current_process().pid}")

        try:
            # 启动通信
            await self.comm_manager.setup()

            # 启动内置任务管理器
            await self.task_manager.start_all()

            # 子类初始化并注册任务类型
            await self.initialize()

            # 启动消息循环
            await self.comm_manager.start_message_loop()
        finally:
            await self.cleanup()

    @abstractmethod
    async def initialize(self):
        """子类初始化 - 在这里注册任务创建器"""
        pass

    async def _handle_task_start(self, message: TaskMessage):
        """处理任务启动"""
        try:
            task_id = message.task_id
            task_data = message.task_data or {}

            # 获取任务类型
            task_type_name = task_data.get("task_type", "default")

            # 查找对应的任务创建器
            if task_type_name not in self.task_creators:
                raise ValueError(f"未注册的任务类型: {task_type_name}")

            # 修正：直接调用创建器，不使用await（因为不再是async）
            creator = self.task_creators[task_type_name]
            task_instance = creator(task_id, task_data)
            # 添加到内置任务管理器
            self.task_manager.add_task(
                name=task_id,
                coro_func=task_instance.execute,  # 直接传递execute方法
                task_type=message.task_type,
                restart_delay=message.restart_delay,
                max_restarts=message.max_restarts,
                auto_remove_on_complete=message.auto_remove_on_complete,
            )

            # 启动任务
            success = await self.task_manager.start_task(task_id)

            if success:
                self.tasks[task_id] = task_instance
                task_instance.update_status(TaskStatus.RUNNING)
                logger.info(f"Worker {self.worker_id} 启动任务: {task_id} (类型: {task_type_name})")
            else:
                logger.error(f"Worker {self.worker_id} 启动任务失败: {task_id}")

        except Exception as e:
            logger.error(f"Worker {self.worker_id} 处理任务启动失败: {e}")

    async def _handle_task_stop(self, message: TaskMessage):
        """处理任务停止"""
        try:
            task_id = message.task_id
            if task_id in self.tasks:
                self.tasks[task_id].update_status(TaskStatus.STOPPED)
                if task := self.tasks.pop(task_id, None):
                    await task.cleanup()
            success = await self.task_manager.remove_task(task_id)
            if success:
                logger.info(f"Worker {self.worker_id} 停止任务: {task_id}")
            else:
                logger.warning(f"Worker {self.worker_id} 停止任务失败: {task_id}")

        except Exception as e:
            logger.error(f"Worker {self.worker_id} 处理任务停止失败: {e}")

    async def _handle_shutdown(self, message: TaskMessage):
        """处理关闭信号"""
        logger.info(f"Worker {self.worker_id} 收到关闭信号")
        self.running = False
        self.comm_manager.stop()

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """获取任务状态"""
        return self.task_manager.get_task_status(task_id)

    def get_all_task_status(self) -> dict[str, dict[str, Any]]:
        """获取所有任务状态"""
        return self.task_manager.get_all_status()

    async def cleanup(self):
        """清理资源"""
        logger.info(f"Worker {self.worker_id} 开始清理")
        for task_id, task in self.tasks.items():
            try:
                task.update_status(TaskStatus.STOPPED)
                await task.cleanup()
                logger.info(f"Worker {self.worker_id} 清理任务: {task_id}")
            except Exception as e:
                logger.error(f"Worker {self.worker_id} 清理任务失败: {task_id}, 错误: {e}")
        try:
            # 停止所有任务
            await self.task_manager.stop_all()
        except Exception as e:
            logger.error(f"Worker {self.worker_id} 停止任务管理器失败: {e}")

        self.tasks.clear()
        # 清理通信
        self.comm_manager.cleanup()
        logger.info(f"Worker {self.worker_id} 清理完成")
