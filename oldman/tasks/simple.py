"""Process-local coroutine supervisor.

Named tasks registered with `add_task()` carry a restart policy; `spawn()` runs a one-off coroutine
in the background and forgets it once it ends. Every task gets a done callback, so completion,
failure and cancellation are handled the moment they happen; no polling loop needs to be running.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from oldman.logging import logger
from oldman.tasks.base import TaskStatus, TaskType
from oldman.utils.singleton import singleton_adv

CoroutineFunction = Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class TaskInfo:
    """Registration record of one supervised coroutine."""

    name: str
    coro_func: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    restart_delay: int = 30
    max_restarts: int = -1  # -1 unlimited, 0 never, n at most n automatic restarts
    restart_count: int = 0
    last_restart: float = 0
    status: TaskStatus = TaskStatus.STOPPED
    task: asyncio.Task[Any] | None = None
    task_type: TaskType = TaskType.PERSISTENT
    auto_remove_on_complete: bool = True
    remove_on_failure: bool = False
    restart_handle: asyncio.TimerHandle | None = None
    restart_task_ref: asyncio.Task[Any] | None = None


@singleton_adv
class BackgroundTaskManager:
    """Supervise coroutines in this process: named tasks with restart policies, plus fire-and-forget spawns."""

    def __init__(self) -> None:
        self.tasks: dict[str, TaskInfo] = {}
        self.running = False
        self._stopping = False
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._spawn_ids = itertools.count(1)

    # -- registration --------------------------------------------------------------------------

    def add_task(
        self,
        name: str,
        coro_func: CoroutineFunction,
        *args: Any,
        restart_delay: int = 30,
        max_restarts: int = -1,
        task_type: TaskType = TaskType.PERSISTENT,
        auto_remove_on_complete: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Register `coro_func(*args, **kwargs)` under `name` without starting it; a taken name is an error."""
        if name in self.tasks:
            raise ValueError(f"Task {name!r} already exists; remove it before registering it again")
        if auto_remove_on_complete is None:
            auto_remove_on_complete = task_type == TaskType.ONE_TIME
        self.tasks[name] = TaskInfo(
            name=name,
            coro_func=coro_func,
            args=args,
            kwargs=kwargs,
            restart_delay=restart_delay,
            max_restarts=max_restarts,
            task_type=task_type,
            auto_remove_on_complete=auto_remove_on_complete,
        )
        logger.info("Added %s task: %s", task_type.value, name)

    def spawn(self, coro_func: CoroutineFunction, *args: Any, name: str | None = None, **kwargs: Any) -> asyncio.Task[Any]:
        """Run `coro_func(*args, **kwargs)` right away as a one-off task that is forgotten once it ends.

        Needs a running event loop. A failure is logged, never retried; cancellation on shutdown is the
        only thing the manager does to it afterwards. The returned Task lets callers await or cancel it.
        """
        if self._stopping:
            raise RuntimeError("BackgroundTaskManager is stopping; it accepts no new tasks")
        if name is None:
            name = f"{getattr(coro_func, '__name__', 'task')}-{next(self._spawn_ids)}"
        elif name in self.tasks:
            raise ValueError(f"Task {name!r} already exists; remove it before spawning it again")
        info = TaskInfo(
            name=name,
            coro_func=coro_func,
            args=args,
            kwargs=kwargs,
            max_restarts=0,
            task_type=TaskType.ONE_TIME,
            auto_remove_on_complete=True,
            remove_on_failure=True,
        )
        self.tasks[name] = info
        try:
            task = self._create(info)
        except BaseException:
            self.tasks.pop(name, None)
            raise
        logger.debug("Spawned task: %s", name)
        return task

    # -- control ---------------------------------------------------------------------------------

    async def start_task(self, name: str) -> bool:
        """Start (or restart from scratch, with a fresh restart budget) the registered task `name`."""
        async with self._get_lock():
            info = self.tasks.get(name)
            if info is None:
                logger.error("Task not found: %s", name)
                return False
            await self._stop_running(info)
            info.restart_count = 0
            try:
                self._create(info)
            except Exception:
                info.status = TaskStatus.ERROR
                logger.exception("Failed to start task %s", name)
                return False
            logger.info("Started task: %s", name)
            return True

    async def stop_task(self, name: str) -> bool:
        """Cancel the task and any pending automatic restart; the registration stays."""
        async with self._get_lock():
            info = self.tasks.get(name)
            if info is None:
                return False
            await self._stop_running(info)
            logger.info("Stopped task: %s", name)
            return True

    async def remove_task(self, name: str) -> bool:
        """Stop the task and drop its registration."""
        async with self._get_lock():
            info = self.tasks.get(name)
            if info is None:
                return False
            await self._stop_running(info)
            del self.tasks[name]
            logger.info("Removed task: %s", name)
            return True

    async def restart_task(self, name: str) -> bool:
        """Restart the task now; counts against `max_restarts` like an automatic restart does."""
        async with self._get_lock():
            info = self.tasks.get(name)
            if info is None:
                logger.warning("Task not found for restart: %s", name)
                return False
            if not self._restart_allowed(info):
                logger.warning("Task %s exceeded max restarts (%s)", name, info.max_restarts)
                info.status = TaskStatus.ERROR
                return False
            await self._stop_running(info, status=TaskStatus.RESTARTING)
            info.restart_count += 1
            logger.info("Restarting task %s (attempt %s)", name, info.restart_count)
            try:
                self._create(info)
            except Exception:
                info.status = TaskStatus.ERROR
                logger.exception("Failed to restart task %s", name)
                return False
            return True

    async def start_all(self) -> None:
        """Start every registered task that is not already running or waiting for its restart."""
        self.running = True
        self._stopping = False
        for name, info in list(self.tasks.items()):
            if info.status in {TaskStatus.RUNNING, TaskStatus.RESTARTING}:
                continue
            await self.start_task(name)
        logger.info("Background task manager started")

    async def stop_all(self) -> None:
        """Cancel every task and pending restart, waiting for each cancellation to land."""
        self.running = False
        self._stopping = True
        async with self._get_lock():
            for info in list(self.tasks.values()):
                await self._stop_running(info)
                logger.info("Stopped task: %s", info.name)
        logger.info("Background task manager stopped")

    def stop_all_sync(self) -> None:
        """Request cancellation of everything without waiting; for signal handlers and closed loops."""
        self.running = False
        self._stopping = True
        cancelled = 0
        for info in self.tasks.values():
            self._cancel_restart(info)
            info.status = TaskStatus.STOPPED
            if info.task is not None and not info.task.done():
                info.task.cancel()
                cancelled += 1
        logger.info("Background task manager stopped (sync) - cancelled %s tasks", cancelled)

    # -- status ------------------------------------------------------------------------------------

    def get_task_status(self, name: str) -> dict[str, Any]:
        """Live status of one task; an unknown name gives an empty dict."""
        info = self.tasks.get(name)
        if info is None:
            return {}
        return {
            "name": info.name,
            "status": info.status.value,
            "restart_count": info.restart_count,
            "last_restart": info.last_restart,
            "is_alive": info.task is not None and not info.task.done(),
        }

    def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Live status of every registered task."""
        return {name: self.get_task_status(name) for name in self.tasks}

    # -- internals -----------------------------------------------------------------------------------

    def _get_lock(self) -> asyncio.Lock:
        """One lock per event loop: the singleton outlives `asyncio.run()` calls in commands and tests."""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def _create(self, info: TaskInfo) -> asyncio.Task[Any]:
        """Instantiate the coroutine, schedule it and hook the done callback; raises when that fails."""
        coro = info.coro_func(*info.args, **info.kwargs)
        task = asyncio.get_running_loop().create_task(coro, name=info.name)
        info.task = task
        info.status = TaskStatus.RUNNING
        info.last_restart = time.time()
        task.add_done_callback(functools.partial(self._on_task_done, info))
        return task

    async def _stop_running(self, info: TaskInfo, *, status: TaskStatus = TaskStatus.STOPPED) -> None:
        """Cancel the current task and wait for it; `status` is set first so the done callback stays quiet."""
        self._cancel_restart(info)
        info.status = status
        task = info.task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            if not task.cancelled():
                raise
        except Exception as error:
            logger.warning("Task %s ended with an error while being stopped: %s", info.name, error)

    def _cancel_restart(self, info: TaskInfo) -> None:
        if info.restart_handle is not None:
            info.restart_handle.cancel()
            info.restart_handle = None

    def _restart_allowed(self, info: TaskInfo) -> bool:
        """Persistent tasks restart within `max_restarts` (-1 unlimited); one-offs only when it is positive."""
        if info.task_type == TaskType.ONE_TIME:
            return 0 < info.max_restarts and info.restart_count < info.max_restarts
        return info.max_restarts < 0 or info.restart_count < info.max_restarts

    def _on_task_done(self, info: TaskInfo, task: asyncio.Task[Any]) -> None:
        """React to the task ending; runs on the loop right after it finishes, so it must never raise."""
        try:
            if info.task is not task or self.tasks.get(info.name) is not info:
                return  # replaced or removed meanwhile
            if info.status is not TaskStatus.RUNNING:
                return  # this manager stopped it and already set the status
            if task.cancelled():
                logger.warning("Task %s was cancelled outside the manager", info.name)
                self._settle(info, error=None, cancelled=True)
                return
            error = task.exception()
            if error is not None:
                logger.error("Task %s failed", info.name, exc_info=error)
            self._settle(info, error=error, cancelled=False)
        except Exception:
            logger.exception("Handling the end of task %s failed", info.name)

    def _settle(self, info: TaskInfo, *, error: BaseException | None, cancelled: bool) -> None:
        """Apply the task type's policy after an unplanned end."""
        if info.task_type == TaskType.ONE_TIME:
            if error is None and not cancelled:
                if info.auto_remove_on_complete:
                    del self.tasks[info.name]
                    logger.debug("One-time task %s completed and was removed", info.name)
                else:
                    info.status = TaskStatus.COMPLETED
                return
            if error is not None and self._schedule_restart(info):
                return
            if info.remove_on_failure:
                del self.tasks[info.name]
                return
            info.status = TaskStatus.ERROR if error is not None else TaskStatus.STOPPED
            return
        if self._schedule_restart(info):
            return
        if error is not None:
            info.status = TaskStatus.ERROR
        elif cancelled:
            info.status = TaskStatus.STOPPED
        else:
            info.status = TaskStatus.COMPLETED

    def _schedule_restart(self, info: TaskInfo) -> bool:
        """Book the next automatic start so that starts stay `restart_delay` seconds apart."""
        if self._stopping or not self._restart_allowed(info):
            if not self._stopping and info.max_restarts > 0:
                logger.warning("Task %s exceeded max restarts (%s)", info.name, info.max_restarts)
            return False
        info.restart_count += 1
        info.status = TaskStatus.RESTARTING
        delay = max(0.0, info.restart_delay - (time.time() - info.last_restart))
        loop = asyncio.get_running_loop()
        info.restart_handle = loop.call_later(delay, self._launch_restart, loop, info)
        logger.info("Task %s restarts in %.0fs (attempt %s)", info.name, delay, info.restart_count)
        return True

    def _launch_restart(self, loop: asyncio.AbstractEventLoop, info: TaskInfo) -> None:
        """Start the restart coroutine, keeping a reference and reporting its failures.

        The returned task used to be discarded. asyncio only holds a weak reference, so
        CPython may collect it before it runs, and an exception raised before `_restart`
        reaches `_create` would surface only as a "never retrieved" warning at shutdown.
        `_create`, two methods above, already does this correctly - it binds the task to
        `info.task` and attaches a done callback - and this is the same manager's own
        rule, written out in db/sqlalchemy/cache.py as the reason not to use a bare
        create_task.
        """
        info.restart_handle = None
        task = loop.create_task(self._restart(info), name=f"{info.name}:restart")
        info.restart_task_ref = task
        task.add_done_callback(functools.partial(self._on_restart_done, info))

    @staticmethod
    def _on_restart_done(info: TaskInfo, task: asyncio.Task[Any]) -> None:
        """Drop the reference and log a restart that failed on its way in."""
        if info.restart_task_ref is task:
            info.restart_task_ref = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Restarting task %s failed before it started", info.name, exc_info=error)

    async def _restart(self, info: TaskInfo) -> None:
        async with self._get_lock():
            if self._stopping or self.tasks.get(info.name) is not info or info.status is not TaskStatus.RESTARTING:
                return
            try:
                self._create(info)
            except Exception:
                logger.exception("Restarting task %s failed", info.name)
                info.status = TaskStatus.ERROR
                info.last_restart = time.time()  # a full delay before the next attempt, never a tight loop
                self._schedule_restart(info)
            else:
                logger.info("Restarted task: %s", info.name)
