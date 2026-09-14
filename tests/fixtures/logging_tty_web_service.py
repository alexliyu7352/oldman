"""Minimal single-worker WebApplication fixture for the real TTY logging gate."""

# ruff: noqa: E402 -- settings must exist before importing runtime consumers.

from __future__ import annotations

import json
import logging
import os
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
ERROR_TOKEN = _required_environment("OLDMAN_TEST_ERROR_TOKEN")
DATABASE_TOKEN = _required_environment("OLDMAN_TEST_DATABASE_TOKEN")
PORT = int(_required_environment("OLDMAN_TEST_PORT"))

SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {"dir": LOG_DIR, "color": "auto"},
        "process": {"pid_dir": LOG_DIR},
        "web": {
            "listen_host": "127.0.0.1",
            "listen_port": PORT,
            "workers": 1,
            "access_log": True,
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
    service_module="logging_tty_web_service",
    config_file=Path(__file__).resolve(),
    settings=SETTINGS,
    apps=AppRegistry(),
)

from sanic.request import Request
from sanic.response import json as json_response
from sanic.worker.manager import WorkerManager

import oldman.runtime.web as web_runtime
from oldman.logging import logger
from oldman.runtime.web import WebApplication
from oldman.web.routing import WebApp


def _write_state(
    *,
    main_process_ready: bool,
    manager_ack_complete: bool,
    finished: bool,
) -> None:
    """Publish one complete primary state snapshot with an atomic replace."""
    temporary = STATE_FILE.with_suffix(f"{STATE_FILE.suffix}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "app_name": APP_NAME,
                "main_process_ready": main_process_ready,
                "manager_ack_complete": manager_ack_complete,
                "finished": finished,
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(STATE_FILE)


_ORIGINAL_MANAGER_WAIT_FOR_ACK = WorkerManager.wait_for_ack


def _wait_for_ack_and_publish(self: WorkerManager) -> Any:
    """Publish only after Sanic's original worker-ack wait returns normally."""
    result = _ORIGINAL_MANAGER_WAIT_FOR_ACK(self)
    _write_state(
        main_process_ready=True,
        manager_ack_complete=True,
        finished=False,
    )
    return result


WorkerManager.wait_for_ack = _wait_for_ack_and_publish


async def _tty_route(request: Request, access_token: str) -> Any:
    """Emit request-time tokens and let Sanic add the real access record."""
    del request, access_token
    logger.info(MAIN_TOKEN)
    logging.getLogger("sanic.error").error(ERROR_TOKEN)
    logging.getLogger("sqlalchemy").info(DATABASE_TOKEN)
    return json_response({"pid": os.getpid()})


class LoggingTtyWebService(WebApplication):
    """Run Oldman's ordinary single-worker Sanic wiring without project apps."""

    async def main_process_ready(self, app: Any) -> None:
        """Publish Sanic's primary-ready happens-before boundary for shutdown."""
        await super().main_process_ready(app)
        _write_state(
            main_process_ready=True,
            manager_ack_complete=False,
            finished=False,
        )

    def init(self) -> None:
        """Initialize the production adapter and register the token route."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime did not create an application")
        app.add_route(
            _tty_route,
            "/tty/<access_token:str>",
            methods={"GET"},
            name="tty",
        )

    def prepare_server(self, app: WebApp) -> None:
        """Prepare the normal Sanic topology with one worker and access logs."""
        settings = conf.settings.web
        app.prepare(
            host=settings.listen_host,
            port=settings.listen_port,
            workers=1,
            access_log=True,
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
        app = LoggingTtyWebService(
            app_name,
            config=BOOTSTRAP_CONTEXT,
        ).create_app()
        Finalize(None, worker_runtime.close, exitpriority=100)
        return app
    except BaseException:
        worker_runtime.close()
        raise


def main() -> None:
    """Serve until SIGTERM and publish completion after normal shutdown."""
    web_runtime._create_sanic_app_factory = _create_fixture_sanic_app
    application = LoggingTtyWebService(APP_NAME, config=BOOTSTRAP_CONTEXT)
    _write_state(
        main_process_ready=False,
        manager_ack_complete=False,
        finished=False,
    )
    application.run()
    _write_state(
        main_process_ready=True,
        manager_ack_complete=True,
        finished=True,
    )


if __name__ == "__main__":
    main()
