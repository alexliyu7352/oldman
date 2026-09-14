"""Strongly typed metadata for installable Oldman applications."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from oldman.i18n import LazyTranslation

if TYPE_CHECKING:
    from oldman.apps.registry import AppRegistry


_LABEL_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_ICON_PATTERN = re.compile(r"(?:ri|mdi|bx|bxs|bxl)-[a-z0-9-]+")
_MODULE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_SETTINGS_NOT_BOUND = object()


def _validate_icon_class(value: object, *, field_name: str) -> str:
    """Return one supported Iconify class or identify the invalid field."""
    if not isinstance(value, str) or _ICON_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be one Iconify class matching "
            f"(?:ri|mdi|bx|bxs|bxl)-[a-z0-9-]+; received {value!r}."
        )
    return value


class AppNotInstalledError(RuntimeError):
    """Raised when code accesses an App absent from the current Registry."""


class AppSettingsNotDefinedError(RuntimeError):
    """Raised when an App without a settings model accesses ``app.settings``."""


class AppSettingsNotReadyError(RuntimeError):
    """Raised when installed App settings have not completed validation."""


class AppConfig[T_AppSettings]:
    """Describe one reusable App while preserving its settings type."""

    label = ""
    display_name: str | LazyTranslation = ""
    icon = "ri-database-2-line"
    settings_model: type[T_AppSettings] | None = None
    models_module = "models"
    migrations_module = "migrations"
    web_module = "views"
    commands_module = "commands"
    tasks_module = "tasks"
    events_module = "events"

    def __init__(self) -> None:
        """Validate static metadata without resolving settings or translations."""
        self._registry: AppRegistry | None = None
        self._settings: T_AppSettings | object = _SETTINGS_NOT_BOUND
        self._validate_metadata()

    def _validate_metadata(self) -> None:
        """Reject metadata that cannot remain a stable App identity."""
        if not isinstance(self.label, str) or _LABEL_PATTERN.fullmatch(self.label) is None:
            raise ValueError(f"AppConfig.label must match [a-z][a-z0-9_]*; received {self.label!r}.")

        if isinstance(self.display_name, LazyTranslation):
            if not self.display_name.singular.strip():
                raise ValueError("AppConfig.display_name cannot be empty.")
        elif not isinstance(self.display_name, str):
            raise TypeError(f"AppConfig.display_name must be a string or LazyTranslation; received {type(self.display_name).__name__}.")
        elif not self.display_name.strip():
            raise ValueError("AppConfig.display_name cannot be empty.")

        _validate_icon_class(self.icon, field_name="AppConfig.icon")

        for field_name in (
            "models_module",
            "migrations_module",
            "web_module",
            "commands_module",
            "tasks_module",
            "events_module",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _MODULE_PATTERN.fullmatch(value) is None:
                raise ValueError(f"AppConfig.{field_name} must be a non-empty relative Python module path; received {value!r}.")

        if self.settings_model is not None and not isinstance(self.settings_model, type):
            raise TypeError(f"AppConfig.settings_model must be a type or None; received {self.settings_model!r}.")

    @property
    def settings(self) -> T_AppSettings:
        """Return the current service's validated settings instance."""
        if self._registry is None:
            raise AppNotInstalledError(f"App {self.label!r} is not installed in the current service.")
        if self.settings_model is None:
            raise AppSettingsNotDefinedError(f"App {self.label!r} does not define a settings model.")
        if self._settings is _SETTINGS_NOT_BOUND:
            raise AppSettingsNotReadyError(f"Settings for App {self.label!r} are not ready; bootstrap the service before accessing app.settings.")
        return cast(T_AppSettings, self._settings)

    def _install(self, registry: AppRegistry) -> None:
        """Bind this process-wide App object to its sole service Registry."""
        if self._registry is not None and self._registry is not registry:
            raise RuntimeError(f"App {self.label!r} is already installed in another Registry.")
        self._registry = registry

    def _bind_settings(self, settings: T_AppSettings) -> None:
        """Publish one validated settings instance after Registry installation."""
        if self._settings is not _SETTINGS_NOT_BOUND and self._settings is not settings:
            raise RuntimeError(f"Settings for App {self.label!r} are already bound.")
        self._settings = settings


__all__ = [
    "AppConfig",
    "AppNotInstalledError",
    "AppSettingsNotDefinedError",
    "AppSettingsNotReadyError",
]
