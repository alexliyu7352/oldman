"""Reusable real-process probes for direct logging acceptance tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import multiprocessing
import os
import resource
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, cast

import billiard

from oldman.logging import ChildLoggingContext, get_active_runtime, logger
from oldman.tasks.worker import BaseWorker


def rotation_thread_names() -> list[str]:
    """Return Oldman coordinator threads visible in the current process."""
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if thread.name == "oldman-log-rotation"
    )


def matrix_runtime_probe() -> dict[str, Any]:
    """Describe the process-local logging runtime used by a matrix child."""
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("process logging runtime is missing")
    return {
        "pid": os.getpid(),
        "handlers": sorted(type(handler).__name__ for handler in logger.handlers),
        "start_method": multiprocessing.get_start_method(),
        "billiard_start_method": cast(Any, billiard).get_start_method(),
        "owns_rotation": runtime.owns_rotation,
        "rotation_threads": rotation_thread_names(),
    }


def write_record_sequence(
    context: ChildLoggingContext,
    producer: str,
    count: int,
    start_event: Any,
    ready_queue: Any,
) -> None:
    """Install a child runtime and append one uniquely numbered record sequence."""
    runtime = context.install()
    try:
        ready_queue.put(
            {
                "pid": os.getpid(),
                "owns_rotation": runtime.owns_rotation,
                "rotation_threads": rotation_thread_names(),
            }
        )
        if not start_event.wait(10):
            raise TimeoutError("record writer did not receive its start event")
        for sequence in range(count):
            logger.info("MP_RECORD:%s:%d", producer, sequence)
    finally:
        runtime.close()


def write_across_rotation(
    context: ChildLoggingContext,
    producer: str,
    records_per_phase: int,
    rotation_barrier: Any,
) -> None:
    """Write before and immediately after a barrier shared with the coordinator."""
    runtime = context.install()
    try:
        for sequence in range(records_per_phase):
            logger.info("ROTATE_RECORD:%s:%d", producer, sequence)
        rotation_barrier.wait(timeout=10)
        for sequence in range(records_per_phase, records_per_phase * 2):
            logger.info("ROTATE_RECORD:%s:%d", producer, sequence)
            if sequence % 16 == 0:
                time.sleep(0)
    finally:
        runtime.close()


class RestartLoggingWorker(BaseWorker):
    """Continuously append records until the manager stops or kills this worker."""

    def __init__(self, worker_id: int, task_queue: Any) -> None:
        """Retain the manager inputs while the probe emits heartbeat records."""
        self.worker_id = worker_id
        self.task_queue = task_queue

    async def initialize(self) -> None:
        """Satisfy the worker contract without registering business tasks."""

    async def start(self) -> None:
        """Emit PID-tagged heartbeats until an external lifecycle action stops us."""
        logger.info(
            "BASE_RESTART_START pid=%d start_method=%s rotation_threads=%s",
            os.getpid(),
            multiprocessing.get_start_method(),
            ",".join(rotation_thread_names()),
        )
        sequence = 0
        while True:
            logger.info("BASE_RESTART_TICK pid=%d sequence=%d", os.getpid(), sequence)
            sequence += 1
            await asyncio.sleep(0.01)


class MatrixLoggingWorker(BaseWorker):
    """Keep the normal BaseWorker protocol while emitting matrix heartbeats."""

    def __init__(self, worker_id: int, task_queue: Any) -> None:
        """Initialize the real worker communication stack used by BaseManager."""
        super().__init__(worker_id, task_queue)
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Start a heartbeat without replacing BaseWorker's message loop."""
        token = os.environ["OLDMAN_TEST_MATRIX_TOKEN"]
        logger.info("MATRIX_BASE_STATE:%s:%s", token, json.dumps(matrix_runtime_probe(), sort_keys=True))
        self._heartbeat_task = asyncio.create_task(self._emit_heartbeats(token))

    async def _emit_heartbeats(self, token: str) -> None:
        """Write PID-tagged records until the manager stops this worker."""
        while self.running:
            logger.info("MATRIX_BASE_TICK:%s:%d", token, os.getpid())
            await asyncio.sleep(0.02)

    async def cleanup(self) -> None:
        """Stop the heartbeat before BaseWorker releases its communication state."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        await super().cleanup()


def _cpu_snapshot() -> dict[str, float]:
    """Return cumulative user and system CPU for one fixture process."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
    }


def _cpu_delta(
    before: dict[str, float],
    after: dict[str, float],
    *,
    elapsed_seconds: float,
    record_count: int,
) -> dict[str, Any]:
    """Normalize process CPU by one measured structured-log sequence."""
    user_seconds = after["user_seconds"] - before["user_seconds"]
    system_seconds = after["system_seconds"] - before["system_seconds"]
    total_seconds = user_seconds + system_seconds
    return {
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_record": total_seconds / record_count,
        "average_cores": total_seconds / elapsed_seconds,
    }


