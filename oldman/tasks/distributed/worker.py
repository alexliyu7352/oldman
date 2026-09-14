"""Native Taskiq process management with bounded first-start readiness reports."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from queue import Empty
from typing import Any, cast

from taskiq.cli.worker.args import WorkerArgs
from taskiq.cli.worker.process_manager import ProcessActionBase, ProcessManager, ReloadOneAction, ShutdownAction
from taskiq.cli.worker.run import start_listen

from oldman.tasks.distributed.receiver import RenewingReceiver

logger = logging.getLogger(__name__)


@dataclass
class WorkerReady(ProcessActionBase):
    """One private startup report on the native manager's existing action queue."""

    pid: int


class WorkerReceiver(RenewingReceiver):
    """Report readiness after actual broker startup, then run the native Receiver."""

    def __init__(self, *, startup_report: Callable[[], None], **kwargs: Any) -> None:
        """Use native receiver kwargs rather than a second execution configuration."""
        super().__init__(**kwargs)
        self._startup_report = startup_report

    async def listen(self, finish_event: asyncio.Event) -> None:
        """All connection checks finish before the parent counts this PID ready."""
        from oldman.conf import settings

        # Core and JetStream share the existing first-start budget, not a
        # connection. With Core disabled, keep the broker's own timeout owner.
        timeout = settings.taskiq.startup_timeout if settings.nats_bus.enabled else None
        async with asyncio.timeout(timeout):
            if settings.nats_bus.enabled:
                from oldman.providers.nats import bus

                await bus._connect()
            await self.broker.startup()
            self.run_startup = False
            self._startup_report()
        await super().listen(finish_event)


class TaskiqProcessManager(ProcessManager):
    """Only first-start readiness differs; the native runtime recovery loop stays."""

    def __init__(self, args: WorkerArgs, worker_function: Callable[..., None], *, attempts: int, startup_timeout: float) -> None:
        """Share native actions; running replacements never emit startup reports."""
        super().__init__(args, worker_function)
        self._startup_phase = multiprocessing.Event()
        self._startup_phase.set()
        self._startup_attempts = attempts
        self._startup_timeout = startup_timeout
        self.worker_function = partial(worker_function, reports=self.action_queue, phase=self._startup_phase)

    def prepare_workers(self) -> None:
        """Each configured position gets its own finite initial attempt budget."""
        super().prepare_workers()
        attempts = [1] * len(self.workers)
        since = [time.monotonic()] * len(self.workers)
        ready: set[int] = set()
        deferred: list[ProcessActionBase] = []
        try:
            while True:
                try:
                    action = self.action_queue.get(timeout=0.2)
                except Empty:
                    action = None
                if isinstance(action, WorkerReady):
                    ready.add(action.pid)
                elif isinstance(action, ShutdownAction):
                    raise InterruptedError("Taskiq startup was stopped")
                elif action is not None:
                    deferred.append(action)

                for position, process in enumerate(self.workers):
                    if process.is_alive() and process.pid not in ready:
                        if time.monotonic() - since[position] > self._startup_timeout + self.args.shutdown_timeout:
                            # The owned child missed both startup and cleanup deadlines.
                            # A stuck import/hook must not make native reload.join hang.
                            logger.error("Taskiq worker position %s did not finish startup; terminating this attempt", position)
                            process.kill()
                            process.join()
                    if not process.is_alive():
                        if attempts[position] >= self._startup_attempts:
                            raise RuntimeError(f"Taskiq worker position {position} failed all {attempts[position]} startup attempts")
                        ready.discard(process.pid or 0)
                        attempts[position] += 1
                        ReloadOneAction(position, is_reload_all=False).handle(self.workers, self.args, self.worker_function)
                        since[position] = time.monotonic()
                if all(process.pid in ready and process.is_alive() for process in self.workers):
                    logger.info("All %s Taskiq worker processes are ready", len(self.workers))
                    return
        finally:
            self._startup_phase.clear()
            for action in deferred:
                self.action_queue.put(action)


def listen_worker(args: WorkerArgs, startup_report: Callable[[], None]) -> None:
    """Use the installed native synchronous runner and its original event loop."""
    args.receiver = "oldman.tasks.distributed.worker:WorkerReceiver"
    # CLI receiver_arg annotations say str, but the native runner passes this
    # dictionary directly to the receiver. This in-process callback is not YAML.
    args.receiver_arg = cast(Any, [("startup_report", startup_report)])
    start_listen(args)


async def close_worker_resources() -> None:
    """Close framework-owned clients after native tasks and broker have finished."""
    from oldman.cache import memory_cache
    from oldman.conf import settings
    from oldman.db import db_manager
    from oldman.providers.redis import redis_client

    closing = [db_manager.close(), memory_cache.close(), redis_client.close()]
    if settings.nats_bus.enabled:
        from oldman.providers.nats import bus

        closing.append(bus.stop())
    results = await asyncio.gather(*closing, return_exceptions=True)
    failures = [result for result in results if isinstance(result, BaseException)]
    if failures:
        raise BaseExceptionGroup("Taskiq worker shared resource cleanup failed", failures)


def report_worker_ready(reports: Any, phase: Any) -> None:
    """Send only one first-start report; runtime restarts have no readiness feed."""
    if phase.is_set():
        reports.put(WorkerReady(os.getpid()))
