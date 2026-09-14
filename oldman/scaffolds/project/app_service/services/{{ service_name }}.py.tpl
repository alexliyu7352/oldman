"""Default background service for {{ project_name }}."""

from __future__ import annotations

from typing import Any

from oldman.runtime import SimpleApplication


class {{ service_class }}(SimpleApplication):
    """Run the project's background workload."""

    def prepare(self) -> None:
        """Prepare synchronous service resources."""

    async def main(self, *args: Any, **kwargs: Any) -> None:
        """Run the service workload."""
        del args, kwargs
