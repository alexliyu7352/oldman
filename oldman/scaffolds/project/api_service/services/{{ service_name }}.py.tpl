"""Default API service for {{ project_name }}."""

from __future__ import annotations

from oldman.runtime import WebApplication


class {{ service_class }}(WebApplication):
    """Serve the project's registered API Apps.

    The listener comes from the `web` settings through WebApplication.prepare_server; override
    that method when this service needs its own socket, worker or asset checks.
    """
