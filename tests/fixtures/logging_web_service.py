"""Real Sanic service used by direct-writer logging integration tests."""

# ruff: noqa: E402 -- project settings must exist before importing runtime consumers.

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from multiprocessing.util import Finalize
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
STATE_FILE = Path(_required_environment("OLDMAN_TEST_STATE_FILE"))
APP_NAME = _required_environment("OLDMAN_TEST_APP_NAME")
MAIN_TOKEN = _required_environment("OLDMAN_TEST_MAIN_TOKEN")
WORKER_TOKEN = _required_environment("OLDMAN_TEST_WORKER_TOKEN")
REQUEST_TOKEN = _required_environment("OLDMAN_TEST_REQUEST_TOKEN")
DATABASE_TOKEN = _required_environment("OLDMAN_TEST_DATABASE_TOKEN")
RELOADER_TOKEN = _required_environment("OLDMAN_TEST_RELOADER_TOKEN")
WORKERS = int(_required_environment("OLDMAN_TEST_WORKERS"))
PORT = int(_required_environment("OLDMAN_TEST_PORT"))
AUTO_RELOAD = os.environ.get("OLDMAN_TEST_AUTO_RELOAD") == "1"

# Every spawned Sanic process imports this module and must see settings first.
SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {
            "dir": LOG_DIR,
            "color": "never",
        },
        "process": {"pid_dir": LOG_DIR},
        "web": {
            "listen_host": "127.0.0.1",
            "listen_port": PORT,
            "workers": WORKERS,
            "access_log": True,
            "auto_reload": AUTO_RELOAD,
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
    service_module="logging_web_service",
    config_file=Path(__file__).resolve(),
    settings=SETTINGS,
    apps=AppRegistry(),
)

from sanic.request import Request
from sanic.response import json as json_response

import oldman.runtime.web as web_runtime
from oldman.logging import get_active_runtime, logger
from oldman.processes import AsyncProcessManager, ProcessTimeoutError, create_subprocess_exec
from oldman.processes.executor import ParentLogPipeReader
from oldman.runtime.web import WebApplication
from oldman.web.routing import WebApp
from tests.fixtures.logging_direct_service import (
    matrix_normal_target,
    matrix_sigkill_target,
    matrix_timeout_target,
)


def _handler_names() -> list[str]:
    """Return concrete handlers attached to Oldman's default logger."""
    return sorted(type(handler).__name__ for handler in logging.getLogger("default").handlers)


def _rotation_thread_names() -> list[str]:
    """Return coordinator threads owned by this process."""
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if thread.name == "oldman-log-rotation"
    )


def _pipe_reader_thread_names() -> list[str]:
    """Return temporary-process console forwarding threads in this process."""
    return sorted(
        thread.name
        for thread in threading.enumerate()
        if isinstance(thread, ParentLogPipeReader)
    )


def _runtime_probe() -> dict[str, Any]:
    """Describe the process-local runtime without exposing private objects."""
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("process logging runtime is missing")
    return {
        "pid": os.getpid(),
        "handlers": _handler_names(),
        "owns_rotation": runtime.owns_rotation,
        "rotation_threads": _rotation_thread_names(),
    }


async def _pid_route(request: Request) -> Any:
    """Report the serving worker and emit a request record through its runtime."""
    del request
    probe = _runtime_probe()
    logger.info("%s %s", REQUEST_TOKEN, json.dumps(probe, sort_keys=True))
    logging.getLogger("sqlalchemy").info("%s pid=%d", DATABASE_TOKEN, os.getpid())
    return json_response(probe)


