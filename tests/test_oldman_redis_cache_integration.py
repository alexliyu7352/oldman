"""Real Redis acceptance tests for the native cache backend."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from collections.abc import Callable
from typing import Any

from oldman.cache.backends.memory import MemoryCache
from oldman.cache.backends.redis import RedisCache
from oldman.cache.base import SENTINEL, CacheKey
from oldman.cache.two_level import TwoLevelCache
from oldman.conf.schemas import DefaultSettings, RedisCacheConfig
from oldman.providers.redis.client import RedisClientRegistry


class ObservingMemoryCache(MemoryCache):
    """Record remote state when a two-level mutation reaches memory."""

    def __init__(self, remote: RedisCache, clear_probe: str) -> None:
        super().__init__()
        self.remote = remote
        self.clear_probe = clear_probe
        self.observations: list[tuple[str, Any]] = []

    async def set(
        self,
        key: CacheKey,
        value: Any,
        ttl: float | None | object = SENTINEL,
        dumps_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> bool:
        self.observations.append(("set", await self.remote.get(key)))
        return await super().set(key, value, ttl=ttl, dumps_fn=dumps_fn, timeout=timeout)

    async def delete(self, key: CacheKey, *, timeout: float | None | object = SENTINEL) -> int:
        self.observations.append(("delete", await self.remote.exists(key)))
        return await super().delete(key, timeout=timeout)

    async def clear(self, *, timeout: float | None | object = SENTINEL) -> bool:
        self.observations.append(("clear", await self.remote.exists(self.clear_probe)))
        return await super().clear(timeout=timeout)


class RealRedisCacheTest(unittest.IsolatedAsyncioTestCase):
    """Exercise Cache behavior against the configured local Redis service."""

    async def asyncSetUp(self) -> None:
        self.registry = RedisClientRegistry(DefaultSettings().redis)
        self.alias = self.registry.using("CACHE")
        self.namespace = f"oldman-test:{uuid.uuid4().hex}"
        self.cache = RedisCache(client=self.alias, namespace=self.namespace, serializer="pickle")
        self.conn = await self.alias.async_get_bin_conn()
        self.foreign_keys: list[bytes] = []

    async def asyncTearDown(self) -> None:
        try:
            try:
                await self.cache.clear()
            finally:
                if self.foreign_keys:
                    connection = await self.alias.async_get_bin_conn()
                    await connection.delete(*self.foreign_keys)
        finally:
            await self.registry.close()

    async def test_round_trips_ttl_batch_and_duplicate_add(self) -> None:
        await self.cache.set("round-trip", {"value": 1})
        self.assertEqual({"value": 1}, await self.cache.get("round-trip"))

        await self.cache.multi_set([("one", {"value": 1}), ("two", [2])], ttl=2.5)
        self.assertEqual(
            [{"value": 1}, [2], None],
            await self.cache.multi_get(["one", "two", "missing"]),
        )
        self.assertGreater(await self.cache.ttl("one"), 0)
        with self.assertRaises(ValueError):
            await self.cache.add("one", 9)

    async def test_delete_match_and_clear_preserve_foreign_keys(self) -> None:
        foreign = f"foreign:{uuid.uuid4().hex}".encode()
        self.foreign_keys.append(foreign)
        await self.conn.set(foreign, b"sentinel")

        await self.cache.multi_set([("user:1", 1), ("job:1", 2)])
        self.assertEqual(1, await self.cache.delete_match("user:*"))
        self.assertEqual(2, await self.cache.get("job:1"))
        await self.cache.clear()

        self.assertEqual(b"sentinel", await self.conn.get(foreign))
        self.assertIsNone(await self.cache.get("job:1"))

    async def test_configurable_serializers(self) -> None:
        for name in ("pickle", "msgpack", "json"):
            with self.subTest(serializer=name):
                cache = RedisCache(
                    client=self.alias,
                    namespace=f"{self.namespace}:{name}",
                    serializer=name,
                )
                await cache.set("key", {"index": 7})
                self.assertEqual({"index": 7}, await cache.get("key"))
                await cache.clear()

        null_cache = RedisCache(
            client=self.alias,
            namespace=f"{self.namespace}:null",
            serializer="null",
        )
        await null_cache.set("bytes", b"value")
        self.assertEqual(b"value", await null_cache.get("bytes"))
        await null_cache.clear()

    async def test_concurrent_first_access_uses_one_lazy_provider_client(self) -> None:
        registry = RedisClientRegistry(DefaultSettings().redis)
        alias = registry.using("CACHE")
        cache = RedisCache(
            client=alias,
            namespace=f"{self.namespace}:concurrent",
            serializer="pickle",
        )
        try:
            await asyncio.gather(*(cache.set(f"key-{index}", {"index": index}) for index in range(20)))
            connections = await asyncio.gather(*(alias.async_get_bin_conn() for _ in range(20)))
            self.assertTrue(all(connection is connections[0] for connection in connections))
            self.assertEqual({"index": 7}, await cache.get("key-7"))
        finally:
            try:
                await cache.clear()
            finally:
                await registry.close()

    async def test_registry_close_allows_lazy_reopen(self) -> None:
        await self.cache.set("lifecycle", {"open": 1})
        first_connection = await self.alias.async_get_bin_conn()

        await self.registry.close()

        reopened_connection = await self.alias.async_get_bin_conn()
        self.assertIsNot(first_connection, reopened_connection)
        self.assertEqual({"open": 1}, await self.cache.get("lifecycle"))

    async def test_integer_and_float_ttl_expire_and_report_redis_ttl_states(self) -> None:
        await self.cache.set("persistent", "value")
        await self.cache.set("integer", "value", ttl=2)
        await self.cache.set("float", "value", ttl=0.5)

        self.assertEqual(-1, await self.cache.ttl("persistent"))
        self.assertEqual(-2, await self.cache.ttl("missing"))
        self.assertGreater(await self.cache.ttl("integer"), 0)
        self.assertGreater(await self.cache.ttl("float"), 0)

        await asyncio.sleep(0.65)
        self.assertIsNone(await self.cache.get("float"))
        self.assertEqual(-2, await self.cache.ttl("float"))

        await asyncio.sleep(1.5)
        self.assertIsNone(await self.cache.get("integer"))
        self.assertEqual(-2, await self.cache.ttl("integer"))

    async def test_settings_source_binds_once_under_concurrent_first_access(self) -> None:
        source_calls = 0
        config = RedisCacheConfig(
            client="CACHE",
            namespace=f"{self.namespace}:settings",
            serializer="msgpack",
        )

        def settings_source() -> RedisCacheConfig:
            nonlocal source_calls
            source_calls += 1
            return config

        cache = RedisCache(settings_source=settings_source)
        redis_globals = RedisCache._prepare.__globals__
        original_registry = redis_globals["redis_client"]
        redis_globals["redis_client"] = self.registry
        try:
            await asyncio.gather(*(cache.set(f"key-{index}", {"index": index}) for index in range(20)))
            self.assertEqual({"index": 7}, await cache.get("key-7"))
            self.assertEqual(1, source_calls)
            self.assertEqual(config.namespace, cache.namespace)
            self.assertEqual("msgpack", cache.serializer.__class__.__name__.removesuffix("Serializer").casefold())
        finally:
            try:
                await cache.clear()
            finally:
                redis_globals["redis_client"] = original_registry

    async def test_special_glob_namespaces_do_not_delete_neighboring_namespaces(self) -> None:
        cases = (
            (f"{self.namespace}:literal*?", f"{self.namespace}:literal-AB"),
            (f"{self.namespace}:literal[ab]", f"{self.namespace}:literala"),
        )
        for special_namespace, neighboring_namespace in cases:
            with self.subTest(namespace=special_namespace):
                special = RedisCache(client=self.alias, namespace=special_namespace, serializer="pickle")
                neighbor = RedisCache(client=self.alias, namespace=neighboring_namespace, serializer="pickle")
                try:
                    await special.set("user:1", "special")
                    await neighbor.set("user:1", "neighbor")
                    self.assertEqual(1, await special.delete_match("user:*"))
                    self.assertEqual("neighbor", await neighbor.get("user:1"))
                finally:
                    await special.clear()
                    await neighbor.clear()

    async def test_real_two_level_cache_backfills_ttl_and_mutates_redis_first(self) -> None:
        remote = RedisCache(
            client=self.alias,
            namespace=f"{self.namespace}:two-level",
            serializer="pickle",
        )
        memory = ObservingMemoryCache(remote, clear_probe="clear-key")
        cache = TwoLevelCache(memory, remote)
        try:
            await remote.set("ttl-key", {"value": 7}, ttl=1.0)
            self.assertEqual({"value": 7}, await cache.get("ttl-key"))
            self.assertEqual({"value": 7}, await memory.get("ttl-key"))
            self.assertGreater(await memory.ttl("ttl-key"), 0)

            memory.observations.clear()
            await cache.set("ordered", "value", ttl=2)
            await cache.delete("ordered")
            await cache.set("clear-key", "clear")
            await cache.clear()

            self.assertEqual(
                [("set", "value"), ("delete", False), ("set", "clear"), ("clear", False)],
                memory.observations,
            )
        finally:
            try:
                await remote.clear()
            finally:
                await memory.close()


if __name__ == "__main__":
    unittest.main()
