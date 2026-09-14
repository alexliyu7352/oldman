"""Real fork, spawn and manager contracts for direct child logging."""

# ruff: noqa: E402 -- spawned consumers require project settings before import.

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import multiprocessing
import os
import re
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path
from queue import Empty
from typing import Any, cast
from unittest.mock import patch

import billiard
from sqlalchemy import text

import oldman.conf as conf
from oldman.conf.schemas import DatabaseConfig, DefaultSettings

# Spawned test processes import this module again, so mirror project bootstrap.
conf.__dict__.setdefault("settings", DefaultSettings())

import oldman.processes.executor as process_module
from oldman.db import DatabaseManager
from oldman.logging import ChildLoggingContext, get_active_runtime, init_logging, logger
from oldman.processes.executor import AsyncProcessManager, ParentLogPipeReader, ProcessTimeoutError
from oldman.tasks.manager import BaseManager
from oldman.tasks.worker import BaseWorker
from tests.fixtures.logging_direct_service import (
    RestartLoggingWorker,
    temporary_normal_target,
    temporary_sigkill_target,
    temporary_timeout_target,
    write_record_sequence,
)

_ASYNC_PROCESS_PARENT_DB_MANAGER: DatabaseManager | None = None


def _flush_default_handlers() -> None:
    """Flush console handlers; atomic file handlers are deliberately unbuffered."""
    for handler in logger.handlers:
        handler.flush()


def _rotation_thread_names() -> list[str]:
    """Return Oldman coordinator thread names visible in the current process."""
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if thread.name == "oldman-log-rotation"
    )


def _open_log_files(pid: int) -> list[str]:
    """Return resolved log-file descriptors for one Linux process."""
    paths: list[str] = []
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = descriptor.resolve(strict=True)
        except (FileNotFoundError, PermissionError):
            continue
        if target.suffix == ".log":
            paths.append(str(target))
    return sorted(paths)