async def _matrix_pid_route(request: Request, access_token: str) -> Any:
    """Emit uniquely correlated main, database and access records on one worker."""
    target = int(request.headers.get("X-Matrix-Target-Pid", os.getpid()))
    if target != os.getpid():
        return json_response({"executed": False, "worker": _runtime_probe()})

    request_token = request.headers.get("X-Matrix-Request-Token", "")
    database_token = request.headers.get("X-Matrix-Database-Token", "")
    if not request_token or not database_token:
        raise ValueError("missing matrix request or database token")

    probe = _runtime_probe()
    logger.info("%s %s", request_token, json.dumps(probe, sort_keys=True))
    logging.getLogger("sqlalchemy").info("%s pid=%d", database_token, os.getpid())
    return json_response(
        {
            "executed": True,
            "worker": probe,
            "access_token": access_token,
            "request_token": request_token,
            "database_token": database_token,
        }
    )


def _matrix_request(request: Request) -> tuple[str, bool]:
    """Return the matrix token and whether this is the selected worker."""
    token = request.headers.get("X-Matrix-Token", "")
    if not token:
        raise ValueError("missing X-Matrix-Token")
    target = int(request.headers.get("X-Matrix-Target-Pid", os.getpid()))
    return token, target == os.getpid()


async def _wait_for_pipe_readers() -> list[str]:
    """Wait for all temporary-process console forwarding threads to exit."""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        names = _pipe_reader_thread_names()
        if not names:
            return []
        await asyncio.sleep(0.02)
    return names


async def _matrix_async_route(request: Request) -> Any:
    """Run all temporary-process outcomes inside one selected Sanic worker."""
    token, selected = _matrix_request(request)
    if not selected:
        return json_response({"executed": False, "worker": _runtime_probe()})

    manager = AsyncProcessManager(workers=1)
    try:
        first = await manager.run_with_timeout(
            matrix_normal_target,
            args=(token, "first"),
            _timeout=5,
        )
        timed_out = False
        try:
            await manager.run_with_timeout(
                matrix_timeout_target,
                args=(token, 3.0),
                _timeout=1,
            )
        except ProcessTimeoutError:
            timed_out = True
        killed = await manager.run_with_timeout(
            matrix_sigkill_target,
            args=(token,),
            _timeout=5,
        )
        final = await manager.run_with_timeout(
            matrix_normal_target,
            args=(token, "final"),
            _timeout=5,
        )
    finally:
        await manager.shutdown()

    return json_response(
        {
            "executed": True,
            "token": token,
            "worker": _runtime_probe(),
            "first": first,
            "timed_out": timed_out,
            "killed": killed,
            "final": final,
            "pipe_reader_threads": await _wait_for_pipe_readers(),
        }
    )


async def _matrix_inherited_subprocess_route(request: Request) -> Any:
    """Run an inherited-stdio asyncio subprocess in one selected worker."""
    token, selected = _matrix_request(request)
    if not selected:
        return json_response({"executed": False, "worker": _runtime_probe()})
    source = (
        "import sys,time; token=sys.argv[1]; time.sleep(0.60); "
        "print(f'WEB_INHERITED_STDOUT:{token}',flush=True); "
        "print(f'WEB_INHERITED_STDERR:{token}',file=sys.stderr,flush=True)"
    )
    process = await create_subprocess_exec(sys.executable, "-c", source, token)
    logger.info("WEB_INHERITED_READY:%s", token)
    returncode = await process.wait()
    if returncode != 0:
        raise RuntimeError(f"inherited subprocess exited with {returncode}")
    return json_response(
        {
            "executed": True,
            "worker": _runtime_probe(),
            "pid": process.pid,
            "stdout_token": f"WEB_INHERITED_STDOUT:{token}",
            "stderr_token": f"WEB_INHERITED_STDERR:{token}",
        }
    )


async def _matrix_pipe_subprocess_route(request: Request) -> Any:
    """Run an explicitly captured asyncio subprocess in one selected worker."""
    token, selected = _matrix_request(request)
    if not selected:
        return json_response({"executed": False, "worker": _runtime_probe()})
    source = (
        "import sys; token=sys.argv[1]; print(f'WEB_PIPE_STDOUT:{token}'); "
        "print(f'WEB_PIPE_STDERR:{token}',file=sys.stderr)"
    )
    process = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
        token,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if stdout is None or stderr is None:
        raise RuntimeError("PIPE subprocess did not return both output streams")
    if process.returncode != 0:
        raise RuntimeError(f"PIPE subprocess exited with {process.returncode}")
    return json_response(
        {
            "executed": True,
            "worker": _runtime_probe(),
            "pid": process.pid,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }
    )


