"""Real SimpleApplication fixture for application and child-process performance."""

# ruff: noqa: E402 -- settings and handler policy must precede runtime imports.

from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import signal
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings

type HandlerVariant = Literal["current", "stdlib", "no_logging"]

FILE_HANDLER_NAMES = ("file", "access_file", "database_file")
FUTURE_ROTATION_WHEN = "S"
FUTURE_ROTATION_INTERVAL = 2**31 - 1


def _required_environment(name: str) -> str:
    """Return one required fixture setting or fail before application startup."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"missing process performance environment variable: {name}")
    return value


def _handler_variant(value: str) -> HandlerVariant:
    """Reject modes outside the fixed current/stdlib/disabled comparison."""
    if value not in {"current", "stdlib", "no_logging"}:
        raise RuntimeError(f"unsupported process performance variant: {value!r}")
    return cast(HandlerVariant, value)


LOG_DIR = Path(_required_environment("OLDMAN_PROCESS_PERF_LOG_DIR"))
RESULT_FILE = Path(_required_environment("OLDMAN_PROCESS_PERF_RESULT_FILE"))
APP_NAME = _required_environment("OLDMAN_PROCESS_PERF_APP_NAME")
TOKEN = _required_environment("OLDMAN_PROCESS_PERF_TOKEN")
VARIANT = _handler_variant(_required_environment("OLDMAN_PROCESS_PERF_VARIANT"))
MAIN_RECORDS = int(_required_environment("OLDMAN_PROCESS_PERF_MAIN_RECORDS"))
BASE_RECORDS = int(_required_environment("OLDMAN_PROCESS_PERF_BASE_RECORDS"))
ASYNC_RECORDS = int(_required_environment("OLDMAN_PROCESS_PERF_ASYNC_RECORDS"))
ASYNC_RUNS = int(_required_environment("OLDMAN_PROCESS_PERF_ASYNC_RUNS"))
SUBPROCESS_BYTES = int(_required_environment("OLDMAN_PROCESS_PERF_SUBPROCESS_BYTES"))
BASE_RESULT = RESULT_FILE.with_name(f"{RESULT_FILE.stem}-base.json")

for _name, _value in (
    ("MAIN_RECORDS", MAIN_RECORDS),
    ("BASE_RECORDS", BASE_RECORDS),
    ("ASYNC_RECORDS", ASYNC_RECORDS),
    ("ASYNC_RUNS", ASYNC_RUNS),
    ("SUBPROCESS_BYTES", SUBPROCESS_BYTES),
):
    if _value <= 0:
        raise RuntimeError(f"{_name} must be positive, got {_value}")

conf.__dict__["settings"] = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {"dir": LOG_DIR, "color": "never"},
        "process": {"pid_dir": LOG_DIR},
        "web": {"workers": 1},
        "static": {"root": "", "url": ""},
        "i18n": {"use_i18n": False},
    }
)

from oldman.logging.config import LOGGING_CONFIG_DEFAULTS

for _handler_name in FILE_HANDLER_NAMES:
    _handler_config = LOGGING_CONFIG_DEFAULTS["handlers"][_handler_name]
    _handler_config["when"] = FUTURE_ROTATION_WHEN
    _handler_config["interval"] = FUTURE_ROTATION_INTERVAL
    if VARIANT == "stdlib":
        _handler_config["class"] = "logging.handlers.TimedRotatingFileHandler"

if VARIANT == "no_logging":
    logging.disable(logging.CRITICAL)

from oldman.processes import (
    AsyncProcessManager,
    ProcessTimeoutError,
    SubprocessTimeoutError,
    create_subprocess_exec,
)
from oldman.runtime.simple import SimpleApplication
from oldman.tasks.manager import BaseManager
from tests.fixtures.logging_direct_service import (
    PerformanceLoggingWorker,
    performance_async_target,
    performance_log_sequence,
    performance_sigkill_target,
    performance_timeout_target,
)


def _usage_snapshot(who: int) -> dict[str, float]:
    """Capture cumulative user/system CPU for self or already-reaped children."""
    usage = resource.getrusage(who)
    return {
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
    }


def _usage_delta(
    before: dict[str, float],
    after: dict[str, float],
    *,
    elapsed_seconds: float,
    units: int,
) -> dict[str, float]:
    """Normalize one CPU delta by completed work and elapsed wall time."""
    user_seconds = after["user_seconds"] - before["user_seconds"]
    system_seconds = after["system_seconds"] - before["system_seconds"]
    total_seconds = user_seconds + system_seconds
    return {
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_unit": total_seconds / units,
        "average_cores": total_seconds / elapsed_seconds,
    }


async def _wait_for_json(path: Path, timeout: float = 15.0) -> dict[str, Any]:
    """Read a child result only after its atomic replace becomes visible."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            await asyncio.sleep(0.02)
            continue
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
        await asyncio.sleep(0.02)
    raise TimeoutError(f"timed out waiting for child result {path}")


