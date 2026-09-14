"""Single-worker WebApplication fixture for managed subprocess parent death."""

# ruff: noqa: E402 -- settings must exist before runtime consumers are imported.

from __future__ import annotations

import asyncio
import os
import sys
import time
from multiprocessing.util import Finalize
from pathlib import Path
from typing import Any

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings


def _required_environment(name: str) -> str:
    """Return one required fixture setting."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"missing fixture environment variable: {name}")
    return value


LOG_DIR = Path(_required_environment("OLDMAN_SUBPROCESS_LOG_DIR"))
STATE_DIR = Path(_required_environment("OLDMAN_SUBPROCESS_STATE_DIR"))
APP_NAME = _required_environment("OLDMAN_SUBPROCESS_APP_NAME")
PORT = int(_required_environment("OLDMAN_SUBPROCESS_PORT"))

SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": STATE_DIR},
        "logging": {"dir": LOG_DIR, "color": "never"},
        "process": {"pid_dir": STATE_DIR},
        "web": {
            "listen_host": "127.0.0.1",
            "listen_port": PORT,
            "workers": 1,
            "access_log": False,
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
    service_module="managed_subprocess_web_service",
    config_file=Path(__file__).resolve(),
    settings=SETTINGS,
    apps=AppRegistry(),
)

from sanic.request import Request
from sanic.response import json as json_response

import oldman.runtime.web as web_runtime
from oldman.processes import ManagedSubprocess, create_subprocess_exec
from oldman.runtime.web import WebApplication
from oldman.web.routing import WebApp

_ACTIVE_PROCESSES: list[ManagedSubprocess] = []


async def _wait_for_text(path: Path, timeout: float = 5.0) -> str:
    """Wait without blocking the Sanic worker event loop."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            await asyncio.sleep(0.02)
            continue
        if value:
            return value
        await asyncio.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {path}")


async def _start_process(request: Request) -> Any:
    """Start one command with a descendant and return its complete ownership state."""
    del request
    descendant_file = STATE_DIR / f"descendant-{os.getpid()}.txt"
    descendant_file.unlink(missing_ok=True)
    source = (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
        "time.sleep(60)"
    )
    process = await create_subprocess_exec(
        sys.executable,
        "-c",
        source,
        str(descendant_file),
    )
    _ACTIVE_PROCESSES.append(process)
    descendant_pid = int(await _wait_for_text(descendant_file))
    return json_response(
        {
            "worker_pid": os.getpid(),
            "pid": process.pid,
            "supervisor_pid": process.supervisor_pid,
            "process_group": process.process_group,
            "descendant_pid": descendant_pid,
        }
    )


class ManagedSubprocessWebService(WebApplication):
    """Run the ordinary Oldman/Sanic topology around one managed command."""

    def init(self) -> None:
        """Initialize the runtime and register the subprocess route."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime did not create an application")
        app.add_route(_start_process, "/start", methods={"GET"}, name="start")

    def prepare_server(self, app: WebApp) -> None:
        """Prepare one real Sanic server worker."""
        app.prepare(
            host="127.0.0.1",
            port=PORT,
            workers=1,
            access_log=False,
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
        app = ManagedSubprocessWebService(
            app_name,
            config=BOOTSTRAP_CONTEXT,
        ).create_app()
        Finalize(None, worker_runtime.close, exitpriority=100)
        return app
    except BaseException:
        worker_runtime.close()
        raise


def main() -> None:
    """Serve until the test stops the primary process group."""
    web_runtime._create_sanic_app_factory = _create_fixture_sanic_app
    ManagedSubprocessWebService(APP_NAME, config=BOOTSTRAP_CONTEXT).run()


if __name__ == "__main__":
    main()