async def _matrix_write_route(request: Request) -> Any:
    """Write one token from a selected worker for inode replacement checks."""
    token, selected = _matrix_request(request)
    if not selected:
        return json_response({"executed": False, "worker": _runtime_probe()})
    logger.info("WEB_MATRIX_WRITE:%s", token)
    return json_response({"executed": True, "worker": _runtime_probe()})


class LoggingWebService(WebApplication):
    """Minimal concrete Web application with no project app discovery."""

    def __init__(
        self,
        app_name: str | None = None,
        *,
        config: ServiceBootstrapContext | None = None,
    ) -> None:
        """Initialize the app and report a separately managed Sanic reloader."""
        super().__init__(app_name, config=config)
        if os.environ.get("SANIC_WORKER_NAME", "").startswith("Sanic-Reloader-"):
            logger.info("%s %s", RELOADER_TOKEN, json.dumps(_runtime_probe(), sort_keys=True))

    def init(self) -> None:
        """Initialize the runtime and register the diagnostic route."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime did not create an application")
        app.add_route(_pid_route, "/pid", methods={"GET"}, name="pid")
        app.add_route(
            _matrix_pid_route,
            "/matrix/pid/<access_token:str>",
            methods={"GET"},
            name="matrix_pid",
        )
        app.add_route(
            _matrix_async_route,
            "/matrix/async",
            methods={"GET"},
            name="matrix_async",
        )
        app.add_route(
            _matrix_inherited_subprocess_route,
            "/matrix/subprocess/inherited",
            methods={"GET"},
            name="matrix_inherited",
        )
        app.add_route(
            _matrix_pipe_subprocess_route,
            "/matrix/subprocess/pipe",
            methods={"GET"},
            name="matrix_pipe",
        )
        app.add_route(
            _matrix_write_route,
            "/matrix/write",
            methods={"GET"},
            name="matrix_write",
        )

    async def before_server_start(self, app: Any) -> None:
        """Log the worker PID and process-local writer topology."""
        await super().before_server_start(app)
        logger.info("%s %s", WORKER_TOKEN, json.dumps(_runtime_probe(), sort_keys=True))

    def prepare_server(self, app: WebApp) -> None:
        """Prepare Sanic's normal primary-plus-server-worker topology."""
        settings = conf.settings.web
        app.prepare(
            host=settings.listen_host,
            port=settings.listen_port,
            workers=settings.workers,
            access_log=settings.access_log,
            auto_reload=settings.auto_reload,
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
        app = LoggingWebService(
            app_name,
            config=BOOTSTRAP_CONTEXT,
        ).create_app()
        Finalize(None, worker_runtime.close, exitpriority=100)
        return app
    except BaseException:
        worker_runtime.close()
        raise


def main() -> None:
    """Start the real service and publish primary state before serving."""
    web_runtime._create_sanic_app_factory = _create_fixture_sanic_app
    application = LoggingWebService(APP_NAME, config=BOOTSTRAP_CONTEXT)
    probe = _runtime_probe()
    logger.info("%s %s", MAIN_TOKEN, json.dumps(probe, sort_keys=True))
    STATE_FILE.write_text(json.dumps(probe), encoding="utf-8")
    application.run()
    deadline = time.monotonic() + 3
    while (
        _rotation_thread_names() or _pipe_reader_thread_names()
    ) and time.monotonic() < deadline:
        time.sleep(0.02)
    probe["after_run"] = {
        "rotation_threads": _rotation_thread_names(),
        "pipe_reader_threads": _pipe_reader_thread_names(),
    }
    STATE_FILE.write_text(json.dumps(probe), encoding="utf-8")


if __name__ == "__main__":
    main()
