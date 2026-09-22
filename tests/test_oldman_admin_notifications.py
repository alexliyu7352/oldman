"""Admin integration tests for persistent notifications and the shared SSE route."""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import cast
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from markupsafe import Markup
from sanic import Request, Sanic

import oldman.conf as conf
from oldman.apps import AppNotInstalledError
from oldman.apps.admin.runtime import install_admin
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.site import AdminSite
from oldman.auth import AuthSettings
from oldman.conf.schemas import SessionConfig, SSEConfig
from oldman.web.messages.notifications import NotificationRoutes
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    make_request,
    runtime_settings,
)


class RegistryStub:
    """Expose only the package lookup consumed by the Admin installer."""

    def __init__(self, *, notifications_installed: bool) -> None:
        self.notifications_installed = notifications_installed

    def get_by_package(self, package: str) -> object:
        if package == "oldman.web.messages.notifications" and self.notifications_installed:
            return object()
        raise AppNotInstalledError(f"{package} is not installed")


class RecordingStream:
    """Record the user identity subscribed by one Admin SSE handler."""

    def __init__(self) -> None:
        self.user_ids: list[int] = []

    async def subscribe_user(self, user_id: int) -> None:
        self.user_ids.append(user_id)


class AdminNotificationInstallerTest(TestCase):
    """Verify runtime feature detection remains owned by the Admin host."""

    def test_installer_uses_registry_and_global_sse_configuration(self) -> None:
        app = FakeApp()
        app.ctx.oldman_app_registry = RegistryStub(notifications_installed=True)
        settings = runtime_settings(
            session=SessionConfig(enabled=True),
        )
        settings.web.sse = SSEConfig(
            enabled=True,
            redis_alias="SSE",
            channel_prefix="admin_test",
        )
        routes = NotificationRoutes(
            topbar_url="/control/user-notifications/topbar",
            read_url="/control/user-notifications/read",
            delete_url="/control/user-notifications/delete",
            center_url="/control/user-notifications",
        )
        site = AdminSite("notification_installer")

        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch("oldman.apps.admin.runtime.install_notifications", return_value=routes) as installer,
            patch.object(site, "register_routes", return_value="/control/user-events") as register_routes,
        ):
            install_admin(
                app,
                admin_site=site,
                auth_settings=AuthSettings(),
                admin_settings=AdminSettings(),
                prefix="/control",
            )

        installer.assert_called_once_with(app, url_prefix="/control")
        register_routes.assert_called_once_with(
            app,
            prefix="/control",
            db_manager=register_routes.call_args.kwargs["db_manager"],
            auth_settings=register_routes.call_args.kwargs["auth_settings"],
            admin_settings=register_routes.call_args.kwargs["admin_settings"],
            notifications_enabled=True,
            sse_enabled=True,
            password_reset_rate_limiter=None,
            login_rate_limit=None,
        )
        self.assertIs(app.ctx.oldman_admin_notification_routes, routes)
        self.assertEqual(app.ctx.oldman_admin_user_events_url, "/control/user-events")

    def test_installer_does_not_infer_an_unregistered_notification_app(self) -> None:
        app = FakeApp()
        app.ctx.oldman_app_registry = RegistryStub(notifications_installed=False)
        settings = runtime_settings(session=SessionConfig(enabled=True))
        settings.web.sse = SSEConfig(
            enabled=True,
            redis_alias="SSE",
            channel_prefix="admin_test",
        )
        site = AdminSite("notification_absent")

        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch("oldman.apps.admin.runtime.install_notifications") as installer,
            patch.object(site, "register_routes", return_value="/control/user-events") as register_routes,
        ):
            install_admin(
                app,
                admin_site=site,
                auth_settings=AuthSettings(),
                admin_settings=AdminSettings(),
                prefix="/control",
            )

        installer.assert_not_called()
        self.assertFalse(register_routes.call_args.kwargs["notifications_enabled"])
        self.assertTrue(register_routes.call_args.kwargs["sse_enabled"])
        self.assertIsNone(app.ctx.oldman_admin_notification_routes)

    def test_installer_keeps_notification_http_routes_when_sse_is_disabled(self) -> None:
        app = FakeApp()
        app.ctx.oldman_app_registry = RegistryStub(notifications_installed=True)
        settings = runtime_settings(session=SessionConfig(enabled=True))
        routes = NotificationRoutes(
            topbar_url="/control/user-notifications/topbar",
            read_url="/control/user-notifications/read",
            delete_url="/control/user-notifications/delete",
            center_url="/control/user-notifications",
        )
        site = AdminSite("notification_without_sse")

        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch(
                "oldman.apps.admin.runtime.install_notifications",
                return_value=routes,
            ) as installer,
            patch.object(site, "register_routes", return_value=None) as register_routes,
        ):
            install_admin(
                app,
                admin_site=site,
                auth_settings=AuthSettings(),
                admin_settings=AdminSettings(),
                prefix="/control",
            )

        installer.assert_called_once_with(app, url_prefix="/control")
        self.assertTrue(register_routes.call_args.kwargs["notifications_enabled"])
        self.assertFalse(register_routes.call_args.kwargs["sse_enabled"])
        self.assertIs(app.ctx.oldman_admin_notification_routes, routes)
        self.assertIsNone(app.ctx.oldman_admin_user_events_url)

    def test_installer_rejects_notifications_when_session_is_disabled(self) -> None:
        app = FakeApp()
        app.ctx.oldman_app_registry = RegistryStub(notifications_installed=True)
        settings = runtime_settings(session=SessionConfig(enabled=False))

        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            self.assertRaisesRegex(RuntimeError, "Session"),
        ):
            install_admin(
                app,
                admin_site=AdminSite("notification_without_session"),
                auth_settings=AuthSettings(),
                admin_settings=AdminSettings(),
                prefix="/control",
            )


