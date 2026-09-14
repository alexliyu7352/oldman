"""Real Sanic service for the fixed 1/2/4-worker logging performance gate."""

# ruff: noqa: E402 -- settings and the reference class must precede runtime imports.

from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import sys
import threading
import time
import traceback
from itertools import count
from logging.handlers import TimedRotatingFileHandler
from multiprocessing.util import Finalize
from pathlib import Path
from signal import Signals
from typing import Any, Literal, cast

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings

type HandlerVariant = Literal["current", "timed_reference", "no_logging"]

REFERENCE_ROLLOVER_AT = 2**63 - 1
FUTURE_ROTATION_WHEN = "S"
FUTURE_ROTATION_INTERVAL = 2**31 - 1
RESPONSE_BODY = b"oldman-sanic-logging-benchmark-response-v1:" + (b"x" * 86)
FILE_HANDLER_NAMES = ("file", "access_file", "database_file")
CONSOLE_HANDLER_NAMES = ("console", "error_console", "access_console")
BENCHMARK_HTTP_METHOD = "POST"


def _required_environment(name: str) -> str:
    """Return one required fixture value with a useful startup error."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"missing fixture environment variable: {name}")
    return value


def _handler_variant(value: str) -> HandlerVariant:
    """Reject variants outside the fixed three-way comparison."""
    if value not in {"current", "timed_reference", "no_logging"}:
        raise RuntimeError(f"unsupported logging benchmark variant: {value!r}")
    return cast(HandlerVariant, value)


LOG_DIR = Path(_required_environment("OLDMAN_WEB_BENCH_LOG_DIR"))
STATE_FILE = Path(_required_environment("OLDMAN_WEB_BENCH_STATE_FILE"))
APP_NAME = _required_environment("OLDMAN_WEB_BENCH_APP_NAME")
VARIANT = _handler_variant(_required_environment("OLDMAN_WEB_BENCH_VARIANT"))
WORKERS = int(_required_environment("OLDMAN_WEB_BENCH_WORKERS"))
PORT = int(_required_environment("OLDMAN_WEB_BENCH_PORT"))
NESTED_ASYNC_RECORDS = int(
    os.environ.get("OLDMAN_WEB_BENCH_NESTED_ASYNC_RECORDS", "100")
)
NESTED_ASYNC_RUNS = int(os.environ.get("OLDMAN_WEB_BENCH_NESTED_ASYNC_RUNS", "1"))
NESTED_SUBPROCESS_BYTES = int(
    os.environ.get("OLDMAN_WEB_BENCH_NESTED_SUBPROCESS_BYTES", "65536")
)
FAULT = os.environ.get("OLDMAN_WEB_BENCH_FAULT", "none")

if FAULT not in {"none", "skip_database"}:
    raise RuntimeError(f"unsupported logging benchmark fault: {FAULT!r}")

# The baseline keeps the same route and logger calls but disables record creation
# before Oldman or Sanic initializes logging.  This measures server work with the
# logging path switched off instead of comparing against a different application.
if VARIANT == "no_logging":
    logging.disable(logging.CRITICAL)

# Every Sanic process imports runtime consumers only after receiving the same
# settings.  This preserves normal production configuration on the benchmark's
# current side and keeps both variants on the same directory, levels, and routes.
SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {"dir": LOG_DIR, "color": "never"},
        "process": {"pid_dir": LOG_DIR},
        "web": {
            "listen_host": "127.0.0.1",
            "listen_port": PORT,
            "workers": WORKERS,
            "access_log": VARIANT != "no_logging",
            "auto_reload": False,
            "media": {"url": ""},
            "static": {"root": "", "url": ""},
        },
        "i18n": {"use_i18n": False},
    }
)
conf.__dict__["settings"] = SETTINGS

from oldman.apps import AppRegistry
from oldman.runtime import ServiceBootstrapContext

BOOTSTRAP_CONTEXT = ServiceBootstrapContext(
    service_module="logging_web_performance_service",
    config_file=Path(__file__).resolve(),
    settings=SETTINGS,
    apps=AppRegistry(),
)

# Both variants receive the same test-only time policy far beyond a benchmark
# window.  Current keeps its Atomic handler and coordinator; reference changes
# exactly the three file handler classes.  Formatters, payloads, console handlers,
# logger routing, levels and every other handler field remain unchanged.
from oldman.logging.config import LOGGING_CONFIG_DEFAULTS

for _handler_name in FILE_HANDLER_NAMES:
    _handler_config = LOGGING_CONFIG_DEFAULTS["handlers"][_handler_name]
    _handler_config["when"] = FUTURE_ROTATION_WHEN
    _handler_config["interval"] = FUTURE_ROTATION_INTERVAL
    if VARIANT == "timed_reference":
        _handler_config["class"] = (
            "logging.handlers.TimedRotatingFileHandler"
        )

from sanic.request import Request
from sanic.response import json as json_response
from sanic.response import raw
from sanic.worker.manager import WorkerManager

import oldman.runtime.web as web_runtime
from oldman.logging import get_active_runtime, logger
from oldman.logging.handlers import AtomicAppendFileHandler
from oldman.processes import (
    AsyncProcessManager,
    ProcessTimeoutError,
    SubprocessTimeoutError,
    create_subprocess_exec,
)
from oldman.processes.executor import ParentLogPipeReader
from oldman.runtime.web import WebApplication
from oldman.web.routing import WebApp
from tests.fixtures.logging_direct_service import (
    performance_async_target,
    performance_sigkill_target,
    performance_timeout_target,
)


def _runtime_named_handlers() -> dict[str, logging.Handler]:
    """Return all six uniquely named handlers owned by this process."""
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("benchmark logging runtime is missing")

    handlers: dict[str, logging.Handler] = {}
    for handler in runtime._handlers:  # pyright: ignore[reportPrivateUsage]
        if handler.name in {*FILE_HANDLER_NAMES, *CONSOLE_HANDLER_NAMES}:
            handlers[str(handler.name)] = handler
    expected = {*FILE_HANDLER_NAMES, *CONSOLE_HANDLER_NAMES}
    if set(handlers) != expected:
        raise RuntimeError(
            f"benchmark handler names mismatch: {sorted(handlers)}"
        )
    return handlers


def _validate_and_pin_handlers() -> dict[str, dict[str, dict[str, Any]]]:
    """Verify equal wiring and pin reference rollover beyond the run window."""
    named_handlers = _runtime_named_handlers()
    file_result: dict[str, dict[str, Any]] = {}
    for name in FILE_HANDLER_NAMES:
        handler = named_handlers[name]
        if VARIANT in {"current", "no_logging"}:
            if not isinstance(handler, AtomicAppendFileHandler):
                raise RuntimeError(
                    f"current {name} handler is {type(handler).__name__}"
                )
            policy = handler.rotation_policy
            if policy is None or policy.kind != "time":
                raise RuntimeError(f"current {name} has no timed rotation policy")
            rotation_when = policy.when
            rotation_interval = policy.interval
            backup_count = policy.backup_count
            rollover_at: int | None = None
        else:
            if type(handler) is not TimedRotatingFileHandler:
                raise RuntimeError(
                    f"reference {name} handler is {type(handler).__name__}"
                )
            handler.rolloverAt = REFERENCE_ROLLOVER_AT
            rotation_when = handler.when
            rotation_interval = handler.interval
            backup_count = handler.backupCount
            rollover_at = handler.rolloverAt

        formatter = handler.formatter
        file_result[name] = {
            "class": f"{type(handler).__module__}.{type(handler).__qualname__}",
            "formatter": (
                None
                if formatter is None
                else f"{type(formatter).__module__}.{type(formatter).__qualname__}"
            ),
            "level": handler.level,
            "rotation": {
                "when": rotation_when,
                "interval": rotation_interval,
                "backup_count": backup_count,
            },
            "rollover_at": rollover_at,
        }
    console_result: dict[str, dict[str, Any]] = {}
    for name in CONSOLE_HANDLER_NAMES:
        handler = named_handlers[name]
        if type(handler) is not logging.StreamHandler:
            raise RuntimeError(f"console {name} handler is {type(handler).__name__}")
        formatter = handler.formatter
        console_result[name] = {
            "class": f"{type(handler).__module__}.{type(handler).__qualname__}",
            "formatter": (
                None
                if formatter is None
                else f"{type(formatter).__module__}.{type(formatter).__qualname__}"
            ),
            "level": handler.level,
        }
    return {"files": file_result, "console": console_result}


_PRIMARY_HANDLER_STATE: dict[str, dict[str, dict[str, Any]]] = {}
_PRIMARY_STATE: dict[str, Any] = {}
_PRIMARY_STATE_VERSION = 0
_STATE_WRITE_SEQUENCE = count()


def _publish_primary_state() -> None:
    """Atomically converge the state file after a nested signal write."""
    while True:
        version = _PRIMARY_STATE_VERSION
        for count_field, events_field in (
            ("shutdown_signal_count", "shutdown_signals"),
            ("manager_kill_count", "manager_kills"),
        ):
            events = _PRIMARY_STATE.get(events_field)
            if isinstance(events, list):
                _PRIMARY_STATE[count_field] = len(events)
        payload = json.dumps(_PRIMARY_STATE, sort_keys=True)
        temporary = STATE_FILE.with_name(
            f"{STATE_FILE.name}.tmp-{os.getpid()}-"
            f"{next(_STATE_WRITE_SEQUENCE)}"
        )
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(STATE_FILE)
        finally:
            temporary.unlink(missing_ok=True)
        if version == _PRIMARY_STATE_VERSION:
            return


def _merge_primary_state(updates: dict[str, Any]) -> None:
    """Merge primary-only evidence without replacing identity or prior ACK."""
    global _PRIMARY_STATE_VERSION

    _PRIMARY_STATE.update(updates)
    _PRIMARY_STATE_VERSION += 1
    _publish_primary_state()


def _safe_merge_primary_state(updates: dict[str, Any]) -> None:
    """Keep diagnostic I/O from changing Sanic's return or exception path."""
    try:
        _merge_primary_state(updates)
    except BaseException:
        pass


