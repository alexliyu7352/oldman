import asyncio
import signal
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from oldman.logging import logger


class AsyncTask:
    def __init__(
        self,
        target: Callable[..., Any],
        task_id: str,
        auto_restart: bool = False,
        period: float | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        初始化一个异步任务

        :param target: 要执行的函数
        :param task_id: 任务标识
        :param auto_restart: 如果为 True，则任务在异常退出后自动重启（非周期性任务下默认延时5秒重启）
        :param period: 如果不为 None，则表示任务周期性运行，每次运行完成后等待 period 秒再重新运行
        :param args: 传递给 target 的位置参数
        :param kwargs: 传递给 target 的关键字参数
        """
        self.target = target
        self.task_id = task_id
        self.args = args
        self.kwargs = kwargs
        self.auto_restart = auto_restart
        self.period = period

    def run(self, thread_pool: "ThreadPool") -> None:
        """
        执行一次性、自动重启或周期性目标函数。

        如果任务设置了 auto_restart 或 period，将以循环方式不断执行任务，
        每次运行完成后等待一定时间（如果任务函数内部有无限循环，则必须自己检查 shutdown_event）。

        :param thread_pool: 当前任务所属的线程池实例
        """
        # 如果任务需要周期性或自动重启，则采用循环执行
        if self.auto_restart or self.period is not None:
            # 如果用户未指定周期，则在自动重启时使用默认延时 5 秒
            delay = self.period if self.period is not None else 5
            while not thread_pool.shutdown_event.is_set():
                try:
                    logger.debug(f"[{threading.current_thread().name}] Running task id: {self.task_id}")
                    self.target(*self.args, **self.kwargs)
                except Exception as e:
                    logger.exception(
                        f"Task {self.task_id} failed with exception:\n{repr(e)}",
                        exc_info=True,
                    )
                # 如果任务函数是正常返回或异常退出，都等待 delay 秒后重新运行
                if thread_pool.shutdown_event.is_set():
                    break
                logger.info(f"[{threading.current_thread().name}] Task {self.task_id} finished, " f"waiting {delay} seconds before next run.")
                time.sleep(delay)
        else:
            # 非重复任务：只执行一次
            try:
                logger.debug(f"[{threading.current_thread().name}] Running task id: {self.task_id}")
                self.target(*self.args, **self.kwargs)
            except Exception as e:
                logger.exception(
                    f"Task {self.task_id} failed with exception:\n{repr(e)}",
                    exc_info=True,
                )


class ThreadPool:
    def __init__(self, name: str = "default", max_workers: int = 10) -> None:
        """
        初始化线程池

        :param name: 线程池名称，用于线程命名前缀
        :param max_workers: 最大工作线程数。注意：Python 标准库中没有无限大小的线程池，
                            如果任务数量可能远超过这个值，可考虑使用队列、协程或自定义实现。
        """
        self.pool_name: str = name
        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=self.pool_name)
        self.future_dict: dict[str, Future] = {}
        self.lock: threading.Lock = threading.Lock()
        self.shutdown_event: threading.Event = threading.Event()

    def is_project_thread_running(self, task_id: str) -> bool:
        """
        检查指定任务是否正在运行

        :param task_id: 任务标识
        :return: 如果任务正在运行返回 True，否则返回 False
        """
        future = self.future_dict.get(task_id)
        return bool(future and future.running())

    def check_future(self) -> list[str]:
        """
        检查所有任务状态：
          - 正在运行的任务，其 task_id 将会被添加到返回列表中
          - 已结束的任务将从 future_dict 中移除

        :return: 正在运行的任务 ID 列表
        """
        running_tasks: list[str] = []
        for task_id in list(self.future_dict.keys()):
            future = self.future_dict.get(task_id)
            if future is not None and future.running():
                running_tasks.append(task_id)
            else:
                self.future_dict.pop(task_id, None)
        return running_tasks

    def add_task(
        self,
        task_id: str | None,
        fun: Callable[..., Any],
        *args: Any,
        auto_restart: bool = False,
        period: float | None = None,
        **kwargs: Any,
    ) -> None:
        """
        添加一个任务到线程池中

        :param task_id: 任务标识，若传入 None 或空字符串，则自动生成唯一 ID
        :param fun: 要执行的函数
        :param args: 传递给 fun 的位置参数
        :param auto_restart: 是否在任务异常退出后自动重启（适用于长期后台任务）
        :param period: 如果不为 None，则任务运行完成后等待指定秒数再自动运行一次（周期性任务）
        :param kwargs: 传递给 fun 的关键字参数
        """
        self.check_future()
        if not task_id:
            task_id = f"{self.pool_name}-{uuid.uuid1()}"
        task = AsyncTask(fun, task_id, auto_restart, period, *args, **kwargs)
        future = self.executor.submit(task.run, self)
        self.future_dict[task_id] = future

    def add_periodic_task(
        self,
        task_id: str | None,
        fun: Callable[..., Any],
        period: float,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        添加一个周期性任务。任务运行完成后，会等待 period 秒后自动重新运行。

        :param task_id: 任务标识，若传入 None 或空字符串，则自动生成唯一 ID
        :param fun: 要执行的函数
        :param period: 任务运行完成后的等待时间（秒）
        :param args: 传递给 fun 的位置参数
        :param kwargs: 传递给 fun 的关键字参数
        """
        # 对周期性任务，我们设置 auto_restart 为 True，同时指定 period
        self.add_task(task_id, fun, *args, auto_restart=True, period=period, **kwargs)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        关闭线程池

        :param wait: 是否等待所有任务结束
        :param cancel_futures: 是否取消等待中的任务（Python 3.9+ 支持）
        """
        self.shutdown_event.set()
        self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def wait(self) -> None:
        """
        等待系统发送终止或杀死信号。该方法会阻塞主线程，
        直到收到 SIGINT 或 SIGTERM 信号，然后触发 shutdown_event，
        从而通知所有自动重启或周期性任务退出。

        注意：此方法应在主线程中调用，避免主线程退出导致程序结束。
        """

        def handler(signum, frame):
            logger.info("Received termination signal, shutting down thread pool.")
            self.shutdown_event.set()

        # 注册信号处理函数
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

        logger.info("Thread pool is running. Press Ctrl+C to exit.")
        # 阻塞等待，直到 shutdown_event 被置位
        self.shutdown_event.wait()

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False)
        except Exception:
            pass


async def handle_timeout(task: asyncio.Task[Any], local_timeout: float | int) -> None:
    try:
        await asyncio.wait_for(task, timeout=local_timeout)
    except TimeoutError:
        logger.error("The coroutine took too long, cancelling the task...")
        task.cancel()
