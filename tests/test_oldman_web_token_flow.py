"""The token routes: obtain, refresh and revoke bearer tokens through a real application."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from sanic import Sanic
from sanic.response import json
from sqlalchemy.schema import Table

import oldman.conf as conf
from oldman.auth import AuthSettings, get_user_by_username, has_staff_access
from oldman.auth.models import User
from oldman.auth.settings import LoginSettings
from oldman.conf.schemas import DatabaseConfig, DefaultSettings
from oldman.db.session import DatabaseManager
from oldman.providers.redis import RedisClientRegistry
from oldman.web.auth import TokenFlow, api_login_required, revoke_user_logins
from oldman.web.authentication import JWTAuthentication, install_authentication, read_access_token
from oldman.web.security.csrf import StatelessCSRFManager
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

SECRET = "token-flow-test-secret-0123456789abcdefgh"


def token_settings() -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth.jwt.secret = SECRET
    return settings


class TokenFlowTest(unittest.IsolatedAsyncioTestCase):
    """A real Sanic application, a real user table and a test-owned redis-server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "token_flow")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"SESSION": 5}))
        self.enterContext(patch("oldman.providers.redis.redis_client", self.registry))
        self.enterContext(patch.dict(conf.__dict__, {"settings": token_settings()}))
        self.connection = await self.registry.using("SESSION").async_get_conn()
        await self.connection.flushdb()

        self.database = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        await self.database.initialize()
        async with self.database.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)
        async with self.database.get_session() as session:
            for username, is_staff in (("ops", True), ("viewer", False)):
                user = User(username=username, password_hash="", is_active=True, is_staff=is_staff, is_superuser=False)
                user.set_password("Right-Pass-2026")
                session.add(user)
        self.auth_settings = AuthSettings(login=LoginSettings(ip_limit=0, username_limit=3))
        self.app = self.build_app()

    async def asyncTearDown(self) -> None:
        Sanic.unregister_app(self.app)
        await self.database.close()
        await self.registry.close()

    def build_app(self) -> Sanic:
        app = Sanic(f"token_flow_{uuid.uuid4().hex}")
        install_authentication(app, (JWTAuthentication(),))
        # Global CSRF enforcement is on: the token routes must work without a CSRF token.
        csrf = StatelessCSRFManager()
        app.ctx.csrf = csrf
        csrf.register_enforcement(app)
        TokenFlow(accept_user=has_staff_access, auth_settings=self.auth_settings, db_manager=self.database).register_routes(
            app, obtain_path="/token", refresh_path="/token/refresh", revoke_path="/token/revoke"
        )
        # A site that hands tokens to everyone it signs in: accept_user does not look at is_active.
        TokenFlow(accept_user=lambda user: True, auth_settings=self.auth_settings, db_manager=self.database).register_routes(
            app, obtain_path="/open/token", refresh_path="/open/token/refresh", revoke_path="/open/token/revoke", name_prefix="open_"
        )

        @app.get("/me")
        @api_login_required(user_keyword="user_id")
        async def me(request, user_id: int | None = None):
            return json({"id": user_id})

        return app

    async def post(self, path: str, body: dict[str, Any], **headers: str) -> Any:
        _request, response = await self.app.asgi_client.post(path, json=body, headers=headers)
        return response

    async def obtain(self, username: str = "ops", password: str = "Right-Pass-2026") -> Any:
        return await self.post("/token", {"username": username, "password": password})

    async def me(self, access_token: str) -> int:
        _request, response = await self.app.asgi_client.get("/me", headers={"authorization": f"Bearer {access_token}"})
        return response.status

    async def ops_id(self) -> int:
        user = await get_user_by_username("ops", auth_settings=self.auth_settings, db_manager=self.database)
        assert user is not None
        return cast(int, user.id)

    async def test_signing_in_answers_with_a_pair_that_nothing_may_cache(self) -> None:
        response = await self.obtain()

        self.assertEqual(200, response.status)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(0, response.json["error_code"])
        data = response.json["data"]
        self.assertEqual(
            {"access_token", "token_type", "expires_in", "refresh_token", "refresh_expires_in"},
            set(data),
        )
        self.assertEqual(("Bearer", 900, 604800), (data["token_type"], data["expires_in"], data["refresh_expires_in"]))
        self.assertEqual(200, await self.me(data["access_token"]))
        user = await get_user_by_username("ops", auth_settings=self.auth_settings, db_manager=self.database)
        assert user is not None
        self.assertIsNotNone(user.last_login_at)

    async def test_the_tokens_carry_the_users_roles_when_the_roles_app_is_installed(self) -> None:
        self.app.ctx.app_registry = SimpleNamespace(labels=("auth", "roles"))
        with patch("oldman.apps.roles.store.user_role_ids", AsyncMock(return_value=(2, 5))):
            first = (await self.obtain()).json["data"]
            renewed = (await self.post("/token/refresh", {"refresh_token": first["refresh_token"]})).json["data"]

        for access_token in (first["access_token"], renewed["access_token"]):
            claims = read_access_token(access_token)
            assert claims is not None
            self.assertEqual([2, 5], claims["roles"])

    async def test_a_form_body_works_as_well_as_json(self) -> None:
        _request, response = await self.app.asgi_client.post("/token", data={"username": "ops", "password": "Right-Pass-2026"})
        self.assertEqual(200, response.status)

    async def test_a_refused_account_gets_the_same_answer_as_a_wrong_password(self) -> None:
        wrong_password = await self.obtain(password="Wrong-Pass-2026")
        not_staff = await self.obtain(username="viewer")

        for response in (wrong_password, not_staff):
            self.assertEqual(401, response.status)
            self.assertEqual({"error_code": 1401, "message": "Invalid credentials", "data": {}, "actions": []}, response.json)

    async def test_failed_sign_ins_run_into_the_login_limit(self) -> None:
        for _attempt in range(3):
            self.assertEqual(401, (await self.obtain(password="Wrong-Pass-2026")).status)

        limited = await self.obtain()

        self.assertEqual(429, limited.status)
        self.assertEqual(1429, limited.json["error_code"])
        self.assertTrue(int(limited.headers["retry-after"]) > 0)

    async def test_missing_fields_are_a_bad_request(self) -> None:
        for body in ({"username": "ops"}, {"username": "ops", "password": 7}, {}):
            with self.subTest(body=body):
                response = await self.post("/token", body)
                self.assertEqual((400, 1000), (response.status, response.json["error_code"]))
        self.assertEqual(400, (await self.post("/token/refresh", {})).status)

    async def test_text_that_cannot_be_utf8_is_a_bad_request_not_a_server_error(self) -> None:
        """G1-1: JSON may carry a lone surrogate; hashing it or putting it in a rate-limit key raised, a 500."""
        bodies = {
            "/token": b'{"username": "\\ud800", "password": "Right-Pass-2026"}',
            "/token/refresh": b'{"refresh_token": "\\ud800"}',
            "/token/revoke": b'{"refresh_token": "\\ud800"}',
        }
        for path, body in bodies.items():
            with self.subTest(path=path):
                _request, response = await self.app.asgi_client.post(path, content=body, headers={"content-type": "application/json"})
                self.assertEqual((400, 1000), (response.status, response.json["error_code"]))

    async def test_refreshing_hands_out_a_new_pair_and_the_used_token_stops_working(self) -> None:
        first = (await self.obtain()).json["data"]

        renewed = await self.post("/token/refresh", {"refresh_token": first["refresh_token"]})
        self.assertEqual(200, renewed.status)
        self.assertEqual("no-store", renewed.headers["cache-control"])
        second = renewed.json["data"]
        self.assertNotEqual(first["refresh_token"], second["refresh_token"])
        self.assertEqual(200, await self.me(second["access_token"]))

        replayed = await self.post("/token/refresh", {"refresh_token": first["refresh_token"]})
        self.assertEqual((401, 1401), (replayed.status, replayed.json["error_code"]))
        # A replaced token came back: the sign-in ended, the current token with it.
        self.assertEqual(401, (await self.post("/token/refresh", {"refresh_token": second["refresh_token"]})).status)

    async def test_an_account_that_no_longer_qualifies_gets_no_new_token(self) -> None:
        for change in ({"is_active": False}, {"is_staff": False}):
            with self.subTest(change=change):
                await self.connection.flushdb()
                async with self.database.get_session() as session:
                    user = await session.get(User, await self.ops_id())
                    assert user is not None
                    user.is_active, user.is_staff = True, True
                refresh_token = (await self.obtain()).json["data"]["refresh_token"]
                async with self.database.get_session() as session:
                    user = await session.get(User, await self.ops_id())
                    assert user is not None
                    for name, value in change.items():
                        setattr(user, name, value)

                self.assertEqual(401, (await self.post("/token/refresh", {"refresh_token": refresh_token})).status)
                async with self.database.get_session() as session:
                    user = await session.get(User, await self.ops_id())
                    assert user is not None
                    user.is_active, user.is_staff = True, True
                # Qualifying again does not bring that sign-in back.
                self.assertEqual(401, (await self.post("/token/refresh", {"refresh_token": refresh_token})).status)

    async def test_refusals_answer_in_the_requests_language(self) -> None:
        """G2-7: the token routes wrote their refusals as literal English."""
        from babel.support import Translations

        from oldman.i18n import bind_translations, reset_translations

        locales = Path(__file__).resolve().parents[1] / "oldman/apps/admin/locales"
        self.addCleanup(reset_translations, bind_translations(Translations.load(str(locales), ["zh_Hans"])))
        cases = (
            ("/token", {"username": "ops"}, "缺少必填字段：username, password"),
            ("/token", {"username": "ops", "password": "Wrong-Pass-2026"}, "用户名或密码错误"),
            ("/token/refresh", {}, "缺少必填字段：refresh_token"),
            ("/token/refresh", {"refresh_token": "unknown"}, "刷新令牌无效"),
        )
        for path, body, message in cases:
            with self.subTest(path=path, body=body):
                self.assertEqual(message, (await self.post(path, body)).json["message"])

    async def test_a_failed_user_lookup_leaves_the_refresh_token_usable(self) -> None:
        """G2-3: the token was used up before the user was read; a database hiccup then cost the client its only token."""
        refresh_token = (await self.obtain()).json["data"]["refresh_token"]
        with patch("oldman.web.auth.tokens.get_user_by_id", AsyncMock(side_effect=RuntimeError("database down"))):
            failed = await self.post("/token/refresh", {"refresh_token": refresh_token})
        self.assertEqual(500, failed.status)

        # Before, the retry counted as reuse of a replaced token: 401, and the whole sign-in ended.
        retried = await self.post("/token/refresh", {"refresh_token": refresh_token})
        self.assertEqual(200, retried.status, retried.body)

    async def test_an_inactive_user_from_a_login_backend_gets_401_not_500(self) -> None:
        """G2-4: backends are not bound to refuse disabled accounts; one that returned such a user made obtain fail with 500."""
        async with self.database.get_session() as session:
            user = await session.get(User, await self.ops_id())
            assert user is not None
            user.is_active = False
        disabled = await get_user_by_username("ops", auth_settings=self.auth_settings, db_manager=self.database)

        with patch("oldman.web.auth.tokens.authenticate_credentials", AsyncMock(return_value=disabled)):
            response = await self.post("/open/token", {"username": "ops", "password": "Right-Pass-2026"})

        self.assertEqual((401, 1401), (response.status, response.json["error_code"]))

    async def test_signing_out_ends_the_sign_in_and_the_access_token_it_presents(self) -> None:
        signed_out = (await self.obtain()).json["data"]
        other_client = (await self.obtain()).json["data"]

        response = await self.post(
            "/token/revoke",
            {"refresh_token": signed_out["refresh_token"]},
            authorization=f"Bearer {signed_out['access_token']}",
        )

        self.assertEqual((200, 0), (response.status, response.json["error_code"]))
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual(401, await self.me(signed_out["access_token"]))
        self.assertEqual(401, (await self.post("/token/refresh", {"refresh_token": signed_out["refresh_token"]})).status)
        self.assertEqual(200, await self.me(other_client["access_token"]))
        self.assertEqual(200, (await self.post("/token/refresh", {"refresh_token": other_client["refresh_token"]})).status)
        # Signing out with a token that is no longer valid is not an error.
        self.assertEqual(200, (await self.post("/token/revoke", {"refresh_token": signed_out["refresh_token"]})).status)

    async def test_ending_a_users_logins_ends_their_token_sign_ins(self) -> None:
        tokens = (await self.obtain()).json["data"]
        # This application keeps no sessions: only the token half of revoke_user_logins is under test.
        sessions = SimpleNamespace(force_logout_user=AsyncMock())
        with patch("oldman.web.auth.session.Session.get_session_manager", return_value=sessions):
            await revoke_user_logins(SimpleNamespace(app=self.app, ctx=SimpleNamespace()), await self.ops_id())

        self.assertEqual(401, await self.me(tokens["access_token"]))
        self.assertEqual(401, (await self.post("/token/refresh", {"refresh_token": tokens["refresh_token"]})).status)


class TokenFlowConfigurationTest(unittest.TestCase):
    def test_who_may_hold_tokens_must_be_said(self) -> None:
        with self.assertRaises(TypeError):
            TokenFlow()  # type: ignore[call-arg]

    def test_the_client_cannot_reach_the_arguments_the_flow_passes_itself(self) -> None:
        for fields in ((), ("username", "db_manager"), ("auth_settings",)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                TokenFlow(accept_user=has_staff_access, credential_fields=fields)


if __name__ == "__main__":
    unittest.main()
