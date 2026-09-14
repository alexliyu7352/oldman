"""Real SimpleApplication used by the application logging matrix."""

# ruff: noqa: E402 -- project settings must exist before importing runtime consumers.

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings


def _required_environment(name: str) -> str:
    """Return one required fixture value with a useful startup error."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"missing fixture environment variable: {name}")
    return value


LOG_DIR = Path(_required_environment("OLDMAN_TEST_LOG_DIR"))
RESULT_FILE = Path(_required_environment("OLDMAN_TEST_RESULT_FILE"))
APP_NAME = _required_environment("OLDMAN_TEST_APP_NAME")
MATRIX_TOKEN = _required_environment("OLDMAN_TEST_MATRIX_TOKEN")

SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {"dir": LOG_DIR, "color": "never"},
        "process": {"pid_dir": LOG_DIR},
        "web": {"workers": 1, "static": {"root": "", "url": ""}},
        "i18n": {"use_i18n": False},
    }
)
conf.__dict__["settings"] = SETTINGS

from oldman.apps import AppRegistry
from oldman.logging import get_active_runtime, logger
from oldman.processes import AsyncProcessManager, ProcessTimeoutError, create_subprocess_exec
from oldman.processes.executor import ParentLogPipeReader
from oldman.runtime.bootstrap import ServiceBootstrapContext
from oldman.runtime.simple import SimpleApplication
from oldman.tasks.manager import BaseManager
from tests.fixtures.logging_direct_service import (
    MatrixLoggingWorker,
    matrix_normal_target,
    matrix_sigkill_target,
    matrix_timeout_target,
    rotation_thread_names,
)

BOOTSTRAP_CONTEXT = ServiceBootstrapContext(
    service_module=APP_NAME,
    config_file=LOG_DIR / "logging_simple_settings.yaml",
    settings=SETTINGS,
    apps=AppRegistry(),
)


def _read_text(path: Path) -> str:
    """Read a possibly not-yet-created fixture log."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