async def _wait_for_replacement(
    manager: BaseManager,
    original_pid: int,
    timeout: float = 15.0,
) -> int:
    """Wait until BaseManager publishes a live replacement worker PID."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker = manager.workers.get(0)
        worker_pid = None if worker is None else worker.process.pid
        if (
            worker is not None
            and worker_pid not in {None, original_pid}
            and worker.process.is_alive()
        ):
            return cast(int, worker_pid)
        await asyncio.sleep(0.05)
    raise TimeoutError(f"BaseManager did not replace PID {original_pid}")


def _process_group_pids(process_group: int) -> list[int]:
    """Return live non-zombie Linux processes in one subprocess-owned group."""
    pids: list[int] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            suffix = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            state = suffix[0]
            group = int(suffix[2])
        except (IndexError, OSError, ValueError):
            continue
        if group == process_group and state != "Z":
            pids.append(int(stat_path.parent.name))
    return sorted(pids)


async def _run_output_subprocesses(byte_count: int) -> dict[str, Any]:
    """Measure inherited and PIPE output while proving the event loop stays alive."""
    source = (
        "import os,sys; n=int(sys.argv[1]); data=b'x'*n; "
        "os.write(1,data); os.write(2,data)"
    )
    children_before = _usage_snapshot(resource.RUSAGE_CHILDREN)
    started_at = time.perf_counter()
    inherited = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
        str(byte_count),
    )
    inherited_returncode = await inherited.wait()
    inherited_elapsed = time.perf_counter() - started_at

    ticks = 0
    ticking = True

    async def ticker() -> None:
        """Count loop turns while communicate drains both child pipes."""
        nonlocal ticks
        while ticking:
            ticks += 1
            await asyncio.sleep(0)

    ticker_task = asyncio.create_task(ticker())
    started_at = time.perf_counter()
    piped = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
        str(byte_count),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await piped.communicate()
    if stdout is None or stderr is None:
        raise RuntimeError("PIPE subprocess did not return both output streams")
    pipe_elapsed = time.perf_counter() - started_at
    ticking = False
    await ticker_task
    child_cpu = _usage_delta(
        children_before,
        _usage_snapshot(resource.RUSAGE_CHILDREN),
        elapsed_seconds=inherited_elapsed + pipe_elapsed,
        units=byte_count * 4,
    )
    return {
        "inherited_pid": inherited.pid,
        "inherited_returncode": inherited_returncode,
        "inherited_elapsed_seconds": inherited_elapsed,
        "pipe_pid": piped.pid,
        "pipe_returncode": piped.returncode,
        "pipe_elapsed_seconds": pipe_elapsed,
        "pipe_stdout_bytes": len(stdout),
        "pipe_stderr_bytes": len(stderr),
        "event_loop_ticks": ticks,
        "child_cpu": child_cpu,
    }


async def _run_subprocess_cleanup() -> dict[str, Any]:
    """Prove timeout and task cancellation remove their complete process groups."""
    sleeper = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "time.sleep(60)"
    )
    timeout_process = await create_subprocess_exec(
        sys.executable,
        "-c",
        sleeper,
        terminate_grace_period=0.1,
    )
    await asyncio.sleep(0.05)
    timeout_group_before = _process_group_pids(timeout_process.process_group)
    timed_out = False
    try:
        await timeout_process.wait(timeout=0.2)
    except SubprocessTimeoutError:
        timed_out = True
    timeout_group_gone = not _process_group_pids(timeout_process.process_group)

    cancelled_process = await create_subprocess_exec(
        sys.executable,
        "-c",
        sleeper,
        terminate_grace_period=0.1,
    )
    wait_task = asyncio.create_task(cancelled_process.wait())
    await asyncio.sleep(0.05)
    cancelled_group_before = _process_group_pids(cancelled_process.process_group)
    wait_task.cancel()
    cancelled = False
    try:
        await wait_task
    except asyncio.CancelledError:
        cancelled = True
    cancelled_group_gone = not _process_group_pids(cancelled_process.process_group)
    return {
        "timeout_pid": timeout_process.pid,
        "timed_out": timed_out,
        "timeout_group_pids_before_cleanup": timeout_group_before,
        "timeout_group_gone": timeout_group_gone,
        "cancelled_pid": cancelled_process.pid,
        "cancelled": cancelled,
        "cancelled_group_pids_before_cleanup": cancelled_group_before,
        "cancelled_group_gone": cancelled_group_gone,
    }


class ProcessPerformanceService(SimpleApplication):
    """Run every supported non-Sanic process model through real application logging."""

    def __init__(self, app_name: str) -> None:
        """Initialize the real SimpleApplication and retain structured evidence."""
        super().__init__(app_name)
        self.result: dict[str, Any] = {}
        self.failure: BaseException | None = None

    def prepare(self) -> None:
        """Keep the performance fixture independent of project startup work."""

    async def _run_async(self, *args: Any, **kwargs: Any) -> None:
        """Retain failures that SimpleApplication.run otherwise logs and swallows."""
        try:
            await super()._run_async(*args, **kwargs)
        except BaseException as exc:
            self.failure = exc
            raise

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Measure main, persistent, temporary and subprocess paths in sequence."""
        del args, kwargs
        total_before = _usage_snapshot(resource.RUSAGE_SELF)
        total_started = time.perf_counter()
        self.result["simple_application"] = performance_log_sequence(
            TOKEN,
            "simple_application",
            MAIN_RECORDS,
        )
        self.result["base_manager"] = await self._run_base_manager()
        self.result["async_manager"] = await self._run_async_manager()
        self.result["subprocess"] = {
            "output": await _run_output_subprocesses(SUBPROCESS_BYTES),
            "cleanup": await _run_subprocess_cleanup(),
        }
        total_elapsed = time.perf_counter() - total_started
        total_units = (
            MAIN_RECORDS
            + BASE_RECORDS * 2
            + ASYNC_RECORDS * (ASYNC_RUNS + 1)
        )
        self.result["application_cpu"] = _usage_delta(
            total_before,
            _usage_snapshot(resource.RUSAGE_SELF),
            elapsed_seconds=total_elapsed,
            units=total_units,
        )
        self.result["application_elapsed_seconds"] = total_elapsed

    async def _run_base_manager(self) -> dict[str, Any]:
        """Measure one worker, force a restart, and measure its replacement."""
        os.environ["OLDMAN_PROCESS_PERF_BASE_RESULT"] = str(BASE_RESULT)
        manager = BaseManager(
            PerformanceLoggingWorker,
            num_workers=1,
            max_worker_restarts=2,
            worker_restart_delay=0,
            monitor_interval=1,
        )
        started_at = time.perf_counter()
        await manager.start()
        try:
            first = await _wait_for_json(BASE_RESULT)
            first_pid = int(first["pid"])
            BASE_RESULT.unlink(missing_ok=True)
            os.kill(first_pid, signal.SIGKILL)
            second_pid = await _wait_for_replacement(manager, first_pid)
            second = await _wait_for_json(BASE_RESULT)
            if int(second["pid"]) != second_pid:
                raise RuntimeError(
                    f"replacement result PID {second['pid']} != manager PID {second_pid}"
                )
            return {
                "first": first,
                "replacement": second,
                "restart_completed": True,
                "elapsed_seconds": time.perf_counter() - started_at,
            }
        finally:
            await manager.shutdown()

    async def _run_async_manager(self) -> dict[str, Any]:
        """Measure repeated children, timeout, abrupt exit and recovery."""
        manager = AsyncProcessManager(workers=1)
        started_at = time.perf_counter()
        results: list[dict[str, Any]] = []
        try:
            for index in range(ASYNC_RUNS):
                result = await manager.run_with_timeout(
                    performance_async_target,
                    args=(TOKEN, f"async_{index}", ASYNC_RECORDS),
                    _timeout=30,
                )
                if not isinstance(result, dict):
                    raise RuntimeError(f"async child {index} returned {result!r}")
                results.append(result)

            timed_out = False
            timeout_started = time.perf_counter()
            try:
                await manager.run_with_timeout(
                    performance_timeout_target,
                    args=(TOKEN, 5.0),
                    _timeout=1,
                )
            except ProcessTimeoutError:
                timed_out = True
            timeout_elapsed = time.perf_counter() - timeout_started

            killed = await manager.run_with_timeout(
                performance_sigkill_target,
                args=(TOKEN,),
                _timeout=5,
            )
            recovery = await manager.run_with_timeout(
                performance_async_target,
                args=(TOKEN, "async_recovery", ASYNC_RECORDS),
                _timeout=30,
            )
            if not isinstance(recovery, dict):
                raise RuntimeError(f"async recovery returned {recovery!r}")
            return {
                "runs": results,
                "timed_out": timed_out,
                "timeout_elapsed_seconds": timeout_elapsed,
                "sigkill_result": killed,
                "recovery": recovery,
                "elapsed_seconds": time.perf_counter() - started_at,
            }
        finally:
            await manager.shutdown()


def main() -> None:
    """Run the real application and atomically publish post-cleanup evidence."""
    application = ProcessPerformanceService(APP_NAME)
    application.run()
    if application.failure is not None:
        raise RuntimeError("process performance fixture failed") from application.failure
    required = {
        "simple_application",
        "base_manager",
        "async_manager",
        "subprocess",
        "application_cpu",
    }
    if application.result.keys() < required:
        raise RuntimeError(f"incomplete process result: {sorted(application.result)}")
    application.result.update(
        {
            "variant": VARIANT,
            "token": TOKEN,
            "pid": os.getpid(),
        }
    )
    temporary = RESULT_FILE.with_suffix(f"{RESULT_FILE.suffix}.tmp")
    temporary.write_text(
        json.dumps(application.result, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(RESULT_FILE)


if __name__ == "__main__":
    main()
