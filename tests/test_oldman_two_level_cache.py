"""Behavior tests for explicit two-level cache composition."""

from __future__ import annotations

import unittest
from typing import Any, cast

from oldman.cache.base import BaseCache, CacheKey
from oldman.cache.two_level import TwoLevelCache


class RecordingCache:
    def __init__(
        self,
        order: list[str] | None = None,
        name: str = "",
        *,
        get_result: Any = None,
        ttl_result: float | int = -1,
        set_error: Exception | None = None,
        delete_error: Exception | None = None,
        clear_error: Exception | None = None,
    ) -> None:
        self.order = order
        self.name = name
        self.get_result = get_result
        self.ttl_result = ttl_result
        self.set_error = set_error
        self.delete_error = delete_error
        self.clear_error = clear_error
        self.calls: list[tuple[Any, ...]] = []
        self.read_calls: list[tuple[str, CacheKey]] = []

    async def get(self, key: CacheKey) -> Any:
        self.read_calls.append(("get", key))
        return self.get_result

    async def ttl(self, key: CacheKey) -> float | int:
        self.read_calls.append(("ttl", key))
        return self.ttl_result

    async def set(self, key: CacheKey, value: Any, ttl: float | None = None) -> None:
        if self.set_error is not None:
            raise self.set_error
        self.calls.append(("set", key, value, ttl))
        if self.order is not None:
            self.order.append(f"{self.name}:set")

    async def delete(self, key: CacheKey) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.calls.append(("delete", key))
        if self.order is not None:
            self.order.append(f"{self.name}:delete")

    async def clear(self) -> None:
        if self.clear_error is not None:
            raise self.clear_error
        self.calls.append(("clear",))
        if self.order is not None:
            self.order.append(f"{self.name}:clear")


class TwoLevelCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_memory_hit_skips_redis(self) -> None:
        memory = RecordingCache(get_result="memory-value")
        redis = RecordingCache(get_result="redis-value")
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        self.assertEqual("memory-value", await cache.get("key"))
        self.assertEqual([("get", "key")], memory.read_calls)
        self.assertEqual([], redis.read_calls)
        self.assertEqual([], memory.calls)

    async def test_redis_miss_returns_default_without_ttl_lookup(self) -> None:
        memory = RecordingCache(get_result=None)
        redis = RecordingCache(get_result=None)
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))
        default = object()

        self.assertIs(default, await cache.get("key", default=default))
        self.assertEqual([("get", "key")], redis.read_calls)
        self.assertEqual([], memory.calls)

    async def test_redis_hit_backfills_memory_with_remaining_ttl(self) -> None:
        memory = RecordingCache(get_result=None)
        redis = RecordingCache(get_result="value", ttl_result=1.25)
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        self.assertEqual("value", await cache.get("key"))
        self.assertEqual([("get", "key"), ("ttl", "key")], redis.read_calls)
        self.assertEqual([("set", "key", "value", 1.25)], memory.calls)

    async def test_missing_after_ttl_race_is_not_backfilled(self) -> None:
        memory = RecordingCache(get_result=None)
        redis = RecordingCache(get_result="value", ttl_result=-2)
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        self.assertEqual("value", await cache.get("key"))
        self.assertFalse(any(call[0] == "set" for call in memory.calls))

    async def test_expired_zero_remaining_ttl_is_not_backfilled(self) -> None:
        memory = RecordingCache(get_result=None)
        redis = RecordingCache(get_result="value", ttl_result=0)
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        self.assertEqual("value", await cache.get("key"))
        self.assertEqual([("get", "key"), ("ttl", "key")], redis.read_calls)
        self.assertFalse(any(call[0] == "set" for call in memory.calls))

    async def test_persistent_redis_value_is_backfilled_without_ttl(self) -> None:
        memory = RecordingCache(get_result=None)
        redis = RecordingCache(get_result="value", ttl_result=-1)
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        self.assertEqual("value", await cache.get("key"))
        self.assertEqual([("set", "key", "value", None)], memory.calls)

    async def test_explicit_ttl_override_skips_redis_ttl_lookup(self) -> None:
        for ttl in (None, 0, 3.5):
            with self.subTest(ttl=ttl):
                memory = RecordingCache(get_result=None)
                redis = RecordingCache(get_result="value", ttl_result=99)
                cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

                self.assertEqual("value", await cache.get("key", ttl=ttl))
                self.assertEqual([("get", "key")], redis.read_calls)
                self.assertEqual([("set", "key", "value", ttl)], memory.calls)

    async def test_set_delete_and_clear_run_redis_first(self) -> None:
        order: list[str] = []
        memory = RecordingCache(order, "memory")
        redis = RecordingCache(order, "redis")
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))

        await cache.set("key", "value", ttl=10)
        await cache.delete("key")
        await cache.clear()

        self.assertEqual(
            ["redis:set", "memory:set", "redis:delete", "memory:delete", "redis:clear", "memory:clear"],
            order,
        )

    async def test_redis_mutation_failures_do_not_touch_memory(self) -> None:
        memory = RecordingCache()
        redis = RecordingCache(set_error=ConnectionError("offline"))
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))
        with self.assertRaises(ConnectionError):
            await cache.set("key", "value")
        self.assertEqual([], memory.calls)

        memory = RecordingCache()
        redis = RecordingCache(delete_error=ConnectionError("offline"))
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))
        with self.assertRaises(ConnectionError):
            await cache.delete("key")
        self.assertEqual([], memory.calls)

        memory = RecordingCache()
        redis = RecordingCache(clear_error=ConnectionError("offline"))
        cache = TwoLevelCache(cast(BaseCache, memory), cast(BaseCache, redis))
        with self.assertRaises(ConnectionError):
            await cache.clear()
        self.assertEqual([], memory.calls)


if __name__ == "__main__":
    unittest.main()
