"""Focused contracts for the async Redis provider refactor."""

from __future__ import annotations

import asyncio
import importlib
import socket
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from oldman.conf import constants
from oldman.conf.manager import DEFAULT_DEPRECATED_SETTINGS_KEYS
from oldman.conf.schemas import (
    DefaultSettings,
    RedisConfig,
    RedisConnectionConfig,
)
from oldman.providers.redis.client import RedisClientRegistry


class RedisSettingsContractTest(unittest.TestCase):
    """Redis and Redis-cache settings must have separate typed boundaries."""

    def test_shared_pool_conversion_preserves_client_options_and_retry_identity(self) -> None:
        """Independent native pools receive the same conversion without changing settings."""
        from oldman.providers.redis.redis import AsyncRedis, redis_pool_options

        for url in ("unix:///tmp/unused-redis.sock?db=3", "redis://user:password@localhost:6379/4"):
            with self.subTest(url=url):
                config = RedisConnectionConfig.model_validate({
                    "redis_url": url, "protocol": 3, "retry_on_timeout": False,
                    "connection_socket_timeout": 2, "max_connections": 12,
                })
                before = config.model_dump()
                values = config.model_dump(exclude=set(config.model_extra or {}))
                converted = redis_pool_options(**values, connection_options=config.connection_options)
                client = AsyncRedis(**config.client_options())
                client_options = client._pool_options()
                self.assertIs(client.retry_strategy, client_options["retry"])
                for options in (converted, client_options):
                    retry = options.pop("retry")
                    self.assertEqual(3, retry._retries)
                    self.assertNotIn(RedisTimeoutError, retry._supported_errors)
                    self.assertEqual(2, options["socket_timeout"])
                    self.assertEqual(12, options["max_connections"])
                self.assertEqual(converted, client_options)
                self.assertEqual(before, config.model_dump())

    def test_redis_settings_keep_builtins_and_merge_partial_aliases(self) -> None:
        settings = DefaultSettings.model_validate({"redis": {"CACHE": {"max_connections": 256}}})

        self.assertEqual("unix:///var/run/redis/redis.sock?db=3", settings.redis["DEFAULT"].redis_url)
        self.assertEqual("redis://localhost:6379/2", settings.redis["CACHE"].redis_url)
        self.assertEqual(256, settings.redis["CACHE"].max_connections)
        self.assertEqual(2, settings.redis["CACHE"].protocol)
        self.assertEqual("redis://localhost:6379/5", settings.redis["SESSION"].redis_url)

    def test_redis_settings_accept_custom_alias_and_flat_connection_options(self) -> None:
        settings = DefaultSettings.model_validate(
            {
                "redis": {
                    "ANALYTICS": {
                        "redis_url": "redis://localhost:6379/8",
                        "connection_socket_timeout": 20,
                        "connection_client_name": "analytics",
                    }
                }
            }
        )

        config = settings.redis["ANALYTICS"]
        self.assertEqual(
            {"socket_timeout": 20, "client_name": "analytics"},
            config.connection_options,
        )

    def test_custom_redis_alias_requires_url(self) -> None:
        with self.assertRaisesRegex(ValidationError, "redis_url"):
            DefaultSettings.model_validate({"redis": {"ANALYTICS": {"max_connections": 8}}})

    def test_redis_connection_rejects_invalid_extension_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "connection_"):
            RedisConnectionConfig.model_validate({"redis_url": "redis://localhost/0", "socket_timeout": 1})
        with self.assertRaisesRegex(ValidationError, "max_connections"):
            RedisConnectionConfig.model_validate({"redis_url": "redis://localhost/0", "connection_max_connections": 8})
        with self.assertRaisesRegex(ValidationError, "socket_keepalive_options"):
            RedisConnectionConfig.model_validate(
                {
                    "redis_url": "redis://localhost/0",
                    "connection_socket_keepalive_options": {socket.TCP_KEEPIDLE: 120},
                }
            )
        with self.assertRaisesRegex(ValidationError, "retry"):
            RedisConnectionConfig.model_validate({"redis_url": "redis://localhost/0", "connection_retry": object()})
        for option in ("url", "connection_pool"):
            with self.subTest(option=option), self.assertRaisesRegex(ValidationError, option):
                RedisConnectionConfig.model_validate(
                    {"redis_url": "redis://localhost/0", f"connection_{option}": object()}
                )

    def test_redis_connection_rejects_invalid_operational_values(self) -> None:
        for field, value in (
            ("redis_url", ""),
            ("max_connections", 0),
            ("health_check_interval", -1),
            ("retry_attempts", -1),
            ("protocol", 4),
            ("backoff_base", -0.1),
            ("backoff_cap", -0.1),
            ("socket_keepalive_idle", 0),
            ("socket_keepalive_interval", 0),
            ("socket_keepalive_count", 0),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                values = {"redis_url": "redis://localhost/0", field: value}
                RedisConnectionConfig.model_validate(values)

    def test_redis_cache_settings_reference_cache_alias(self) -> None:
        settings = DefaultSettings()

        self.assertEqual("CACHE", settings.cache.client)
        self.assertEqual("main", settings.cache.namespace)
        self.assertEqual("pickle", settings.cache.serializer)

    def test_redis_protocol_accepts_nested_yaml_values(self) -> None:
        settings = DefaultSettings.model_validate(
            {"redis": {"CACHE": {"protocol": 3}}}
        )

        self.assertEqual(3, settings.redis["CACHE"].protocol)

    def test_old_redis_fallback_constants_are_removed(self) -> None:
        self.assertFalse(hasattr(constants, "DEFAULT_REDIS_URL"))
        self.assertFalse(hasattr(constants, "REDIS_CONFIG"))
        self.assertEqual("redis", DEFAULT_DEPRECATED_SETTINGS_KEYS["REDIS_CONFIG"])


class AsyncRedisContractTest(unittest.IsolatedAsyncioTestCase):
    """The concrete Redis client must own one configurable async pool."""

    def test_redis_package_exposes_async_core_without_deferred_modules(self) -> None:
        redis_package = importlib.import_module("oldman.providers.redis")

        self.assertTrue(hasattr(redis_package, "AsyncRedis"))

    async def test_async_redis_passes_configured_pool_options(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        fake_pool = Mock()
        fake_pool.disconnect = AsyncMock()
        fake_connection = Mock()
        fake_connection.aclose = AsyncMock()
        client = AsyncRedis(
            "rediss://redis.example/3",
            max_connections=12,
            health_check_interval=7,
            protocol=3,
            retry_attempts=5,
            backoff_base=0.2,
            backoff_cap=4.0,
            socket_keepalive_idle=70,
            connection_socket_timeout=9,
            connection_retry_on_error=[RuntimeError],
        )

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", return_value=fake_pool) as pool_factory,
            patch("oldman.providers.redis.redis.aioredis.Redis", return_value=fake_connection) as redis_factory,
        ):
            connection = await client.async_get_conn()

        self.assertIs(fake_connection, connection)
        pool_options = pool_factory.call_args.kwargs
        self.assertEqual(12, pool_options["max_connections"])
        self.assertEqual(7, pool_options["health_check_interval"])
        self.assertEqual(9, pool_options["socket_timeout"])
        self.assertEqual([RuntimeError], pool_options["retry_on_error"])
        self.assertEqual(3, pool_options["protocol"])
        self.assertTrue(pool_options["socket_keepalive"])
        self.assertEqual(70, pool_options["socket_keepalive_options"][socket.TCP_KEEPIDLE])
        self.assertEqual(5, pool_options["retry"]._retries)
        redis_factory.assert_called_once_with(connection_pool=fake_pool)

    async def test_async_redis_omits_tcp_keepalive_for_unix_socket(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        fake_pool = Mock()
        fake_pool.disconnect = AsyncMock()
        fake_connection = Mock()
        fake_connection.aclose = AsyncMock()
        client = AsyncRedis("unix:///var/run/redis/redis.sock?db=3")

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", return_value=fake_pool) as pool_factory,
            patch("oldman.providers.redis.redis.aioredis.Redis", return_value=fake_connection),
        ):
            await client.async_get_conn()

        self.assertNotIn("socket_keepalive", pool_factory.call_args.kwargs)
        self.assertNotIn("socket_keepalive_options", pool_factory.call_args.kwargs)

    async def test_async_redis_can_disable_timeout_retries(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        fake_pool = Mock()
        fake_pool.disconnect = AsyncMock()
        fake_connection = Mock()
        fake_connection.aclose = AsyncMock()
        client = AsyncRedis("redis://localhost:6379/0", retry_on_timeout=False)

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", return_value=fake_pool) as pool_factory,
            patch("oldman.providers.redis.redis.aioredis.Redis", return_value=fake_connection),
        ):
            await client.async_get_conn()

        pool_options = pool_factory.call_args.kwargs
        self.assertNotIn("retry_on_error", pool_options)
        self.assertIn(RedisConnectionError, pool_options["retry"]._supported_errors)
        self.assertNotIn(RedisTimeoutError, pool_options["retry"]._supported_errors)

    async def test_async_redis_uses_init_mutex_instead_of_command_semaphore(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        client = AsyncRedis("redis://localhost:6379/0")

        self.assertIsInstance(client._init_lock, asyncio.Lock)
        self.assertFalse(hasattr(client, "_semaphore"))

    async def test_async_redis_initializes_once_under_concurrency(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        fake_pool = Mock()
        fake_pool.disconnect = AsyncMock()
        fake_connection = Mock()
        fake_connection.aclose = AsyncMock()
        client = AsyncRedis("redis://localhost:6379/0")

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", return_value=fake_pool) as pool_factory,
            patch("oldman.providers.redis.redis.aioredis.Redis", return_value=fake_connection) as redis_factory,
        ):
            connections = await asyncio.gather(*(client.async_get_conn() for _ in range(20)))

        self.assertTrue(all(connection is fake_connection for connection in connections))
        pool_factory.assert_called_once()
        redis_factory.assert_called_once()

    async def test_async_redis_close_is_idempotent_and_allows_reinitialization(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        pools = [Mock(), Mock()]
        connections = [Mock(), Mock()]
        for pool in pools:
            pool.disconnect = AsyncMock()
        for connection in connections:
            connection.aclose = AsyncMock()
        client = AsyncRedis("redis://localhost:6379/0")

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", side_effect=pools) as pool_factory,
            patch("oldman.providers.redis.redis.aioredis.Redis", side_effect=connections),
        ):
            self.assertIs(connections[0], await client.async_get_conn())
            await client.close()
            await client.close()
            self.assertIs(connections[1], await client.async_get_conn())

        self.assertEqual(2, pool_factory.call_count)
        connections[0].aclose.assert_awaited_once()
        pools[0].disconnect.assert_awaited_once()

    async def test_async_redis_cleans_pool_when_client_construction_fails(self) -> None:
        from oldman.providers.redis.redis import AsyncRedis

        fake_pool = Mock()
        fake_pool.disconnect = AsyncMock()
        client = AsyncRedis("redis://localhost:6379/0")

        with (
            patch("oldman.providers.redis.redis.aioredis.ConnectionPool.from_url", return_value=fake_pool),
            patch("oldman.providers.redis.redis.aioredis.Redis", side_effect=RuntimeError("client failed")),
            self.assertRaisesRegex(RuntimeError, "client failed"),
        ):
            await client.async_get_conn()

        fake_pool.disconnect.assert_awaited_once()
        self.assertIsNone(client._pool)
        self.assertIsNone(client._conn)


class _FakeAsyncRedis:
    """Observable concrete client used to test the registry without Redis I/O."""

    created: list[_FakeAsyncRedis] = []

    def __init__(self, **options: object) -> None:
        self.options = options
        self.connection = object()
        self.close_count = 0
        self.fail_close = False
        self.lock_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        type(self).created.append(self)

    async def async_get_conn(self) -> object:
        return self.connection

    async def close(self) -> None:
        self.close_count += 1
        if self.fail_close:
            raise RuntimeError("close failed")

    async def get_db_lock(self, *args: object, **kwargs: object) -> bool:
        self.lock_calls.append(("get_db_lock", args, kwargs))
        return True

    async def is_db_lock(self, *args: object, **kwargs: object) -> bool:
        self.lock_calls.append(("is_db_lock", args, kwargs))
        return False

    async def acquire_lock(self, *args: object, **kwargs: object) -> str:
        self.lock_calls.append(("acquire_lock", args, kwargs))
        return "token"

    async def release_lock(self, *args: object, **kwargs: object) -> bool:
        self.lock_calls.append(("release_lock", args, kwargs))
        return True

    async def get_locker(self, *args: object, **kwargs: object) -> object:
        self.lock_calls.append(("get_locker", args, kwargs))
        return self.connection


class RedisRegistryContractTest(unittest.IsolatedAsyncioTestCase):
    """The global shape is one registry with lazy alias-bound clients."""

    def setUp(self) -> None:
        _FakeAsyncRedis.created.clear()

    def test_using_is_lazy_case_sensitive_and_rejects_missing_alias(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)

        cache_client = registry.using("CACHE")

        self.assertIs(cache_client, registry.using("CACHE"))
        self.assertEqual([], _FakeAsyncRedis.created)
        with self.assertRaisesRegex(LookupError, "cache"):
            registry.using("cache")

    async def test_registry_caches_normal_and_binary_clients_per_alias(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            bound = registry.using("CACHE")
            normal = await bound.async_get_conn()
            same_normal = await bound.async_get_conn()
            binary = await bound.async_get_bin_conn()

        self.assertIs(normal, same_normal)
        self.assertIsNot(binary, normal)
        self.assertEqual([True, False], [client.options["decode_responses"] for client in _FakeAsyncRedis.created])

    async def test_registry_reuses_binary_client_when_alias_is_already_binary(self) -> None:
        redis_config = RedisConfig.model_validate({"CACHE": {"decode_responses": False}})
        registry = RedisClientRegistry(redis_config)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            bound = registry.using("CACHE")
            normal = await bound.async_get_conn()
            binary = await bound.async_get_bin_conn()

        self.assertIs(normal, binary)
        self.assertEqual(1, len(_FakeAsyncRedis.created))

    async def test_registry_default_methods_use_default_alias(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            await registry.async_get_conn()

        self.assertEqual("unix:///var/run/redis/redis.sock?db=3", _FakeAsyncRedis.created[0].options["redis_url"])

    async def test_registry_preserves_flat_connection_options_for_concrete_client(self) -> None:
        redis_config = RedisConfig.model_validate(
            {
                "ANALYTICS": {
                    "redis_url": "redis://localhost:6379/8",
                    "protocol": 3,
                    "connection_socket_timeout": 20,
                }
            }
        )
        registry = RedisClientRegistry(redis_config)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            await registry.using("ANALYTICS").async_get_conn()

        self.assertEqual(20, _FakeAsyncRedis.created[0].options["connection_socket_timeout"])
        self.assertEqual(3, _FakeAsyncRedis.created[0].options["protocol"])
        self.assertNotIn("socket_timeout", _FakeAsyncRedis.created[0].options)

    async def test_registry_delegates_lock_helpers_to_the_bound_alias(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            result = await registry.using("CACHE").get_db_lock("job", expire_timeout=12)

        self.assertTrue(result)
        self.assertEqual(
            [("get_db_lock", ("job",), {"expire_timeout": 12})],
            _FakeAsyncRedis.created[0].lock_calls,
        )

    async def test_registry_close_attempts_every_client_and_allows_recreation(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)
        with patch("oldman.providers.redis.client.AsyncRedis", _FakeAsyncRedis):
            await registry.using("DEFAULT").async_get_conn()
            await registry.using("CACHE").async_get_bin_conn()
            first_clients = tuple(_FakeAsyncRedis.created)
            first_clients[0].fail_close = True

            with self.assertRaisesRegex(BaseExceptionGroup, "Redis clients failed to close"):
                await registry.close()

            self.assertEqual([1, 1], [client.close_count for client in first_clients])
            await registry.using("DEFAULT").async_get_conn()

        self.assertEqual(3, len(_FakeAsyncRedis.created))

    def test_public_package_exports_only_redis_core(self) -> None:
        redis_package = importlib.import_module("oldman.providers.redis")

        for name in (
            "AsyncRedis",
            "RedisAliasClient",
            "RedisAliasNotConfiguredError",
            "RedisClientRegistry",
            "redis_client",
        ):
            self.assertTrue(hasattr(redis_package, name), name)
        for name in (
            "AsyncRedisClient",
            "SettingsBoundAsyncRedis",
            "SyncRedis",
            "SyncRedisClient",
            "redis_bin_client",
            "redis_cache_client",
        ):
            self.assertFalse(hasattr(redis_package, name), name)

    def test_obsolete_fixed_alias_module_is_removed(self) -> None:
        provider_root = Path(__file__).resolve().parents[1] / "oldman" / "providers" / "redis"

        self.assertFalse((provider_root / "async_redis.py").exists())


if __name__ == "__main__":
    unittest.main()
