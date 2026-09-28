"""Bearer access tokens: issuing, reading, and authenticating requests with them."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sanic import Sanic
from sanic.response import json, text

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.security.jwt import jwt_encode
from oldman.web.authentication import (
    JWTAuthentication,
    install_authentication,
    issue_access_token,
    read_access_token,
    resolve_authenticators,
)
from oldman.web.request import bearer_credential

SECRET = "access-token-test-secret-0123456789abcdef"


def jwt_settings(**overrides: object) -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth.jwt.secret = SECRET
    for name, value in overrides.items():
        setattr(settings.web.auth.jwt, name, value)
    return settings


def a_user(**fields: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 7,
        "username": "ops",
        "display_name": "",
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
    }
    values.update(fields)
    return SimpleNamespace(**values)


class MemoryRedis:
    """The commands access-token revocation issues, over one dict."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def mget(self, *keys: str) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    async def set(self, key: str, value: object, ex: int | None = None) -> bool:
        self.values[key] = str(value)
        self.expiries[key] = ex
        return True


class JWTSettingsTestCase(unittest.TestCase):
    settings_overrides: dict[str, object] = {}

    def setUp(self) -> None:
        self.settings = jwt_settings(**self.settings_overrides)
        self.enterContext(patch.dict(conf.__dict__, {"settings": self.settings}))
        # Verification looks up revocation in Redis; never the developer's own instance.
        self.redis = MemoryRedis()
        self.enterContext(patch("oldman.web.security.store.security_redis_connection", AsyncMock(return_value=self.redis)))


class BearerCredentialTest(unittest.TestCase):
    def test_only_the_bearer_scheme_is_read(self) -> None:
        cases = {
            "Bearer abc": "abc",
            "bearer  abc ": "abc",
            "BEARER abc": "abc",
            "Token abc": None,
            "Basic YWxhZGRpbjpvcGVuc2VzYW1l": None,
            "Bearer": None,
            "abc": None,
        }
        for header, expected in cases.items():
            with self.subTest(header=header):
                self.assertEqual(expected, bearer_credential(SimpleNamespace(headers={"authorization": header})))
        self.assertIsNone(bearer_credential(SimpleNamespace(headers={})))


class IssueAccessTokenTest(JWTSettingsTestCase):
    def test_the_token_carries_the_user_snapshot_and_exactly_the_configured_lifetime(self) -> None:
        issued = issue_access_token(a_user())
        claims = read_access_token(issued.token)

        assert claims is not None
        self.assertEqual(
            ("7", "ops", "ops", True, False), (claims["sub"], claims["username"], claims["display_name"], claims["is_staff"], claims["is_superuser"])
        )
        self.assertEqual(900, claims["exp"] - claims["iat"])
        self.assertEqual(900, issued.expires_in)
        self.assertNotEqual(issued.claims["jti"], issue_access_token(a_user()).claims["jti"])

    def test_only_an_active_user_with_an_integer_id_gets_one(self) -> None:
        with self.assertRaises(ValueError):
            issue_access_token(a_user(is_active=False))
        with self.assertRaises(TypeError):
            issue_access_token(a_user(id="7"))

    def test_without_a_key_nothing_is_signed(self) -> None:
        self.settings.web.auth.jwt.secret = None
        with self.assertRaisesRegex(RuntimeError, "web.auth.jwt.secret"):
            issue_access_token(a_user())


class IssuerAndAudienceTest(JWTSettingsTestCase):
    settings_overrides = {"issuer": "auth", "audience": "billing"}

    def test_configured_issuer_and_audience_are_written_and_required(self) -> None:
        issued = issue_access_token(a_user())
        self.assertEqual(("auth", "billing"), (issued.claims["iss"], issued.claims["aud"]))
        self.assertIsNotNone(read_access_token(issued.token))

        self.settings.web.auth.jwt.audience = "reports"
        self.assertIsNone(read_access_token(issued.token))


