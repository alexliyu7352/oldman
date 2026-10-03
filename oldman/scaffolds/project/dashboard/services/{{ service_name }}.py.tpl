"""Default Dashboard service for {{ project_name }}."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.accounts.routes import install_account_pages
from config.settings import settings
{{ admin_import }}from oldman.auth.user_permissions import VIEW_USERS
from oldman.i18n import gettext
from oldman.runtime import WebApplication
from oldman.web.auth import has_perm
from oldman.web.i18n import ensure_frontend_catalogs
from oldman.web.messages.notifications import init_app as install_notifications
from oldman.web.security.csrf import StatelessCSRFManager
from oldman.web.staticfiles import (
    DEV_MODE_ENV,
    StaticBundleRegistry,
    app_bundle_registry,
    dev_mode_requested,
    register_project_bundle,
)
from oldman.web.template import install_template_loaders

if TYPE_CHECKING:
    from oldman.web.routing import WebApp

APP_MAIN_BUNDLE = "app:main"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def can_manage_users(request: Any) -> bool:
    """Whether the menu lists User management: the permission its pages check (a superuser holds it)."""
    return await has_perm(request, VIEW_USERS)


def install_dashboard_templates(app: WebApp) -> StaticBundleRegistry:
    """Install shared templates, the project's Vite bundle and the public bundle helpers."""
    registry = app_bundle_registry(app)
    register_project_bundle(
        registry,
        name=APP_MAIN_BUNDLE,
        entry_path="src/main.ts",
        static_root=settings.web.static.root,
        static_url=settings.web.static.url,
        dev_mode=dev_mode_requested(),
        dev_server_url=settings.web.frontend.vite_dev_server_url,
    )
    environment = install_template_loaders(
        app.ext.environment,
        settings.web.template.dir,
    )
    environment.globals.setdefault("_", gettext)
    environment.globals.setdefault("gettext", gettext)
    registry.install_template_globals(environment)
    environment.globals["app_main_bundle"] = APP_MAIN_BUNDLE
    environment.globals["can_manage_users"] = can_manage_users
    return registry


class {{ service_class }}(WebApplication):
    """Serve the dashboard: its pages, the account pages and the project's Apps."""

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
        os.environ[DEV_MODE_ENV] = "1"
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
        """Install CSRF, notifications, the templates and bundle, then the account pages."""
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Web runtime was not initialized")
        StatelessCSRFManager(app)
        notification_routes = install_notifications(app)
        install_dashboard_templates(app)
        install_account_pages(app, notification_routes=notification_routes)
{{ admin_install }}
    def prepare_server(self, app: WebApp) -> None:
        """Fail fast on a missing frontend build, then take the framework's listener options."""
        registry = app_bundle_registry(app)
        registry.ensure_build_available(APP_MAIN_BUNDLE)
        # 配置里的语言必须都编译过：少一份目录，切换器里就有一个点下去没有翻译的语言。
        ensure_frontend_catalogs(registry, APP_MAIN_BUNDLE, source_dir=PROJECT_ROOT / "frontend" / "public" / "i18n")
        super().prepare_server(app)
