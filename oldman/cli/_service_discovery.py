"""Cold CLI view of project service definitions."""

from __future__ import annotations

from oldman.conf.constants import _find_project_root
from oldman.runtime.discovery import ServiceDefinition, discover_service_definitions


def discover_services() -> dict[str, ServiceDefinition]:
    """Return static service definitions without importing service modules."""
    return discover_service_definitions(_find_project_root())


__all__ = ["discover_services"]