def performance_log_sequence(token: str, label: str, count: int) -> dict[str, Any]:
    """Write an exact child sequence and return its wall/CPU measurements."""
    if count <= 0:
        raise ValueError("performance record count must be positive")
    cpu_before = _cpu_snapshot()
    started_at = time.perf_counter()
    for sequence in range(count):
        logger.info(
            "PROCESS_PERF token=%s label=%s sequence=%08d",
            token,
            label,
            sequence,
        )
    elapsed = time.perf_counter() - started_at
    cpu = _cpu_delta(
        cpu_before,
        _cpu_snapshot(),
        elapsed_seconds=elapsed,
        record_count=count,
    )
    return {
        "pid": os.getpid(),
        "label": label,
        "records": count,
        "elapsed_seconds": elapsed,
        "records_per_second": count / elapsed,
        "cpu": cpu,
        "runtime": matrix_runtime_probe(),
    }


class PerformanceLoggingWorker(BaseWorker):
    """Measure one BaseManager worker's real child logging path."""

    async def initialize(self) -> None:
        """Write the configured sequence and publish an atomic child result."""
        token = os.environ["OLDMAN_PROCESS_PERF_TOKEN"]
        count = int(os.environ["OLDMAN_PROCESS_PERF_BASE_RECORDS"])
        result_path = Path(os.environ["OLDMAN_PROCESS_PERF_BASE_RESULT"])
        result = performance_log_sequence(
            token,
            f"base_manager_{os.getpid()}",
            count,
        )
        temporary = result_path.with_suffix(f"{result_path.suffix}.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        temporary.replace(result_path)


def performance_async_target(token: str, label: str, count: int) -> dict[str, Any]:
    """Measure one short-lived AsyncProcessManager child logging sequence."""
    return performance_log_sequence(token, label, count)


def performance_timeout_target(token: str, delay: float) -> None:
    """Emit a timeout marker before remaining alive for manager termination."""
    logger.warning("PROCESS_PERF_TIMEOUT token=%s pid=%d", token, os.getpid())
    time.sleep(delay)


def performance_sigkill_target(token: str) -> None:
    """Emit an abrupt-exit marker before killing the temporary child."""
    logger.warning("PROCESS_PERF_SIGKILL token=%s pid=%d", token, os.getpid())
    os.kill(os.getpid(), signal.SIGKILL)


def temporary_normal_target(label: str) -> dict[str, Any]:
    """Complete normally after emitting structured and raw child output."""
    logger.info("ASYNC_NORMAL:%s pid=%d", label, os.getpid())
    print(f"ASYNC_RAW:{label}", flush=True)
    return {
        "label": label,
        "rotation_threads": rotation_thread_names(),
    }


def temporary_timeout_target(delay: float) -> None:
    """Emit one record and remain alive until AsyncProcessManager times out."""
    logger.warning("ASYNC_TIMEOUT_BEFORE_KILL pid=%d", os.getpid())
    time.sleep(delay)


def temporary_sigkill_target() -> None:
    """Emit one record and terminate abruptly without running Python cleanup."""
    logger.warning("ASYNC_SIGKILL_BEFORE_EXIT pid=%d", os.getpid())
    os.kill(os.getpid(), signal.SIGKILL)


def matrix_normal_target(token: str, label: str) -> dict[str, Any]:
    """Emit structured and raw output, then return the child runtime probe."""
    probe = matrix_runtime_probe()
    logger.info("MATRIX_CHILD_PID:%d MATRIX_ASYNC:%s:%s", os.getpid(), token, label)
    print(f"MATRIX_RAW_STDOUT:{token}:{label}", flush=True)
    print(f"MATRIX_RAW_STDERR:{token}:{label}", file=sys.stderr, flush=True)
    return {**probe, "label": label}


def matrix_timeout_target(token: str, delay: float) -> None:
    """Emit one structured record and remain alive until the manager timeout."""
    logger.warning("MATRIX_CHILD_PID:%d MATRIX_TIMEOUT:%s", os.getpid(), token)
    time.sleep(delay)


def matrix_sigkill_target(token: str) -> None:
    """Emit one structured record and terminate without Python cleanup."""
    logger.warning("MATRIX_CHILD_PID:%d MATRIX_SIGKILL:%s", os.getpid(), token)
    os.kill(os.getpid(), signal.SIGKILL)


__all__ = [
    "MatrixLoggingWorker",
    "PerformanceLoggingWorker",
    "RestartLoggingWorker",
    "matrix_normal_target",
    "matrix_runtime_probe",
    "matrix_sigkill_target",
    "matrix_timeout_target",
    "performance_async_target",
    "performance_log_sequence",
    "performance_sigkill_target",
    "performance_timeout_target",
    "rotation_thread_names",
    "temporary_normal_target",
    "temporary_sigkill_target",
    "temporary_timeout_target",
    "write_across_rotation",
    "write_record_sequence",
]
