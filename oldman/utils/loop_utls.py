__author__ = "alex"

import asyncio
import functools
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any, ParamSpec, TypeVar

T = TypeVar("T")  # 返回值类型
P = ParamSpec("P")  # 参数类型
R = TypeVar("R")


def use_uvloop() -> None:
    """
    uvloop
    :return:
    """
    try:
        # 声明使用 uvloop 事件循环
        import asyncio

        import uvloop

        if not isinstance(asyncio.get_event_loop_policy(), uvloop.EventLoopPolicy):
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            loop = uvloop.new_event_loop()
            asyncio.set_event_loop(loop)
    except ImportError:
        pass


def ensure_async_context(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, R | Coroutine[Any, Any, R]]:  # noqa: UP047 -- the explicit TypeVar/ParamSpec signature is part of the public API
    """
    装饰一个 async 函数
    同步环境：返回 R（内部 asyncio.run）
    异步环境：返回 Coroutine[Any, Any, R]（调用方应 await）
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | Coroutine[Any, Any, R]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(func(*args, **kwargs))
        else:
            return func(*args, **kwargs)

    return wrapper


async def cancellable_sleep(delay: float) -> bool:
    """
    可取消的睡眠函数

    Args:
        delay: 睡眠时间（秒）

    Returns:
        bool: True表示正常完成睡眠，False表示被取消

    Raises:
        asyncio.CancelledError: 如果任务被取消
    """
    try:
        await asyncio.sleep(delay)
        return True
    except asyncio.CancelledError:
        return False


async def safe_cancellable_sleep(delay: float, log_cancel: bool = True) -> bool:
    """
    安全的可取消睡眠函数，不抛出CancelledError异常

    Args:
        delay: 睡眠时间（秒）
        log_cancel: 是否记录取消日志

    Returns:
        bool: True表示正常完成睡眠，False表示被取消
    """
    try:
        await asyncio.sleep(delay)
        return True
    except asyncio.CancelledError:
        if log_cancel:
            from oldman.logging import logger
            logger.warning(f"睡眠被取消，剩余时间: {delay}秒")
        return False


class AsyncToSync:
    """异步转同步工具类"""

    # 使用线程本地存储来存储每个线程的事件循环
    _thread_locals = threading.local()

    @classmethod
    def get_thread_loop(cls) -> asyncio.AbstractEventLoop | None:
        """获取当前线程的事件循环"""
        return getattr(cls._thread_locals, "loop", None)

    @classmethod
    def set_thread_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """设置当前线程的事件循环"""
        cls._thread_locals.loop = loop

    @classmethod
    def run_async(cls, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """
        在新线程中运行异步函数

        Args:
            func: 异步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            异步函数的返回值

        Raises:
            Exception: 执行过程中的任何异常都会被传递给调用方
        """
        try:
            # 检查当前是否在事件循环中
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # 如果当前线程已经有事件循环在运行，使用新线程
        if running_loop is not None:
            return cls._run_in_new_thread(func, *args, **kwargs)

        # 获取或创建事件循环
        loop = cls.get_thread_loop()
        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cls.set_thread_loop(loop)

        return loop.run_until_complete(func(*args, **kwargs))

    @classmethod
    def _run_in_new_thread(cls, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """在新线程中运行异步函数"""

        def run_in_thread() -> T:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cls.set_thread_loop(loop)
            try:
                result = loop.run_until_complete(func(*args, **kwargs))
                return result
            finally:
                loop.close()
                # 需要先获取None循环再设置，避免类型检查错误
                asyncio.set_event_loop(None)
                if hasattr(cls._thread_locals, "loop"):
                    delattr(cls._thread_locals, "loop")
            # 这行代码在正常情况下不会执行，但确保类型检查器满意
            raise RuntimeError("Unexpected execution path")

        # 使用ThreadPoolExecutor来运行新线程
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    @classmethod
    def sync_method(cls, func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
        """装饰器：将异步方法转换为同步方法"""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return cls.run_async(func, *args, **kwargs)

        return wrapper
