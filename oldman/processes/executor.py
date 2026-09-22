"""Run short-lived Python callables in isolated Billiard spawn processes.

@author:alex
@date:2024/12/25
@time:17:20
"""

__author__ = "alex"

import asyncio
import contextlib
import logging
import os
import signal
import sys
import threading
import time
import traceback
from asyncio import Semaphore as AsyncSemaphore
from queue import Empty
from typing import Any, TextIO, cast

import billiard
import billiard.spawn
import pyprctl

from oldman.logging import ChildLoggingContext, logger, resolve_child_logging_context


class ProcessTimeoutError(Exception):
    """Because every timeout deserves its moment in the exception spotlight"""

    pass


_BILLIARD_SPAWN_PREPARATION_LOCK = threading.Lock()


def _read_process_result(result_queue: Any, stopped: threading.Event, timeout: float) -> Any:
    """Keep one Queue reader interruptible between reads, without changing its payload."""
    deadline = time.monotonic() + timeout
    while not stopped.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Empty
        try:
            return result_queue.get(timeout=min(0.1, remaining))
        except Empty:
            pass
    return None


def _start_spawn_process(process: Any) -> None:
    """Start Billiard spawn safely from a parent that was itself spawned."""
    with _BILLIARD_SPAWN_PREPARATION_LOCK:
        main_module = sys.modules.get("__main__")
        main_spec = getattr(main_module, "__spec__", None)
        main_name = getattr(main_module, "__name__", None)
        spec_name = getattr(main_spec, "name", None)
        if "__mp_main__" not in {main_name, spec_name}:
            process.start()
            return

        main_path = getattr(main_module, "__file__", None)
        if main_path is None:
            raise RuntimeError(
                "Billiard spawn from __mp_main__ requires an importable main file"
            )

        # Billiard 4.2 treats ``__mp_main__`` as an importable module name.
        # Python's own nested-spawn path instead reloads the original file.
        original_get_preparation_data = billiard.spawn.get_preparation_data

        def get_preparation_data(process_name: str) -> dict[str, Any]:
            """Translate Billiard's invalid nested-main name into its source path."""
            data = original_get_preparation_data(process_name)
            if data.get("init_main_from_name") == "__mp_main__":
                data.pop("init_main_from_name")
                data["init_main_from_path"] = os.path.abspath(main_path)
            return data

        billiard.spawn.get_preparation_data = get_preparation_data
        try:
            process.start()
        finally:
            billiard.spawn.get_preparation_data = original_get_preparation_data


class ParentLogPipeReader(threading.Thread):
    """
    运行在主进程的线程。
    直接从 OS 管道读取子进程的原始 stdout/stderr，并透传到指定控制台流。
    """

    def __init__(self, connection: Any, stream: TextIO, prefix: str = "") -> None:
        """Bind one spawn-transferable pipe endpoint to the parent console."""
        super().__init__(daemon=True)  # 设为守护线程，父进程死则死
        self.connection = connection
        self.stream = stream
        self.prefix = prefix

    def run(self) -> None:
        """Forward raw lines without converting them into structured LogRecords."""
        reader_fd = -1
        try:
            # Connection 只负责把 FD 安全传过 spawn；实际负载仍是逐行文本。
            reader_fd = os.dup(self.connection.fileno())
            self.connection.close()
            with os.fdopen(
                reader_fd,
                "r",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            ) as reader:
                reader_fd = -1
                for line in reader:
                    self.stream.write(f"{self.prefix}{line}")
                    self.stream.flush()
        except (ValueError, OSError):
            # 管道被关闭 (子进程结束)，退出循环
            pass
        except Exception as e:
            # 防止线程静默崩溃，打印到 stderr
            print(f"Log pipe reader error: {e}", file=sys.__stderr__)
        finally:
            self.connection.close()
            if reader_fd >= 0:
                os.close(reader_fd)


