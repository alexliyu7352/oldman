"""Behavior tests for the native in-process memory cache."""

from __future__ import annotations

import unittest

from oldman.cache.backends import memory_cache as exported_memory_cache
from oldman.cache.backends.memory import MemoryCache
from oldman.cache.backends.memory import memory_cache as module_memory_cache


class MemoryCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_values_are_never_evicted_for_capacity(self) -> None:
        cache = MemoryCache()
        for index in range(2_000):
            await cache.set(f"key-{index}", index)
        self.assertEqual(2_000, len(cache._cache))
        self.assertEqual(0, await cache.get("key-0"))

    async def test_replacing_ttl_cancels_previous_timer(self) -> None:
        cache = MemoryCache(namespace="main")
        await cache.set("key", "old", ttl=10)
        old_handle = cache._handlers["main:key"]
        await cache.set("key", "new", ttl=20)
        self.assertTrue(old_handle.cancelled())
        self.assertIn("main:key", cache._handlers)
        self.assertNotIn("key", cache._handlers)

    async def test_overwriting_without_ttl_removes_previous_timer(self) -> None:
        cache = MemoryCache()
        await cache.set("key", "old", ttl=10)
        old_handle = cache._handlers["key"]
        await cache.set("key", "new")
        self.assertTrue(old_handle.cancelled())
        self.assertEqual(-1, await cache.ttl("key"))

    async def test_falsy_and_none_values_can_be_deleted(self) -> None:
        cache = MemoryCache()
        for value in (None, False, 0, ""):
            await cache.set("key", value)
            self.assertEqual(1, await cache.delete("key"))

    async def test_ttl_and_expire_contract(self) -> None:
        cache = MemoryCache()
        self.assertEqual(-2, await cache.ttl("missing"))
        await cache.set("forever", 1)
        self.assertEqual(-1, await cache.ttl("forever"))
        await cache.expire("forever", 0.2)
        ttl = await cache.ttl("forever")
        self.assertIsInstance(ttl, float)
        self.assertGreater(ttl, 0)
        # uvloop stores sub-second deadlines with finite precision.
        self.assertLessEqual(ttl, 0.201)

    async def test_expire_replaces_existing_timer(self) -> None:
        cache = MemoryCache()
        await cache.set("key", "value", ttl=30)
        old_handle = cache._handlers["key"]
        self.assertTrue(await cache.expire("key", 20))
        self.assertTrue(old_handle.cancelled())
        self.assertIsNot(old_handle, cache._handlers["key"])

    async def test_expire_zero_removes_timer_and_persists_value(self) -> None:
        cache = MemoryCache()
        await cache.set("key", "value", ttl=30)
        old_handle = cache._handlers["key"]
        self.assertTrue(await cache.expire("key", 0))
        self.assertTrue(old_handle.cancelled())
        self.assertNotIn("key", cache._handlers)
        self.assertEqual(-1, await cache.ttl("key"))
        self.assertEqual("value", await cache.get("key"))

    async def test_expire_missing_key_returns_false(self) -> None:
        cache = MemoryCache()
        self.assertFalse(await cache.expire("missing", 10))

    async def test_delete_match_is_namespace_scoped(self) -> None:
        cache = MemoryCache(namespace="main")
        await cache.multi_set([("user:1", 1), ("user:2", 2), ("job:1", 3)], ttl=30)
        user_handles = [cache._handlers["main:user:1"], cache._handlers["main:user:2"]]
        job_handle = cache._handlers["main:job:1"]
        self.assertEqual(2, await cache.delete_match("user:*"))
        self.assertTrue(all(handle.cancelled() for handle in user_handles))
        self.assertNotIn("main:user:1", cache._handlers)
        self.assertNotIn("main:user:2", cache._handlers)
        self.assertFalse(job_handle.cancelled())
        self.assertIs(job_handle, cache._handlers["main:job:1"])
        self.assertEqual(3, await cache.get("job:1"))

    async def test_multi_get_preserves_order_and_missing_placeholders(self) -> None:
        cache = MemoryCache()
        await cache.multi_set([("one", 1), ("two", 2)])
        self.assertEqual([2, None, 1, 2], await cache.multi_get(["two", "missing", "one", "two"]))

    async def test_multi_set_ttl_creates_a_handle_for_each_namespaced_key(self) -> None:
        cache = MemoryCache(namespace="main")
        await cache.multi_set([("one", 1), ("two", 2)], ttl=30)
        self.assertEqual({"main:one", "main:two"}, cache._handlers.keys())
        self.assertTrue(all(not handle.cancelled() for handle in cache._handlers.values()))

    async def test_delete_cancels_and_removes_timer(self) -> None:
        cache = MemoryCache()
        await cache.set("key", "value", ttl=30)
        handle = cache._handlers["key"]
        self.assertEqual(1, await cache.delete("key"))
        self.assertTrue(handle.cancelled())
        self.assertNotIn("key", cache._handlers)

    async def test_clear_cancels_timers_and_clears_values(self) -> None:
        cache = MemoryCache()
        await cache.multi_set([("one", 1), ("two", 2)], ttl=30)
        handles = list(cache._handlers.values())
        self.assertTrue(await cache.clear())
        self.assertTrue(all(handle.cancelled() for handle in handles))
        self.assertEqual({}, cache._cache)
        self.assertEqual({}, cache._handlers)

    async def test_close_cancels_timers_and_clears_values(self) -> None:
        cache = MemoryCache()
        await cache.set("key", "value", ttl=30)
        handle = cache._handlers["key"]
        await cache.close()
        self.assertTrue(handle.cancelled())
        self.assertEqual({}, cache._cache)
        self.assertEqual({}, cache._handlers)

    def test_backend_package_reexports_the_module_singleton(self) -> None:
        self.assertIs(exported_memory_cache, module_memory_cache)
        self.assertIsInstance(exported_memory_cache, MemoryCache)


if __name__ == "__main__":
    unittest.main()
