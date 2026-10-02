"""LoginFlow: the login page, its submit and sign-out a dashboard (or the Admin) installs."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from jinja2 import DictLoader, Environment
from markupsafe import Markup
from sanic.response import html as sanic_html

import oldman.conf as conf
from oldman.auth import AuthSettings
from oldman.web.auth import LoginFlow, LoginRateLimit
from oldman.web.security.csrf import StatelessCSRFManager
from oldman.web.template import install_template_loaders, template_globals
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    MemoryWindowCounter,
    make_post_request,
    make_request,
    render_with_request_environment,
    runtime_settings,
)

TEMPLATES = {
    "account/login.html": "login|{{ login_url }}|{{ next_url }}|{{ login_error }}|{{ password_reset_url }}|{{ login_form.username.name }}",
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


def make_flow(**overrides: Any) -> LoginFlow:
    auth_settings = AuthSettings()
    options: dict[str, Any] = {
        "login_path": "/signin",
        "logout_path": "/signout",
        "home_path": "/home",
        "auth_settings": auth_settings,
        "rate_limit": LoginRateLimit(auth_settings=auth_settings, counter=MemoryWindowCounter()),
    }
    options.update(overrides)
    return LoginFlow(**options)


def member(*, is_staff: bool = False) -> Any:
    """An active account as a login backend returns it."""
    return SimpleNamespace(id=7, username="mia", display_name="Mia", is_active=True, is_staff=is_staff, is_superuser=False)


class LoginFlowRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": runtime_settings()}))
        self.enterContext(patch("oldman.web.auth.login.render_template", side_effect=render_with_request_environment))
        self.app = RoutesApp()
        StatelessCSRFManager(cast(Any, self.app))

    def call(self, path: str, method: str, request: Any) -> Any:
        handler = cast(Any, self.app.route_handlers[(path, (method,))])
        return asyncio.run(handler(request))

    def submit(self, form: dict[str, str]) -> Any:
        return make_post_request(cast(Any, self.app), path="/signin", session=FakeSession(), accept="text/html", form=form)

    def test_routes_and_names_follow_the_flow_paths(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account", name_prefix="site_")

        self.assertEqual(
            {
                ("/signin", ("GET",)): "site_login",
                ("/signin", ("POST",)): "site_login_submit",
                ("/signout", ("GET",)): "site_logout",
            },
            self.app.route_names,
        )

    def test_exactly_one_renderer_must_be_given(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_flow().register_routes(cast(Any, self.app))

    def test_the_page_names_the_login_url_a_safe_next_and_the_reset_link_only_when_installed(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        request = make_request(cast(Any, self.app), path="/signin")
        request.args = {"next": "https://evil.example/", "error": "invalid_credentials"}

        body = self.call("/signin", "GET", request).body.decode()

        login_url, next_url, error, reset_url, field = body.split("|")[1:]
        self.assertEqual(("/signin", "/home", "None", "username"), (login_url, next_url, reset_url, field))
        self.assertEqual("Invalid username or password.", error)

        other = RoutesApp()
        StatelessCSRFManager(cast(Any, other))
        make_flow(password_reset_path="/signin/reset").register_routes(cast(Any, other), template_prefix="account")
        handler = cast(Any, other.route_handlers[("/signin", ("GET",))])
        self.assertTrue(asyncio.run(handler(make_request(cast(Any, other), path="/signin"))).body.decode().endswith("|/signin/reset|username"))

    def test_a_signed_in_browser_skips_the_page(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account", is_authenticated=lambda request: True)
        request = make_request(cast(Any, self.app), path="/signin")
        request.args = {"next": "/reports"}

        response = self.call("/signin", "GET", request)

        self.assertEqual(302, response.status)
        self.assertEqual("/reports", response.headers["Location"])

    def test_without_a_rule_every_active_account_signs_in(self) -> None:
        """A dashboard's default: no staff needed; being active is checked by authenticate_credentials."""
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        signed_in = sanic_html("signed in")
        with (
            patch("oldman.web.auth.login.authenticate_credentials", AsyncMock(return_value=member())),
            patch("oldman.web.auth.login.login_user", AsyncMock(return_value=signed_in)) as login_user,
        ):
            response = self.call("/signin", "POST", self.submit({"username": "mia", "password": "pw", "next": "/reports"}))

        self.assertIs(signed_in, response)
        assert login_user.await_args is not None
        self.assertEqual("/reports", login_user.await_args.kwargs["response"].headers["Location"])

    def test_an_account_the_site_rule_refuses_gets_the_wrong_password_answer(self) -> None:
        flow = make_flow(accept_user=lambda user: bool(user.is_staff))
        flow.register_routes(cast(Any, self.app), template_prefix="account")
        with (
            patch("oldman.web.auth.login.authenticate_credentials", AsyncMock(return_value=member(is_staff=False))),
            patch("oldman.web.auth.login.login_user", AsyncMock()) as login_user,
        ):
            response = self.call("/signin", "POST", self.submit({"username": "mia", "password": "pw", "next": "/reports"}))

        self.assertEqual(303, response.status)
        self.assertEqual("/signin?next=%2Freports&error=invalid_credentials", response.headers["Location"])
        login_user.assert_not_awaited()
        counter = cast(MemoryWindowCounter, cast(LoginRateLimit, flow.rate_limit).counter)
        self.assertIn(1, counter.windows.values(), "the refusal counts as a failed sign-in")

    def test_sign_out_returns_to_the_login_page(self) -> None:
        make_flow().register_routes(cast(Any, self.app), template_prefix="account")
        with patch("oldman.web.auth.login.logout_user", AsyncMock(return_value="out")) as logout_user:
            self.assertEqual("out", self.call("/signout", "GET", make_request(cast(Any, self.app), path="/signout")))
        assert logout_user.await_args is not None
        self.assertEqual("/signin", logout_user.await_args.args[1])