def _exception_summary(exc: BaseException, *, with_traceback: bool) -> dict[str, Any]:
    """Return JSON-safe exception evidence without changing the exception."""
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": (
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if with_traceback
            else None
        ),
    }


def _begin_shutdown_signal(
    manager: WorkerManager,
    signal_number: int,
) -> dict[str, Any] | None:
    """Record one signal before delegating to Sanic's current implementation."""
    try:
        try:
            signal_name = Signals(signal_number).name
        except ValueError:
            signal_name = str(signal_number)
        signals = cast(
            list[dict[str, Any]],
            _PRIMARY_STATE["shutdown_signals"],
        )
        event = {
            "name": signal_name,
            "already_shutting_down": bool(manager._shutting_down),
            "original_returned": None,
            "exception": None,
        }
        # Python invokes signal handlers on the primary main thread.  Keep the
        # canonical object and its event identity so a nested handler can append
        # without either invocation later writing a stale list or index.
        signals.append(event)
        _safe_merge_primary_state({})
        return event
    except BaseException:
        return None


def _finish_event(
    event: dict[str, Any] | None,
    *,
    original_returned: bool,
    exception: BaseException | None,
) -> None:
    """Complete one wrapper event while preserving nested events."""
    if event is None:
        return
    try:
        exception_state = (
            None
            if exception is None
            else _exception_summary(exception, with_traceback=False)
        )
        event.update(
            {
                "original_returned": original_returned,
                "exception": exception_state,
            }
        )
        _safe_merge_primary_state({})
    except BaseException:
        pass


