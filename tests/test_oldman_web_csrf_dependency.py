"""Oldman Web CSRF tests."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sanic import Sanic
from sanic.response import text

import oldman.conf as conf
from oldman.conf.schemas import CSRFConfig, DefaultSettings, WebConfig, WebSecurityConfig
from oldman.providers.redis import RedisClientRegistry
from oldman.web.auth import login_required
from oldman.web.security import WebSecurityPurpose, derive_web_security_key
from oldman.web.security.csrf import StatelessCSRFManager, add_csrf_token, csrf_exempt, csrf_protect
from oldman.web.session import DefaultSessionInterface, Session, SessionData
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

ROOT = Path(__file__).resolve().parents[1]


class FakeApp:
    """Small app object for CSRF tests."""

    def __init__(self) -> None:
        self.config = {"SECRET_KEY": "secret"}
        self.ctx = SimpleNamespace()
        self.listeners: list[tuple[object, str]] = []
        self.middlewares: list[tuple[Any, str]] = []

    def register_listener(self, listener, event: str) -> None:
        """Record registered listener."""
        self.listeners.append((listener, event))

    def register_middleware(self, middleware, location: str, **kwargs: object) -> None:
        """Record registered middleware."""
        del kwargs
        self.middlewares.append((middleware, location))


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
            path="/submit",
            headers={},
            host="example.test",
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

        # A hand-built request no Session middleware opened is bound to its user id.
        self.assertEqual("user:0", manager._binding(cast(Any, request), issue=False))
        self.assertEqual((True, "Valid"), manager.validate_token(cast(Any, request), token))

    def test_same_origin_check_uses_origin_first_and_rejects_cross_site(self) -> None:
        """Origin is the primary check; null, foreign, and both-missing are all rejected."""
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret")  # check_referer defaults True
        self.assertTrue(manager.check_referer)

        def request_with(headers: dict[str, str]):
            request = SimpleNamespace(
                app=app,
                ctx=SimpleNamespace(session={"sid": "s1"}),
                path="/submit",
                headers=headers,
                host="example.test",
                form={},
                json=None,
            )
            token = manager.generate_token(cast(Any, request))
            request.form = {"csrfmiddlewaretoken": token}
            return cast(Any, request)

        # A real page mints its own token and submits with a matching Origin.
        same_origin = request_with({"Origin": "https://example.test"})
        self.assertEqual((True, "Valid"), manager.validate_token(same_origin, same_origin.form["csrfmiddlewaretoken"]))

        # Under no-referrer a browser sends the literal "null" Origin, same-site posts included.
        null_origin = request_with({"Origin": "null"})
        accepted, reason = manager.validate_token(null_origin, null_origin.form["csrfmiddlewaretoken"])
        self.assertFalse(accepted)
        self.assertEqual("Cross-origin request blocked", reason)

        # A foreign Origin is rejected even with a valid token.
        foreign = request_with({"Origin": "https://attacker.test"})
        self.assertFalse(manager.validate_token(foreign, foreign.form["csrfmiddlewaretoken"])[0])

        # Neither Origin nor Referer present: rejected (option A).
        bare = request_with({})
        self.assertFalse(manager.validate_token(bare, bare.form["csrfmiddlewaretoken"])[0])

        # Referer is the fallback when Origin is absent.
        referer_ok = request_with({"Referer": "https://example.test/page"})
        self.assertTrue(manager.validate_token(referer_ok, referer_ok.form["csrfmiddlewaretoken"])[0])
        referer_bad = request_with({"Referer": "https://attacker.test/page"})
        self.assertFalse(manager.validate_token(referer_bad, referer_bad.form["csrfmiddlewaretoken"])[0])

        # A subdomain is no longer blanket-trusted (W-7).
        subdomain = request_with({"Origin": "https://evil.example.test"})
        self.assertFalse(manager.validate_token(subdomain, subdomain.form["csrfmiddlewaretoken"])[0])

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
        source = (ROOT / "oldman" / "web" / "security" / "csrf" / "__init__.py").read_text(encoding="utf-8")
        legacy_prefix = "ac" + "_base"

        self.assertNotIn(legacy_prefix, source)


if __name__ == "__main__":
    unittest.main()


class SessionBoundTokenTest(unittest.IsolatedAsyncioTestCase):
    """What a token is bound to, through a real Sanic app, the Session middleware and an owned redis-server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "csrf_binding")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        settings = DefaultSettings()
        settings.core.namespace = "csrf_binding"
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"SESSION": 0}))
        self.enterContext(patch("oldman.web.session.base.redis_client", self.registry))
        await (await self.registry.using("SESSION").async_get_bin_conn()).flushdb()
        self.interface = DefaultSessionInterface(cookie_name="sid", session_model=SessionData)
        app = Sanic(f"csrf_binding_{uuid.uuid4().hex}")
        Session(app, self.interface)
        StatelessCSRFManager(cast(Any, app), secret_key="csrf-binding-test-secret", check_referer=False)

        @app.get("/form")
        @add_csrf_token()
        async def form(request):
            return text(request.ctx.csrf_token)

        @app.post("/submit")
        @csrf_protect()
        async def submit(request):
            return text("ok")

        @app.post("/account")
        @csrf_protect()
        @login_required()
        async def account(request):
            return text("ok")

        self.app = app

    async def asyncTearDown(self) -> None:
        Sanic.unregister_app(self.app)
        await self.registry.close()

    def client(self) -> Any:
        """The test client with an empty cookie jar: each request carries exactly the cookies it is given."""
        client = self.app.asgi_client
        client.cookies.clear()
        return client

    async def form(self, cookies: dict[str, str]) -> tuple[str, str | None]:
        """A token, and the CSRF cookie the response set, if it set one."""
        _request, response = await self.client().get("/form", cookies=cookies)
        return response.text, response.cookies.get("csrf_id")

    async def submit(self, token: str, cookies: dict[str, str]) -> int:
        _request, response = await self.client().post("/submit", data={"csrfmiddlewaretoken": token}, cookies=cookies)
        return response.status

    async def test_an_anonymous_token_holds_only_with_the_visitors_own_cookie(self) -> None:
        """Every anonymous token used to bind the same "anonymous" and pass for any visitor."""
        token_a, cookie_a = await self.form({})
        token_b, cookie_b = await self.form({})
        assert cookie_a is not None and cookie_b is not None

        self.assertEqual(200, await self.submit(token_a, {"csrf_id": cookie_a}))
        self.assertEqual(403, await self.submit(token_a, {"csrf_id": cookie_b}))
        self.assertEqual(403, await self.submit(token_a, {}))
        # A visitor who has the cookie keeps it: the next page binds to it and sets nothing.
        token_again, cookie_again = await self.form({"csrf_id": cookie_a})
        self.assertIsNone(cookie_again)
        self.assertEqual(200, await self.submit(token_again, {"csrf_id": cookie_a}))

    async def test_a_signed_in_token_holds_only_in_its_own_session(self) -> None:
        """Tokens were bound to the user id: another session of the same user, or signing out, kept them valid."""
        anonymous_token, csrf_cookie = await self.form({})
        assert csrf_cookie is not None
        first = await self.interface.login(SessionData(user_id=7, username="ops", is_active=True))
        second = await self.interface.login(SessionData(user_id=7, username="ops", is_active=True))
        token, issued = await self.form({"sid": first, "csrf_id": csrf_cookie})
        self.assertIsNone(issued)

        self.assertEqual(200, await self.submit(token, {"sid": first, "csrf_id": csrf_cookie}))
        # Another session, or signing in again, in the same browser: its CSRF cookie does not stand in for the session.
        self.assertEqual(403, await self.submit(token, {"sid": second, "csrf_id": csrf_cookie}))
        self.assertEqual(403, await self.submit(token, {}))
        # A form opened before signing in needs a reload after it.
        self.assertEqual(403, await self.submit(anonymous_token, {"sid": first, "csrf_id": csrf_cookie}))

    async def test_a_form_left_open_until_its_session_was_ended_reaches_the_sign_in_check(self) -> None:
        """Ended by an administrator, the session cookie stays and names a session that is gone. The form's
        token was a CSRF failure (403) instead of a sign-in."""
        sid = await self.interface.login(SessionData(user_id=7, username="ops", is_active=True))
        token, csrf_cookie = await self.form({"sid": sid})
        # A signed-in page gives a browser without one its CSRF cookie too.
        assert csrf_cookie is not None
        await self.interface.force_logout_user(7)

        _request, response = await self.client().post("/account", data={"csrfmiddlewaretoken": token}, cookies={"sid": sid, "csrf_id": csrf_cookie})
        self.assertEqual(302, response.status)
        self.assertIn("/login", response.headers.get("location", ""))
        # Without the browser's CSRF cookie nothing ties the request to that form.
        self.assertEqual(403, await self.submit(token, {"sid": sid}))
        self.assertEqual(403, await self.submit(token, {}))

    async def test_a_form_left_open_until_the_user_signed_out_reaches_the_sign_in_check(self) -> None:
        """Signing out, or the session expiring, takes the session cookie with it: only the CSRF cookie the
        browser got before signing in is left. The form's token was a CSRF failure (403) instead of a sign-in."""
        _anonymous_token, csrf_cookie = await self.form({})
        assert csrf_cookie is not None
        sid = await self.interface.login(SessionData(user_id=7, username="ops", is_active=True))
        token, _cookie = await self.form({"sid": sid, "csrf_id": csrf_cookie})
        await self.interface.logout(sid)

        _request, response = await self.client().post("/account", data={"csrfmiddlewaretoken": token}, cookies={"csrf_id": csrf_cookie})
        self.assertEqual(302, response.status)
        self.assertIn("/login", response.headers.get("location", ""))
        # Another browser's CSRF cookie does not pass it.
        _other_token, other_cookie = await self.form({})
        assert other_cookie is not None
        self.assertEqual(403, await self.submit(token, {"csrf_id": other_cookie}))

    async def test_the_cookie_travels_like_the_session_cookie_and_only_with_a_token(self) -> None:
        _request, response = await self.client().get("/form")
        header = next(value for key, value in response.headers.items() if key.lower() == "set-cookie" and value.startswith("csrf_id="))
        self.assertIn("HttpOnly", header)
        self.assertIn("Path=/", header)
        self.assertIn("Max-Age=31536000", header)
        # A request that generated no token sets no cookie.
        _request, response = await self.client().post("/submit", data={})
        self.assertNotIn("csrf_id", response.cookies)