class AdminNotificationRoutesTest(TestCase):
    """Verify Admin wrappers own URLs, permissions, and shared rendering only."""

    def test_optional_routes_default_to_disabled(self) -> None:
        app = FakeApp()
        site = AdminSite("notification_defaults")

        result = site.register_routes(
            cast(Sanic, app),
            auth_settings=AuthSettings(),
            admin_settings=AdminSettings(),
        )

        self.assertIsNone(result)
        self.assertNotIn(("/admin/user-notifications", ("GET",)), app.routes)
        self.assertNotIn(("/admin/user-events", ("GET",)), app.routes)

    def test_center_uses_staff_identity_and_shared_content_renderer(self) -> None:
        app = FakeApp()
        site = AdminSite("notification_center")

        site.register_routes(
            cast(Sanic, app),
            prefix="/control",
            auth_settings=AuthSettings(),
            admin_settings=AdminSettings(),
            notifications_enabled=True,
        )
        handler = app.route_handlers[("/control/user-notifications", ("GET",))]
        staff_request = make_request(
            app,
            path="/control/user-notifications?state=unread&page=2",
            session=FakeSession(user_id=17, is_active=True, is_staff=True),
        )
        with (
            patch("oldman.apps.admin.site.render_center_content", new=AsyncMock(return_value=Markup("<section>center</section>"))) as renderer,
            patch("oldman.apps.admin.site.render_admin_template", new=AsyncMock(return_value="rendered")) as render_page,
        ):
            response = asyncio.run(handler(staff_request))  # type: ignore[operator]

        self.assertEqual(response, "rendered")
        renderer.assert_awaited_once_with(staff_request, user_id=17)
        render_page.assert_awaited_once_with(
            "admin/user_notifications.html",
            staff_request,
            admin_prefix="/control",
            site=site,
            menu_items=site.menu_items("/control"),
            notification_center_content=Markup("<section>center</section>"),
        )

    def test_staff_permission_runs_before_the_sse_response_opens(self) -> None:
        app = FakeApp()
        site = AdminSite("notification_events")
        stream = RecordingStream()
        opened: list[bool] = []

        def streaming(**options: object):
            self.assertEqual(options, {"session_guard": True, "login_url": "/control/login"})

            def decorator(handler):
                @wraps(handler)
                async def wrapped(request, *args, **kwargs):
                    opened.append(True)
                    return await handler(request, stream, *args, **kwargs)

                return wrapped

            return decorator

        with patch("oldman.apps.admin.site.sse.streaming", side_effect=streaming):
            user_events_url = site.register_routes(
                cast(Sanic, app),
                prefix="/control",
                auth_settings=AuthSettings(),
                admin_settings=AdminSettings(require_superuser=False),
                sse_enabled=True,
            )

        self.assertEqual(user_events_url, "/control/user-events")
        handler = app.route_handlers[("/control/user-events", ("GET",))]
        denied_request = make_request(
            app,
            path="/control/user-events",
            session=FakeSession(user_id=9, is_active=True, is_staff=False),
        )
        denied = asyncio.run(handler(denied_request))  # type: ignore[operator]
        self.assertEqual(denied.status, 403)
        self.assertEqual(opened, [])

        staff_request = make_request(
            app,
            path="/control/user-events",
            session=FakeSession(user_id=9, is_active=True, is_staff=True),
        )
        asyncio.run(handler(staff_request))  # type: ignore[operator]
        self.assertEqual(opened, [True])
        self.assertEqual(stream.user_ids, [9])

    def test_render_context_exposes_only_installed_host_urls(self) -> None:
        app = FakeApp()
        app.ctx.oldman_admin_notification_routes = NotificationRoutes(
            topbar_url="/control/user-notifications/topbar",
            read_url="/control/user-notifications/read",
            delete_url="/control/user-notifications/delete",
            center_url="/control/user-notifications",
        )
        app.ctx.oldman_admin_user_events_url = "/control/user-events"
        request = make_request(
            app,
            path="/control",
            session=FakeSession(user_id=1, is_active=True, is_staff=True),
        )
        captured: dict[str, object] = {}

        async def capture(_template_name: str, *, context: dict[str, object]):
            captured.update(context)
            return "rendered"

        with (
            patch.dict(conf.__dict__, {"settings": runtime_settings()}),
            patch("oldman.apps.admin.site.render_template", side_effect=capture),
        ):
            from oldman.apps.admin.site import render_admin_template

            asyncio.run(
                render_admin_template(
                    "admin/index.html",
                    cast(Request, request),
                )
            )

        self.assertEqual(captured["admin_user_events_url"], "/control/user-events")
        self.assertEqual(
            captured["admin_user_notification_urls"],
            {
                "center": "/control/user-notifications",
                "topbar": "/control/user-notifications/topbar",
            },
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
