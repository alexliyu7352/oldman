"""Cold-path project settings helpers for CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings

if TYPE_CHECKING:
    from oldman.runtime.discovery import ServiceDefinition


class SettingsCliError(RuntimeError):
    """An expected project-schema prerequisite error safe for CLI display."""

    def __init__(self, message: str, **variables: Any) -> None:
        """Store a translatable source message and its interpolation values."""
        super().__init__(message)
        self.message = message
        self.variables = variables


def ensure_cwd_on_syspath() -> None:
    """Make the current project importable for explicit module discovery."""
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


def load_project_settings_schema() -> type[DefaultSettings]:
    """Load the required project schema without publishing runtime settings."""
    ensure_cwd_on_syspath()
    try:
        from oldman.conf import _load_project_settings_class

        return _load_project_settings_class()
    except (RuntimeError, TypeError) as exc:
        raise SettingsCliError(str(exc)) from None


def get_settings_manager(
    service_definition: ServiceDefinition,
    config_file: Path | None = None,
) -> SettingsManager:
    """Create a manager for one cold-discovered service definition."""
    settings_class = load_project_settings_schema()
    project_root = service_definition.module_path.parent.parent
    resolved_config = (
        Path(config_file)
        if config_file is not None
        else project_root
        / "data"
        / f"{service_definition.module_name}_settings.yaml"
    )
    return SettingsManager(
        settings_class,
        service_definition,
        resolved_config.resolve(),
    )


__all__ = [
    "SettingsCliError",
    "ensure_cwd_on_syspath",
    "get_settings_manager",
    "load_project_settings_schema",
]
