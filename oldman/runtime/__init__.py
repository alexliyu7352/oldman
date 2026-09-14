"""Lazy public exports for service discovery, bootstrap, and runtimes."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oldman.runtime.base import BaseApplication as BaseApplication
    from oldman.runtime.bootstrap import (
        ServiceBootstrapContext as ServiceBootstrapContext,
    )
    from oldman.runtime.bootstrap import bootstrap_service as bootstrap_service
    from oldman.runtime.discovery import (
        ServiceDefinition as ServiceDefinition,
    )
    from oldman.runtime.discovery import (
        discover_service_definitions as discover_service_definitions,
    )
    from oldman.runtime.discovery import (
        get_service_definition as get_service_definition,
    )
    from oldman.runtime.discovery import load_service_class as load_service_class
    from oldman.runtime.simple import SimpleApplication as SimpleApplication
    from oldman.runtime.taskiq import TaskiqSchedulerApplication as TaskiqSchedulerApplication
    from oldman.runtime.taskiq import TaskiqWorkerApplication as TaskiqWorkerApplication
    from oldman.runtime.web import WebApplication as WebApplication

_EXPORTS = {
    "BaseApplication": ("oldman.runtime.base", "BaseApplication"),
    "ServiceBootstrapContext": (
        "oldman.runtime.bootstrap",
        "ServiceBootstrapContext",
    ),
    "ServiceDefinition": ("oldman.runtime.discovery", "ServiceDefinition"),
    "SimpleApplication": ("oldman.runtime.simple", "SimpleApplication"),
    "TaskiqWorkerApplication": ("oldman.runtime.taskiq", "TaskiqWorkerApplication"),
    "TaskiqSchedulerApplication": ("oldman.runtime.taskiq", "TaskiqSchedulerApplication"),
    "WebApplication": ("oldman.runtime.web", "WebApplication"),
    "bootstrap_service": ("oldman.runtime.bootstrap", "bootstrap_service"),
    "discover_service_definitions": (
        "oldman.runtime.discovery",
        "discover_service_definitions",
    ),
    "get_service_definition": (
        "oldman.runtime.discovery",
        "get_service_definition",
    ),
    "load_service_class": ("oldman.runtime.discovery", "load_service_class"),
}


def __getattr__(name: str) -> Any:
    """Import only the requested runtime boundary."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to shells and static inspection."""
    return sorted((*globals(), *_EXPORTS))


__all__ = [
    "BaseApplication",
    "ServiceBootstrapContext",
    "ServiceDefinition",
    "SimpleApplication",
    "TaskiqWorkerApplication",
    "TaskiqSchedulerApplication",
    "WebApplication",
    "bootstrap_service",
    "discover_service_definitions",
    "get_service_definition",
    "load_service_class",
]
