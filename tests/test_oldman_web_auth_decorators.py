"""Strongly typed Web authentication adapter tests."""

from __future__ import annotations

import ast
import asyncio
import json
import unittest
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from oldman.auth.models import User
from oldman.web.auth import (
    api_authorized,
    api_key_authorized,
    api_login_required,
    decorators,
    login_required,
    session_data_for_user,
    staff_required,
    superuser_required,
)
from oldman.web.session import SessionData


class OldmanWebAuthDecoratorsTest(unittest.TestCase):
    """Verify that Web authorization consumes the frozen SessionData contract."""

    def test_user_mapping_builds_only_the_base_session_snapshot(self) -> None:
        """A mapped User should become the configured typed session model."""
        user = User(
            id=42,
            username="alex",
            display_name=None,
            password_hash="unused",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        session = session_data_for_user(
            SessionData,
            user,
            expiry=600,
            login_ip="127.0.0.1",
            login_time=1_234_567_890,
        )

        self.assertEqual(42, session.user_id)
        self.assertEqual("alex", session.username)
        self.assertEqual("alex", session.display_name)
        self.assertEqual("127.0.0.1", session.login_ip)
        self.assertEqual(1_234_567_890, session.login_time)
        self.assertTrue(session.is_active)
        self.assertTrue(session.is_staff)
        self.assertFalse(session.is_superuser)
        self.assertEqual(600, session.expiry)

    def test_login_decorators_return_the_shared_html_and_json_protocols(self) -> None:
        """Anonymous HTML and API requests should retain the shared 302/401 contract."""

        @login_required(login_url="/account/sign-in")
        async def html_endpoint(request: Any) -> Any:
            del request
            return "unreachable"

        @api_login_required()
        async def api_endpoint(request: Any) -> Any:
            del request
            return "unreachable"

        html_response = run_async(html_endpoint(make_request(path="/projects", query_string="page=2")))
        api_response = run_async(api_endpoint(make_request()))
        api_payload = json.loads(api_response.body)

        self.assertEqual(302, html_response.status)
        self.assertEqual(
            "/account/sign-in?next=%2Fprojects%3Fpage%3D2",
            html_response.headers["Location"],
        )
        self.assertEqual(401, api_response.status)
        self.assertEqual({"login_url": "/login"}, api_payload["data"])
        self.assertEqual([], api_payload["actions"])

    def test_login_required_injects_the_integer_session_identity(self) -> None:
        """The optional keyword should expose SessionData.user_id unchanged."""

        @login_required(user_keyword="current_user_id")
        async def endpoint(request: Any, *, current_user_id: int = 0) -> int:
            del request
            return current_user_id

        result = run_async(endpoint(make_request(session=authenticated_session())))

        self.assertEqual(42, result)

    def test_staff_and_superuser_policies_are_distinct(self) -> None:
        """Staff and superuser checks should deny only after authentication succeeds."""

        @staff_required(response_mode="json")
        async def staff_endpoint(request: Any) -> Any:
            del request
            return "staff"

        @superuser_required(response_mode="json")
        async def superuser_endpoint(request: Any) -> Any:
            del request
            return "superuser"

        ordinary_response = run_async(staff_endpoint(make_request(session=authenticated_session())))
        staff_result = run_async(staff_endpoint(make_request(session=authenticated_session(is_staff=True))))
        staff_only_response = run_async(superuser_endpoint(make_request(session=authenticated_session(is_staff=True))))
        superuser_result = run_async(superuser_endpoint(make_request(session=authenticated_session(is_staff=True, is_superuser=True))))

        self.assertEqual(403, ordinary_response.status)
        self.assertEqual("staff", staff_result)
        self.assertEqual(403, staff_only_response.status)
        self.assertEqual("superuser", superuser_result)

    def test_decorators_adapt_bound_methods_without_dict_session_fallbacks(self) -> None:
        """The source method-adaptor behavior should remain available to Web views."""

        class DemoView:
            @staff_required()
            async def endpoint(self, request: Any) -> str:
                del request
                return "method-ok"

        result = run_async(DemoView().endpoint(make_request(session=authenticated_session(is_staff=True))))

        self.assertEqual("method-ok", result)

    def test_api_secrets_are_explicit_and_preserve_query_and_token_sources(self) -> None:
        """Shared-secret adapters must not read an unrelated Admin setting."""

        @api_authorized("query-secret")
        async def query_endpoint(request: Any) -> Any:
            del request
            return "query-ok"

        @api_key_authorized("token-secret")
        async def token_endpoint(request: Any) -> Any:
            del request
            return "token-ok"

        rejected_query = run_async(query_endpoint(make_request(args={"admin_secrets": "wrong"})))
        accepted_query = run_async(query_endpoint(make_request(args={"admin_secrets": "query-secret"})))
        loopback_query = run_async(query_endpoint(make_request(ip="127.0.0.1", client_ip="127.0.0.1")))
        rejected_token = run_async(token_endpoint(make_request(token="wrong")))
        accepted_token = run_async(token_endpoint(make_request(token="token-secret")))

        self.assertEqual(403, rejected_query.status)
        self.assertEqual("query-ok", accepted_query)
        self.assertEqual("query-ok", loopback_query)
        self.assertEqual(403, rejected_token.status)
        self.assertEqual("token-ok", accepted_token)

        with self.assertRaises(TypeError):

            @api_authorized()  # pyright: ignore[reportCallIssue] -- intentional contract rejection
            async def missing_secret(request: Any) -> None:
                del request

    def test_a_missing_secret_is_denied_rather_than_raising(self) -> None:
        """No query parameter and no Authorization header must reach the same 403, not a TypeError."""

        @api_authorized("query-secret")
        async def query_endpoint(request: Any) -> Any:
            del request
            return "query-ok"

        @api_key_authorized("token-secret")
        async def token_endpoint(request: Any) -> Any:
            del request
            return "token-ok"

        missing_query = run_async(query_endpoint(make_request()))
        missing_token = run_async(token_endpoint(make_request()))

        self.assertEqual(403, missing_query.status)
        self.assertEqual(403, missing_token.status)

    def test_shared_secrets_are_never_compared_with_an_equality_operator(self) -> None:
        """`==` stops at the first differing byte; the secret's prefix must not be readable from the timing."""
        source = Path(decorators.__file__).read_text(encoding="utf-8")
        equality_comparisons = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops) and "secret" in ast.unparse(node)
        ]

        self.assertEqual([], [ast.unparse(node) for node in equality_comparisons])


