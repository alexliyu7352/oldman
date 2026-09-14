"""Default Web service for {{ project_name }}."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from config.settings import settings
from oldman.runtime import WebApplication

if TYPE_CHECKING:
    from oldman.web.routing import WebApp


class {{ service_class }}(WebApplication):
    """Serve the project's registered Web Apps."""

    def get_ext_config(self) -> Mapping[str, Any]:
        """Enable the configured async template environment."""
        return {
            "oas": False,
            "oas_autodoc": False,
            "templating_path_to_templates": settings.web.template.dir,
            "templating_enable_async": True,
            "logging": False,
        }

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
