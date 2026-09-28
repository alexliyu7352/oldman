"""Ending a user's logins: sessions and access tokens, with and without a request."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.providers.redis import RedisClientRegistry
from oldman.web.auth import end_user_logins, revoke_user_logins
from oldman.web.authentication import access_token_revoked, issue_access_token, revoke_access_token, revoke_user_tokens
from oldman.web.session import Session, SessionData
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

SECRET = "revocation-test-secret-0123456789abcdefgh"


def token_settings() -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth.jwt.secret = SECRET
    return settings


def a_user() -> SimpleNamespace:
    return SimpleNamespace(id=7, username="ops", display_name="", is_active=True, is_staff=True, is_superuser=False)


class AccessTokenCutoffRedisTest(unittest.IsolatedAsyncioTestCase):
    """The cutoff against a real, test-owned redis-server — never the developer's own."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "revocation")

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

    async def asyncTearDown(self) -> None:
        await self.registry.close()

    async def test_the_cutoff_is_stored_for_one_token_lifetime_and_read_back(self) -> None:
        now = float(int(time.time()))
        with patch("oldman.web.authentication.jwt.time.time", return_value=now - 5):
            before = issue_access_token(a_user()).claims
        with patch("oldman.web.authentication.jwt.time.time", return_value=now + 1):
            after = issue_access_token(a_user()).claims
        with patch("oldman.web.authentication.jwt.time.time", return_value=now):
            await revoke_user_tokens(7)

        self.assertTrue(await access_token_revoked(before))
        self.assertFalse(await access_token_revoked(after))
        key = "oldman:token:revoked_before:7"
        self.assertEqual(str(int(now)), await self.connection.get(key))
        # Refresh tokens read the same cutoff, so it lives as long as they can.
        self.assertTrue(604790 < await self.connection.ttl(key) <= 604800)

    async def test_one_revoked_token_is_refused_until_it_would_have_expired(self) -> None:
        signed_out = issue_access_token(a_user()).claims
        other_client = issue_access_token(a_user()).claims
        await revoke_access_token(signed_out)

        self.assertTrue(await access_token_revoked(signed_out))
        self.assertFalse(await access_token_revoked(other_client))
        key = f"oldman:token:revoked:{signed_out['jti']}"
        self.assertTrue(890 < await self.connection.ttl(key) <= 900)

    async def test_revoking_an_expired_token_writes_nothing(self) -> None:
        with patch("oldman.web.authentication.jwt.time.time", return_value=time.time() - 1000):
            expired = issue_access_token(a_user()).claims
        await revoke_access_token(expired)
        self.assertEqual([], await self.connection.keys("*"))


class RevokeUserLoginsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": token_settings()}))
        self.interface = Mock()
        self.interface.force_logout_user = AsyncMock(return_value=())
        self.manager = Session()
        self.manager.interface = self.interface
        self.request = SimpleNamespace(
            app=SimpleNamespace(ctx=SimpleNamespace(session=self.manager)),
            ctx=SimpleNamespace(session=SessionData(user_id=3, is_active=True)),
        )

    def test_sessions_and_tokens_are_both_ended(self) -> None:
        with patch("oldman.web.auth.session.revoke_user_tokens", AsyncMock()) as tokens:
            ended_own = asyncio.run(revoke_user_logins(self.request, 9))
        self.assertFalse(ended_own)
        self.interface.force_logout_user.assert_awaited_once_with(9)
        tokens.assert_awaited_once_with(9)

    def test_one_store_failing_does_not_keep_the_other_alive(self) -> None:
        self.interface.force_logout_user.side_effect = ConnectionError("sessions down")
        with patch("oldman.web.auth.session.revoke_user_tokens", AsyncMock()) as tokens:
            asyncio.run(revoke_user_logins(self.request, 9))
        tokens.assert_awaited_once_with(9)

        self.interface.force_logout_user.side_effect = None
        self.interface.force_logout_user.reset_mock()
        with patch("oldman.web.auth.session.revoke_user_tokens", AsyncMock(side_effect=ConnectionError("tokens down"))):
            asyncio.run(revoke_user_logins(self.request, 9))
        self.interface.force_logout_user.assert_awaited_once_with(9)


class EndUserLoginsTest(unittest.TestCase):
    """The command line has no request; it reaches the same stores from settings."""

    def test_it_ends_sessions_through_the_configured_store_and_cuts_tokens_off(self) -> None:
        settings = token_settings()
        settings.web.session.enabled = True
        interface = Mock()
        interface.force_logout_user = AsyncMock(return_value=())
        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch("oldman.web.auth.session.Session._configured_interface", return_value=interface),
            patch("oldman.web.auth.session.revoke_user_tokens", AsyncMock()) as tokens,
        ):
            asyncio.run(end_user_logins(9))
        interface.force_logout_user.assert_awaited_once_with(9)
        tokens.assert_awaited_once_with(9)

    def test_without_sessions_only_tokens_are_cut_off(self) -> None:
        with (
            patch.dict(conf.__dict__, {"settings": token_settings()}),
            patch("oldman.web.auth.session.Session._configured_interface") as configured,
            patch("oldman.web.auth.session.revoke_user_tokens", AsyncMock()) as tokens,
        ):
            asyncio.run(end_user_logins(9))
        configured.assert_not_called()
        tokens.assert_awaited_once_with(9)


if __name__ == "__main__":
    unittest.main()
