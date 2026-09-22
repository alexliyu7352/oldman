"""
@author:alex
@date:2025/9/29
@time:22:34
"""

__author__ = "alex"

import asyncio
import multiprocessing as mp
import queue

from oldman.logging import logger
from oldman.tasks.messages import TaskMessage


class AsyncQueue:
    """基于multiprocessing.Queue的异步队列封装"""

    def __init__(self, queue: mp.Queue):
        self.queue = queue
        self._loop: asyncio.AbstractEventLoop | None = None
        self._data_available: asyncio.Event | None = None
        self._is_setup = False

    async def setup(self) -> None:
        """设置异步读取"""
        if self._is_setup:
            return

        self._loop = asyncio.get_running_loop()
        self._data_available = asyncio.Event()

        try:
            # 注册文件描述符到事件循环
            self._loop.add_reader(self.queue._reader.fileno(), self._data_available.set)  # type: ignore
            self._is_setup = True
            logger.debug("AsyncQueue设置完成")
        except Exception as e:
            logger.error(f"AsyncQueue设置失败: {e}")
            raise

    async def get(self) -> TaskMessage:
        """异步非阻塞获取消息"""
        if not self._is_setup:
            raise RuntimeError("队列未初始化，请先调用setup()")

        while True:
            # 检查是否有数据可读
            try:
                logger.debug("检查队列是否有数据")
                if not self.queue.empty():
                    logger.debug("队列有数据，准备读取")
                    # 获取序列化的数据并解码
                    serialized_data = self.queue.get_nowait()
                    logger.debug("队列数据读取成功，准备反序列化")
                    # 直接使用消息类型的反序列化方法
                    return TaskMessage.from_msgpack(serialized_data)
            except queue.Empty:
                # empty() 和 get_nowait() 之间另一个消费者可能已经取走了这条消息。
                # 这是正常竞态，不是故障：继续等待下一个信号，而不是把它报给调用方。
                pass
            except Exception:
                logger.exception("从队列获取消息失败")
                raise

            # 等待数据可用信号
            assert self._data_available is not None
            await self._data_available.wait()
            self._data_available.clear()

    def put_nowait(self, message: TaskMessage) -> None:
        """非阻塞放入消息"""
        try:
            # 直接使用消息对象的序列化方法
            serialized_data = message.to_msgpack()
            self.queue.put_nowait(serialized_data)
        except Exception as e:
            logger.error(f"队列放入消息失败: {e}")
            raise

    def put_nowait_raw(self, serialized_data: bytes) -> None:
        """直接放入已序列化的数据（用于转发等场景）"""
        try:
            self.queue.put_nowait(serialized_data)
        except Exception as e:
            logger.error(f"队列放入原始数据失败: {e}")
            raise

    def cleanup(self) -> None:
        """清理资源"""
        if self._is_setup and self._loop:
            try:
                self._loop.remove_reader(self.queue._reader.fileno())  # type: ignore
                self._is_setup = False
                logger.debug("AsyncQueue清理完成")
            except Exception as e:
                logger.warning(f"队列清理时出错: {e}")