def _worker_state_summary(manager: WorkerManager) -> list[dict[str, Any]]:
    """Snapshot Sanic worker objects immediately before manager kill."""
    workers: list[dict[str, Any]] = []
    for process in manager.processes:
        try:
            workers.append(
                {
                    "name": process.name,
                    "pid": process.pid,
                    "state": process.state.name,
                    "exit_code": process.exitcode,
                    "alive": process.is_alive(),
                }
            )
        except BaseException as exc:
            workers.append(
                {
                    "name": getattr(process, "name", None),
                    "summary_error": _exception_summary(
                        exc,
                        with_traceback=False,
                    ),
                }
            )
    return workers


def _begin_manager_kill(manager: WorkerManager) -> dict[str, Any] | None:
    """Record one manager kill and its worker state before delegation."""
    try:
        kills = cast(list[dict[str, Any]], _PRIMARY_STATE["manager_kills"])
        event = {
            "workers": _worker_state_summary(manager),
            "original_returned": None,
            "exception": None,
        }
        kills.append(event)
        _safe_merge_primary_state({})
        return event
    except BaseException:
        return None


_ORIGINAL_MANAGER_WAIT_FOR_ACK = WorkerManager.wait_for_ack
_ORIGINAL_MANAGER_SHUTDOWN_SIGNAL = WorkerManager.shutdown_signal
_ORIGINAL_MANAGER_KILL = WorkerManager.kill