async def _wait_until(
    predicate: Callable[[], bool],
    description: str,
    *,
    timeout: float = 10.0,
) -> None:
    """Wait without blocking the application event loop."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {description}")


def _runtime_probe() -> dict[str, Any]:
    """Describe the main process runtime and its concrete handlers."""
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("application logging runtime is missing")
    return {
        "pid": os.getpid(),
        "handlers": sorted(
            type(handler).__name__
            for handler in logging.getLogger("default").handlers
        ),
        "owns_rotation": runtime.owns_rotation,
        "rotation_threads": rotation_thread_names(),
    }


def _parse_base_probes(text: str) -> dict[int, dict[str, Any]]:
    """Parse PID-indexed BaseManager runtime probes from formatted records."""
    marker = f"MATRIX_BASE_STATE:{MATRIX_TOKEN}:"
    probes: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        if marker not in line:
            continue
        probe = json.loads(line.split(marker, 1)[1])
        probes[int(probe["pid"])] = probe
    return probes


def _pipe_reader_thread_names() -> list[str]:
    """Return live AsyncProcessManager console reader threads."""
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if isinstance(thread, ParentLogPipeReader)
    )


async def _run_inherited_subprocess() -> dict[str, Any]:
    """Run an inherited-stdio child while proving the loop remains responsive."""
    code = (
        "import os,sys,time; "
        "token=sys.argv[1]; "
        "print(f'INHERITED_STDOUT:{token}', flush=True); "
        "print(f'INHERITED_STDERR:{token}', file=sys.stderr, flush=True); "
        "time.sleep(0.3)"
    )
    process = await create_subprocess_exec(sys.executable, "-c", code, MATRIX_TOKEN)
    ticks = 0
    while process.returncode is None:
        ticks += 1
        await asyncio.sleep(0.02)
    returncode = await process.wait()
    if returncode != 0:
        raise RuntimeError(f"inherited subprocess exited with {returncode}")
    return {
        "pid": process.pid,
        "returncode": returncode,
        "event_loop_ticks": ticks,
    }


async def _run_pipe_subprocess() -> dict[str, Any]:
    """Run an explicitly captured child without forwarding its output."""
    code = (
        "import sys; token=sys.argv[1]; "
        "print(f'PIPE_STDOUT:{token}', flush=True); "
        "print(f'PIPE_STDERR:{token}', file=sys.stderr, flush=True)"
    )
    process = await create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        MATRIX_TOKEN,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if stdout is None or stderr is None:
        raise RuntimeError("PIPE subprocess did not return both output streams")
    if process.returncode != 0:
        raise RuntimeError(f"PIPE subprocess exited with {process.returncode}")
    return {
        "pid": process.pid,
        "returncode": process.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
    }


class LoggingSimpleService(SimpleApplication):
    """Exercise every supported SimpleApplication child process boundary."""

    def __init__(self, app_name: str) -> None:
        """Initialize application logging and retain matrix results for the parent."""
        super().__init__(app_name, config=BOOTSTRAP_CONTEXT)
        self.result: dict[str, Any] = {}
        self.failure: BaseException | None = None

    def prepare(self) -> None:
        """Keep the fixture independent of project-specific startup work."""

    async def _run_async(self, *args: Any, **kwargs: Any) -> None:
        """Expose failures from every lifecycle hook despite run() logging them."""
        try:
            await super()._run_async(*args, **kwargs)
        except BaseException as exc:
            self.failure = exc
            raise

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Run the SimpleApplication matrix through real public managers."""
        del args, kwargs
        try:
            self.result["main"] = _runtime_probe()
            logger.info("SIMPLE_MAIN:%s", MATRIX_TOKEN)
            logging.getLogger("sqlalchemy").info("SIMPLE_DATABASE:%s", MATRIX_TOKEN)
            self.result["base_manager"] = await self._run_base_manager()
            self.result["async_manager"] = await self._run_async_manager()
            inherited = await _run_inherited_subprocess()
            piped = await _run_pipe_subprocess()
            self.result["subprocess"] = {
                "inherited_pid": inherited["pid"],
                "inherited_returncode": inherited["returncode"],
                "event_loop_ticks": inherited["event_loop_ticks"],
                "pipe_pid": piped["pid"],
                "pipe_returncode": piped["returncode"],
                "pipe_stdout": piped["stdout"],
                "pipe_stderr": piped["stderr"],
            }
        except BaseException as exc:
            self.failure = exc
            raise

    async def _run_base_manager(self) -> dict[str, Any]:
        """Verify persistent worker restart and inode-following behavior."""
        active_log = LOG_DIR / f"{APP_NAME}.log"
        archived_log = LOG_DIR / f"{APP_NAME}.log.matrix"
        manager = BaseManager(
            MatrixLoggingWorker,
            num_workers=1,
            max_worker_restarts=2,
            worker_restart_delay=0,
            monitor_interval=1,
        )
        await manager.start()
        try:
            first_process = manager.workers[0].process
            first_pid = first_process.pid
            if first_pid is None:
                raise RuntimeError("first BaseManager worker has no PID")
            first_tick = f"MATRIX_BASE_TICK:{MATRIX_TOKEN}:{first_pid}"
            await _wait_until(
                lambda: first_tick in _read_text(active_log),
                "first BaseManager heartbeat",
            )
            first_probe = _parse_base_probes(_read_text(active_log))[first_pid]

            active_log.replace(archived_log)
            active_log.touch()
            await _wait_until(
                lambda: first_tick in _read_text(active_log),
                "first worker following the replacement inode",
            )

            os.kill(first_pid, signal.SIGKILL)
            await _wait_until(
                lambda: (
                    0 in manager.workers
                    and manager.workers[0].process.pid not in (None, first_pid)
                    and manager.workers[0].process.is_alive()
                ),
                "automatic BaseManager replacement",
                timeout=12,
            )
            second_pid = manager.workers[0].process.pid
            if second_pid is None:
                raise RuntimeError("replacement BaseManager worker has no PID")
            second_tick = f"MATRIX_BASE_TICK:{MATRIX_TOKEN}:{second_pid}"
            await _wait_until(
                lambda: second_tick in _read_text(active_log),
                "replacement BaseManager heartbeat",
            )
            second_probe = _parse_base_probes(_read_text(active_log))[second_pid]
            return {
                "first_pid": first_pid,
                "second_pid": second_pid,
                "first_probe": first_probe,
                "second_probe": second_probe,
            }
        finally:
            await manager.shutdown()

    async def _run_async_manager(self) -> dict[str, Any]:
        """Exercise normal, timeout, abrupt-exit and recovery generations."""
        manager = AsyncProcessManager(workers=1)
        try:
            first = await manager.run_with_timeout(
                matrix_normal_target,
                args=(MATRIX_TOKEN, "first"),
                _timeout=5,
            )
            if first is None:
                raise RuntimeError("first temporary process returned no result")

            timed_out = False
            try:
                await manager.run_with_timeout(
                    matrix_timeout_target,
                    args=(MATRIX_TOKEN, 3.0),
                    _timeout=1,
                )
            except ProcessTimeoutError:
                timed_out = True

            killed = await manager.run_with_timeout(
                matrix_sigkill_target,
                args=(MATRIX_TOKEN,),
                _timeout=5,
            )
            final = await manager.run_with_timeout(
                matrix_normal_target,
                args=(MATRIX_TOKEN, "final"),
                _timeout=5,
            )
            if final is None:
                raise RuntimeError("final temporary process returned no result")
            return {
                "first": first,
                "timed_out": timed_out,
                "killed": killed,
                "final": final,
            }
        finally:
            await manager.shutdown()
            await _wait_until(
                lambda: not _pipe_reader_thread_names(),
                "AsyncProcessManager pipe reader shutdown",
            )


def main() -> None:
    """Run the fixture and publish cleanup state after logging has closed."""
    application = LoggingSimpleService(APP_NAME)
    application.run()
    if application.failure is not None:
        raise RuntimeError("SimpleApplication matrix failed") from application.failure
    required_sections = {"main", "base_manager", "async_manager", "subprocess"}
    if application.result.keys() < required_sections:
        raise RuntimeError(f"incomplete matrix result: {sorted(application.result)}")
    deadline = time.monotonic() + 3
    while _pipe_reader_thread_names() and time.monotonic() < deadline:
        time.sleep(0.02)
    application.result["after_run"] = {
        "rotation_threads": rotation_thread_names(),
        "pipe_reader_threads": _pipe_reader_thread_names(),
    }
    temporary_result = RESULT_FILE.with_suffix(f"{RESULT_FILE.suffix}.tmp")
    temporary_result.write_text(
        json.dumps(application.result, sort_keys=True),
        encoding="utf-8",
    )
    temporary_result.replace(RESULT_FILE)


if __name__ == "__main__":
    main()
