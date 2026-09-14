"""Real-Redis acceptance tests for the dynamic settings container."""

from __future__ import annotations

import asyncio
import unittest
import uuid

from redis.exceptions import ResponseError

from oldman.conf.containers import RedisSettings
from oldman.conf.schemas import DefaultSettings
from oldman.providers.redis.client import RedisClientRegistry


class RedisSettingsIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Verify settings types and Redis-native structures against real Redis."""

    async def asyncSetUp(self) -> None:
        """Create an isolated namespace on the configured DEFAULT Redis database."""
        self.registry = RedisClientRegistry(DefaultSettings().redis)
        self.client = self.registry.using("DEFAULT")
        self.namespace = f"oldman-test:settings:{uuid.uuid4().hex}"
        self.settings = RedisSettings(self.client, namespace=self.namespace)
        self.connection = await self.client.async_get_bin_conn()
        self.keys: set[str] = set()

    async def asyncTearDown(self) -> None:
        """Delete only keys owned by this test and close its client registry."""
        if self.keys:
            await self.connection.delete(*self.keys)
        await self.registry.close()

    def redis_key(self, name: str) -> str:
        """Track and return one exact Redis key owned by this test."""
        key = f"{self.namespace}:{name}"
        self.keys.add(key)
        return key

    async def test_values_ttl_sets_and_lists_use_expected_redis_types(self) -> None:
        """Round-trip typed values while retaining String, Set, and List storage."""
        scalar_key = self.redis_key("scalar")
        set_key = self.redis_key("set")
        list_key = self.redis_key("list")
        ttl_key = self.redis_key("ttl")

        for value in (False, 0, 1.5, "text", b"bytes"):
            await self.settings.set_value("scalar", value)
            loaded = await self.settings.get_value("scalar")
            self.assertEqual(value, loaded)
            self.assertIs(type(value), type(loaded))

        await self.settings.add_set_member("set", False)
        await self.settings.add_set_member("set", "enabled")
        await self.settings.append_list_item("list", "second")
        await self.settings.prepend_list_item("list", "first")
        await self.settings.set_value("ttl", True, ttl=1)

        self.assertEqual({False, "enabled"}, await self.settings.get_set_members("set"))
        self.assertEqual(["first", "second"], await self.settings.get_list_items("list"))
        self.assertEqual(b"string", await self.connection.type(scalar_key))
        self.assertEqual(b"set", await self.connection.type(set_key))
        self.assertEqual(b"list", await self.connection.type(list_key))
        self.assertGreater(await self.connection.pttl(ttl_key), 0)

        await asyncio.sleep(1.1)
        self.assertIsNone(await self.settings.get_value("ttl"))

    async def test_wrong_redis_type_errors_are_not_hidden(self) -> None:
        """Expose Redis WRONGTYPE errors instead of silently replacing data."""
        key = self.redis_key("wrong-type")
        await self.connection.set(key, b"scalar")

        with self.assertRaisesRegex(ResponseError, "WRONGTYPE"):
            await self.settings.add_set_member("wrong-type", "member")


if __name__ == "__main__":
    unittest.main()