def _wait_for_ack_and_publish(self: WorkerManager) -> Any:
    """Publish only after Sanic's original worker-ack wait returns normally."""
    result = _ORIGINAL_MANAGER_WAIT_FOR_ACK(self)
    _safe_merge_primary_state({"manager_ack_complete": True})
    return result


def _shutdown_signal_and_publish(
    self: WorkerManager,
    signal: int,
    frame: Any,
) -> Any:
    """Record signal entry/exit without changing Sanic's behavior."""
    event = _begin_shutdown_signal(self, signal)
    try:
        result = _ORIGINAL_MANAGER_SHUTDOWN_SIGNAL(self, signal, frame)
    except BaseException as exc:
        _finish_event(
            event,
            original_returned=False,
            exception=exc,
        )
        raise
    _finish_event(
        event,
        original_returned=True,
        exception=None,
    )
    return result


def _kill_and_publish(self: WorkerManager) -> Any:
    """Record manager kill entry/exit without changing Sanic's behavior."""
    event = _begin_manager_kill(self)
    try:
        result = _ORIGINAL_MANAGER_KILL(self)
    except BaseException as exc:
        _finish_event(
            event,
            original_returned=False,
            exception=exc,
        )
        raise
    _finish_event(
        event,
        original_returned=True,
        exception=None,
    )
    return result


WorkerManager.wait_for_ack = _wait_for_ack_and_publish
WorkerManager.shutdown_signal = _shutdown_signal_and_publish
WorkerManager.kill = _kill_and_publish


async def _ready_route(request: Request) -> Any:
    """Return fixed readiness metadata without emitting benchmark tokens."""
    del request
    return json_response({"ready": True, "pid": os.getpid()})


async def _benchmark_route(request: Request, token: str) -> Any:
    """Emit one main and database record before Sanic emits one access record."""
    del request
    logger.info(
        "WEB_BENCH_MAIN token=%s payload=Oldman-中文-café-fixed-v1",
        token,
    )
    # The deliberate smoke-only fault proves exact counts fail closed.  It is
    # accepted for only one first measurement token by the runner's CLI guard.
    if not (FAULT == "skip_database" and token.endswith("_M_00000000")):
        logging.getLogger("sqlalchemy").info(
            "WEB_BENCH_DATABASE token=%s payload=Oldman-中文-café-fixed-v1",
            token,
        )
    return raw(RESPONSE_BODY, content_type="application/octet-stream")


