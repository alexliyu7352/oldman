"""Oldman Web CSRF tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import oldman.conf as conf
from oldman.conf.schemas import CSRFConfig, WebConfig, WebSecurityConfig
from oldman.web.security import WebSecurityPurpose, derive_web_security_key
from oldman.web.security.csrf import StatelessCSRFManager, add_csrf_token, csrf_protect
from oldman.web.session import SessionData

ROOT = Path(__file__).resolve().parents[1]


class FakeApp:
    """Small app object for CSRF tests."""

    def __init__(self) -> None:
        self.config = {"SECRET_KEY": "secret"}
        self.ctx = SimpleNamespace()
        self.listeners: list[tuple[object, str]] = []

    def register_listener(self, listener, event: str) -> None:
        """Record registered listener."""
        self.listeners.append((listener, event))


class OldmanWebCsrfDependencyTest(unittest.TestCase):
    """Verify CSRF manager is self-contained under oldman.web."""

    def test_csrf_uses_global_security_without_app_settings(self) -> None:
        """The global root key and CSRF options govern tokens without a ctx alias."""
        app = FakeApp()
        root_secret = "oldman-global-csrf-configuration-test-secret"
        settings = SimpleNamespace(
            web=WebConfig(
                security=WebSecurityConfig(
                    secret_key=root_secret,
                    csrf=CSRFConfig(ttl=120, check_referer=False, check_url=True),
                ),
            ),
        )
        with patch.dict(conf.__dict__, {"settings": settings}):
            manager = StatelessCSRFManager(cast(Any, app))

        self.assertFalse(hasattr(app.ctx, "settings"))
        self.assertEqual(120, manager.ttl)
        self.assertFalse(manager.check_referer)
        self.assertTrue(manager.check_url)
        request = SimpleNamespace(
            ctx=SimpleNamespace(session={"sid": "session-1"}),
            path="/submit", headers={}, host="example.test",
        )
        token = manager.generate_token(cast(Any, request))
        verifier = StatelessCSRFManager(
            cast(Any, FakeApp()),
            secret_key=derive_web_security_key(root_secret, WebSecurityPurpose.CSRF),
            check_referer=False,
        )
        self.assertEqual((True, "Valid"), verifier.validate_token(cast(Any, request), token))
        request.path = "/other"
        self.assertEqual((False, "Token URL mismatch"), manager.validate_token(cast(Any, request), token))

    def test_csrf_manager_generates_and_validates_token_without_legacy_package(self) -> None:
        """CSRF token crypto must work without importing the legacy package."""
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)
        request = SimpleNamespace(
            app=app,
            ctx=SimpleNamespace(session={"sid": "session-1"}),
            path="/submit",
            headers={},
            host="example.test",
            form={},
            json=None,
        )

        token = manager.generate_token(cast(Any, request))

        self.assertTrue(token)
        self.assertEqual((True, "Valid"), manager.validate_token(cast(Any, request), token))
        self.assertIs(app.ctx.csrf, manager)
        self.assertIn((manager.before_server_start, "before_server_start"), app.listeners)

    def test_csrf_decorators_work_for_function_routes(self) -> None:
        """Decorators should locate the request argument directly."""
        app = FakeApp()
        StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)
        request = SimpleNamespace(app=app, ctx=SimpleNamespace(session={}), path="/submit", headers={}, host="example.test", form={}, json=None)

        @add_csrf_token()
        async def show_form(request):
            return request.ctx.csrf_token

        import asyncio

        token = asyncio.run(cast(Any, show_form)(request))
        request.form = {"csrfmiddlewaretoken": token}

        @csrf_protect()
        async def submit(request):
            return "ok"

        self.assertEqual(asyncio.run(cast(Any, submit)(request)), "ok")

    def test_csrf_token_encodes_integer_session_identity_at_its_wire_boundary(self) -> None:
        """Integer zero remains authenticated while the encrypted payload stores text."""
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)
        request = SimpleNamespace(
            app=app,
            ctx=SimpleNamespace(session=SessionData(user_id=0, is_active=True)),
            path="/submit",
            headers={},
            host="example.test",
            form={},
            json=None,
        )

        token = manager.generate_token(cast(Any, request))

        self.assertEqual("0", manager._get_session_id(cast(Any, request)))
        self.assertEqual((True, "Valid"), manager.validate_token(cast(Any, request), token))

    def test_form_token_lookup_does_not_force_json_parsing(self) -> None:
        """缺少 token 的表单请求必须进入 403 分支，不能被 request.json 提前变成 400。"""
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)

        class FormRequest:
            form: dict[str, str] = {}
            headers = {"content-type": "application/x-www-form-urlencoded"}

            @property
            def json(self) -> object:
                raise AssertionError("form token lookup must not parse JSON")

        self.assertIsNone(manager.get_token_from_request(cast(Any, FormRequest())))

    def test_token_lookup_handles_none_form_json_suffix_and_precedence(self) -> None:
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)

        form_first = SimpleNamespace(
            form={"csrfmiddlewaretoken": "form-token"},
            headers={"X-CSRFToken": "header-token", "content-type": "application/problem+json"},
            json={"csrfmiddlewaretoken": "json-token"},
        )
        header_second = SimpleNamespace(
            form=None,
            headers={"X-CSRF-Token": "header-token", "content-type": "application/problem+json"},
            json={"csrfmiddlewaretoken": "json-token"},
        )
        json_third = SimpleNamespace(
            form=None,
            headers={"content-type": "application/problem+json; charset=utf-8"},
            json={"csrfmiddlewaretoken": "json-token"},
        )
        non_mapping_json = SimpleNamespace(
            form=None,
            headers={"content-type": "application/json"},
            json=["not", "a", "mapping"],
        )

        self.assertEqual("form-token", manager.get_token_from_request(cast(Any, form_first)))
        self.assertEqual("header-token", manager.get_token_from_request(cast(Any, header_second)))
        self.assertEqual("json-token", manager.get_token_from_request(cast(Any, json_third)))
        self.assertIsNone(manager.get_token_from_request(cast(Any, non_mapping_json)))

    def test_token_operations_fail_fast_before_manager_initialization(self) -> None:
        manager = StatelessCSRFManager(check_referer=False)
        request = SimpleNamespace(ctx=SimpleNamespace(session={}), path="/submit", headers={}, host="example.test")

        with self.assertRaisesRegex(RuntimeError, r"init_app\(\)"):
            manager.generate_token(cast(Any, request))
        with self.assertRaisesRegex(RuntimeError, r"init_app\(\)"):
            manager.validate_token(cast(Any, request), "malformed")

    def test_initialized_manager_still_classifies_malformed_tokens_as_invalid(self) -> None:
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", check_referer=False)
        request = SimpleNamespace(ctx=SimpleNamespace(session={}), path="/submit", headers={}, host="example.test")

        self.assertEqual((False, "Invalid token format"), manager.validate_token(cast(Any, request), "malformed"))

    def test_csrf_source_does_not_import_legacy_package(self) -> None:
        """CSRF implementation must not depend on the legacy package."""
        source = (
            ROOT / "oldman" / "web" / "security" / "csrf" / "__init__.py"
        ).read_text(encoding="utf-8")
        legacy_prefix = "ac" + "_base"

        self.assertNotIn(legacy_prefix, source)


if __name__ == "__main__":
    unittest.main()
