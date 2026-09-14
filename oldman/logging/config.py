"""Pure logging configuration generation for Oldman runtimes."""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

ColorPolicy = Literal["auto", "always", "never"]

_MAIN_HANDLERS = ["console", "file"]


LOGGING_CONFIG_DEFAULTS: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "generic": {
            "()": "oldman.logging.formatters.ConsoleFormatter",
            "format": "%(asctime)s [%(process)s] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "color": "auto",
            "stream": "ext://sys.stdout",
        },
        "error": {
            "()": "oldman.logging.formatters.ConsoleFormatter",
            "format": "%(asctime)s [%(process)s] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "color": "auto",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "()": "oldman.logging.formatters.AccessConsoleFormatter",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "color": "auto",
            "stream": "ext://sys.stdout",
        },
        "no_color": {
            "class": "oldman.logging.formatters.PlainTextFormatter",
            "format": (
                "%(asctime)s [%(process)s] [%(levelname)s] "
                "[%(filename)s:%(lineno)s]  %(message)s"
            ),
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
        },
        "no_color_access": {
            "class": "oldman.logging.formatters.PlainTextAccessFormatter",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": "ext://sys.stdout",
        },
        "error_console": {
            "class": "logging.StreamHandler",
            "formatter": "error",
            "stream": "ext://sys.stderr",
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "oldman.logging.handlers.AtomicAppendFileHandler",
            "formatter": "no_color",
            "filename": "logs/oldman.log",
            "when": "D",
            "interval": 1,
            "backupCount": 3,
            "encoding": "utf-8",
        },
        "access_file": {
            "class": "oldman.logging.handlers.AtomicAppendFileHandler",
            "formatter": "no_color_access",
            "filename": "logs/oldman_access.log",
            "when": "D",
            "interval": 1,
            "backupCount": 3,
            "encoding": "utf-8",
        },
        "database_file": {
            "class": "oldman.logging.handlers.AtomicAppendFileHandler",
            "formatter": "no_color",
            "filename": "logs/oldman_database.log",
            "when": "D",
            "interval": 1,
            "backupCount": 3,
            "encoding": "utf-8",
        },
    },
    "root": {"level": logging.INFO, "handlers": _MAIN_HANDLERS.copy()},
    "loggers": {
        "default": {
            "level": logging.INFO,
            "handlers": _MAIN_HANDLERS.copy(),
            "propagate": False,
        },
        "oldman": {"level": logging.INFO, "handlers": [], "propagate": True},
        "sqlalchemy": {
            "level": logging.INFO,
            "handlers": ["console", "database_file"],
            "propagate": False,
        },
        "sqlalchemy.engine": {"level": logging.INFO, "handlers": [], "propagate": True},
        "sqlalchemy.pool": {"level": logging.INFO, "handlers": [], "propagate": True},
        "sqlalchemy.orm": {"level": logging.INFO, "handlers": [], "propagate": True},
        "sanic.root": {
            "level": logging.INFO,
            "handlers": _MAIN_HANDLERS.copy(),
            "propagate": False,
        },
        "sanic.error": {
            "level": logging.INFO,
            "handlers": ["error_console", "file"],
            "propagate": False,
        },
        "sanic.access": {
            "level": logging.INFO,
            "handlers": ["access_console", "access_file"],
            "propagate": False,
        },
        "sanic.server": {
            "level": logging.INFO,
            "handlers": _MAIN_HANDLERS.copy(),
            "propagate": False,
        },
        "sanic.websockets": {
            "level": logging.INFO,
            "handlers": _MAIN_HANDLERS.copy(),
            "propagate": False,
        },
    },
}


def _deep_merge(target: dict[str, Any], override: Mapping[str, Any]) -> None:
    """Merge nested mappings without sharing mutable values with the caller."""
    for key, value in override.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _deep_merge(current, value)
        else:
            target[key] = copy.deepcopy(value)


def _normalize_app_name(app_name: str) -> str:
    """Retain the historical lowercase and space-to-underscore file prefix."""
    return app_name.lower().strip().replace(" ", "_")


def build_sink_config(
    app_name: str,
    logger_path: str | os.PathLike[str],
    logger_level: int,
    color: ColorPolicy,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one independent sink configuration without opening any handlers."""
    config = copy.deepcopy(LOGGING_CONFIG_DEFAULTS)
    config["root"]["level"] = logger_level
    for logger_config in config["loggers"].values():
        logger_config["level"] = logger_level

    # Preserve the existing suppression of noisy SQLAlchemy internals outside DEBUG.
    if logger_level > logging.DEBUG:
        for logger_name in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.orm"):
            config["loggers"][logger_name]["level"] = logging.WARNING

    config["formatters"]["generic"]["color"] = color
    config["formatters"]["error"]["color"] = color
    config["formatters"]["access"]["color"] = color

    prefix = _normalize_app_name(app_name)
    directory = Path(logger_path)
    config["handlers"]["file"]["filename"] = str(directory / f"{prefix}.log")
    config["handlers"]["access_file"]["filename"] = str(directory / f"{prefix}_access.log")
    config["handlers"]["database_file"]["filename"] = str(directory / f"{prefix}_database.log")

    if overrides:
        _deep_merge(config, overrides)

    return config


__all__ = [
    "ColorPolicy",
    "LOGGING_CONFIG_DEFAULTS",
    "build_sink_config",
]