class GlobalCsrfEnforcementTest(unittest.TestCase):
    """csrf_exempt must exempt a route from something that actually runs.

    It used to set `func._csrf_exempt = True` and nothing anywhere read that attribute.
    There was no global middleware either, so protection was opt-in per route: a handler
    that forgot @csrf_protect was unprotected and nothing said so, while a webhook marked
    csrf_exempt was still blocked if it happened to carry @csrf_protect. A public API
    that reads like a security control and is a no-op is worse than no API.

    Enforcement is off by default, because switching it on covers routes that are
    unprotected today - API and webhook endpoints that authenticate by token rather than
    by session - so a deployment has to mark those exempt first.
    """

    @staticmethod
    def _request(app: Any, method: str, handler: Any, *, token: str | None = None) -> Any:
        return SimpleNamespace(
            app=app,
            ctx=SimpleNamespace(session={"sid": "session-1"}),
            path="/submit",
            headers={"Origin": "http://example.test"},
            host="example.test",
            form={"csrfmiddlewaretoken": token} if token else {},
            json=None,
            method=method,
            route=SimpleNamespace(handler=handler),
        )

    def test_enforcement_is_off_unless_the_setting_asks_for_it(self) -> None:
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret")
        self.assertFalse(manager.enforce)
        self.assertEqual([], app.middlewares, "a default deployment must keep its current behaviour")

    def test_an_unsafe_request_without_a_token_is_refused(self) -> None:
        from oldman.web.exceptions import Forbidden

        app = FakeApp()
        StatelessCSRFManager(cast(Any, app), secret_key="secret", enforce=True)
        middleware = app.middlewares[0][0]

        async def handler(request: Any) -> str:
            return "ok"

        with self.assertRaises(Forbidden):
            asyncio.run(middleware(self._request(app, "POST", handler)))

    def test_a_safe_method_is_left_alone(self) -> None:
        app = FakeApp()
        StatelessCSRFManager(cast(Any, app), secret_key="secret", enforce=True)
        middleware = app.middlewares[0][0]

        async def handler(request: Any) -> str:
            return "ok"

        for method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            with self.subTest(method=method):
                self.assertIsNone(asyncio.run(middleware(self._request(app, method, handler))))

    def test_csrf_exempt_now_exempts(self) -> None:
        app = FakeApp()
        StatelessCSRFManager(cast(Any, app), secret_key="secret", enforce=True)
        middleware = app.middlewares[0][0]

        @csrf_exempt
        async def webhook(request: Any) -> str:
            return "ok"

        self.assertIsNone(asyncio.run(middleware(self._request(app, "POST", webhook))))

    def test_a_valid_token_passes_enforcement(self) -> None:
        app = FakeApp()
        manager = StatelessCSRFManager(cast(Any, app), secret_key="secret", enforce=True)
        middleware = app.middlewares[0][0]

        async def handler(request: Any) -> str:
            return "ok"

        request = self._request(app, "POST", handler)
        request.form = {"csrfmiddlewaretoken": manager.generate_token(request)}
        self.assertIsNone(asyncio.run(middleware(request)))

    def test_the_decorator_and_the_middleware_share_one_implementation(self) -> None:
        """Two copies of "what counts as valid" is how they drift apart."""
        import inspect

        from oldman.web.security.csrf import manager as manager_module
        from oldman.web.security.csrf.decorators import enforce_csrf

        # The decorator body calls the shared function rather than restating the checks.
        decorator_source = inspect.getsource(manager_module.__dict__["StatelessCSRFManager"].register_enforcement)
        self.assertIn("enforce_csrf", decorator_source)
        self.assertEqual(1, inspect.getsource(enforce_csrf).count("CSRF token missing"))
        self.assertNotIn("CSRF token missing", inspect.getsource(manager_module))