def _usage_snapshot(who: int) -> dict[str, float]:
    """Capture cumulative worker or reaped-child CPU around nested processes."""
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
    """Return normalized CPU cost for one nested-process workload."""
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


def _process_group_pids(process_group: int) -> list[int]:
    """Return live non-zombie processes in a subprocess-owned Linux group."""
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


async def _nested_subprocess_output(byte_count: int) -> dict[str, Any]:
    """Measure inherited and PIPE output inside a real Sanic server worker."""
    source = (
        "import os,sys; n=int(sys.argv[1]); data=b'x'*n; "
        "os.write(1,data); os.write(2,data)"
    )
    children_before = _usage_snapshot(resource.RUSAGE_CHILDREN)
    inherited_started = time.perf_counter()
    inherited = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
        str(byte_count),
    )
    inherited_returncode = await inherited.wait()
    inherited_elapsed = time.perf_counter() - inherited_started

    ticks = 0
    ticking = True

    async def ticker() -> None:
        """Count loop turns while asyncio drains both subprocess pipes."""
        nonlocal ticks
        while ticking:
            ticks += 1
            await asyncio.sleep(0)

    ticker_task = asyncio.create_task(ticker())
    pipe_started = time.perf_counter()
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
    pipe_elapsed = time.perf_counter() - pipe_started
    ticking = False
    await ticker_task
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
        "child_cpu": _usage_delta(
            children_before,
            _usage_snapshot(resource.RUSAGE_CHILDREN),
            elapsed_seconds=inherited_elapsed + pipe_elapsed,
            units=byte_count * 4,
        ),
    }


async def _nested_subprocess_cleanup() -> dict[str, Any]:
    """Prove timeout and cancellation remove a subprocess and its descendant."""
    source = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "time.sleep(60)"
    )
    timeout_process = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
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
        source,
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


