"""Behavior contracts for Redis-backed dynamic settings."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import msgspec

from oldman.conf.containers import RedisSettings


class FakeBinarySettingsConnection:
    """Store binary Redis String values for isolated settings tests."""

    def __init__(self) -> None:
        """Initialize an empty key/value store and command log."""
        self.values: dict[str, bytes] = {}
        self.sets: dict[str, set[bytes]] = {}
        self.lists: dict[str, list[bytes]] = {}
        self.calls: list[tuple[Any, ...]] = []

    async def get(self, key: str) -> bytes | None:
        """Return the raw bytes stored at key."""
        self.calls.append(("get", key))
        return self.values.get(key)

    async def set(self, key: str, value: bytes, *, ex: int | None = None) -> bool:
        """Store raw bytes with an optional second-based expiry argument."""
        self.calls.append(("set", key, value, ex))
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        """Delete key and return the number of removed entries."""
        self.calls.append(("delete", key))
        deleted = False
        for store in (self.values, self.sets, self.lists):
            deleted = store.pop(key, None) is not None or deleted
        return int(deleted)

    async def sadd(self, key: str, value: bytes) -> int:
        """Add one raw member and return whether the set changed."""
        members = self.sets.setdefault(key, set())
        size = len(members)
        members.add(value)
        return int(len(members) != size)

    async def srem(self, key: str, value: bytes) -> int:
        """Remove one raw member and return whether it existed."""
        members = self.sets.get(key, set())
        if value not in members:
            return 0
        members.remove(value)
        return 1

    async def smembers(self, key: str) -> set[bytes]:
        """Return a copy of every raw set member."""
        return set(self.sets.get(key, set()))

    async def sismember(self, key: str, value: bytes) -> int:
        """Return whether the raw member exists."""
        return int(value in self.sets.get(key, set()))

    async def srandmember(self, key: str) -> bytes | None:
        """Return a deterministic member for isolated tests."""
        members = self.sets.get(key, set())
        return next(iter(members), None)

    async def rpush(self, key: str, value: bytes) -> int:
        """Append one raw item and return the new length."""
        items = self.lists.setdefault(key, [])
        items.append(value)
        return len(items)

    async def lpush(self, key: str, value: bytes) -> int:
        """Prepend one raw item and return the new length."""
        items = self.lists.setdefault(key, [])
        items.insert(0, value)
        return len(items)

    async def lpop(self, key: str) -> bytes | None:
        """Pop the first raw item when present."""
        items = self.lists.get(key, [])
        return items.pop(0) if items else None

    async def rpop(self, key: str) -> bytes | None:
        """Pop the last raw item when present."""
        items = self.lists.get(key, [])
        return items.pop() if items else None

    async def lrange(self, key: str, start: int, stop: int) -> list[bytes]:
        """Return one inclusive raw list range."""
        items = self.lists.get(key, [])
        end = len(items) if stop == -1 else stop + 1
        return items[start:end]


class FakeRedisSettingsClient:
    """Expose one fake binary connection and count lazy resolutions."""

    def __init__(self) -> None:
        """Create the fake connection without resolving it."""
        self.connection = FakeBinarySettingsConnection()
        self.connection_count = 0

    async def async_get_bin_conn(self) -> FakeBinarySettingsConnection:
        """Return the fake binary connection."""
        self.connection_count += 1
        return self.connection


class RedisSettingsScalarTest(unittest.IsolatedAsyncioTestCase):
    """Verify scalar settings typing, validation, and lazy client binding."""

    async def test_scalar_values_round_trip_without_losing_falsey_types(self) -> None:
        """MsgPack must preserve every supported scalar type and falsey value."""
        client = FakeRedisSettingsClient()
        settings = RedisSettings(client, namespace="config")

        for index, value in enumerate((False, 0, 1.5, "", "text", b"bytes")):
            with self.subTest(value=value):
                key = f"value-{index}"
                await settings.set_value(key, value)
                loaded = await settings.get_value(key)
                self.assertEqual(value, loaded)
                self.assertIs(type(value), type(loaded))

        self.assertEqual("fallback", await settings.get_value("missing", default="fallback"))

    async def test_ttl_and_delete_keep_explicit_success_semantics(self) -> None:
        """A scalar write forwards TTL while delete reports actual removal."""
        client = FakeRedisSettingsClient()
        settings = RedisSettings(client, namespace="config")

        self.assertIsNone(await settings.set_value("enabled", True, ttl=30))
        set_call = next(call for call in client.connection.calls if call[0] == "set")
        self.assertEqual(("set", "config:enabled"), set_call[:2])
        self.assertEqual(30, set_call[3])
        self.assertTrue(await settings.delete("enabled"))
        self.assertFalse(await settings.delete("enabled"))

    async def test_default_client_is_resolved_only_on_first_operation(self) -> None:
        """Constructing RedisSettings must not touch the global DEFAULT pool."""
        registry = FakeRedisSettingsClient()
        settings = RedisSettings(namespace="config")

        with patch("oldman.providers.redis.redis_client", registry):
            self.assertEqual(0, registry.connection_count)
            await settings.set_value("enabled", True)

        self.assertEqual(1, registry.connection_count)

    async def test_invalid_values_are_rejected_before_redis_access(self) -> None:
        """Only the approved primitive settings types may reach Redis."""
        client = FakeRedisSettingsClient()
        settings = RedisSettings(client)

        for value in (None, [], {}, set()):
            with self.subTest(value=value), self.assertRaises(TypeError):
                await settings.set_value("invalid", value)  # type: ignore[arg-type]

        self.assertEqual(0, client.connection_count)

    async def test_operation_key_is_validated_before_redis_access(self) -> None:
        """An empty or non-string setting key is a local API error."""
        client = FakeRedisSettingsClient()
        settings = RedisSettings(client)

        for key in ("", 1):
            with self.subTest(key=key), self.assertRaises(ValueError):
                await settings.get_value(key)  # type: ignore[arg-type]

        self.assertEqual(0, client.connection_count)

    async def test_corrupt_msgpack_is_not_reported_as_missing(self) -> None:
        """Invalid stored bytes must raise instead of selecting the default."""
        client = FakeRedisSettingsClient()
        client.connection.values["config:broken"] = b"\xc1"
        settings = RedisSettings(client, namespace="config")

        with self.assertRaises(msgspec.DecodeError):
            await settings.get_value("broken", default="fallback")

    def test_namespace_must_be_a_non_empty_string(self) -> None:
        """The container namespace must own an unambiguous Redis prefix."""
        for namespace in ("", 1):
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                RedisSettings(namespace=namespace)  # type: ignore[arg-type]


class RedisSettingsCollectionTest(unittest.IsolatedAsyncioTestCase):
    """Verify configuration-oriented Set and List behavior."""

    async def test_set_members_keep_python_types_and_change_results(self) -> None:
        """Set methods preserve types and report whether membership changed."""
        settings = RedisSettings(FakeRedisSettingsClient(), namespace="config")

        self.assertTrue(await settings.add_set_member("allowed", False))
        self.assertFalse(await settings.add_set_member("allowed", False))
        self.assertTrue(await settings.add_set_member("allowed", "US"))
        self.assertEqual({False, "US"}, await settings.get_set_members("allowed"))
        self.assertTrue(await settings.contains_set_member("allowed", False))
        self.assertTrue(await settings.remove_set_member("allowed", "US"))
        self.assertFalse(await settings.remove_set_member("allowed", "missing"))

    async def test_empty_and_random_set_results_have_configuration_semantics(self) -> None:
        """Missing sets are empty and random lookup returns a decoded value."""
        settings = RedisSettings(FakeRedisSettingsClient(), namespace="config")

        self.assertEqual(set(), await settings.get_set_members("missing"))
        self.assertIsNone(await settings.get_random_set_member("missing"))
        await settings.add_set_member("single", 7)
        value = await settings.get_random_set_member("single")
        self.assertEqual(7, value)
        self.assertIs(int, type(value))

    async def test_list_methods_have_explicit_and_stable_direction(self) -> None:
        """Append, prepend, and first/last pop use the named list sides."""
        settings = RedisSettings(FakeRedisSettingsClient(), namespace="config")

        self.assertEqual(1, await settings.append_list_item("hosts", "second"))
        self.assertEqual(2, await settings.prepend_list_item("hosts", "first"))
        self.assertEqual(["first", "second"], await settings.get_list_items("hosts"))
        self.assertEqual(["first"], await settings.get_list_items("hosts", 0, 0))
        self.assertEqual("first", await settings.pop_first_list_item("hosts"))
        self.assertEqual("second", await settings.pop_last_list_item("hosts"))
        self.assertIsNone(await settings.pop_last_list_item("hosts"))
        self.assertEqual([], await settings.get_list_items("missing"))

    async def test_collection_values_are_validated_before_redis_access(self) -> None:
        """Unsupported collection values fail before obtaining a connection."""
        client = FakeRedisSettingsClient()
        settings = RedisSettings(client)

        for operation in (settings.add_set_member, settings.append_list_item):
            with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                await operation("invalid", [1])  # type: ignore[arg-type]

        self.assertEqual(0, client.connection_count)


if __name__ == "__main__":
    unittest.main()
