"""Runtime installer for the built-in Admin site."""

from __future__ import annotations

from typing import Any

import oldman.conf as conf
from oldman.apps import AppNotInstalledError
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.site import AdminSite
from oldman.apps.admin.site import site as default_admin_site
from oldman.apps.admin.staticfiles import (
    ADMIN_ENTRY_PATH,
    register_admin_static_bundle,
)
from oldman.apps.admin.template import install_admin_template_loader
from oldman.auth import AuthSettings, get_user_model
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n.translations import gettext, ngettext
from oldman.web.auth.login import LoginRateLimit
from oldman.web.auth.password_reset import RateLimiter
from oldman.web.messages.notifications import init_app as install_notifications
from oldman.web.security.csrf import CsrfExtension, StatelessCSRFManager
from oldman.web.staticfiles import app_bundle_registry
from oldman.web.template import install_template_loaders


def install_admin(
    app: Any,
    *,
    db_manager: DatabaseManager | None = None,
    admin_site: AdminSite | None = None,
    prefix: str = "/admin",
    dev_mode: bool = False,
    dev_server_url: str = "",
    extension_bundle_name: str | None = None,
    auth_settings: AuthSettings | None = None,
    admin_settings: AdminSettings | None = None,
    password_reset_rate_limiter: RateLimiter | None = None,
    login_rate_limit: LoginRateLimit | None = None,
) -> AdminSite:
    """Install Admin routes, templates and the collected frontend bundle."""
    resolved_site = admin_site if admin_site is not None else default_admin_site
    manager = db_manager if db_manager is not None else default_db_manager
    app_registry = getattr(app.ctx, "oldman_app_registry", None)
    if app_registry is not None:
        resolved_site.bind_app_registry(app_registry)
    if auth_settings is None:
        from oldman.auth.apps import app as auth_app

        auth_settings = auth_app.settings
    if admin_settings is None:
        from oldman.apps.admin.apps import app as admin_app

        admin_settings = admin_app.settings
    resolved_site.register_user_model(get_user_model(auth_settings))
    registry = app_bundle_registry(app)

    static_config = conf.settings.web.static
    register_admin_static_bundle(
        registry,
        static_root=static_config.root,
        static_url=static_config.url,
        dev_mode=dev_mode,
        dev_server_url=dev_server_url,
    )
    registry.ensure_build_available("oldman:admin", ADMIN_ENTRY_PATH)
    if extension_bundle_name is not None:
        extension_bundle = registry.get(extension_bundle_name)
        if not extension_bundle.entry_path.lower().endswith(".css"):
            raise ValueError(f"Admin extension bundle {extension_bundle_name} must use a .css entry")
        registry.ensure_build_available(extension_bundle_name)
    app.ctx.oldman_admin_extension_bundle_name = extension_bundle_name

    environment = getattr(getattr(app, "ext", None), "environment", None)
    if environment is None:
        raise RuntimeError("Oldman Admin requires the Sanic-Ext template environment")
    csrf_manager = getattr(app.ctx, "csrf", None)
    if csrf_manager is None:
        csrf_manager = StatelessCSRFManager(app)
    app.ctx.csrf = csrf_manager
    environment.add_extension(CsrfExtension)
    install_template_loaders(environment)
    install_admin_template_loader(environment)
    environment.globals.setdefault("_", gettext)
    environment.globals.setdefault("gettext", gettext)
    environment.globals.setdefault("ngettext", ngettext)
    registry.install_template_globals(environment)

    notification_routes = None
    if app_registry is not None:
        try:
            app_registry.get_by_package("oldman.web.messages.notifications")
        except AppNotInstalledError:
            pass
        else:
            notification_routes = install_notifications(app, url_prefix=prefix)

    user_events_url = resolved_site.register_routes(
        app,
        prefix=prefix,
        db_manager=manager,
        auth_settings=auth_settings,
        admin_settings=admin_settings,
        notifications_enabled=notification_routes is not None,
        sse_enabled=conf.settings.web.sse.enabled,
        password_reset_rate_limiter=password_reset_rate_limiter,
        login_rate_limit=login_rate_limit,
    )
    app.ctx.oldman_admin_notification_routes = notification_routes
    app.ctx.oldman_admin_user_events_url = user_events_url
    return resolved_site


__all__ = ["install_admin"]