class Args(dict[str, str]):
    """Small Sanic request.args-compatible mapping."""

    def getlist(self, key: str) -> list[str]:
        """Return all values for one test query parameter."""
        value = self.get(key)
        return [] if value is None else [value]


def authenticated_session(
    *,
    is_staff: bool = False,
    is_superuser: bool = False,
) -> SessionData:
    """Build a real authenticated SessionData for Web adapter tests."""
    return SessionData(
        user_id=42,
        username="alex",
        is_active=True,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )


def run_async[T](awaitable: Awaitable[T]) -> T:
    """Run an Awaitable returned through the decorator protocol."""

    async def resolve() -> T:
        return await awaitable

    return asyncio.run(resolve())


def make_request(
    *,
    session: SessionData | None = None,
    args: dict[str, str] | None = None,
    path: str = "/demo",
    query_string: str = "",
    ip: str = "203.0.113.10",
    client_ip: str = "203.0.113.10",
    token: str | None = None,
) -> Any:
    """Build the request surface used by the authentication decorators."""
    return SimpleNamespace(
        args=Args(args or {}),
        client_ip=client_ip,
        ctx=SimpleNamespace(session=session),
        headers={},
        ip=ip,
        path=path,
        query_string=query_string,
        token=token,
    )


if __name__ == "__main__":
    unittest.main()
