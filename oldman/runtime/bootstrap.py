"""One process-wide service bootstrap shared by runtime and developer tools."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import oldman.conf as conf
from oldman.apps import AppRegistry
from oldman.conf.constants import _find_project_root
from oldman.conf.schemas import DefaultSettings
from oldman.runtime.discovery import get_service_definition


@dataclass(frozen=True, slots=True)
class ServiceBootstrapContext:
    """Validated settings and model Registry for one selected service process."""

    service_module: str
    config_file: Path
    settings: DefaultSettings
    apps: AppRegistry


_BOOTSTRAP_LOCK = threading.RLock()
_bootstrap_context: ServiceBootstrapContext | None = None


def _get_bootstrap_context() -> ServiceBootstrapContext:
    """Return the sole process context required by Application construction."""
    if _bootstrap_context is None:
        raise RuntimeError(
            "Oldman service bootstrap has not completed; call bootstrap_service() first."
        )
    return _bootstrap_context


def bootstrap_service(
    service_module: str,
    *,
    config_file: str | Path | None = None,
) -> ServiceBootstrapContext:
    """Load one service's YAML, App settings and models without starting it."""
    global _bootstrap_context

    project_root = _find_project_root()
    definition = get_service_definition(service_module, project_root)
    selected_config = (
        Path(config_file)
        if config_file is not None
        else project_root / "data" / f"{service_module}_settings.yaml"
    ).expanduser().resolve()

    with _BOOTSTRAP_LOCK:
        if _bootstrap_context is not None:
            if (
                _bootstrap_context.service_module == service_module
                and _bootstrap_context.config_file == selected_config
            ):
                return _bootstrap_context
            raise RuntimeError(
                "Oldman is already bootstrapped for service "
                f"{_bootstrap_context.service_module!r} with "
                f"{str(_bootstrap_context.config_file)!r}."
            )

        settings_class = conf._load_project_settings_class()
        manager = conf.SettingsManager(
            settings_class,
            definition,
            selected_config,
        )
        settings = manager.load()
        conf._publish_settings(settings)
        # Registered model modules are ordinary project code and may consume the
        # validated global and App settings during import.
        manager.registry.load_models()
        conf._log_settings_diagnostics(manager.diagnostics)

        context = ServiceBootstrapContext(
            service_module=service_module,
            config_file=selected_config,
            settings=settings,
            apps=manager.registry,
        )
        _bootstrap_context = context
        return context


__all__ = ["ServiceBootstrapContext", "bootstrap_service"]
