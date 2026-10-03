"""AccountFlow and account_urls: the signed-in user's own pages a dashboard (or the Admin) installs."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from jinja2 import DictLoader, Environment
from markupsafe import Markup

import oldman.conf as conf
from oldman.conf.schemas import AccountConfig, SSEConfig
from oldman.web.auth import AccountFlow, account_urls
from oldman.web.messages.notifications import NotificationRoutes
from oldman.web.security.csrf import StatelessCSRFManager
from oldman.web.template import install_template_loaders
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    make_request,
    render_with_request_environment,
    runtime_settings,
)

TEMPLATES = {
    "account/user_session.html": "session|{{ session_profile.username }}|{{ session_path }}|{{ password_modal_path }}|{{ logout_path }}",
    "account/user_notifications.html": "center|{{ notification_center_content }}",
}

NOTIFICATIONS = NotificationRoutes(
    topbar_url="/user-notifications/topbar",
    read_url="/user-notifications/read",
    delete_url="/user-notifications/delete",
    center_url="/user-notifications",
)


class RoutesApp(FakeApp):
    """FakeApp that also keeps the route names."""

    def __init__(self) -> None:
        super().__init__()
        self.route_names: dict[tuple[str, tuple[str, ...]], str] = {}
        self.ext.environment = Environment(loader=DictLoader(TEMPLATES), enable_async=True)

    def add_route(self, handler, path: str, *, methods: list[str], name: str) -> None:
        super().add_route(handler, path, methods=methods, name=name)
        self.route_names[(path, tuple(methods))] = name


def make_flow(**overrides: Any) -> AccountFlow:
    options: dict[str, Any] = {
        "profile_path": "/me",
        "login_path": "/signin",
        "logout_path": "/signout",
        "language_path": "/language",
        "notification_routes": NOTIFICATIONS,
        "user_events_path": "/me/events",
    }
    options.update(overrides)
    return AccountFlow(**options)


def member_session() -> FakeSession:
    """A signed-in account that is not staff: a dashboard admits every active user."""
    return FakeSession(user_id=7, username="mia", is_active=True, is_staff=False)


def settings_with_sse(enabled: bool) -> Any:
    settings = runtime_settings()
    settings.web.sse = SSEConfig(enabled=enabled, redis_alias="SSE")
    return settings


class AccountFlowRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings_with_sse(False)}))
        self.enterContext(patch("oldman.web.auth.flows.render_template", side_effect=render_with_request_environment))
        self.app = RoutesApp()
        StatelessCSRFManager(cast(Any, self.app))

    def call(self, path: str, method: str, request: Any) -> Any:
        handler = cast(Any, self.app.route_handlers[(path, (method,))])
        return asyncio.run(handler(request))

    def test_routes_follow_the_flow_paths_and_the_stream_waits_for_sse(self) -> None:
        self.assertIsNone(make_flow().register_routes(cast(Any, self.app), template_prefix="account", name_prefix="site_"))
        self.assertEqual(
            {
                ("/me", ("GET",)): "site_user_session",
                ("/me/password-modal", ("GET",)): "site_user_session_password_modal",
                ("/me/password", ("POST",)): "site_user_session_password_submit",
                ("/language", ("POST",)): "site_language_preference",
                ("/user-notifications", ("GET",)): "site_user_notifications",
            },
            self.app.route_names,
        )

        with_sse = RoutesApp()
        with patch.dict(conf.__dict__, {"settings": settings_with_sse(True)}):
            self.assertEqual("/me/events", make_flow().register_routes(cast(Any, with_sse), template_prefix="account"))
        self.assertIn(("/me/events", ("GET",)), with_sse.routes)

    def test_a_signed_in_member_who_is_not_staff_gets_the_profile_page(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")

        body = self.call("/me", "GET", make_request(cast(Any, self.app), path="/me", session=member_session())).body.decode()

        self.assertEqual("session|mia|/me|/me/password-modal|/signout", body)

    def test_a_visitor_who_has_not_signed_in_is_sent_to_the_login_page(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        page = make_request(cast(Any, self.app), path="/me")
        api = make_request(cast(Any, self.app), path="/me/password-modal")
        api.headers = {"accept": "application/json"}

        redirected = self.call("/me", "GET", page)
        refused = self.call("/me/password-modal", "GET", api)

        self.assertEqual(302, redirected.status)
        self.assertEqual("/signin?next=%2Fme", redirected.headers["Location"])
        self.assertEqual(401, refused.status)
        self.assertEqual({"login_url": "/signin"}, json.loads(refused.body)["data"])

    def test_the_host_rule_refuses_a_signed_in_user_with_403(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account", allow=lambda request: False)
        request = make_request(cast(Any, self.app), path="/me", session=member_session())
        request.headers = {"accept": "application/json"}

        self.assertEqual(403, self.call("/me", "GET", request).status)

    def test_changing_the_own_password_sends_the_browser_to_the_flow_login_page(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        request = make_request(cast(Any, self.app), path="/me/password", session=member_session())
        request.method = "POST"
        request.headers = {"X-CSRFToken": self.app.ctx.csrf.generate_token(request), "Origin": "http://example.test"}
        with patch("oldman.web.auth.account.update_session_password", AsyncMock(return_value="changed")) as update:
            self.assertEqual("changed", self.call("/me/password", "POST", request))
        assert update.await_args is not None
        self.assertEqual("/signin", update.await_args.kwargs["login_url"])

    def test_a_visitor_saves_a_language_before_signing_in(self) -> None:
        """The login page has a language switcher, so the endpoint takes anonymous visitors."""
        make_flow().register_routes(cast(Any, self.app), template_prefix="account", allow=lambda request: False)
        request = make_request(cast(Any, self.app), path="/language")
        request.method = "POST"
        request.json = {"language": "en"}
        request.headers = {
            "X-CSRFToken": self.app.ctx.csrf.generate_token(request),
            "content-type": "application/json",
            "Origin": "http://example.test",
        }

        response = self.call("/language", "POST", request)

        self.assertEqual(200, response.status)
        self.assertEqual("en", json.loads(response.body)["data"]["language"])

    def test_the_notification_center_shows_the_signed_in_user_s_notifications(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        request = make_request(cast(Any, self.app), path="/user-notifications", session=member_session())
        with patch("oldman.web.messages.notifications.render_center_content", AsyncMock(return_value=Markup("<ol></ol>"))) as center:
            body = self.call("/user-notifications", "GET", request).body.decode()

        self.assertEqual("center|<ol></ol>", body)
        center.assert_awaited_once_with(request, user_id=7)


class AccountUrlsTest(unittest.TestCase):
    def test_the_addresses_come_from_the_settings(self) -> None:
        settings = settings_with_sse(False)
        settings.web.account = AccountConfig(
            login_url="/signin", profile_url="/me", password_reset_url="/signin/reset", login_redirect_url="/console", users_url="/people"
        )
        with patch.dict(conf.__dict__, {"settings": settings}):
            urls = account_urls(make_request(cast(Any, FakeApp()), path="/"))

        self.assertEqual(
            {
                "home": "/console",
                "login": "/signin",
                "logout": "/logout",
                "profile": "/me",
                "users": "/people",
                "password_reset": "/signin/reset",
                "user_events": None,
                "notifications": None,
            },
            urls,
        )

    def test_user_events_need_sse_and_notifications_need_the_site_to_install_them(self) -> None:
        app = FakeApp()
        with (
            patch("oldman.web.messages.notifications.installed_routes", return_value=NOTIFICATIONS),
            patch.dict(conf.__dict__, {"settings": settings_with_sse(True)}),
        ):
            urls = account_urls(make_request(cast(Any, app), path="/"))

        self.assertEqual("/user-events", urls["user_events"])
        self.assertEqual({"center": "/user-notifications", "topbar": "/user-notifications/topbar"}, urls["notifications"])


class DashboardAccountTemplatesTest(unittest.TestCase):
    def test_the_profile_page_sits_in_the_project_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "base.html").write_text("<main>{% block content %}{% endblock %}</main>", encoding="utf-8")
            environment = install_template_loaders(Environment(enable_async=True), tmp_dir)
            request = make_request(cast(Any, FakeApp()), path="/me", session=member_session())
            profile = SimpleNamespace(
                username="mia", display_name="Mia", login_ip="-", login_time="-", is_active=True, is_staff=False, is_superuser=False
            )
            with patch.dict(conf.__dict__, {"settings": runtime_settings()}):
                html = asyncio.run(
                    environment.get_template("oldman/dashboard/account/user_session.html").render_async(
                        request=request, session_profile=profile, session_path="/me", password_modal_path="/me/password-modal", logout_path="/signout"
                    )
                )

        self.assertTrue(html.startswith("<main>"), "the project's base wraps the page")
        self.assertIn('data-om-modal-url="/me/password-modal"', html)
        self.assertIn('href="/signout"', html)


if __name__ == "__main__":
    unittest.main()
