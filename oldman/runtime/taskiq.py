"""Dedicated Taskiq services; ordinary Web and Simple lifecycles remain separate."""

from __future__ import annotations

import asyncio
import fcntl
import multiprocessing
import os
import signal
import subprocess
import sys
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oldman.logging import ChildLoggingContext, logger
from oldman.runtime._taskiq_process import GroupIdentity, service_process_group, spawn_stopper, stop_process_group
from oldman.runtime.base import BaseApplication
from oldman.runtime.bootstrap import bootstrap_service
from oldman.runtime.simple import SimpleApplication

if TYPE_CHECKING:
    from taskiq.cli.worker.args import WorkerArgs


def _worker_entry(*, args: WorkerArgs, service: str, config_file: Path, logging_context: ChildLoggingContext, reports: Any, phase: Any) -> None:
    """Spawn imports this configuration-free module before binding child settings."""
    logging_runtime = logging_context.install()
    loop: asyncio.AbstractEventLoop | None = None
    failure: BaseException | None = None
    try:
        context = bootstrap_service(service, config_file=config_file)
        from oldman.storage import storages
        from oldman.tasks.distributed import broker
        from oldman.tasks.distributed.worker import close_worker_resources, listen_worker, report_worker_ready

        broker.is_worker_process = True
        storages.init_app()
        context.apps.load_tasks()
        asyncio.set_event_loop(None)
        try:
            listen_worker(args, partial(report_worker_ready, reports, phase))
            if broker._broken:
                # Native start_listen logs shutdown_broker failures instead of
                # propagating them. A dedicated service must still exit nonzero.
                raise RuntimeError("Taskiq worker broker cleanup failed; see the original shutdown error above")
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop is not None and not loop.is_closed():
                try:
                    loop.run_until_complete(asyncio.wait_for(close_worker_resources(), context.settings.taskiq.shutdown_timeout))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(loop.shutdown_default_executor())
                except BaseException:
                    if failure is None:
                        raise
                    logger.exception("Taskiq worker cleanup failed; preserving the original worker error")
                finally:
                    loop.close()
    finally:
        reports.close()
        reports.join_thread()
        logging_runtime.close()


