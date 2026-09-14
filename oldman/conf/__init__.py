"""Application settings bootstrap and public configuration API."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, cast

from oldman.conf import constants
from oldman.conf.manager import SettingsFileMissingError, SettingsManager
from oldman.conf.schemas import DefaultSettings

PROJECT_BASE_PATH = constants.BASE_PATH

_BOOTSTRAP_LOGGER = logging.Logger("oldman.conf.bootstrap", level=logging.WARNING)
_BOOTSTRAP_LOGGER.propagate = False
_BOOTSTRAP_HANDLER = logging.StreamHandler()
_BOOTSTRAP_HANDLER.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
_BOOTSTRAP_LOGGER.addHandler(_BOOTSTRAP_HANDLER)
_SETTINGS_LOCK = threading.RLock()
_settings_instance: DefaultSettings | None = None
settings: DefaultSettings


def _load_project_settings_class() -> type[DefaultSettings]:
    """Import the project's sole Settings type without publishing an instance."""
    try:
        module = importlib.import_module("config.schemas")
    except ModuleNotFoundError as exc:
        if exc.name not in {"config", "config.schemas"}:
            raise
        raise RuntimeError(
            "Service bootstrap requires config.schemas.Settings in the current project."
        ) from None

    settings_class = getattr(module, "Settings", None)
    if not isinstance(settings_class, type) or not issubclass(
        settings_class,
        DefaultSettings,
    ):
        raise TypeError(
            "config.schemas.Settings must inherit oldman.conf.DefaultSettings."
        )
    return cast(type[DefaultSettings], settings_class)


def _publish_settings(instance: DefaultSettings) -> None:
    """Publish the validated process settings for the unified bootstrap only."""
    global _settings_instance, settings

    with _SETTINGS_LOCK:
        if _settings_instance is not None and _settings_instance is not instance:
            raise RuntimeError("Oldman settings are already configured")
        settings = instance
        _settings_instance = instance


def _log_settings_diagnostics(messages: tuple[str, ...]) -> None:
    """Report non-fatal configuration advice before normal logging starts."""
    for message in messages:
        _BOOTSTRAP_LOGGER.warning("%s", message)


def __getattr__(name: str) -> Any:
    if name == "settings":
        raise RuntimeError(
            "Oldman settings are not configured; bootstrap the service before importing settings consumers"
        )
    raise AttributeError(name)


__all__ = [
    "DefaultSettings",
    "PROJECT_BASE_PATH",
    "SettingsFileMissingError",
    "SettingsManager",
    "settings",
]