class ReadAccessTokenTest(JWTSettingsTestCase):
    def sign(self, **changes: object) -> str:
        claims = dict(issue_access_token(a_user()).claims)
        for name, value in changes.items():
            if value is None:
                claims.pop(name)
            else:
                claims[name] = value
        return jwt_encode(claims, SECRET)

    def test_a_token_is_refused_unless_every_claim_is_there_with_its_type(self) -> None:
        cases = {
            "no subject": {"sub": None},
            "non-numeric subject": {"sub": "ops"},
            "no expiry": {"exp": None},
            "no token id": {"jti": None},
            "empty token id": {"jti": ""},
            "flag as text": {"is_staff": "yes"},
            "missing flag": {"is_superuser": None},
        }
        for label, changes in cases.items():
            with self.subTest(label):
                self.assertIsNone(read_access_token(self.sign(**changes)))

    def test_a_token_signed_to_live_longer_than_configured_is_refused(self) -> None:
        issued = issue_access_token(a_user())
        longer = self.sign(exp=issued.claims["iat"] + 3600)
        self.assertIsNone(read_access_token(longer))

    def test_expired_foreign_and_tampered_tokens_are_refused(self) -> None:
        with patch("oldman.web.authentication.jwt.time.time", return_value=1_000_000.0):
            expired = issue_access_token(a_user()).token
        foreign = jwt_encode(dict(issue_access_token(a_user()).claims), "another-key-" + "x" * 30)
        header, payload, signature = issue_access_token(a_user()).token.split(".")
        tampered = ".".join((header, payload, signature[:-2] + ("AA" if signature[-2:] != "AA" else "BB")))
        for label, token in (("expired", expired), ("foreign key", foreign), ("tampered", tampered)):
            with self.subTest(label):
                self.assertIsNone(read_access_token(token))


class JWTAuthenticationTest(JWTSettingsTestCase):
    def test_listing_jwt_without_a_key_stops_startup(self) -> None:
        self.settings.web.auth.jwt.secret = None
        with self.assertRaisesRegex(ValueError, "web.auth.jwt.secret"):
            resolve_authenticators(["jwt"], session_enabled=False)

    def test_requests_carrying_a_token_are_that_user_and_others_fall_through(self) -> None:
        import asyncio

        token = issue_access_token(a_user()).token
        method = JWTAuthentication()
        result = asyncio.run(method.authenticate(SimpleNamespace(headers={"authorization": f"Bearer {token}"})))
        assert result is not None
        self.assertEqual(("jwt", 7, "ops", True, False), (result.method, result.user.id, result.user.username, result.user.is_staff, result.ambient))
        self.assertIsNone(asyncio.run(method.authenticate(SimpleNamespace(headers={}))))
        self.assertIsNone(asyncio.run(method.authenticate(SimpleNamespace(headers={"authorization": "Bearer not-a-token"}))))


class AccessTokenRequestTest(JWTSettingsTestCase):
    """Real Sanic requests through the pipeline, the permission layer and CSRF."""

    def build_app(self, name: str) -> Sanic:
        from oldman.web.auth import api_login_required, login_required
        from oldman.web.security.csrf import StatelessCSRFManager, csrf_protect

        app = Sanic(name)
        install_authentication(app, (JWTAuthentication(),))
        # A manager with no key: requests exempt from CSRF never reach it, others fail on the missing token.
        app.ctx.csrf = StatelessCSRFManager()

        @app.get("/me")
        @api_login_required(user_keyword="user_id")
        async def me(request, user_id: int | None = None):
            return json({"id": user_id, "method": request.ctx.auth.method})

        @app.get("/page")
        @login_required()
        async def page(request):
            return text("page")

        @app.post("/write")
        @csrf_protect()
        @login_required()
        async def write(request):
            return text("written")

        return app

    def test_a_token_reaches_protected_handlers_and_skips_csrf(self) -> None:
        app = self.build_app("access_token_requests")
        token = issue_access_token(a_user()).token
        with patch("oldman.web.authentication.jwt.time.time", return_value=1_000_000.0):
            expired = issue_access_token(a_user()).token
        try:
            _, me = app.test_client.get("/me", headers={"authorization": f"Bearer {token}"})
            _, other_scheme = app.test_client.get("/me", headers={"authorization": f"Token {token}"})
            _, stale = app.test_client.get("/page", headers={"authorization": f"Bearer {expired}", "accept": "*/*"})
            _, written = app.test_client.post("/write", headers={"authorization": f"Bearer {token}"})
            _, forged = app.test_client.post("/write")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual((200, {"id": 7, "method": "jwt"}), (me.status, me.json))
        self.assertEqual(401, other_scheme.status)
        # An API client with an expired token gets JSON it can act on, not a redirect to a login page.
        self.assertEqual(401, stale.status)
        self.assertEqual(1401, stale.json["error_code"])
        self.assertEqual((200, "written"), (written.status, written.text))
        self.assertEqual(403, forged.status)

    def test_global_csrf_enforcement_lets_token_requests_through(self) -> None:
        from oldman.web.security.csrf import StatelessCSRFManager

        app = Sanic("access_token_global_csrf")
        install_authentication(app, (JWTAuthentication(),))
        manager = StatelessCSRFManager()
        app.ctx.csrf = manager
        manager.register_enforcement(app)

        @app.post("/hook")
        async def hook(request):
            return text("ok")

        token = issue_access_token(a_user()).token
        try:
            _, with_token = app.test_client.post("/hook", headers={"authorization": f"Bearer {token}"})
            _, without = app.test_client.post("/hook")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual(200, with_token.status)
        self.assertEqual(403, without.status)


