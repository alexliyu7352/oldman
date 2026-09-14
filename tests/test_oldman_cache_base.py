from __future__ import annotations

import asyncio
import fnmatch
import unittest
from typing import Any

from oldman.cache.base import SENTINEL, BaseCache
from oldman.serializers.cache import NullSerializer


class RecordingCache(BaseCache):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.values: dict[str, Any] = {}
        self.set_ttls: list[float | None] = []

    async def _get(self, key: str) -> Any | None:
        return self.values.get(key)

    async def _set(self, key: str, value: Any, ttl: float | None) -> bool:
        self.values[key] = value
        self.set_ttls.append(ttl)
        return True

    async def _add(self, key: str, value: Any, ttl: float | None) -> bool:
        if key in self.values:
            raise ValueError("exists")
        return await self._set(key, value, ttl)

    async def _multi_get(self, keys: list[str]) -> list[Any | None]:
        return [self.values.get(key) for key in keys]

    async def _multi_set(self, pairs: list[tuple[str, Any]], ttl: float | None) -> bool:
        self.values.update(pairs)
        self.set_ttls.append(ttl)
        return True

    async def _delete(self, key: str) -> int:
        return int(self.values.pop(key, SENTINEL) is not SENTINEL)

    async def _delete_match(self, pattern: str) -> int:
        matches = [key for key in self.values if fnmatch.fnmatchcase(key, pattern)]
        for key in matches:
            self.values.pop(key)
        return len(matches)

    async def _exists(self, key: str) -> bool:
        return key in self.values

    async def _expire(self, key: str, ttl: float) -> bool:
        return key in self.values

    async def _ttl(self, key: str) -> float | int:
        return -1 if key in self.values else -2

    async def _clear(self) -> bool:
        self.values.clear()
        return True

    async def _close(self) -> None:
        self.values.clear()


class SlowRecordingCache(RecordingCache):
    async def _get(self, key: str) -> Any | None:
        await asyncio.sleep(0.02)
        return await super()._get(key)


class BaseCacheContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_namespace_key_conversion_and_codec_overrides(self) -> None:
        cache = RecordingCache(namespace="main", serializer=NullSerializer())
        await cache.set(42, "encoded", dumps_fn=lambda value: f"<{value}>")
        self.assertEqual({"main:42": "<encoded>"}, cache.values)
        self.assertEqual("encoded", await cache.get(42, loads_fn=lambda value: value[1:-1]))

    async def test_default_ttl_and_operation_override_are_distinct(self) -> None:
        cache = RecordingCache(ttl=30)
        await cache.set("default", 1)
        await cache.set("forever", 2, ttl=None)
        self.assertEqual([30.0, None], cache.set_ttls)

    async def test_timeout_override_raises_asyncio_timeout_error(self) -> None:
        cache = SlowRecordingCache(timeout=0.01)
        with self.assertRaises(asyncio.TimeoutError):
            await cache.get("slow")
        self.assertIsNone(await cache.get("slow", timeout=None))

    async def test_context_manager_closes_cache(self) -> None:
        async with RecordingCache() as cache:
            await cache.set("key", "value")
        self.assertEqual({}, cache.values)

    async def test_public_operations_delegate_with_namespaced_keys(self) -> None:
        cache = RecordingCache(namespace="main")

        self.assertTrue(await cache.add("one", 1))
        with self.assertRaisesRegex(ValueError, "exists"):
            await cache.add("one", 2)
        self.assertTrue(await cache.multi_set((("two", 2), (3, 3)), ttl=5))
        self.assertEqual([1, 2, 3, None], await cache.multi_get(("one", "two", 3, "missing")))
        self.assertTrue(await cache.exists("two"))
        self.assertTrue(await cache.expire("two", 10))
        self.assertEqual(-1, await cache.ttl("two"))
        self.assertEqual(1, await cache.delete_match("t*"))
        self.assertEqual(1, await cache.delete("one"))
        self.assertEqual(0, await cache.delete("missing"))
        self.assertTrue(await cache.clear())
