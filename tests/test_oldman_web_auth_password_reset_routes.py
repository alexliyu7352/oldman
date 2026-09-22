"""PasswordResetFlow.register_routes: the six views a login site gets from the flow."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import ANY, patch

from jinja2 import DictLoader, Environment

import oldman.conf as conf
from oldman.auth import AuthSettings
from oldman.web.auth import PasswordResetFlow
from oldman.web.security.csrf import StatelessCSRFManager
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    make_post_request,
    make_request,
    render_with_request_environment,
    runtime_settings,
)

TEMPLATES = {
    "reset/request.html": "request|{{ login_url }}|{{ request_url }}|{{ expiry_hours }}|{{ action }}|{{ form.email.name }}|{{ rate_limited }}",
    "reset/sent.html": "sent|{{ login_url }}",
    "reset/confirm.html": "confirm|{{ username }}|{{ action }}",
    "reset/invalid.html": "invalid|{{ request_url }}",
    "reset/done.html": "done|{{ login_url }}",
}


class RoutesApp(FakeApp):
    """FakeApp that also keeps the route names."""

    def __init__(self) -> None:
        super().__init__()
        self.route_names: dict[tuple[str, tuple[str, ...]], str] = {}
        self.ext.environment = Environment(loader=DictLoader(TEMPLATES), enable_async=True)

    def add_route(self, handler, path: str, *, methods: list[str], name: str) -> None:
        super().add_route(handler, path, methods=methods, name=name)
        self.route_names[(path, tuple(methods))] = name


class AlwaysLimited:
    async def is_rate_limited(self, subject: int | str, path: str, limit: int, period: int) -> bool:
        return str(subject).startswith("ip:")


def make_flow(**overrides: Any) -> PasswordResetFlow:
    options: dict[str, Any] = {
        "request_path": "/account/reset",
        "sent_path": "/account/reset/sent",
        "done_path": "/account/reset/done",
        "login_path": "/account/login",
        "home_path": "/",
        "confirm_path": lambda uidb64, token: f"/account/reset/{uidb64}/{token}",
        "auth_settings": AuthSettings(),
        "rate_limiter": AlwaysLimited(),
    }
    options.update(overrides)
    return PasswordResetFlow(**options)


class PasswordResetRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": runtime_settings()}))
        self.enterContext(patch("oldman.web.auth.password_reset.render_template", side_effect=render_with_request_environment))
        self.app = RoutesApp()
        StatelessCSRFManager(cast(Any, self.app))

    def call(self, path: str, method: str, request: Any, **kwargs: Any):
        handler = cast(Any, self.app.route_handlers[(path, (method,))])
        return asyncio.run(handler(request, **kwargs))

    def get(self, path: str, *, session: FakeSession | None = None) -> Any:
        return make_request(self.app, path=path, session=session)

    def test_routes_and_names_follow_the_flow_paths(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="reset", name_prefix="account_")

        self.assertEqual(
            {
                ("/account/reset", ("GET",)): "account_password_reset",
                ("/account/reset", ("POST",)): "account_password_reset_submit",
                ("/account/reset/sent", ("GET",)): "account_password_reset_sent",
                ("/account/reset/<uidb64:str>/<token:str>", ("GET",)): "account_password_reset_confirm",
                ("/account/reset/<uidb64:str>/<token:str>", ("POST",)): "account_password_reset_confirm_submit",
                ("/account/reset/done", ("GET",)): "account_password_reset_done",
            },
            self.app.route_names,
        )

    def test_exactly_one_renderer_must_be_given(self) -> None:
        flow = make_flow()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            flow.register_routes(cast(Any, self.app))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            flow.register_routes(cast(Any, self.app), template_prefix="reset", render=cast(Any, object()))

    def test_template_prefix_renders_every_page_with_the_shared_context_and_headers(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="reset/")

        request_page = self.call("/account/reset", "GET", self.get("/account/reset"))
        self.assertEqual(200, request_page.status)
        self.assertEqual("no-store", request_page.headers["Cache-Control"])
        self.assertEqual("no-referrer", request_page.headers["Referrer-Policy"])
        self.assertNotIn("Retry-After", request_page.headers)
        self.assertEqual("request|/account/login|/account/reset|24|/account/reset|email|", request_page.body.decode())

        self.assertEqual("sent|/account/login", self.call("/account/reset/sent", "GET", self.get("/account/reset/sent")).body.decode())
        self.assertEqual("done|/account/login", self.call("/account/reset/done", "GET", self.get("/account/reset/done")).body.decode())
        invalid = self.call("/account/reset/<uidb64:str>/<token:str>", "GET", self.get("/account/reset/x/y"), uidb64="x", token="y")
        self.assertEqual("no-store", invalid.headers["Cache-Control"])
        self.assertEqual("invalid|/account/reset", invalid.body.decode())

    def test_a_signed_in_browser_is_sent_home_only_when_home_path_is_set(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="reset")
        signed_in = FakeSession(user_id=5, is_active=True)

        response = self.call("/account/reset", "GET", self.get("/account/reset", session=signed_in))
        self.assertEqual(302, response.status)
        self.assertEqual("/", response.headers["Location"])

        other = RoutesApp()
        StatelessCSRFManager(cast(Any, other))
        make_flow(home_path=None).register_routes(cast(Any, other), template_prefix="reset")
        page = asyncio.run(
            cast(Any, other.route_handlers[("/account/reset", ("GET",))])(make_request(other, path="/account/reset", session=signed_in))
        )
        self.assertEqual(200, page.status)

    def test_a_custom_renderer_and_authentication_check_replace_the_defaults(self) -> None:
        seen: list[tuple[str, dict[str, Any]]] = []

        async def render(request: Any, page: str, /, **context: Any):
            del request
            seen.append((page, context))
            return await render_with_request_environment("reset/sent.html", context={"request": self.get("/"), **context})

        make_flow().register_routes(cast(Any, self.app), render=render, is_authenticated=lambda request: request.path.endswith("/reset"))

        home = self.call("/account/reset", "GET", self.get("/account/reset"))
        self.assertEqual(302, home.status)
        sent = self.call("/account/reset/sent", "GET", self.get("/account/reset/sent"))
        self.assertEqual("no-store", sent.headers["Cache-Control"])
        self.assertEqual(
            [("sent", {"csrf_token": ANY, "login_url": "/account/login", "request_url": "/account/reset", "expiry_hours": 24})],
            seen,
        )

    def test_an_ip_limited_request_answers_429_with_retry_after_and_the_form(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="reset")
        request = make_post_request(
            self.app, path="/account/reset", session=FakeSession(), accept="text/html", form={"email": "someone@example.test"}
        )
        request.ip = "203.0.113.9"
        request.client_ip = None

        response = self.call("/account/reset", "POST", request)

        self.assertEqual(429, response.status)
        self.assertEqual(str(AuthSettings().password_reset.ip_window), response.headers["Retry-After"])
        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.assertTrue(response.body.decode().endswith("|/account/reset|email|True"))


if __name__ == "__main__":
    unittest.main()
