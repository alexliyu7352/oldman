"""
@author:alex
@date:2025/9/29
@time:22:36
"""

__author__ = "alex"

import asyncio
import inspect
import multiprocessing as mp
from collections.abc import Awaitable, Callable
from typing import Any

from oldman.logging import logger
from oldman.tasks.messages import MessageType, TaskMessage
from oldman.tasks.queue import AsyncQueue

Handler = Callable[[TaskMessage], Awaitable[Any]]


class CommunicationManager:
    """通信管理器 - 处理进程间通信的底层逻辑"""

    def __init__(self):
        self.queue: AsyncQueue | None = None
        self.message_handlers: dict[MessageType, Handler] = {}
        self._running = False

    def register_queue(self, queue: mp.Queue) -> None:
        """注册单个队列"""
        self.queue = AsyncQueue(queue)
        logger.info("Registering the message queue")

    async def setup(self) -> None:
        """设置队列"""
        if self.queue:
            await self.queue.setup()
            logger.info("Message queue set up")

    def register_handler(self, msg_type: MessageType, handler: Handler) -> None:
        """注册消息处理器 - 直接支持异步"""
        self.message_handlers[msg_type] = handler
        logger.debug(f"Registered handler: {msg_type.value}")

    async def send_message(self, message: TaskMessage) -> None:
        """发送消息"""
        if not self.queue:
            raise RuntimeError("队列未初始化")

        try:
            self.queue.put_nowait(message)
            logger.debug(f"Sending message: {message.type.value}")
        except Exception as e:
            logger.error(f"Sending message failed: {e}")
            raise

    async def start_message_loop(self) -> None:
        """启动消息循环 - 直接支持异步handler"""
        if not self.queue:
            raise RuntimeError("队列未初始化")

        self._running = True
        logger.info("Starting the message loop")

        while self._running:
            try:
                if not self.queue:
                    logger.warning("Message queue is not initialized; stopping the message loop")
                    break
                message = await self.queue.get()
                logger.info(f"Received message: {message.type.value} - task ID: {message.task_id}")
                if message and message.type in self.message_handlers:
                    handler = self.message_handlers[message.type]
                    try:
                        # 直接判断是否为异步函数
                        if inspect.iscoroutinefunction(handler):
                            await handler(message)
                        else:
                            handler(message)
                    except Exception as e:
                        logger.error(f"Handling message {message.type.value} failed: {e}")
                else:
                    logger.warning(f"No handler for message: {message.type.value}")
            except Exception as e:
                logger.error(f"Message loop error: {e}")
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        """停止消息循环"""
        self._running = False
        logger.info("Message loop stopped")

    def cleanup(self) -> None:
        """清理资源"""
        if self.queue:
            self.queue.cleanup()
        logger.info("Communication manager cleaned up")
