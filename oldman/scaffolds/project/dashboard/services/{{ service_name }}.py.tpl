"""Default Dashboard service for {{ project_name }}."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config.settings import settings
from oldman.i18n import gettext
from oldman.runtime import WebApplication
from oldman.web.staticfiles import StaticBundle, StaticBundleRegistry
from oldman.web.template import install_template_loaders

if TYPE_CHECKING:
    from oldman.web.routing import WebApp

APP_MAIN_BUNDLE = "app:main"


def is_vite_dev_mode() -> bool:
    """Return whether assets should be served by Vite."""
    return os.environ.get("OLDMAN_DEV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def create_static_bundle_registry() -> StaticBundleRegistry:
    """Create the generated project's Vite bundle registry."""
    dev_mode = is_vite_dev_mode()
    static_root = str(settings.web.static.root).strip()
    static_url = str(settings.web.static.url).strip()
    if not dev_mode and (not static_root or not static_url):
        raise RuntimeError(
            "Dashboard production assets require web.static.root and "
            "web.static.url; configure them and run `oldman static collect`"
        )

    registry = StaticBundleRegistry()
    registry.register(
        StaticBundle(
            name=APP_MAIN_BUNDLE,
            entry_path="src/main.ts",
            manifest_path=Path(static_root) / "dist" / ".vite" / "manifest.json",
            static_url=f"{static_url.rstrip('/')}/dist",
            dev_server_url=settings.web.frontend.vite_dev_server_url,
            dev_mode=dev_mode,
        )
    )
    return registry


def install_dashboard_templates(app: WebApp) -> StaticBundleRegistry:
    """Install shared templates and public bundle helpers."""
    registry = create_static_bundle_registry()
    app.ctx.static_bundle_registry = registry
    environment = install_template_loaders(
        app.ext.environment,
        settings.web.template.dir,
    )
    environment.globals.setdefault("_", gettext)
    environment.globals.setdefault("gettext", gettext)
    environment.globals.update(
        app_main_bundle=APP_MAIN_BUNDLE,
        bundle_asset_base_url=registry.asset_base_url,
        bundle_entry=registry.entry_tags,
    )
    return registry


class {{ service_class }}(WebApplication):
    """Serve the project's registered Dashboard Apps."""

    @classmethod
    def get_default_commands(
        cls,
    ) -> dict[str, tuple[Callable[..., Any], str]]:
        """Add the explicit Vite development command."""
        commands = super().get_default_commands()
        commands["dev"] = (
            cls.dev,
            "Start with assets served by the Vite development server",
        )
        return commands

    def dev(self, *args: Any, **kwargs: Any) -> None:
        """Start the service in Vite development mode."""
        os.environ["OLDMAN_DEV"] = "1"
        self.start(*args, **kwargs)

    def get_ext_config(self) -> Mapping[str, Any]:
        """Enable the configured async template environment."""
        return {
            "oas": False,
            "oas_autodoc": False,
            "templating_path_to_templates": settings.web.template.dir,
            "templating_enable_async": True,
            "logging": False,
        }

    def init(self) -> None:
        """Install the shared templates and frontend bundle registry."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime was not initialized")
        install_dashboard_templates(app)

    def prepare_server(self, app: WebApp) -> None:
        """Validate assets and apply configured listener options."""
        create_static_bundle_registry().ensure_build_available(APP_MAIN_BUNDLE)
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
