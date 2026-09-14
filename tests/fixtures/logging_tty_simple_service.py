"""Minimal SimpleApplication fixture for the real TTY logging gate."""

# ruff: noqa: E402 -- settings must exist before importing runtime consumers.

from __future__ import annotations

import json
import logging
import os
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

SETTINGS = DefaultSettings.model_validate(
    {
        "core": {"app_name": APP_NAME, "data_dir": LOG_DIR},
        "logging": {"dir": LOG_DIR, "color": "auto"},
        "process": {"pid_dir": LOG_DIR},
        "web": {"workers": 1, "static": {"root": "", "url": ""}},
        "i18n": {"use_i18n": False},
    }
)
conf.__dict__["settings"] = SETTINGS

from oldman.apps import AppRegistry
from oldman.logging import logger
from oldman.runtime.bootstrap import ServiceBootstrapContext
from oldman.runtime.simple import SimpleApplication

BOOTSTRAP_CONTEXT = ServiceBootstrapContext(
    service_module=APP_NAME,
    config_file=LOG_DIR / "logging_tty_simple_settings.yaml",
    settings=SETTINGS,
    apps=AppRegistry(),
)


class LoggingTtySimpleService(SimpleApplication):
    """Emit one main, error and database token, then exit naturally."""

    def prepare(self) -> None:
        """Keep the fixture independent of project startup work."""

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Write only the three unique records exercised by the TTY gate."""
        del args, kwargs
        logger.info(MAIN_TOKEN)
        logging.getLogger("sanic.error").error(ERROR_TOKEN)
        logging.getLogger("sqlalchemy").info(DATABASE_TOKEN)


def main() -> None:
    """Run the application and publish normal completion after cleanup."""
    application = LoggingTtySimpleService(APP_NAME, config=BOOTSTRAP_CONTEXT)
    application.run()
    STATE_FILE.write_text(
        json.dumps({"pid": os.getpid(), "app_name": APP_NAME, "finished": True}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
