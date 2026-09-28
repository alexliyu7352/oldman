__author__ = "alex"

import asyncio
import threading
import weakref
from collections.abc import Callable, Coroutine
from typing import Any


def new_event_loop() -> asyncio.AbstractEventLoop:
    """新建一个事件循环：装了 uvloop 就用 uvloop，否则用标准库的。

    用法：``asyncio.run(main(), loop_factory=new_event_loop)``，或
    ``asyncio.Runner(loop_factory=new_event_loop)``。框架启动服务、执行命令时建的循环都用它。

    Python 3.14 弃用、3.16 删除了全局事件循环策略，不能再用一次调用把整个进程之后新建的循环都换成
    uvloop，只能在建循环的地方指定。
    """
    try:
        import uvloop
    except ImportError:
        return asyncio.new_event_loop()
    return uvloop.new_event_loop()


async def interruptible_sleep(delay: float, stop: asyncio.Event) -> bool:
    """睡 delay 秒，stop 一被设置就提前醒来。给靠标志位停止的长循环用::

        while True:
            ...
            if not await interruptible_sleep(600, stop):
                break

    返回 True 表示睡满了 delay 秒，False 表示 stop 已被设置（调用时已设置也立即返回 False）。
    任务被取消时 CancelledError 照常抛出、不吞掉；想让取消也变成正常退出，用 safe_cancellable_sleep。
    别的线程要叫醒它，用 ``loop.call_soon_threadsafe(stop.set)``；线程里的循环用
    ``threading.Event.wait(timeout)``，效果相同。
    """
    if stop.is_set():
        return False
    try:
        async with asyncio.timeout(delay):
            await stop.wait()
    except TimeoutError:
        return True
    return False


async def safe_cancellable_sleep(delay: float, log_cancel: bool = True) -> bool:
    """睡 delay 秒；睡眠期间任务被取消时**吞掉取消**，返回 False，让循环记日志后正常结束::

        while True:
            ...
            if not await safe_cancellable_sleep(600):
                break

    返回 True 表示睡满了 delay 秒，False 表示睡眠期间被取消。吞掉时用 ``Task.uncancel()`` 把任务的取消计数
    清零（被取消几次就撤销几次），之后的收尾代码里 ``TaskGroup`` 照常工作：计数不为零时，Python 3.13 起收尾里
    有子任务失败的 TaskGroup 会整组以 CancelledError 结束，而不是抛出子任务的异常。

    只用在后台任务最外层的循环里，而且停止它的一方只负责取消、不需要知道它是被取消的：

    - 取消落在循环里别的 await 上时照常抛出；那种情况也要正常退出，就给那段代码加
      ``except asyncio.CancelledError: ...; break``。
    - 不要放在 ``asyncio.timeout`` / ``asyncio.wait_for`` 里面：超时靠取消实现，取消被吞掉后不会抛 TimeoutError，
      调用方以为正常完成。
    - 不要用在别人 await 等它结果的函数里，调用方分不出“完成了”和“被取消了”。

    这些情况用 ``asyncio.sleep``，让取消照常抛出；靠标志位停止的循环用 interruptible_sleep。

    Args:
        delay: 睡眠时间（秒）
        log_cancel: 被取消时是否记一条 warning 日志
    """
    try:
        await asyncio.sleep(delay)
        return True
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None:
            while task.cancelling():
                task.uncancel()
        if log_cancel:
            from oldman.logging import logger

            logger.warning("睡眠被取消（计划睡眠 %s 秒）", delay)
        return False


_thread_runners = threading.local()


def _close_runner(runner: asyncio.Runner) -> None:
    """关闭一个线程的 runner：线程结束时在那个线程里调用，进程退出时对仍在的线程调用。

    循环还在运行（进程退出时有线程停在 run_sync 里）就不动它：从这里关闭会在别的线程底下取消它的任务。
    关闭失败只记日志，不影响其他 runner。
    """
    try:
        if not runner.get_loop().is_running():
            runner.close()
    except Exception:
        from oldman.logging import logger

        logger.exception("关闭 run_sync 的事件循环失败")


class _ThreadRunner:
    """存在线程本地变量里的 runner。线程结束时 Python 丢弃它的本地变量，finalize 随即在那个线程里关闭 runner；
    进程退出时 finalize 关闭仍在运行的线程留下的 runner。"""

    def __init__(self) -> None:
        self.runner = asyncio.Runner(loop_factory=new_event_loop)
        # 现在就建好循环：关闭前要看它是否在运行，get_loop() 不能在那时才新建一个。
        self.runner.get_loop()
        weakref.finalize(self, _close_runner, self.runner)


def run_sync[**P, R](func: Callable[P, Coroutine[Any, Any, R]], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """在同步代码里调用异步函数，等它执行完并返回结果。

    - 当前线程没有在运行的事件循环（脚本、同步命令、测试、普通线程）：在这个线程固定的一个事件循环上执行。
      多次调用共用它，缓存在循环上的资源（连接池等）在线程结束前一直有效。线程结束时关闭它的循环，进程退出时
      关闭仍在运行的线程的循环（循环正在运行的除外）。每个新线程第一次调用都要新建循环，频繁新建线程的程序
      用固定的线程池更省。
    - 当前线程正在运行事件循环：抛 RuntimeError。在这里同步等待只会卡住整个事件循环；把调用方改成 async
      直接 await，或者把同步代码放进 ``asyncio.to_thread``。

    服务的工作线程里要用服务主循环上的资源（例如数据库连接池）时，这里的循环用不上它们，改用
    ``asyncio.run_coroutine_threadsafe(func(...), 主循环).result()``。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "run_sync() cannot wait for a coroutine on a thread that is running an event loop; "
            "await it instead, or move the synchronous caller into asyncio.to_thread()"
        )
    thread_runner: _ThreadRunner | None = getattr(_thread_runners, "runner", None)
    if thread_runner is None:
        thread_runner = _ThreadRunner()
        _thread_runners.runner = thread_runner
    return thread_runner.runner.run(func(*args, **kwargs))