async def _wait_for_pipe_readers() -> list[str]:
    """Wait for AsyncProcessManager's raw-output reader threads to reach EOF."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        names = [
            thread.name
            for thread in threading.enumerate()
            if isinstance(thread, ParentLogPipeReader)
        ]
        if not names:
            return []
        await asyncio.sleep(0.02)
    return [
        thread.name
        for thread in threading.enumerate()
        if isinstance(thread, ParentLogPipeReader)
    ]


async def _nested_process_route(request: Request, token: str) -> Any:
    """Exercise temporary processes and subprocesses in the real server worker."""
    del request
    manager = AsyncProcessManager(workers=1)
    repeated: list[dict[str, Any]] = []
    try:
        for index in range(NESTED_ASYNC_RUNS):
            result = await manager.run_with_timeout(
                performance_async_target,
                args=(token, f"web_async_{index}", NESTED_ASYNC_RECORDS),
                _timeout=30,
            )
            if not isinstance(result, dict):
                raise RuntimeError(f"web async child {index} returned {result!r}")
            repeated.append(result)
        timed_out = False
        try:
            await manager.run_with_timeout(
                performance_timeout_target,
                args=(token, 5.0),
                _timeout=1,
            )
        except ProcessTimeoutError:
            timed_out = True
        killed = await manager.run_with_timeout(
            performance_sigkill_target,
            args=(token,),
            _timeout=5,
        )
        recovery = await manager.run_with_timeout(
            performance_async_target,
            args=(token, "web_async_recovery", NESTED_ASYNC_RECORDS),
            _timeout=30,
        )
        if not isinstance(recovery, dict):
            raise RuntimeError(f"web async recovery returned {recovery!r}")
    finally:
        await manager.shutdown()
    pipe_readers = await _wait_for_pipe_readers()
    output = await _nested_subprocess_output(NESTED_SUBPROCESS_BYTES)
    cleanup = await _nested_subprocess_cleanup()
    return json_response(
        {
            "worker_pid": os.getpid(),
            "async_manager": {
                "runs": repeated,
                "timed_out": timed_out,
                "sigkill_result": killed,
                "recovery": recovery,
                "pipe_reader_threads": pipe_readers,
            },
            "subprocess": {"output": output, "cleanup": cleanup},
        }
    )


class LoggingWebPerformanceService(WebApplication):
    """Run Oldman's real Sanic topology with a benchmark-only route set."""

    def __init__(
        self,
        app_name: str | None = None,
        *,
        config: ServiceBootstrapContext | None = None,
    ) -> None:
        """Initialize normal runtime wiring and validate process-local handlers."""
        super().__init__(app_name, config=config)
        self.benchmark_handler_state = _validate_and_pin_handlers()

    def init(self) -> None:
        """Initialize the production adapter and register identical routes."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime did not create an application")
        app.add_route(_ready_route, "/ready", methods={"GET"}, name="ready")
        app.add_route(
            _benchmark_route,
            "/bench/<token:str>",
            methods={BENCHMARK_HTTP_METHOD},
            name="benchmark",
        )
        app.add_route(
            _nested_process_route,
            "/nested/processes/<token:str>",
            methods={BENCHMARK_HTTP_METHOD},
            name="nested_processes",
        )

    def prepare_server(self, app: WebApp) -> None:
        """Prepare the requested real primary-plus-worker Sanic topology."""
        settings = conf.settings.web
        app.prepare(
            host=settings.listen_host,
            port=settings.listen_port,
            workers=settings.workers,
            access_log=VARIANT != "no_logging",
            auto_reload=False,
            motd=False,
        )


def _create_fixture_sanic_app(
    service_module: str,
    config_file: str | Path,
    app_name: str,
    child_context: Any,
) -> Any:
    """Rebuild this standalone fixture without project service discovery."""
    del service_module, config_file
    worker_runtime = child_context.install()
    try:
        app = LoggingWebPerformanceService(
            app_name,
            config=BOOTSTRAP_CONTEXT,
        ).create_app()
        Finalize(None, worker_runtime.close, exitpriority=100)
        return app
    except BaseException:
        worker_runtime.close()
        raise


def main() -> None:
    """Publish primary wiring, then serve until the runner sends SIGTERM."""
    global _PRIMARY_HANDLER_STATE, _PRIMARY_STATE, _PRIMARY_STATE_VERSION

    web_runtime._create_sanic_app_factory = _create_fixture_sanic_app
    application = LoggingWebPerformanceService(
        APP_NAME,
        config=BOOTSTRAP_CONTEXT,
    )
    _PRIMARY_HANDLER_STATE = application.benchmark_handler_state
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("benchmark logging runtime is missing while publishing")
    _PRIMARY_STATE = {
        "pid": os.getpid(),
        "app_name": APP_NAME,
        "variant": VARIANT,
        "workers": WORKERS,
        "handlers": _PRIMARY_HANDLER_STATE,
        "response_bytes": len(RESPONSE_BODY),
        "benchmark_method": BENCHMARK_HTTP_METHOD,
        "logging_disabled": VARIANT == "no_logging",
        "access_log": VARIANT != "no_logging",
        "owns_rotation_coordinator": runtime.owns_rotation,
        "manager_ack_complete": False,
        "shutdown_signal_count": 0,
        "shutdown_signals": [],
        "manager_kill_count": 0,
        "manager_kills": [],
        "sanic_serve_returned": False,
        "main_returned": False,
        "unhandled_exception": None,
    }
    _PRIMARY_STATE_VERSION += 1
    _publish_primary_state()

    serve_returned = False
    try:
        application.run()
    except BaseException as exc:
        _safe_merge_primary_state(
            {"unhandled_exception": _exception_summary(exc, with_traceback=True)}
        )
        raise
    else:
        serve_returned = True
        _safe_merge_primary_state({"sanic_serve_returned": True})
    finally:
        if serve_returned:
            _safe_merge_primary_state({"main_returned": True})


if __name__ == "__main__":
    main()