class AuthPageTemplatesTest(unittest.TestCase):
    """The dashboard's login page on the shared standalone auth base."""

    def render(self, **context: Any) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            environment = install_template_loaders(Environment(enable_async=True), tmp_dir)
            template_globals(environment).update(
                app_main_bundle="app:main",
                bundle_asset_base_url=lambda name: f"/static/{name}/",
                bundle_entry=lambda name, include_dev_client=False: Markup(f'<script type="module" src="/static/{name}/main.js"></script>'),
            )
            request = make_request(cast(Any, FakeApp()), path="/signin")
            request.ctx.csrf_token = "token-1"
            form = SimpleNamespace(render_field=lambda name: Markup(f'<input name="{name}">'))
            template = environment.get_template("oldman/dashboard/account/login.html")
            return asyncio.run(
                template.render_async(request=request, login_form=form, login_url="/signin", next_url="/home", login_error="", **context)
            )

    def test_the_page_stands_alone_with_what_both_hosts_had_in_its_head(self) -> None:
        with patch.dict(conf.__dict__, {"settings": runtime_settings()}):
            html = self.render(password_reset_url=None)

        for expected in (
            '<meta name="turbo-visit-control" content="reload">',
            '<meta name="turbo-cache-control" content="no-cache">',
            '<meta name="csrf-token" content="',
            '<meta name="oldman-asset-base" content="/static/app:main/">',
            'data-om-critical="theme"',
            'data-om-page="login"',
            '<form action="/signin" method="post"',
            'name="csrfmiddlewaretoken" value="token-1"',
            'href="/signin"',
        ):
            self.assertIn(expected, html)
        self.assertNotIn("oldman-sidebar", html)
        self.assertNotIn("Forgot password?", html)

    def test_the_reset_link_appears_when_the_site_installs_the_reset_flow(self) -> None:
        with patch.dict(conf.__dict__, {"settings": runtime_settings()}):
            html = self.render(password_reset_url="/signin/reset")

        self.assertIn('href="/signin/reset"', html)

    def test_a_project_can_restyle_the_dashboard_auth_pages_alone(self) -> None:
        """Overriding the dashboard wrapper leaves the shared base, and so the Admin's pages, untouched."""
        self.assertTrue(Path("oldman/web/templates/oldman/dashboard/account/auth_base.html").is_file())
        self.assertTrue(Path("oldman/apps/admin/templates/admin/auth_base.html").is_file())
        for wrapper in ("oldman/web/templates/oldman/dashboard/account/auth_base.html", "oldman/apps/admin/templates/admin/auth_base.html"):
            self.assertIn('{% extends "oldman/auth/base.html" %}', Path(wrapper).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