class AsyncProcessManager:
    """
    管理按请求创建的短生命周期异步任务进程。

    特性:
    - 支持并发控制（workers 限制）
    - 自动超时管理
    - 优雅关闭机制
    - 原始 stdout/stderr 转发到父进程控制台
    - 结构化日志沿用框架子进程日志上下文
    - 父进程死亡自动退出
    - 固定使用 spawn，禁止复制父进程的连接池、锁和后台线程

    示例:
        manager = AsyncProcessManager(workers=3)
        result = await manager.run_with_timeout(
            target=my_function,
            args=(arg1, arg2),
            _timeout=30
        )
        await manager.shutdown()
    """

    def __init__(
        self,
        workers: int = 1,
        logging_context: ChildLoggingContext | None = None,
    ) -> None:
        """
        初始化进程管理器

        Args:
            workers: 同时运行的最大进程数
        """
        # 私有上下文不改变宿主应用的全局启动方式。
        self._process_context: Any = cast(Any, billiard).get_context("spawn")
        # 使用 Set 跟踪所有活动进程。
        self.active_processes: set[tuple[Any, asyncio.Task[None]]] = set()
        # 使用 Event 标记是否正在关闭
        self.shutting_down = asyncio.Event()
        # 可以同时运行的进程数
        self.workers = workers
        # 使用 asyncio.Semaphore 控制并发
        self.semaphore = AsyncSemaphore(workers)
        self._logging_context = logging_context

        # 移除 self.log_queue (它是死锁之源)
        # 移除 self.log_consumer_task (不再需要)

    async def _monitor_process(self, process: Any, _timeout: int) -> None:
        """
        监控进程执行状态

        Args:
            process: 要监控的进程
            _timeout: 超时时间（秒）
        """
        try:
            start_time = time.time()
            while process.is_alive():
                # 检查是否超时或正在关闭
                elapsed = time.time() - start_time
                if self.shutting_down.is_set() or (elapsed > _timeout):
                    logger.warning(f"Process {process.pid} timeout/shutdown, terminating...")
                    process.terminate()

                    # 等待一小段时间看是否退出
                    wait_time = 0.0
                    while process.is_alive() and wait_time < 2.0:
                        await asyncio.sleep(0.1)
                        wait_time += 0.1

                    # 如果还活着，强制杀死
                    if process.is_alive():
                        logger.error(f"进程 {process.pid} 未能正常终止，强制杀死")
                        try:
                            os.kill(process.pid, signal.SIGKILL)  # type: ignore
                        except ProcessLookupError:
                            pass
                    if time.time() - start_time > _timeout:
                        raise ProcessTimeoutError(f"Process exceeded timeout of {_timeout} seconds")
                    break

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # Cancellation owns this child too; terminate before waiting for join.
            if process.is_alive():
                process.terminate()
            raise
        finally:
            if process.pid is not None:  # 只有启动过的进程才有 pid
                try:
                    # 等待进程退出（最多 5 秒）
                    await asyncio.to_thread(process.join, timeout=5)
                except Exception as e:
                    logger.error(f"进程 {process.pid} join 失败: {e}")

                # 如果还活着，最后尝试强制杀死
                if process.is_alive():
                    logger.error(f"Process {process.pid} did not exit, force killing")
                    try:
                        os.kill(process.pid, signal.SIGKILL)  # type: ignore
                    except ProcessLookupError:
                        pass  # 进程已经不存在了
                    except Exception as e:
                        logger.error(f"强制杀死进程 {process.pid} 失败: {e}")

                    # 再次等待
                    try:
                        await asyncio.to_thread(process.join, timeout=1)
                    except Exception:
                        pass

    @contextlib.asynccontextmanager
    async def _process_lifecycle(self, process: Any, _timeout: int):
        """
        监控一个已经启动的进程，并向调用方传播超时。

        Args:
            process: 要管理的进程
            _timeout: 超时时间（秒）
        """
        if process.pid is None:
            raise RuntimeError("cannot monitor a process before it starts")
        monitor_task = asyncio.create_task(self._monitor_process(process, _timeout))
        self.active_processes.add((process, monitor_task))
        try:
            yield
        except asyncio.CancelledError:
            # Do not turn caller cancellation into a later process timeout.
            monitor_task.cancel()
            raise
        finally:
            try:
                # 即使任务已经结束也必须 await，否则超时异常会被静默丢弃。
                await monitor_task
            except ProcessTimeoutError:
                raise
            except Exception as e:
                logger.error(f"监控任务异常: {e}")
            finally:
                self.active_processes.discard((process, monitor_task))

    def _resolve_logging_context(self) -> ChildLoggingContext | None:
        """Resolve the active application context immediately before Process.start()."""
        return resolve_child_logging_context(self._logging_context)

    @staticmethod
    async def _start_process(process: Any) -> None:
        """Finish an in-flight spawn before cancellation starts process cleanup."""
        start_task = asyncio.create_task(
            asyncio.to_thread(_start_spawn_process, process)
        )
        try:
            await asyncio.shield(start_task)
        except asyncio.CancelledError:
            # A thread cannot be cancelled. Waiting here prevents it from starting
            # a child after run_with_timeout() has already finished cleanup.
            with contextlib.suppress(Exception):
                await start_task
            raise

    @staticmethod
    def _target_wrapper(
        target_func: Any,
        args: tuple[Any, ...],
        result_queue: Any,
        pipe_writer: Any,
        logging_context: ChildLoggingContext | None,
        logging_disable_level: int,
    ) -> None:
        """Install child I/O and logging before invoking one picklable target."""
        original_parent_pid = os.getppid()

        # 恢复信号处理为默认行为
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        # 设置父进程死亡信号
        pyprctl.set_pdeathsig(signal.SIGTERM)

        # 检查父进程是否已经退出
        if os.getppid() != original_parent_pid:
            os._exit(1)

        child_runtime = None
        try:
            # Billiard Connection 负责跨 spawn 传递 FD，子进程随后只使用
            # 标准文本流，避免把原始输出编码成多进程消息协议。
            pipe_write_fd = pipe_writer.fileno()
            os.dup2(pipe_write_fd, 1)
            os.dup2(pipe_write_fd, 2)
            pipe_writer.close()
            sys.stdout = os.fdopen(
                1,
                "w",
                encoding="utf-8",
                buffering=1,
                closefd=False,
            )
            sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)

            # Structured Python records use the same explicit protocol as every
            # other framework child; only raw stdout/stderr remains on this pipe.
            logging.disable(logging_disable_level)
            if logging_context is not None:
                child_runtime = logging_context.install()

            # 执行任务
            res = target_func(*args)
            result_queue.put(res)

        except Exception:
            traceback.print_exc()
            result_queue.put(None)

        finally:
            if child_runtime is not None:
                child_runtime.close()
            # 清理
            try:
                if sys.stdout:
                    sys.stdout.flush()
                if sys.stderr:
                    sys.stderr.flush()
            except Exception:
                pass
            pipe_writer.close()
            sys.stdout = None
            sys.stderr = None
            # 关闭两个副本后父进程才能收到 EOF。
            try:
                os.close(1)
                os.close(2)
            except Exception:
                pass

    async def run_with_timeout(self, target, args=(), _timeout: int = 30) -> dict | None:
        """Run one import-safe, pickleable callable and enforce its timeout."""
        if self.shutting_down.is_set():
            return None

        logger.info(f"当前任务数量: {len(self.active_processes)}, 是否需要等待: {len(self.active_processes) >= self.workers}")
        # 异步等待信号量
        await self.semaphore.acquire()
        logger.info(f"等待结束, 当前任务数量: {len(self.active_processes)}")

        process = None
        pipe_reader = None
        pipe_writer = None
        reader_thread = None
        result_queue = None
        result_task = None  # 初始化为 None，方便 finally 清理
        result_stopped = threading.Event()

        try:
            if self.shutting_down.is_set():
                return None

            # 原始 os.pipe() 的整数 FD 无法可靠跨 spawn 传递，因此所有
            # 进程原语都必须来自同一个 Billiard spawn 上下文。
            pipe_reader, pipe_writer = self._process_context.Pipe(duplex=False)

            prefix = "[Worker-Pending] "
            console_stream = sys.stdout if sys.stdout is not None else sys.__stdout__
            if console_stream is None:
                raise RuntimeError("no parent console stream is available for child output")
            reader_thread = ParentLogPipeReader(
                pipe_reader,
                console_stream,
                prefix=prefix,
            )
            reader_thread.start()
            # 读取线程从此独占读端，管理协程不得再关闭同一个对象。
            pipe_reader = None

            # 每次调用独占一个结果 Queue；超时或 SIGKILL 不会污染下一次调用。
            result_queue = self._process_context.Queue()

            # spawn 要求 target、args 和日志上下文都可序列化；不再回退到 fork。
            logging_context = self._resolve_logging_context()
            logging_disable_level = logging.root.manager.disable
            process = self._process_context.Process(
                target=self._target_wrapper,
                args=(
                    target,
                    args,
                    result_queue,
                    pipe_writer,
                    logging_context,
                    logging_disable_level,
                ),
                daemon=True,
            )

            logger.info(f"Process daemon status before start: {process.daemon}")
            # 监控只能在 start 完成后创建；否则监控协程可能先看到
            # is_alive() == False 并提前退出，使超时永久失效。
            await self._start_process(process)
            pipe_writer.close()
            pipe_writer = None
            # This parent is a consumer only. Billiard exposes no public half-close;
            # release its unused write endpoint so a killed producer yields EOF,
            # including when it dies halfway through a large result frame.
            result_queue._writer.close()

            async with self._process_lifecycle(process, _timeout):
                # 更新日志前缀 (有了 PID)
                reader_thread.prefix = f"[Worker-{process.pid}] "
                # 必须并行读取结果，防止大结果填满 Queue 的底层管道。
                # 防止结果数据量过大导致 Pipe 满载，从而引发父子进程死锁
                result_task = asyncio.create_task(
                    asyncio.to_thread(_read_process_result, result_queue, result_stopped, _timeout + 5)
                )

                # 4. 监控进程存活
                while process.is_alive():
                    if self.shutting_down.is_set():
                        # result_task 会在 finally 中被取消
                        return None
                    await asyncio.sleep(0.1)

                # 5. 检查退出状态
                if process.exitcode != 0:
                    logger.error(f"Process {process.pid} exited with code {process.exitcode}")
                    return None

                # 6. 获取结果
                try:
                    # 此时进程已死，结果应该已经在 queue 里或者已经被 task 读到了
                    result = await asyncio.shield(result_task)
                    logger.info(f"Process {process.pid} finished with result")
                    return result
                except Exception:
                    # 如果 task 抛出 Empty (超时) 或者被 Cancel
                    logger.warning(f"Process {process.pid} finished but queue is empty or error")
                    return {}

        except ProcessTimeoutError:
            # 超时已经在 monitor 中处理过 kill 了，这里只需要记录
            logger.error(f"Process timed out after {_timeout} seconds")
            raise

        except Exception as e:
            # 捕获常规异常，记录日志
            logger.error(f"Error during process execution: {repr(e)}")
            raise e

        finally:
            # 1. 确保释放信号量 (解决死锁隐患)
            self.semaphore.release()

            # Cancelling to_thread does not stop its thread. Signal and join the
            # short-poll reader before closing its Queue or leaving the loop.
            result_stopped.set()
            if result_task is not None:
                with contextlib.suppress(Exception):
                    await result_task

            # 关闭尚未转交出去的管道端点；正常路径的读端归读取线程所有。
            if pipe_writer is not None:
                pipe_writer.close()
            if pipe_reader is not None:
                pipe_reader.close()

            # 兜底清理：无论异常、取消还是正常结束，都不留下任务进程。
            # 只要进程还活着，就必须弄死，防止孤儿进程
            if process and process.is_alive():
                logger.warning(f"Cleaning up orphan process {process.pid} in finally block")
                try:
                    process.terminate()
                except Exception:
                    pass

                # 给它 0.1 秒喘息
                await asyncio.sleep(0.1)

                if process.is_alive():
                    try:
                        logger.error(f"Force killing process {process.pid}")
                        os.kill(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception as e:
                        logger.error(f"Failed to kill process: {e}")

                await asyncio.to_thread(process.join, timeout=1)

            # 被 SIGKILL 的生产者不能参与 Queue 的线程回收；直接关闭本次
            # 调用的端点即可，下一次调用会创建全新的 Queue。
            if result_queue is not None:
                with contextlib.suppress(Exception):
                    result_queue.cancel_join_thread()
                with contextlib.suppress(Exception):
                    result_queue.close()

            # 子进程和父进程写端都关闭后，等待控制台转发读到 EOF。
            if reader_thread is not None and reader_thread.is_alive():
                await asyncio.to_thread(reader_thread.join, 1)

    async def shutdown(self):
        """
        优雅关闭所有活动进程

        步骤:
        1. 设置关闭标志
        2. 终止所有活动进程（SIGTERM）
        3. 等待进程退出（最多 5 秒）
        4. 强制杀死仍存活的进程（SIGKILL）
        5. 清理资源
        """
        logger.info("开始优雅关闭进程管理器")
        self.shutting_down.set()

        if not self.active_processes:
            logger.info("没有活动进程，直接退出")
            return

        # 终止所有活动进程
        shutdown_tasks = []
        for process, monitor_task in list(self.active_processes):
            if process.is_alive():
                logger.info(f"终止进程 {process.pid}")
                try:
                    process.terminate()
                except Exception as e:
                    logger.error(f"终止进程 {process.pid} 失败: {e}")
                await asyncio.sleep(0.1)
                if process.is_alive():
                    try:
                        os.kill(process.pid, signal.SIGKILL)  # type: ignore
                    except ProcessLookupError:
                        pass

            # 让监视者谢幕，但不需要等待它完成 process.join()
            if not monitor_task.done():
                monitor_task.cancel()
                # 我们只关心取消操作本身，不等待它完成
                # 因为 monitor_task 中的 join() 可能会和后面的 join() 打架
                shutdown_tasks.append(monitor_task)

        # 等待所有监控任务完成
        if shutdown_tasks:
            try:
                # 给它们一个短暂的告别时间
                await asyncio.wait(shutdown_tasks, timeout=1.0)
            except asyncio.CancelledError:
                pass  # 优雅地假装什么都没发生

        # 强制杀死仍存活的进程
        for process, _ in list(self.active_processes):
            # 只 join 已启动的进程
            if process.pid is not None:
                try:
                    await asyncio.to_thread(process.join, timeout=5)
                    if process.is_alive():
                        logger.warning(f"Process {process.pid} still alive after join timeout")
                        try:
                            os.kill(process.pid, signal.SIGKILL)  # type: ignore
                        except ProcessLookupError:
                            pass
                except Exception as e:
                    logger.error(f"Error while waiting for process {process.pid} to join: {repr(e)}")

        self.active_processes.clear()
        logger.info("进程管理器已关闭")
