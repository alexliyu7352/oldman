"""Every Redis key and channel the framework writes lives under the service namespace."""

from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import oldman.conf as conf
from oldman.auth import AuthSettings
from oldman.auth.models import User
from oldman.cache.backends.redis import RedisCache
from oldman.conf.containers import RedisSet, RedisSettings, RedisStore
from oldman.conf.schemas import DefaultSettings, SSEConfig
from oldman.db.sqlalchemy.cache import AsyncQueryCache
from oldman.providers.redis import RedisClientRegistry, redis_key
from oldman.serializers import MsgspecModel
from oldman.web.auth.login import LoginRateLimit
from oldman.web.authentication import (
    access_token_revoked,
    issue_access_token,
    issue_refresh_token,
    revoke_access_token,
    revoke_user_tokens,
    rotate_refresh_token,
)
from oldman.web.security.fingerprint import log_fake_fingerprint_attempt
from oldman.web.session import SessionData
from oldman.web.session.base import DefaultSessionInterface
from oldman.web.sse import SSEPublisher
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

SECRET = "namespace-test-secret-0123456789abcdefgh"
ALIASES = ("DEFAULT", "SESSION", "CACHE", "SSE")


class Ping(MsgspecModel):
    value: int


class Flags(MsgspecModel):
    enabled: bool = False


def service_settings(namespace: str) -> DefaultSettings:
    settings = DefaultSettings()
    settings.core.namespace = namespace
    settings.web.auth.jwt.secret = SECRET
    settings.web.sse = SSEConfig(enabled=True, redis_alias="SSE")
    return settings


class RedisNamespaceTest(unittest.IsolatedAsyncioTestCase):
    """A test-owned redis-server with every alias on one database, so one scan sees everything."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "namespace")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, dict.fromkeys(ALIASES, 0)))
        # Modules that bound the process registry at import time get this one too.
        for target in (
            "oldman.providers.redis.redis_client",
            "oldman.cache.backends.redis.redis_client",
            "oldman.db.sqlalchemy.cache.redis_client",
            "oldman.web.session.base.redis_client",
        ):
            self.enterContext(patch(target, self.registry))
        self.connection = await self.registry.using("DEFAULT").async_get_conn()
        await self.connection.flushdb()

    async def asyncTearDown(self) -> None:
        await self.registry.close()

    def serve_as(self, namespace: str) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": service_settings(namespace)}))

    async def test_no_key_or_channel_escapes_the_namespace(self) -> None:
        self.serve_as("svc_a")
        # SSE payloads are msgpack: listen on a binary connection.
        pubsub = (await self.registry.using("DEFAULT").async_get_bin_conn()).pubsub()
        await pubsub.psubscribe("*")
        await pubsub.get_message(timeout=1)

        await DefaultSessionInterface(session_model=SessionData).login(SessionData(user_id=1, is_active=True))
        await LoginRateLimit(auth_settings=AuthSettings()).record_failure(SimpleNamespace(client_ip="10.0.0.1"), "alice")
        await RedisCache(settings_source=lambda: conf.settings.cache).set("greeting", "hello")
        await AsyncQueryCache(User).invalidate_cache()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            legacy_settings = RedisSettings(self.registry.using("DEFAULT"))
        await legacy_settings.set_value("feature", True)
        await RedisStore(Flags, "flags", client=self.registry.using("DEFAULT")).update(enabled=True)
        await RedisSet(str, "devices", client=self.registry.using("DEFAULT")).add("tv-1")
        await self.registry.using("DEFAULT").acquire_lock("job")
        await revoke_user_tokens(1)
        await revoke_access_token(
            issue_access_token(SimpleNamespace(id=2, username="bob", display_name="", is_active=True, is_staff=False, is_superuser=False)).claims
        )
        refresh = await issue_refresh_token(1)
        await rotate_refresh_token(refresh.token)
        await log_fake_fingerprint_attempt("10.0.0.1", "forged")
        self.assertTrue(
            await SSEPublisher(conf.settings.web.sse, registry=self.registry).publish_user(user_id=1, event="ping", payload=Ping(value=1))
        )

        keys = await self.connection.keys("*")
        self.assertEqual([], [key for key in keys if not key.startswith("svc_a:")])
        # Every subsystem above really wrote something, so the check above is not vacuous.
        families = {key.split(":")[1] for key in keys}
        self.assertEqual(
            {"session", "user_session", "ratelimit", "cache", "model_cache", "settings", "store", "lock", "token", "fingerprint"},
            families,
        )
        message = await pubsub.get_message(timeout=1)
        while message is not None and message["type"] != "pmessage":
            message = await pubsub.get_message(timeout=1)
        assert message is not None
        self.assertEqual(b"svc_a:events:v1", message["channel"])
        await pubsub.aclose()

    async def test_services_sharing_a_namespace_share_a_revocation_and_others_do_not(self) -> None:
        self.serve_as("site")
        claims = issue_access_token(SimpleNamespace(id=7, username="ops", display_name="", is_active=True, is_staff=True, is_superuser=False)).claims
        await revoke_user_tokens(7)

        # The front site and the dashboard set the same namespace: a password changed on one ends tokens on both.
        self.serve_as("site")
        self.assertTrue(await access_token_revoked(claims))
        # A service that keeps its own namespace is not touched.
        self.serve_as("elsewhere")
        self.assertFalse(await access_token_revoked(claims))

    def test_the_namespace_defaults_to_the_app_name_and_may_not_hold_the_separator(self) -> None:
        settings = DefaultSettings()
        settings.core.app_name = "billing"
        with patch.dict(conf.__dict__, {"settings": settings}):
            self.assertEqual("billing:session:abc", redis_key("session", "abc"))
        for invalid in ("a:b", "a b"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                DefaultSettings.model_validate({"core": {"namespace": invalid}})
            # G4-11: app_name stands in for an unset namespace, so the same rule applies to it.
            with self.subTest(app_name=invalid), self.assertRaisesRegex(ValueError, "core.namespace"):
                DefaultSettings.model_validate({"core": {"app_name": invalid}})
            # A namespace of its own leaves app_name free to read as it likes.
            DefaultSettings.model_validate({"core": {"app_name": invalid, "namespace": "billing"}})


if __name__ == "__main__":
    unittest.main()