class _TaskiqServiceLifecycle:
    """Share explicit group-safe start/stop between Worker and Scheduler only."""

    # These members are provided by the actual Application base, not a proxy.
    if TYPE_CHECKING:
        from oldman.runtime.bootstrap import ServiceBootstrapContext

        bootstrap_context: ServiceBootstrapContext
        pid_file_path: str
        _pid_cleanup_callback: Any

        def run(self, *args: Any, **kwargs: Any) -> None: ...
        def _close_logging(self) -> None: ...

    @property
    def _identity_path(self) -> Path:
        """Keep the existing numeric PID file protocol; add private group identity."""
        return Path(self.pid_file_path).with_suffix(".taskiq.json")

    def start(self, *args: Any, **kwargs: Any) -> None:
        """Hold the service PID lock for its lifetime and retain terminal signals."""
        if not self.bootstrap_context.settings.taskiq.enabled:
            self._close_logging()
            raise RuntimeError("This service requires settings.taskiq.enabled=true")
        pid_path = Path(self.pid_file_path)
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with pid_path.open("a+", encoding="ascii") as pid_file:
                try:
                    fcntl.flock(pid_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError("Taskiq service is already running") from None
                pid_file.seek(0)
                previous = pid_file.read().strip()
                if previous and Path(f"/proc/{int(previous)}").exists():
                    raise RuntimeError(f"Service PID {previous} is still present; refusing to overwrite its PID file")
                with service_process_group() as identity:
                    self._group_identity = identity
                    self._stopper: subprocess.Popen[bytes] | None = None
                    pid_file.seek(0)
                    pid_file.truncate()
                    pid_file.write(str(identity.pid))
                    pid_file.flush()
                    self._identity_path.write_text(identity.to_json(), encoding="utf-8")
                    try:
                        self.run(*args, **kwargs)
                    finally:
                        self.delete_pid_file()
        finally:
            self._close_logging()

    def delete_pid_file(self) -> None:
        """A stop-command instance must never remove another process's PID files."""
        path = Path(self.pid_file_path)
        if path.exists() and path.read_text().strip() == str(os.getpid()):
            path.unlink(missing_ok=True)
            self._identity_path.unlink(missing_ok=True)

    def _ensure_stopper(self) -> None:
        """Only create a short-lived stopper when stop has actually been requested."""
        if self._stopper is None:
            self._stopper = spawn_stopper(self._group_identity, self.bootstrap_context.settings.taskiq.stop_timeout)

    def stop(self, *args: Any, **kwargs: Any) -> int:
        """One command includes graceful waiting, deadline escalation and checking."""
        try:
            if not self._identity_path.exists():
                if Path(self.pid_file_path).exists():
                    raise RuntimeError("Taskiq group identity is missing; refusing to stop an unverified PID")
                logger.info("Taskiq service is not running")
                return 0
            identity = GroupIdentity.from_json(self._identity_path.read_text())
            forced = stop_process_group(identity, self.bootstrap_context.settings.taskiq.stop_timeout)
            logger.info("Taskiq service group stopped%s", " after the stop deadline" if forced else "")
            # Remove stale files only when they still describe the stopped service.
            if self._identity_path.exists() and self._identity_path.read_text() == identity.to_json():
                self._identity_path.unlink()
                path = Path(self.pid_file_path)
                if path.exists() and path.read_text().strip() == str(identity.pid):
                    path.unlink()
            return identity.pid
        finally:
            self._close_logging()

    def restart(self, *args: Any, **kwargs: Any) -> None:
        """Do not start a replacement until stop has verified the old group gone."""
        self.stop(*args, **kwargs)
        # stop closes its command instance's logging; reuse the normal constructor.
        type(self)().start(*args, **kwargs)


class TaskiqWorkerApplication(_TaskiqServiceLifecycle, BaseApplication):
    """A native Taskiq process manager, not a SimpleApplication background task."""

    def init(self) -> None:
        """The manager itself opens no broker, database, storage or HTTP clients."""
        self._setup_system_signals()

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Use native runtime recovery and join children on every manager exit."""
        self.init()
        multiprocessing.set_start_method("spawn", force=True)
        from taskiq.cli.worker.args import WorkerArgs

        from oldman.tasks.distributed.worker import TaskiqProcessManager

        config = self.bootstrap_context.settings.taskiq
        native_args = WorkerArgs(
            broker="oldman.tasks.distributed:broker", modules=[], configure_logging=False,
            workers=config.workers, max_async_tasks=config.max_async_tasks, max_prefetch=config.max_prefetch,
            shutdown_timeout=config.shutdown_timeout, max_fails=-1, wait_tasks_timeout=None, hardkill_count=sys.maxsize,
        )
        manager = TaskiqProcessManager(
            native_args,
            partial(_worker_entry, service=self.bootstrap_context.service_module, config_file=self.bootstrap_context.config_file,
                    logging_context=self.logging_runtime.child_context),
            attempts=config.startup_attempts, startup_timeout=config.startup_timeout,
        )
        native_interrupt = signal.getsignal(signal.SIGINT)

        def interrupt(signum: int, frame: Any) -> None:
            """A stuck manager cannot prevent Ctrl+C's independent stop deadline."""
            self._ensure_stopper()
            if callable(native_interrupt):
                native_interrupt(signum, frame)

        signal.signal(signal.SIGINT, interrupt)
        try:
            status = manager.start()
            if status:
                raise RuntimeError(f"Taskiq process manager failed with status {status}")
        except InterruptedError:
            manager._shutdown_workers()
        except BaseException:
            self._ensure_stopper()
            manager._shutdown_workers()
            raise
        finally:
            manager._startup_phase.clear()
            for process in manager.workers:
                process.join()
                process.close()
            manager.action_queue.close()
            manager.action_queue.join_thread()


class TaskiqSchedulerApplication(_TaskiqServiceLifecycle, SimpleApplication):
    """Run one native Scheduler, with dedicated signals and bounded group stop."""

    def prepare(self) -> None:
        """Bootstrap already loaded models; collect task labels before scheduling."""
        from oldman.tasks.distributed import broker

        broker.is_scheduler_process = True
        self.bootstrap_context.apps.load_tasks()

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Reuse Simple's initialization, not its loop.stop or cancel-all cleanup."""
        self.init()
        self.prepare()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._scheduler_stop = asyncio.Event()
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def interrupt(signum: int, frame: Any) -> None:
            """The loop can be blocked; start the independent deadline immediately."""
            self._ensure_stopper()
            self._scheduler_stop.set()

        try:
            for sig in previous:
                signal.signal(sig, interrupt)
            self.loop.run_until_complete(self.main(*args, **kwargs))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
        except BaseException:
            self._ensure_stopper()
            raise
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.loop.close()
            asyncio.set_event_loop(None)

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Stop new scheduling first, drain in-flight work, then close resources."""
        from oldman.tasks.distributed import broker
        from oldman.tasks.distributed.scheduler import WaitingScheduler
        from oldman.tasks.distributed.worker import close_worker_resources

        scheduler = WaitingScheduler(broker)
        running: asyncio.Task[None] | None = None
        stopping: asyncio.Task[bool] | None = None
        failure: BaseException | None = None
        try:
            try:
                if self.bootstrap_context.settings.nats_bus.enabled:
                    from oldman.providers.nats import bus

                    await bus._connect()
                await scheduler.startup()
                logger.info("Taskiq Scheduler is ready")
                running = asyncio.create_task(scheduler.loop.run(
                    update_interval=timedelta(seconds=broker.config.schedule_update_interval),
                ))
                stopping = asyncio.create_task(self._scheduler_stop.wait())
                await asyncio.wait((running, stopping), return_when=asyncio.FIRST_COMPLETED)
            finally:
                if stopping is not None:
                    stopping.cancel()
                    await asyncio.gather(stopping, return_exceptions=True)
                loop_error: BaseException | None = None
                if running is not None:
                    running.cancel()
                    (loop_error,) = await asyncio.gather(running, return_exceptions=True)
                await scheduler.drain()
                if isinstance(loop_error, Exception):
                    raise loop_error  # Do not report a failed native loop as clean stop.
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                async with asyncio.timeout(broker.config.shutdown_timeout):
                    # Native shutdown hooks may use Core. Only then close shared
                    # clients, attempting them even when a hook failed/cancelled.
                    shutdown_error: BaseException | None = None
                    try:
                        await scheduler.shutdown()
                    except BaseException as error:
                        shutdown_error = error
                        raise
                    finally:
                        try:
                            await close_worker_resources()
                        except BaseException:
                            if shutdown_error is None:
                                raise
                            logger.exception("Taskiq shared cleanup failed; preserving the scheduler shutdown error")
            except BaseException:
                if failure is None:
                    raise
                logger.exception("Taskiq Scheduler cleanup failed; preserving the original service error")
