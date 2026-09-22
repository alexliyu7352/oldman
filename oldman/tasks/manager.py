import asyncio
import multiprocessing as mp
import time
from abc import ABC
from typing import Any, Literal

from oldman.logging import ChildLoggingContext, logger, resolve_child_logging_context
from oldman.tasks.base import TaskType
from oldman.tasks.messages import MessageType, TaskMessage
from oldman.tasks.worker import BaseWorker
from oldman.utils.loop_utls import safe_cancellable_sleep


class WorkerInfo:
    """Worker信息"""

    def __init__(self, worker_id: int, process: mp.Process, task_queue: mp.Queue):
        self.worker_id = worker_id
        self.process = process
        self.task_queue = task_queue
        self.start_time = time.time()
        self.restart_count = 0
        self.last_restart = 0
        self.is_healthy = True


class BaseManager(ABC):  # noqa: B024 -- retained source boundary has no abstract hook yet.
    """极简管理器基类 - 只发送任务，不等待结果"""

    def __init__(
        self,
        worker_class: type[BaseWorker],
        num_workers: int = 4,
        max_worker_restarts: int = -1,
        worker_restart_delay: int = 5,
        monitor_interval: int = 60,
        logging_context: ChildLoggingContext | None = None,
        process_start_method: Literal["spawn", "forkserver", "fork"] = "spawn",
    ):
        """Configure persistent workers and their isolated multiprocessing context."""
        self.worker_class = worker_class
        self.num_workers = num_workers
        self.max_worker_restarts = max_worker_restarts
        self.worker_restart_delay = worker_restart_delay
        self.monitor_interval = monitor_interval
        self._logging_context = logging_context
        # BaseApplication already owns background threads by the time workers
        # start. The private context avoids changing the embedding application's
        # global start method, while the spawn default avoids multithreaded fork.
        # Typeshed's BaseContext omits the concrete contexts' runtime Process
        # factory, so this boundary deliberately uses Any.
        self._mp_context: Any = mp.get_context(process_start_method)

        # Worker管理
        self.workers: dict[int, WorkerInfo] = {}
        self.task_counter = 0
        self._round_robin_counter = 0
        self.running = False

        # 监控任务
        self._monitor_task: asyncio.Task | None = None

    def _create_worker_process(self, worker_id: int, task_queue: mp.Queue) -> mp.Process:
        """创建worker进程 - 统一实现"""
        logging_context = self._resolve_logging_context()
        return self._mp_context.Process(
            target=self._worker_process_entry,
            args=(self.worker_class, worker_id, task_queue, logging_context),
        )

    def _resolve_logging_context(self) -> ChildLoggingContext | None:
        """Resolve the active application context immediately before Process.start()."""
        return resolve_child_logging_context(self._logging_context)

    @staticmethod
    def _close_task_queue(task_queue: mp.Queue) -> None:
        """Release a parent-owned Worker queue and its feeder thread."""
        task_queue.close()
        task_queue.join_thread()

    @staticmethod
    def _worker_process_entry(
        worker_class: type[BaseWorker],
        worker_id: int,
        task_queue: mp.Queue,
        logging_context: ChildLoggingContext | None,
    ) -> None:
        """Install process-local logging before constructing and running one worker."""
        child_runtime = None
        try:
            if logging_context is not None:
                child_runtime = logging_context.install()
            worker = worker_class(worker_id, task_queue)
            asyncio.run(worker.start())
        except Exception as e:
            logger.error(f"Worker {worker_id} 进程异常退出: {e}")
        finally:
            if child_runtime is not None:
                child_runtime.close()

    async def start(self):
        """启动管理器"""
        self.running = True
        logger.info(f"启动管理器，{self.num_workers} 个worker")

        # 启动所有worker
        for worker_id in range(self.num_workers):
            await self._start_worker(worker_id)

        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor_workers())

        # 等待worker启动
        if not await safe_cancellable_sleep(3):
            logger.warning("管理器启动被取消")
            return
        logger.info("管理器启动完成")

    async def _start_worker(self, worker_id: int) -> bool:
        """启动单个worker"""
        try:
            # 停止现有worker（如果存在）
            if worker_id in self.workers:
                await self._stop_worker(worker_id)

            # 创建新的task queue和process
            # Queue and Process must come from the same multiprocessing context;
            # cross-context synchronization primitives are not compatible.
            task_queue = self._mp_context.Queue()
            process = self._create_worker_process(worker_id, task_queue)
            try:
                process.start()
            except Exception:
                try:
                    self._close_task_queue(task_queue)
                except Exception as cleanup_error:
                    logger.error(f"清理启动失败的Worker {worker_id} 队列时出错: {cleanup_error}")
                raise

            # 记录worker信息
            worker_info = WorkerInfo(worker_id, process, task_queue)
            self.workers[worker_id] = worker_info

            logger.info(f"启动Worker {worker_id}, PID: {process.pid}")
            return True

        except Exception as e:
            logger.error(f"启动Worker {worker_id} 失败: {e}")
            return False

    async def _stop_worker(self, worker_id: int) -> None:
        """停止单个worker"""
        if worker_id not in self.workers:
            return

        worker_info = self.workers[worker_id]

        try:
            # 发送关闭信号
            if worker_info.process.is_alive():
                shutdown_msg = TaskMessage(type=MessageType.SHUTDOWN, task_id="", worker_id=worker_id)
                worker_info.task_queue.put_nowait(shutdown_msg.to_msgpack())

                # 等待进程退出
                worker_info.process.join(timeout=5)

                # 强制终止
                if worker_info.process.is_alive():
                    worker_info.process.terminate()
                    worker_info.process.join(timeout=3)

                    if worker_info.process.is_alive():
                        worker_info.process.kill()
                        worker_info.process.join()

        except Exception as e:
            logger.error(f"停止Worker {worker_id} 时出错: {e}")
        finally:
            try:
                self._close_task_queue(worker_info.task_queue)
            except Exception as e:
                logger.error(f"清理Worker {worker_id} 队列时出错: {e}")
            self.workers.pop(worker_id, None)
            logger.info(f"Worker {worker_id} 已停止")

    async def _restart_worker(self, worker_id: int) -> bool:
        """重启worker"""
        if worker_id not in self.workers:
            return False

        worker_info = self.workers[worker_id]

        # 检查重启限制
        if worker_info.restart_count >= self.max_worker_restarts >= 0:
            logger.error(f"Worker {worker_id} 超过最大重启次数 ({self.max_worker_restarts})")
            worker_info.is_healthy = False
            return False

        # 检查重启间隔
        current_time = int(time.time())
        if current_time - worker_info.last_restart < self.worker_restart_delay:
            return False

        logger.warning(f"重启Worker {worker_id} (第 {worker_info.restart_count + 1} 次)")

        # 执行重启
        await self._stop_worker(worker_id)
        await asyncio.sleep(2)  # 缓冲时间

        success = await self._start_worker(worker_id)

        if success and worker_id in self.workers:
            worker_info = self.workers[worker_id]
            worker_info.restart_count += 1
            worker_info.last_restart = current_time
            worker_info.is_healthy = True

        return success

    async def _monitor_workers(self):
        """监控worker进程"""
        while self.running:
            try:
                logger.info(f"监控 {len(self.workers)} 个worker进程")

                # 检查每个worker状态
                for worker_id, worker_info in list(self.workers.items()):
                    if not worker_info.process.is_alive():
                        logger.warning(f"检测到Worker {worker_id} 进程已退出 (PID: {worker_info.process.pid})")

                        if worker_info.is_healthy:
                            # 尝试重启
                            restart_success = await self._restart_worker(worker_id)
                            if restart_success:
                                logger.info(f"Worker {worker_id} 重启成功")
                            else:
                                logger.error(f"Worker {worker_id} 重启失败")
                        else:
                            logger.error(f"Worker {worker_id} 标记为不健康，不再重启")

                # 报告状态
                healthy_workers = sum(1 for w in self.workers.values() if w.is_healthy and w.process.is_alive())
                logger.info(f"健康worker数量: {healthy_workers}/{self.num_workers}")

                if not await safe_cancellable_sleep(self.monitor_interval):
                    logger.warning("Worker监控任务被取消")

            except Exception as e:
                logger.error(f"Worker监控出错: {e}")
                if not await safe_cancellable_sleep(self.monitor_interval):
                    logger.warning("Worker监控任务被取消")

    def _select_worker(self) -> int | None:
        """选择健康的worker"""
        healthy_workers = [worker_id for worker_id, worker_info in self.workers.items() if worker_info.is_healthy and worker_info.process.is_alive()]

        if not healthy_workers:
            return None

        # 简单轮询
        selected = healthy_workers[self._round_robin_counter % len(healthy_workers)]
        self._round_robin_counter += 1
        return selected

    async def add_task(
        self,
        task_data: dict[str, Any],
        task_type: TaskType = TaskType.PERSISTENT,
        restart_delay: int = 5,
        max_restarts: int = -1,
        auto_remove_on_complete: bool | None = None,
    ) -> str | None:
        """添加任务"""
        # 选择worker
        worker_id = self._select_worker()
        if worker_id is None:
            logger.error("没有可用的健康worker")
            return None
        task_id = f"{worker_id}_{self.task_counter}_{int(time.time())}"
        self.task_counter += 1

        # 默认行为：一次性任务完成后自动移除
        if auto_remove_on_complete is None:
            auto_remove_on_complete = task_type == TaskType.ONE_TIME

        # 创建任务消息
        task_msg = TaskMessage(
            type=MessageType.TASK_START,
            task_id=task_id,
            worker_id=worker_id,
            task_data=task_data,
            task_type=task_type,
            restart_delay=restart_delay,
            max_restarts=max_restarts,
            auto_remove_on_complete=auto_remove_on_complete,
        )

        try:
            worker_info = self.workers[worker_id]
            worker_info.task_queue.put_nowait(task_msg.to_msgpack())
            logger.info(f"发送任务 {task_id} 到 Worker {worker_id}")
            return task_id
        except Exception as e:
            logger.error(f"发送任务失败: {e}")
            return None

    async def stop_task(self, task_id: str, worker_id: int = -1):
        """停止任务"""
        if worker_id == -1:
            # 从task_id中提取worker_id
            try:
                worker_id = int(task_id.split("_")[0])
            except (IndexError, ValueError):
                logger.error(f"无法从任务ID {task_id} 中提取Worker ID")
                return
        if worker_id not in self.workers:
            logger.warning(f"Worker {worker_id} 不存在")
            return

        stop_msg = TaskMessage(type=MessageType.TASK_STOP, task_id=task_id, worker_id=worker_id)

        try:
            worker_info = self.workers[worker_id]
            worker_info.task_queue.put_nowait(stop_msg.to_msgpack())
            logger.info(f"发送停止命令 {task_id} 到 Worker {worker_id}")
        except Exception as e:
            logger.error(f"发送停止命令失败: {e}")

    def get_manager_status(self) -> dict[str, Any]:
        """获取管理器状态"""
        healthy_count = sum(1 for w in self.workers.values() if w.is_healthy and w.process.is_alive())

        worker_status = {}
        for worker_id, worker_info in self.workers.items():
            worker_status[worker_id] = {
                "pid": worker_info.process.pid,
                "is_alive": worker_info.process.is_alive(),
                "is_healthy": worker_info.is_healthy,
                "restart_count": worker_info.restart_count,
                "uptime": time.time() - worker_info.start_time,
            }

        return {"total_workers": self.num_workers, "healthy_workers": healthy_count, "worker_status": worker_status}

    async def shutdown(self):
        """关闭管理器"""
        logger.info("关闭管理器...")
        self.running = False

        # 停止监控任务
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # 停止所有worker
        for worker_id in list(self.workers.keys()):
            await self._stop_worker(worker_id)

        logger.info("管理器已关闭")