async def _wait_for_log_text(path: Path, pattern: str, timeout: float = 10.0) -> str:
    """Wait asynchronously until a live child appends a matching log fragment."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if pattern in text:
            return text
        await asyncio.sleep(0.02)
    raise TimeoutError(f"log file did not contain {pattern!r} before timeout")


def _child_log(context: ChildLoggingContext, message: str, result_queue: Any) -> None:
    """Install one child context, emit a record and report its local resources."""
    runtime = context.install()
    try:
        logger.info(message)
        _flush_default_handlers()
        result_queue.put(
            {
                "handler_names": sorted(type(handler).__name__ for handler in logger.handlers),
                "owns_rotation": runtime.owns_rotation,
                "rotation_threads": _rotation_thread_names(),
                "open_files": _open_log_files(os.getpid()),
            }
        )
    finally:
        runtime.close()


def _child_log_after_external_rotation(
    context: ChildLoggingContext,
    message: str,
    ready: Any,
    release: Any,
    result_queue: Any,
) -> None:
    """Open child writers before a rename, then emit after the active path changes."""
    runtime = context.install()
    try:
        ready.set()
        if not release.wait(10):
            result_queue.put("release-timeout")
            return
        logger.info(message)
        result_queue.put("written")
    finally:
        runtime.close()


class LoggingProbeWorker(BaseWorker):
    """Emit deterministic records and report child handler state through the log."""

    def __init__(self, worker_id: int, task_queue: Any) -> None:
        """Store only inputs required by the abstract worker surface."""
        self.worker_id = worker_id
        self.task_queue = task_queue

    async def initialize(self) -> None:
        """Satisfy the abstract worker contract without registering tasks."""

    async def start(self) -> None:
        """Write structured levels and exit without starting the normal worker loop."""
        handler_names = sorted(type(handler).__name__ for handler in logger.handlers)
        logger.info(
            "base-manager-info-token handlers=%s start_method=%s rotation_threads=%s",
            ",".join(handler_names),
            multiprocessing.get_start_method(),
            ",".join(_rotation_thread_names()),
        )
        logger.warning("base-manager-warning-token")
        try:
            raise RuntimeError("base-manager-exception-token")
        except RuntimeError:
            logger.exception("base-manager-traceback-token")


def _async_process_logging_probe() -> dict[str, Any]:
    """Emit one structured warning and one raw console line from a temporary child."""
    handler_names = sorted(type(handler).__name__ for handler in logger.handlers)
    logger.warning("async-manager-warning-token handlers=%s", ",".join(handler_names))
    print("async-manager-raw-output-token", flush=True)
    return {
        "billiard_start_method": cast(Any, billiard).get_start_method(),
        "handler_names": handler_names,
        "logging_disable_level": logging.root.manager.disable,
        "rotation_threads": _rotation_thread_names(),
    }


def _async_process_database_probe(database_url: str) -> dict[str, Any]:
    """Open a child-local engine and report whether parent DB state was inherited."""
    inherited_manager = _ASYNC_PROCESS_PARENT_DB_MANAGER

    async def query() -> int:
        manager = DatabaseManager(
            DatabaseConfig(
                url=database_url,
                echo=False,
            )
        )
        try:
            await manager.initialize()
            async with manager.engine.connect() as connection:
                return (
                    await connection.execute(
                        text("select value from process_probe")
                    )
                ).scalar_one()
        finally:
            await manager.close()

    return {
        "billiard_start_method": cast(Any, billiard).get_start_method(),
        "inherited_initialized_manager": (
            inherited_manager is not None and inherited_manager.is_initialized
        ),
        "value": asyncio.run(query()),
    }


class ProcessManagerLoggingTest(unittest.TestCase):
    """Verify framework process helpers attach the active child writer context."""

    def tearDown(self) -> None:
        """Close an active runtime if a process assertion exits early."""
        runtime = get_active_runtime()
        if runtime is not None:
            runtime.close()

    def test_base_manager_snapshots_context_when_starting_real_worker(self) -> None:
        """A manager built early resolves the current runtime immediately before start."""
        with tempfile.TemporaryDirectory() as tmp:
            manager = BaseManager(LoggingProbeWorker, num_workers=1, logging_context=None)
            runtime = init_logging(
                "base_manager",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            worker_info = None
            try:
                self.assertTrue(asyncio.run(manager._start_worker(0)))
                worker_info = manager.workers[0]
                worker_info.process.join(10)
                if worker_info.process.is_alive():
                    worker_info.process.terminate()
                    worker_info.process.join(2)
                self.assertFalse(worker_info.process.is_alive())
                self.assertEqual(0, worker_info.process.exitcode)
            finally:
                if worker_info is not None:
                    worker_info.task_queue.close()
                    worker_info.task_queue.join_thread()
                manager.workers.clear()
                runtime.close()

            log_text = (Path(tmp) / "base_manager.log").read_text(encoding="utf-8")
            self.assertIn("AtomicAppendFileHandler", log_text)
            self.assertIn("start_method=spawn", log_text)
            self.assertIn("rotation_threads=", log_text)
            self.assertNotIn("rotation_threads=oldman-log-rotation", log_text)
            self.assertEqual(1, log_text.count("base-manager-info-token"))
            self.assertEqual(1, log_text.count("base-manager-warning-token"))
            self.assertEqual(1, log_text.count("base-manager-traceback-token"))
            self.assertIn("base-manager-exception-token", log_text)
            self.assertIn("Traceback (most recent call last)", log_text)

        source = inspect.getsource(BaseManager._worker_process_entry)
        self.assertNotIn("StreamHandler", source)
        self.assertNotIn("root_logger", source)

    def test_base_manager_accepts_an_explicit_forkserver_context(self) -> None:
        """Advanced callers can select forkserver without changing global process state."""
        self.assertIn("process_start_method", inspect.signature(BaseManager).parameters)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = init_logging(
                "base_manager_forkserver",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            manager = BaseManager(
                LoggingProbeWorker,
                num_workers=1,
                logging_context=None,
                process_start_method="forkserver",
            )
            worker_info = None
            try:
                self.assertTrue(asyncio.run(manager._start_worker(0)))
                worker_info = manager.workers[0]
                worker_info.process.join(10)
                if worker_info.process.is_alive():
                    worker_info.process.terminate()
                    worker_info.process.join(2)
                self.assertFalse(worker_info.process.is_alive())
                self.assertEqual(0, worker_info.process.exitcode)
            finally:
                if worker_info is not None:
                    worker_info.task_queue.close()
                    worker_info.task_queue.join_thread()
                manager.workers.clear()
                runtime.close()

            log_text = (Path(tmp) / "base_manager_forkserver.log").read_text(encoding="utf-8")
            self.assertIn("start_method=forkserver", log_text)

    def test_async_process_manager_separates_structured_logs_from_raw_output(self) -> None:
        """Structured records retain level metadata while print remains console-only."""
        with tempfile.TemporaryDirectory() as tmp:
            console = io.StringIO()
            with (
                patch("oldman.processes.executor.sys.stdout", console),
                patch("oldman.processes.executor.sys.stderr", console),
            ):
                manager = AsyncProcessManager(workers=1, logging_context=None)
                runtime = init_logging(
                    "async_manager",
                    logger_path=tmp,
                    logger_level=logging.INFO,
                    color="never",
                )
                try:
                    result = asyncio.run(
                        manager.run_with_timeout(_async_process_logging_probe, _timeout=10)
                    )
                finally:
                    runtime.close()

                deadline = time.monotonic() + 2
                while (
                    "async-manager-raw-output-token" not in console.getvalue()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)

            log_text = (Path(tmp) / "async_manager.log").read_text(encoding="utf-8")
            self.assertIsNotNone(result, f"{console.getvalue()}\n{log_text}")
            result_payload = cast(dict[str, Any], result)
            self.assertEqual("spawn", result_payload["billiard_start_method"])
            self.assertIn("AtomicAppendFileHandler", result_payload["handler_names"])
            self.assertEqual(logging.NOTSET, result_payload["logging_disable_level"])
            self.assertEqual([], result_payload["rotation_threads"])
            self.assertIn("async-manager-raw-output-token", console.getvalue())
            self.assertEqual(1, log_text.count("async-manager-warning-token"))
            self.assertIn("WARNING", log_text)
            self.assertNotIn("async-manager-raw-output-token", log_text)

        wrapper_source = inspect.getsource(AsyncProcessManager._target_wrapper)
        reader_source = inspect.getsource(ParentLogPipeReader.run)
        self.assertNotIn("logging.shutdown", wrapper_source)
        self.assertNotIn("StreamHandler", wrapper_source)
        self.assertNotIn("logging.LogRecord", reader_source)
        self.assertNotIn("getLogger", reader_source)

    def test_async_process_manager_propagates_disabled_logging_policy(self) -> None:
        """Spawn preserves an explicit parent-wide logging cutoff."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = init_logging(
                "async_manager_disabled",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            manager = AsyncProcessManager(workers=1, logging_context=None)
            logging.disable(logging.CRITICAL)
            try:
                result = asyncio.run(
                    manager.run_with_timeout(
                        _async_process_logging_probe,
                        _timeout=10,
                    )
                )
            finally:
                logging.disable(logging.NOTSET)
                runtime.close()

            self.assertIsNotNone(result)
            payload = cast(dict[str, Any], result)
            self.assertEqual(logging.CRITICAL, payload["logging_disable_level"])
            log_path = Path(tmp) / "async_manager_disabled.log"
            log_text = (
                log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            )
            self.assertNotIn("async-manager-warning-token", log_text)

    def test_async_process_manager_cancellation_cannot_outlive_process_start(
        self,
    ) -> None:
        """Cancellation waits for spawn and then reaps the newly created child."""
        started: list[Any] = []
        start_entered = threading.Event()
        release_start = threading.Event()
        original_start = process_module._start_spawn_process

        def delayed_start(process: Any) -> None:
            """Hold Process.start until the caller has issued cancellation."""
            started.append(process)
            start_entered.set()
            if not release_start.wait(5):
                raise TimeoutError("test did not release delayed process start")
            original_start(process)

        async def exercise() -> tuple[int | None, bool, int]:
            manager = AsyncProcessManager(workers=1, logging_context=None)
            try:
                with patch(
                    "oldman.processes.executor._start_spawn_process",
                    side_effect=delayed_start,
                ):
                    task = asyncio.create_task(
                        manager.run_with_timeout(os.getpid, _timeout=10)
                    )
                    entered = await asyncio.to_thread(start_entered.wait, 5)
                    self.assertTrue(entered)
                    task.cancel()
                    release_start.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                process = started[0]
                return process.pid, process.is_alive(), len(manager.active_processes)
            finally:
                release_start.set()
                await manager.shutdown()

        pid, alive, active_count = asyncio.run(exercise())
        self.assertIsNotNone(pid)
        self.assertFalse(alive)
        self.assertEqual(0, active_count)
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_async_process_manager_does_not_inherit_parent_database_state(
        self,
    ) -> None:
        """A temporary child must import clean state instead of copying a live pool."""
        global _ASYNC_PROCESS_PARENT_DB_MANAGER

        with tempfile.TemporaryDirectory() as tmp:
            database_url = (
                f"sqlite+aiosqlite:///{(Path(tmp) / 'process.sqlite3').as_posix()}"
            )

            async def exercise() -> tuple[dict[str, Any] | None, int]:
                parent_manager = DatabaseManager(
                    DatabaseConfig(
                        url=database_url,
                        echo=False,
                    )
                )
                _ASYNC_PROCESS_PARENT_DB_MANAGER = parent_manager
                process_manager = AsyncProcessManager(
                    workers=1,
                    logging_context=None,
                )
                try:
                    await parent_manager.initialize()
                    async with parent_manager.engine.begin() as connection:
                        await connection.execute(
                            text("create table process_probe (value integer)")
                        )
                        await connection.execute(
                            text("insert into process_probe values (42)")
                        )

                    child_result = await process_manager.run_with_timeout(
                        _async_process_database_probe,
                        args=(database_url,),
                        _timeout=10,
                    )
                    async with parent_manager.engine.connect() as connection:
                        parent_value = (
                            await connection.execute(
                                text("select value from process_probe")
                            )
                        ).scalar_one()
                    return child_result, parent_value
                finally:
                    await process_manager.shutdown()
                    await parent_manager.close()

            try:
                result, parent_value = asyncio.run(exercise())
            finally:
                _ASYNC_PROCESS_PARENT_DB_MANAGER = None

        self.assertIsNotNone(result)
        payload = cast(dict[str, Any], result)
        self.assertEqual("spawn", payload["billiard_start_method"])
        self.assertFalse(payload["inherited_initialized_manager"])
        self.assertEqual(42, payload["value"])
        self.assertEqual(42, parent_value)

    def test_base_manager_worker_kill_and_restart_keeps_direct_logging_live(self) -> None:
        """A killed persistent worker is replaced without creating a child coordinator."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "base_restart.log"
            runtime = init_logging(
                "base_restart",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
                config={
                    "root": {"handlers": ["file"]},
                    "loggers": {"default": {"handlers": ["file"]}},
                },
            )
            manager = BaseManager(
                RestartLoggingWorker,
                num_workers=1,
                max_worker_restarts=2,
                worker_restart_delay=0,
                logging_context=None,
            )
            first_worker = None
            second_worker = None

            async def exercise_restart() -> tuple[int, int]:
                """Kill generation one and invoke the manager's existing restart path."""
                self.assertTrue(await manager._start_worker(0))
                nonlocal first_worker, second_worker
                first_worker = manager.workers[0]
                first_pid = cast(int, first_worker.process.pid)
                await _wait_for_log_text(log_path, f"BASE_RESTART_START pid={first_pid}")
                os.kill(first_pid, signal.SIGKILL)
                await asyncio.to_thread(first_worker.process.join, 5)
                self.assertFalse(first_worker.process.is_alive())

                self.assertTrue(await manager._restart_worker(0))
                second_worker = manager.workers[0]
                second_pid = cast(int, second_worker.process.pid)
                await _wait_for_log_text(log_path, f"BASE_RESTART_START pid={second_pid}")
                return first_pid, second_pid

            try:
                first_pid, second_pid = asyncio.run(exercise_restart())
            finally:
                for worker_info in (first_worker, second_worker):
                    if worker_info is None:
                        continue
                    if worker_info.process.is_alive():
                        worker_info.process.terminate()
                        worker_info.process.join(3)
                    worker_info.task_queue.close()
                    worker_info.task_queue.join_thread()
                manager.workers.clear()
                runtime.close()

            self.assertNotEqual(first_pid, second_pid)
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn(f"BASE_RESTART_TICK pid={first_pid}", log_text)
            self.assertIn(f"BASE_RESTART_TICK pid={second_pid}", log_text)
            self.assertEqual(2, log_text.count("start_method=spawn"))
            self.assertNotIn("rotation_threads=oldman-log-rotation", log_text)

    def test_async_process_manager_recovers_after_timeout_and_sigkill(self) -> None:
        """Terminated temporary children cannot poison logs or later process launches."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "async_recovery.log"
            runtime = init_logging(
                "async_recovery",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
                config={
                    "root": {"handlers": ["file"]},
                    "loggers": {"default": {"handlers": ["file"]}},
                },
            )
            console = io.StringIO()

            async def exercise_failures() -> tuple[dict[str, Any] | None, bool, Any, dict[str, Any] | None]:
                """Run normal, timeout, abrupt-death and final-normal children in order."""
                manager = AsyncProcessManager(workers=1, logging_context=None)
                first = await manager.run_with_timeout(
                    temporary_normal_target,
                    args=("first",),
                    _timeout=5,
                )
                timed_out = False
                try:
                    await manager.run_with_timeout(
                        temporary_timeout_target,
                        args=(5.0,),
                        _timeout=1,
                    )
                except ProcessTimeoutError:
                    timed_out = True
                killed = await manager.run_with_timeout(
                    temporary_sigkill_target,
                    _timeout=5,
                )
                final = await manager.run_with_timeout(
                    temporary_normal_target,
                    args=("final",),
                    _timeout=5,
                )
                await manager.shutdown()
                return first, timed_out, killed, final

            try:
                with (
                    patch("oldman.processes.executor.sys.stdout", console),
                    patch("oldman.processes.executor.sys.stderr", console),
                ):
                    first, timed_out, killed, final = asyncio.run(exercise_failures())
            finally:
                runtime.close()

            self.assertEqual("first", cast(dict[str, Any], first)["label"])
            self.assertIsNone(killed)
            self.assertEqual("final", cast(dict[str, Any], final)["label"])
            self.assertEqual([], cast(dict[str, Any], final)["rotation_threads"])
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("ASYNC_NORMAL:first", log_text)
            self.assertIn("ASYNC_TIMEOUT_BEFORE_KILL", log_text)
            self.assertIn("ASYNC_SIGKILL_BEFORE_EXIT", log_text)
            self.assertIn("ASYNC_NORMAL:final", log_text)
            self.assertIn("ASYNC_RAW:first", console.getvalue())
            self.assertIn("ASYNC_RAW:final", console.getvalue())
            # Check this after recovery evidence so one assertion covers the full
            # required normal/timeout/SIGKILL/normal sequence.
            self.assertTrue(timed_out)


class DirectMultiprocessIntegrityTest(unittest.TestCase):
    """Verify complete unbuffered records from one main and four child processes."""

    def tearDown(self) -> None:
        """Close an active runtime after a failed process assertion."""
        runtime = get_active_runtime()
        if runtime is not None:
            runtime.close()

    def test_main_and_four_children_preserve_every_unique_record(self) -> None:
        """Shared O_APPEND writers keep complete UTF-8 lines without ANSI bytes."""
        context: Any = multiprocessing.get_context("spawn")
        producers = [f"child-{index}" for index in range(4)]
        records_per_producer = 150
        with tempfile.TemporaryDirectory() as tmp:
            runtime = init_logging(
                "integrity",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="always",
                config={
                    "root": {"handlers": ["file"]},
                    "loggers": {"default": {"handlers": ["file"]}},
                },
            )
            start_event = context.Event()
            ready_queue = context.Queue()
            processes = [
                context.Process(
                    target=write_record_sequence,
                    args=(
                        runtime.child_context,
                        producer,
                        records_per_producer,
                        start_event,
                        ready_queue,
                    ),
                )
                for producer in producers
            ]
            for process in processes:
                process.start()
            reports = [ready_queue.get(timeout=10) for _ in processes]
            start_event.set()
            for sequence in range(records_per_producer):
                logger.info("MP_RECORD:main:%d", sequence)
            for process in processes:
                process.join(15)
            runtime.close()
            try:
                for process in processes:
                    self.assertFalse(process.is_alive())
                    self.assertEqual(0, process.exitcode)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join(2)
                ready_queue.close()
                ready_queue.join_thread()

            self.assertTrue(all(not report["owns_rotation"] for report in reports))
            self.assertTrue(all(report["rotation_threads"] == [] for report in reports))
            combined = b"".join(
                path.read_bytes()
                for path in sorted(Path(tmp).glob("integrity.log*"))
            )
            expected = {
                (producer, sequence)
                for producer in ["main", *producers]
                for sequence in range(records_per_producer)
            }
            observed = {
                (producer, int(sequence))
                for producer, sequence in re.findall(
                    rb"MP_RECORD:([a-z0-9-]+):(\d+)",
                    combined,
                )
            }
            observed = {
                (producer.decode("ascii"), sequence)
                for producer, sequence in observed
            }
            self.assertEqual(expected, observed)
            self.assertNotIn(b"\x1b[", combined)
            self.assertTrue(
                all(line.endswith(b"\n") for line in combined.splitlines(keepends=True))
            )


class ChildLoggingContextTest(unittest.TestCase):
    """Verify one explicit writer-only child protocol under fork and spawn."""

    def tearDown(self) -> None:
        """Close an active parent runtime after failed process assertions."""
        runtime = get_active_runtime()
        if runtime is not None:
            runtime.close()

    def test_child_context_uses_atomic_handler_under_fork_and_spawn(self) -> None:
        """Every child reopens local writers without starting a coordinator thread."""
        for method in ("fork", "spawn"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as tmp:
                runtime = init_logging(
                    f"child-{method}",
                    logger_path=tmp,
                    logger_level=logging.INFO,
                    color="never",
                )
                context: Any = multiprocessing.get_context(method)
                result_queue = context.Queue()
                process = context.Process(
                    target=_child_log,
                    args=(runtime.child_context, f"{method}-message", result_queue),
                )
                process.start()
                process.join(10)
                runtime.close()

                self.assertFalse(process.is_alive())
                self.assertEqual(0, process.exitcode)
                try:
                    report = result_queue.get(timeout=2)
                except Empty as exc:
                    self.fail(f"{method} child did not report handler types: {exc}")
                finally:
                    result_queue.close()
                    result_queue.join_thread()
                self.assertIn("AtomicAppendFileHandler", report["handler_names"])
                self.assertFalse(report["owns_rotation"])
                self.assertEqual([], report["rotation_threads"])
                self.assertIn(
                    str(Path(tmp) / f"child-{method}.log"),
                    report["open_files"],
                )
                self.assertIn(
                    f"{method}-message",
                    (Path(tmp) / f"child-{method}.log").read_text(encoding="utf-8"),
                )

    def test_child_reopens_the_active_file_after_external_rotation(self) -> None:
        """A child must stop writing to a renamed inode after the active path changes."""
        context: Any = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            runtime = init_logging(
                "rollover",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            ready = context.Event()
            release = context.Event()
            result_queue = context.Queue()
            process = context.Process(
                target=_child_log_after_external_rotation,
                args=(runtime.child_context, "after-rollover", ready, release, result_queue),
            )
            process.start()
            self.assertTrue(ready.wait(10), "child did not install its handlers")

            active = Path(tmp) / "rollover.log"
            archived = Path(tmp) / "rollover.log.manual"
            logger.info("before-rollover")
            active.rename(archived)
            active.touch()
            release.set()
            process.join(10)
            runtime.close()

            self.assertFalse(process.is_alive())
            self.assertEqual(0, process.exitcode)
            try:
                self.assertEqual("written", result_queue.get(timeout=2))
            except Empty as exc:
                self.fail(f"child did not report its write: {exc}")
            finally:
                result_queue.close()
                result_queue.join_thread()
            self.assertIn("before-rollover", archived.read_text(encoding="utf-8"))
            self.assertIn("after-rollover", active.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
