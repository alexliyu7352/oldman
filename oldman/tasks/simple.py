import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from oldman.logging import logger
from oldman.tasks.base import TaskStatus, TaskType
from oldman.utils.singleton import singleton_adv


@dataclass
class TaskInfo:
    name: str
    coro_func: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    restart_delay: int = 30
    max_restarts: int = -1  # -1 表示无限重启
    restart_count: int = 0
    last_restart: float = 0
    status: TaskStatus = TaskStatus.STOPPED
    task: asyncio.Task | None = None
    task_type: TaskType = TaskType.PERSISTENT  # 新增：任务类型
    auto_remove_on_complete: bool = True  # 新增：完成后是否自动移除


@singleton_adv
class BackgroundTaskManager:
    """后台任务管理器，支持任务监控、自动重启和健康检查"""

    def __init__(self):
        self.tasks: dict[str, TaskInfo] = {}
        self.monitor_task: asyncio.Task | None = None
        self.running = False
        self.monitor_interval = 60  # 监控间隔（秒）
        self._lock = asyncio.Lock()  # 添加异步锁

    def add_task(
        self,
        name: str,
        coro_func: Callable,
        *args,
        restart_delay: int = 30,
        max_restarts: int = -1,
        task_type: TaskType = TaskType.PERSISTENT,
        auto_remove_on_complete: bool | None = None,
        **kwargs,
    ):
        """添加任务"""
        if name in self.tasks:
            logger.warning(f"Task {name} already exists, overwriting")

        # 默认行为：一次性任务完成后自动移除
        if auto_remove_on_complete is None:
            auto_remove_on_complete = task_type == TaskType.ONE_TIME

        task_info = TaskInfo(
            name=name,
            coro_func=coro_func,
            args=args,
            kwargs=kwargs,
            restart_delay=restart_delay,
            max_restarts=max_restarts,
            task_type=task_type,
            auto_remove_on_complete=auto_remove_on_complete,
        )
        self.tasks[name] = task_info
        logger.info(f"Added {task_type.value} task: {name}")

    async def start_task(self, name: str) -> bool:
        """启动单个任务"""
        if name not in self.tasks:
            logger.error(f"Task not found: {name}")
            return False

        task_info = self.tasks[name]

        # 如果任务已经在运行，先停止它
        await self._stop_task_internal(task_info)

        try:
            # 创建新任务
            coro = task_info.coro_func(*task_info.args, **task_info.kwargs)
            task_info.task = asyncio.create_task(coro, name=name)
            task_info.status = TaskStatus.RUNNING
            task_info.last_restart = time.time()

            logger.info(f"Started task: {name}")
            return True
        except Exception as e:
            task_info.status = TaskStatus.ERROR
            logger.error(f"Failed to start task {name}: {e}")
            return False

    async def _stop_task_internal(self, task_info: TaskInfo) -> None:
        """内部停止任务方法，不加锁"""
        if task_info.task and not task_info.task.done():
            task_info.task.cancel()
            try:
                await task_info.task
            except asyncio.CancelledError:
                pass
        task_info.status = TaskStatus.STOPPED

    async def stop_task(self, name: str) -> bool:
        """停止单个任务"""
        async with self._lock:
            if name not in self.tasks:
                return False

            task_info = self.tasks[name]
            await self._stop_task_internal(task_info)
            logger.info(f"Stopped task: {name}")
            return True

    async def remove_task(self, name: str) -> bool:
        """移除任务"""
        async with self._lock:
            if name not in self.tasks:
                return False

            task_info = self.tasks[name]
            await self._stop_task_internal(task_info)
            del self.tasks[name]
            logger.info(f"Removed task: {name}")
            return True

    async def restart_task(self, name: str) -> bool:
        """重启任务"""
        async with self._lock:
            if name not in self.tasks:
                logger.warning(f"Task not found for restart: {name}")
                return False

            task_info = self.tasks[name]

            # 检查是否超过最大重启次数
            if 0 < task_info.max_restarts <= task_info.restart_count:
                logger.warning(f"Task {name} exceeded max restarts ({task_info.max_restarts})")
                task_info.status = TaskStatus.ERROR
                return False

            # 检查重启间隔
            current_time = time.time()
            if current_time - task_info.last_restart < task_info.restart_delay:
                return False

            task_info.status = TaskStatus.RESTARTING
            task_info.restart_count += 1

            logger.info(f"Restarting task {name} (attempt {task_info.restart_count})")

            await self._stop_task_internal(task_info)
            await asyncio.sleep(1)  # 给一点缓冲时间

            # 重新启动任务（不需要再加锁，因为已在锁内）
            try:
                coro = task_info.coro_func(*task_info.args, **task_info.kwargs)
                task_info.task = asyncio.create_task(coro, name=name)
                task_info.status = TaskStatus.RUNNING
                task_info.last_restart = time.time()
                return True
            except Exception as e:
                task_info.status = TaskStatus.ERROR
                logger.error(f"Failed to restart task {name}: {e}")
                return False

    async def monitor_tasks(self):
        """监控任务状态"""
        while self.running:
            try:
                logger.info(f"当前总共有 {len(self.tasks)} 个任务")

                # 收集需要移除的任务名称
                tasks_to_remove = []

                # 使用 list() 创建快照，避免迭代时修改字典
                for name, task_info in list(self.tasks.items()):
                    is_alive = task_info.task and not task_info.task.done() if task_info.task else False

                    # 记录每个任务的详细状态
                    logger.info(  # 改为 info 级别，确保能看到
                        f"Task {name}: status={task_info.status.value}, "
                        f"restart_count={task_info.restart_count}, "
                        f"alive={is_alive}, "
                        f"type={task_info.task_type.value}, "
                        f"task_id={id(task_info.task) if task_info.task else None}"
                    )

                    if task_info.status == TaskStatus.RUNNING and not is_alive:
                        # 任务已结束，判断结束原因
                        completed_normally = False
                        exception_info = None

                        if task_info.task:
                            try:
                                result_info = task_info.task.result()
                                completed_normally = True
                                logger.info(f"Task {name} completed normally with result: {result_info}")
                            except Exception as exception:
                                exception_info = exception
                                task_info.status = TaskStatus.ERROR
                                logger.error(f"Task {name} failed with exception: {exception}")

                        # 根据任务类型和完成状态决定后续操作
                        if completed_normally and task_info.task_type == TaskType.ONE_TIME:
                            # 一次性任务正常完成，根据配置决定是否移除
                            if task_info.auto_remove_on_complete:
                                tasks_to_remove.append(name)
                                logger.info(f"One-time task {name} completed, will be removed")
                            else:
                                task_info.status = TaskStatus.COMPLETED
                                logger.info(f"One-time task {name} completed, keeping in list")
                        else:
                            # 异常退出或持久任务需要重启
                            task_info.status = TaskStatus.ERROR
                            logger.warning(f"Task {name} needs restart (type: {task_info.task_type.value})")
                            restart_success = await self.restart_task(name)
                            logger.info(f"Task {name} restart {'successful' if restart_success else 'failed'}")
                            # 如果重启失败，记录更详细信息
                            if not restart_success:
                                logger.error(f"Task {name} restart failed - exception: {exception_info}")

                # 批量移除已完成的一次性任务
                for task_name in tasks_to_remove:
                    self.tasks.pop(task_name, None)
                    logger.info(f"Removed completed one-time task: {task_name}")

                if tasks_to_remove:
                    logger.info(f"Removed {len(tasks_to_remove)} completed one-time tasks")

                await asyncio.sleep(self.monitor_interval)

            except asyncio.CancelledError:
                logger.info("Task monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(self.monitor_interval)

    async def start_all(self):
        """启动所有任务和监控器"""
        self.running = True

        # 启动所有任务
        for name in list(self.tasks.keys()):  # 使用快照避免迭代时修改
            await self.start_task(name)

        # 启动监控器
        self.monitor_task = asyncio.create_task(self.monitor_tasks(), name="task_monitor")
        logger.info("Background task manager started")

    async def stop_all(self):
        """停止所有任务"""
        self.running = False

        try:
            # 停止监控器
            if self.monitor_task:
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass

            # 直接使用内部方法停止所有任务，避免异步锁
            for name, task_info in list(self.tasks.items()):
                await self._stop_task_internal(task_info)
                logger.info(f"Stopped task: {name}")

            logger.info("Background task manager stopped")

        except RuntimeError as e:
            if "Event loop" in str(e):
                # 事件循环已停止，执行强制清理
                self.stop_all_sync()
            else:
                raise
        except Exception as e:
            logger.error(f"Error in stop_all: {e}")
            # 作为备选，执行强制清理
            self.stop_all_sync()

    def stop_all_sync(self):
        """同步版本的停止所有任务，用于信号处理"""
        try:
            self.running = False

            # 取消监控任务
            if self.monitor_task and not self.monitor_task.done():
                self.monitor_task.cancel()

            # 取消所有任务
            cancelled_count = 0
            for task_info in self.tasks.values():
                if task_info.task and not task_info.task.done():
                    task_info.task.cancel()
                    cancelled_count += 1
                task_info.status = TaskStatus.STOPPED

            logger.info(f"Background task manager stopped (sync) - cancelled {cancelled_count} tasks")

        except Exception as e:
            logger.error(f"Error in stop_all_sync: {e}")
            # 即使出错也要确保状态正确
            self.running = False
            for task_info in self.tasks.values():
                task_info.status = TaskStatus.STOPPED

    def get_task_status(self, name: str) -> dict:
        """获取任务状态"""
        if name not in self.tasks:
            return {}

        task_info = self.tasks[name]
        return {
            "name": task_info.name,
            "status": task_info.status.value,
            "restart_count": task_info.restart_count,
            "last_restart": task_info.last_restart,
            "is_alive": task_info.task and not task_info.task.done() if task_info.task else False,
        }

    def get_all_status(self) -> dict[str, dict]:
        """获取所有任务状态"""
        return {name: self.get_task_status(name) for name in self.tasks}
