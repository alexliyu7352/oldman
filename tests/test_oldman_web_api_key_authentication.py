"""API keys: callers that are not users, recognized by a named key, admitted by authenticated_by."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError
from sanic import Sanic
from sanic.response import json

import oldman.conf as conf
from oldman.conf.schemas import AuthConfig, DefaultSettings
from oldman.web.auth import authenticated_by
from oldman.web.authentication import (
    APIKeyAuthentication,
    Authentication,
    RequestUser,
    exempt_from_csrf,
    install_authentication,
    resolve_authenticators,
)
from oldman.web.authentication import api_key as api_key_module
from oldman.web.session import SessionData

MONITOR_SECRET = "monitor-key-0123456789abcdef"
WORKER_SECRET = "worker-key-0123456789abcdef"
STAFF = RequestUser(id=7, username="ops", is_staff=True)


def api_key_settings() -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth = AuthConfig.model_validate(
        {
            "api_keys": {
                "monitor": {"secret": MONITOR_SECRET, "query_param": "admin_secrets"},
                "worker": {"secret": WORKER_SECRET, "authorization": True},
            }
        }
    )
    return settings


class UserHeaderAuthentication:
    """A user method standing in for a session or token: recognized by one header."""

    name = "user_header"

    async def authenticate(self, request: Any) -> Authentication | None:
        if request.headers.get("x-test-user") is None:
            return None
        return Authentication(method=self.name, user=STAFF, ambient=False)


class APIKeyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": api_key_settings()}))

    def serve(self, *routes: tuple[str, Any]) -> Sanic:
        """A Sanic app running the pipeline (a user method, then API keys) and the given guarded routes."""
        app = Sanic(f"api_key_{self._testMethodName}")
        self.addCleanup(lambda: Sanic.unregister_app(app))
        install_authentication(app, (UserHeaderAuthentication(), APIKeyAuthentication()))
        for path, guard in routes:

            async def endpoint(request: Any) -> Any:
                auth = request.ctx.auth
                return json({"caller": auth.caller, "user": request.ctx.user.id})

            app.add_route(guard(endpoint), path, name=path.strip("/").replace("/", "_") or "root")
        return app


class APIKeyAuthenticationTest(APIKeyTestCase):
    def test_a_key_in_the_header_names_its_caller(self) -> None:
        app = self.serve(("/api", authenticated_by("api_key")))

        _, response = app.test_client.get("/api", headers={"X-API-Key": MONITOR_SECRET})

        self.assertEqual(200, response.status)
        self.assertEqual({"caller": "monitor", "user": None}, response.json)

    def test_a_wrong_or_missing_key_is_not_authenticated(self) -> None:
        app = self.serve(("/api", authenticated_by("api_key")))

        _, wrong = app.test_client.get("/api", headers={"X-API-Key": "not-a-key"})
        _, missing = app.test_client.get("/api")

        self.assertEqual((401, 401), (wrong.status, missing.status))
        self.assertEqual(1401, wrong.json["error_code"])

    def test_the_query_parameter_and_bearer_header_count_only_for_keys_that_opt_in(self) -> None:
        app = self.serve(("/api", authenticated_by("api_key")))

        _, monitor_query = app.test_client.get(f"/api?admin_secrets={MONITOR_SECRET}")
        _, worker_query = app.test_client.get(f"/api?admin_secrets={WORKER_SECRET}")
        _, worker_bearer = app.test_client.get("/api", headers={"Authorization": f"Bearer {WORKER_SECRET}"})
        _, monitor_bearer = app.test_client.get("/api", headers={"Authorization": f"Bearer {MONITOR_SECRET}"})

        self.assertEqual((200, "monitor"), (monitor_query.status, monitor_query.json["caller"]))
        self.assertEqual(401, worker_query.status)
        self.assertEqual((200, "worker"), (worker_bearer.status, worker_bearer.json["caller"]))
        self.assertEqual(401, monitor_bearer.status)

    def test_a_non_ascii_key_is_refused_rather_than_raising(self) -> None:
        """Constant-time comparison of non-ASCII text used to raise TypeError and answer 500."""
        app = self.serve(("/api", authenticated_by("api_key")))

        _, response = app.test_client.get("/api?admin_secrets=%E5%AF%86%E9%92%A5")

        self.assertEqual(401, response.status)

    def test_callers_restrict_keys_but_not_users(self) -> None:
        app = self.serve(("/monitor", authenticated_by("user_header", "api_key", callers={"monitor"})))

        _, monitor = app.test_client.get("/monitor", headers={"X-API-Key": MONITOR_SECRET})
        _, worker = app.test_client.get("/monitor", headers={"X-API-Key": WORKER_SECRET})
        _, user = app.test_client.get("/monitor", headers={"x-test-user": "1"})

        self.assertEqual(200, monitor.status)
        self.assertEqual(403, worker.status)
        self.assertEqual((200, 7), (user.status, user.json["user"]))

    def test_a_request_authenticated_some_other_way_is_forbidden(self) -> None:
        app = self.serve(("/keys-only", authenticated_by("api_key")))

        _, response = app.test_client.get("/keys-only", headers={"x-test-user": "1"})

        self.assertEqual(403, response.status)
        self.assertEqual("application/json", response.content_type)

    def test_listing_session_sends_an_unauthenticated_browser_to_the_login_page(self) -> None:
        app = self.serve(("/page", authenticated_by("session", "api_key")))

        _, browser = app.test_client.get("/page", allow_redirects=False)
        _, script = app.test_client.get("/page", headers={"Accept": "application/json"})

        self.assertEqual(302, browser.status)
        self.assertEqual(401, script.status)

    def test_a_key_is_not_ambient_so_csrf_does_not_apply(self) -> None:
        request = SimpleNamespace(ctx=SimpleNamespace(session=SessionData(), auth=Authentication(method="api_key", caller="monitor", ambient=False)))

        self.assertTrue(exempt_from_csrf(request))

    def test_keys_are_never_compared_with_an_equality_operator(self) -> None:
        """`==` stops at the first differing byte; a key's prefix must not be readable from the timing."""
        source = Path(api_key_module.__file__).read_text(encoding="utf-8")
        equality = [
            ast.unparse(node)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops) and "secret" in ast.unparse(node)
        ]

        self.assertEqual([], equality)


class APIKeyConfigurationTest(unittest.TestCase):
    def test_listing_api_key_without_keys_is_refused_at_startup(self) -> None:
        with patch.dict(conf.__dict__, {"settings": DefaultSettings()}), self.assertRaises(ValueError):
            resolve_authenticators(["api_key"], session_enabled=False)

    def test_keys_need_a_secret_and_names_may_not_share_one(self) -> None:
        with self.assertRaises(ValidationError):
            AuthConfig.model_validate({"api_keys": {"blank": {"secret": "  "}}})
        with self.assertRaises(ValidationError):
            AuthConfig.model_validate({"api_keys": {"a": {"secret": MONITOR_SECRET}, "b": {"secret": MONITOR_SECRET}}})

    def test_authenticated_by_needs_a_method(self) -> None:
        async def endpoint(request: Any) -> None:
            del request

        with self.assertRaises(ValueError):
            authenticated_by()(endpoint)


if __name__ == "__main__":
    unittest.main()
