"""Target-owned cache boundary behavior."""

from __future__ import annotations

import asyncio
import unittest

from oldman.cache.backends.memory import MemoryCache


class OldmanCacheBoundariesTest(unittest.TestCase):
    def test_memory_cache_implements_backend_get_set_delete_contract(self) -> None:
        async def scenario() -> None:
            cache = MemoryCache()
            self.assertIsNone(await cache.get("answer"))
            await cache.set("answer", {"value": 42})
            self.assertEqual({"value": 42}, await cache.get("answer"))
            await cache.delete("answer")
            self.assertIsNone(await cache.get("answer"))

        asyncio.run(scenario())

    def test_memory_cache_expires_entries_at_the_declared_ttl(self) -> None:
        async def scenario() -> None:
            cache = MemoryCache()
            await cache.set("answer", 42, ttl=0.01)
            self.assertEqual(42, await cache.get("answer"))
            await asyncio.sleep(0.02)
            self.assertIsNone(await cache.get("answer"))
            self.assertNotIn("answer", cache._cache)
            self.assertNotIn("answer", cache._handlers)

        asyncio.run(scenario())

if __name__ == "__main__":
    unittest.main()