class RevocationTest(JWTSettingsTestCase):
    def test_a_revocation_cuts_off_tokens_issued_up_to_that_second(self) -> None:
        import asyncio

        from oldman.web.authentication import revoke_user_tokens

        method = JWTAuthentication()

        def issued_at(moment: float) -> str:
            with patch("oldman.web.authentication.jwt.time.time", return_value=moment):
                return issue_access_token(a_user()).token

        def accepted(token: str) -> bool:
            request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
            return asyncio.run(method.authenticate(request)) is not None

        import time

        now = float(int(time.time()))
        before, same_second, after = issued_at(now - 5), issued_at(now), issued_at(now + 1)
        with patch("oldman.web.authentication.jwt.time.time", return_value=now):
            asyncio.run(revoke_user_tokens(7))

        self.assertEqual((False, False, True), (accepted(before), accepted(same_second), accepted(after)))
        # The cutoff lives exactly as long as the longer-lived token, a refresh token, can.
        self.assertEqual({604800}, set(self.redis.expiries.values()))

    def test_another_users_revocation_does_not_touch_this_one(self) -> None:
        import asyncio

        from oldman.web.authentication import revoke_user_tokens

        token = issue_access_token(a_user()).token
        asyncio.run(revoke_user_tokens(8))
        self.assertIsNotNone(asyncio.run(JWTAuthentication().authenticate(SimpleNamespace(headers={"authorization": f"Bearer {token}"}))))

    def test_an_unreachable_revocation_store_is_not_read_as_not_revoked(self) -> None:
        import asyncio

        from redis.exceptions import ConnectionError as RedisConnectionError
        from sanic.exceptions import ServiceUnavailable

        token = issue_access_token(a_user()).token
        broken = AsyncMock(side_effect=RedisConnectionError("down"))
        with patch("oldman.web.security.store.security_redis_connection", broken), self.assertRaises(ServiceUnavailable):
            asyncio.run(JWTAuthentication().authenticate(SimpleNamespace(headers={"authorization": f"Bearer {token}"})))

    def test_a_service_that_signs_no_tokens_still_writes_the_cutoff(self) -> None:
        """G1-2: an Admin without the jwt secret disabled a user, and the tokens the API service had issued stayed valid."""
        import asyncio

        from oldman.web.authentication import revoke_user_tokens

        secret = self.settings.web.auth.jwt.secret
        token = issue_access_token(a_user()).token
        self.settings.web.auth.jwt.secret = None
        asyncio.run(revoke_user_tokens(7))
        self.settings.web.auth.jwt.secret = secret

        request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
        self.assertIsNone(asyncio.run(JWTAuthentication().authenticate(request)))


class JWTSettingsValidationTest(unittest.TestCase):
    def test_a_short_key_is_refused_and_the_old_unused_setting_is_gone(self) -> None:
        settings = DefaultSettings()
        with self.assertRaisesRegex(ValueError, "32 characters"):
            type(settings.web.auth.jwt).model_validate({"secret": "short"})
        self.assertFalse(hasattr(settings.web.security, "token_expire_time"))


if __name__ == "__main__":
    unittest.main()
