"""Default API service for {{ project_name }}."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.settings import settings
from oldman.runtime import WebApplication

if TYPE_CHECKING:
    from oldman.web.routing import WebApp


class {{ service_class }}(WebApplication):
    """Serve the project's registered API Apps."""

    def prepare_server(self, app: WebApp) -> None:
        """Apply the configured Sanic listener options."""
        app.prepare(
            host=settings.web.listen_host,
            port=settings.web.listen_port,
            debug=settings.web.debug,
            motd=False,
            auto_reload=settings.web.auto_reload,
            single_process=True,
            workers=settings.web.workers,
            access_log=settings.web.access_log,
        )
