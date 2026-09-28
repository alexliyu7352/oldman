"""HTTP Basic: fixed accounts for tools and machines, a browser prompt where Basic alone is accepted."""

from __future__ import annotations

import ast
import base64
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sanic import Sanic
from sanic.response import json

import oldman.conf as conf
from oldman.conf.schemas import AuthConfig, DefaultSettings
from oldman.web.auth import authenticated_by
from oldman.web.authentication import (
    Authentication,
    HTTPBasicAuthentication,
    exempt_from_csrf,
    install_authentication,
    resolve_authenticators,
)
from oldman.web.authentication import http_basic as http_basic_module
from oldman.web.request import basic_credentials
from oldman.web.session import SessionData


def basic(username: str, password: str, scheme: str = "Basic") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"{scheme} {token}"}


def basic_settings() -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth = AuthConfig.model_validate({"http_basic": {"realm": "Internal", "accounts": {"admin": "s3cret:with-colon", "ops": "密码"}}})
    return settings


class BasicCredentialsTest(unittest.TestCase):
    def test_the_header_is_read_as_rfc_7617_describes(self) -> None:
        cases = {
            "Basic YWRtaW46cHc=": ("admin", "pw"),
            "basic YWRtaW46cHc=": ("admin", "pw"),
            "Basic YWRtaW46YTpi": ("admin", "a:b"),
            "Basic YWRtaW4=": None,  # no colon
            "Basic not*base64": None,
            "Basic /w==": None,  # not UTF-8
            "Bearer YWRtaW46cHc=": None,
            "Basic ": None,
            "": None,
        }
        for header, expected in cases.items():
            with self.subTest(header=header):
                self.assertEqual(expected, basic_credentials(SimpleNamespace(headers={"authorization": header})))


class HTTPBasicAuthenticationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": basic_settings()}))

    def serve(self, guard: Any) -> Sanic:
        app = Sanic(f"http_basic_{self._testMethodName}")
        self.addCleanup(lambda: Sanic.unregister_app(app))
        install_authentication(app, (HTTPBasicAuthentication(),))

        async def endpoint(request: Any) -> Any:
            return json({"caller": request.ctx.auth.caller, "user": request.ctx.user.id})

        app.add_route(guard(endpoint), "/internal", name="internal")
        return app

    def test_a_configured_account_is_the_caller(self) -> None:
        app = self.serve(authenticated_by("http_basic"))

        _, admin = app.test_client.get("/internal", headers=basic("admin", "s3cret:with-colon"))
        _, ops = app.test_client.get("/internal", headers=basic("ops", "密码"))

        self.assertEqual((200, {"caller": "admin", "user": None}), (admin.status, admin.json))
        self.assertEqual((200, "ops"), (ops.status, ops.json["caller"]))

    def test_a_refused_request_is_challenged_for_basic_credentials(self) -> None:
        app = self.serve(authenticated_by("http_basic"))

        _, wrong_password = app.test_client.get("/internal", headers=basic("admin", "nope"))
        _, unknown_user = app.test_client.get("/internal", headers=basic("root", "s3cret:with-colon"))
        _, missing = app.test_client.get("/internal")

        for response in (wrong_password, unknown_user, missing):
            with self.subTest(status=response.status):
                self.assertEqual(401, response.status)
                self.assertEqual('Basic realm="Internal", charset="UTF-8"', response.headers.get("www-authenticate"))

    def test_a_page_that_also_takes_the_session_sends_browsers_to_the_login_page_instead(self) -> None:
        app = self.serve(authenticated_by("session", "http_basic"))

        _, response = app.test_client.get("/internal", allow_redirects=False)

        self.assertEqual(302, response.status)
        self.assertIsNone(response.headers.get("www-authenticate"))

    def test_basic_credentials_are_ambient_so_csrf_still_applies(self) -> None:
        request = SimpleNamespace(ctx=SimpleNamespace(session=SessionData(), auth=Authentication(method="http_basic", caller="admin", ambient=True)))

        self.assertFalse(exempt_from_csrf(request))

    def test_passwords_are_never_compared_with_an_equality_operator(self) -> None:
        source = Path(http_basic_module.__file__).read_text(encoding="utf-8")
        equality = [
            ast.unparse(node)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Compare)
            and any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops)
            and any(word in ast.unparse(node) for word in ("password", "expected", "username", "account"))
        ]

        self.assertEqual([], equality)


class HTTPBasicConfigurationTest(unittest.TestCase):
    def test_listing_http_basic_without_accounts_is_refused_at_startup(self) -> None:
        with patch.dict(conf.__dict__, {"settings": DefaultSettings()}), self.assertRaises(ValueError):
            resolve_authenticators(["http_basic"], session_enabled=False)


if __name__ == "__main__":
    unittest.main()
