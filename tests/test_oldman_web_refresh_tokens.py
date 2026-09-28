"""Refresh tokens: one family per sign-in, rotated on every use, ended on reuse or revocation."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError
from sanic.exceptions import ServiceUnavailable

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, RedisConfig
from oldman.providers.redis import RedisClientRegistry
from oldman.web.authentication import issue_refresh_token, revoke_refresh_token, revoke_user_tokens, rotate_refresh_token
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

SECRET = "refresh-token-test-secret-0123456789abcdef"


def token_settings() -> DefaultSettings:
    settings = DefaultSettings()
    settings.web.auth.jwt.secret = SECRET
    return settings


class RefreshTokenStoreTest(unittest.IsolatedAsyncioTestCase):
    """Against a real, test-owned redis-server — the rotation is a Lua script — never the developer's own."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "refresh")

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

    async def test_each_use_hands_out_the_next_token_and_the_used_one_stops_working(self) -> None:
        first = await issue_refresh_token(7)
        self.assertEqual(604800, first.expires_in)

        rotated = await rotate_refresh_token(first.token)
        assert rotated is not None
        self.assertEqual(7, rotated.user_id)
        self.assertNotEqual(first.token, rotated.refresh_token.token)

        again = await rotate_refresh_token(rotated.refresh_token.token)
        assert again is not None
        self.assertEqual(7, again.user_id)

    async def test_a_replaced_token_coming_back_ends_the_whole_sign_in(self) -> None:
        stolen = await issue_refresh_token(7)
        rotated = await rotate_refresh_token(stolen.token)
        assert rotated is not None

        self.assertIsNone(await rotate_refresh_token(stolen.token))
        # Nobody can tell the client from the copier, so the client's current token ends too.
        self.assertIsNone(await rotate_refresh_token(rotated.refresh_token.token))

    async def test_two_requests_racing_with_one_token_cannot_both_win(self) -> None:
        token = await issue_refresh_token(7)
        results = await asyncio.gather(rotate_refresh_token(token.token), rotate_refresh_token(token.token))
        winners = [result for result in results if result is not None]
        self.assertEqual(1, len(winners))
        # The loser counted as reuse: the winner's token is gone with the family.
        self.assertIsNone(await rotate_refresh_token(winners[0].refresh_token.token))

    async def test_every_use_restarts_the_lifetime(self) -> None:
        first = await issue_refresh_token(7)
        family_key = next(key for key in await self.connection.keys("oldman:token:refresh_family:*"))
        await self.connection.expire(family_key, 10)

        rotated = await rotate_refresh_token(first.token)
        assert rotated is not None
        self.assertTrue(604790 < await self.connection.ttl(family_key) <= 604800)

    async def test_signing_out_ends_the_sign_in_and_unknown_tokens_are_ignored(self) -> None:
        token = await issue_refresh_token(7)
        other_client = await issue_refresh_token(7)
        await revoke_refresh_token(token.token)
        await revoke_refresh_token("never-issued")
        await revoke_refresh_token(None)

        self.assertIsNone(await rotate_refresh_token(token.token))
        self.assertIsNotNone(await rotate_refresh_token(other_client.token))

    async def test_a_user_cutoff_ends_sign_ins_made_up_to_it(self) -> None:
        now = float(int(time.time()))
        with patch("oldman.web.authentication.refresh.time.time", return_value=now):
            before = await issue_refresh_token(7)
        with patch("oldman.web.authentication.refresh.time.time", return_value=now + 1):
            after = await issue_refresh_token(7)
        other_user = await issue_refresh_token(8)
        with patch("oldman.web.authentication.jwt.time.time", return_value=now):
            await revoke_user_tokens(7)

        self.assertIsNone(await rotate_refresh_token(before.token))
        self.assertIsNotNone(await rotate_refresh_token(after.token))
        self.assertIsNotNone(await rotate_refresh_token(other_user.token))

    async def test_malformed_tokens_are_simply_not_valid(self) -> None:
        # "\ud800": a lone surrogate, which JSON can carry and UTF-8 cannot encode (G1-1).
        for token in ("", "garbage", None, 7, "\ud800"):
            with self.subTest(token=token):
                self.assertIsNone(await rotate_refresh_token(token))

    async def test_a_store_that_answers_in_bytes_works_as_well(self) -> None:
        """G1-5: with decode_responses false on the alias, rotation read the record as text and raised TypeError."""
        alias = {"redis_url": f"unix://{self._redis.socket_path.as_posix()}?db=5", "health_check_interval": 0, "decode_responses": False}
        registry = RedisClientRegistry(RedisConfig.model_validate({"SESSION": alias}))
        self.addAsyncCleanup(registry.close)
        with patch("oldman.providers.redis.redis_client", registry):
            issued = await issue_refresh_token(7)
            rotated = await rotate_refresh_token(issued.token)
        self.assertEqual(7, getattr(rotated, "user_id", None))

    async def test_the_store_holds_no_token_a_client_could_present(self) -> None:
        token = await issue_refresh_token(7)
        rotated = await rotate_refresh_token(token.token)
        assert rotated is not None
        stored = []
        for key in await self.connection.keys("*"):
            stored.append(key)
            if await self.connection.type(key) == "hash":
                stored.extend((await self.connection.hgetall(key)).values())
            else:
                stored.append(await self.connection.get(key))
        for presented in (token.token, rotated.refresh_token.token):
            self.assertFalse(any(presented in value for value in stored))


class RefreshTokenStoreFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_an_unreachable_store_is_503_rather_than_a_refused_token(self) -> None:
        broken = AsyncMock(side_effect=RedisConnectionError("down"))
        with (
            patch.dict(conf.__dict__, {"settings": token_settings()}),
            patch("oldman.web.security.store.security_redis_connection", broken),
        ):
            for attempt in (issue_refresh_token(7), rotate_refresh_token("token"), revoke_refresh_token("token")):
                with self.subTest(attempt=attempt.__name__), self.assertRaises(ServiceUnavailable):
                    await attempt


if __name__ == "__main__":
    unittest.main()
