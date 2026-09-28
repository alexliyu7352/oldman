"""RedisStore and RedisSet against a test-owned redis-server."""

from __future__ import annotations

import asyncio
import datetime as dt
import enum
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import msgspec

import oldman.conf as conf
from oldman.conf.containers import RedisSet, RedisStore
from oldman.conf.schemas import DefaultSettings
from oldman.providers.redis import RedisClientRegistry
from oldman.serializers import MsgspecModel
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server

NAMESPACE = "store_test"


class ThirdEmail(enum.IntEnum):
    DISABLED = 0
    SENDGRID = 1


class Limits(MsgspecModel):
    per_minute: int = 10


class CloudFlags(MsgspecModel):
    check_server: str | None = None
    allow_free_trial: bool = False
    third_email: ThirdEmail = ThirdEmail.DISABLED
    banner_until: dt.datetime | None = None
    limits: Limits = msgspec.field(default_factory=Limits)


class RedisStoreTestCase(unittest.IsolatedAsyncioTestCase):
    """One owned Redis for the class; each test gets an empty database and the service namespace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "store")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        self.registry = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"DEFAULT": 0}))
        self.client = self.registry.using("DEFAULT")
        self.connection = await self.client.async_get_bin_conn()
        await self.connection.flushdb()
        settings = DefaultSettings()
        settings.core.namespace = NAMESPACE
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))

    async def asyncTearDown(self) -> None:
        await self.registry.close()


class RedisStoreTest(RedisStoreTestCase):
    async def test_a_missing_key_reads_as_the_defaults_without_writing(self) -> None:
        store = RedisStore(CloudFlags, "cloud", client=self.client)

        self.assertEqual(CloudFlags(), await store.get())
        self.assertEqual(0, await self.connection.exists(f"{NAMESPACE}:store:cloud"))

    async def test_saved_values_keep_their_types(self) -> None:
        store = RedisStore(CloudFlags, "cloud", client=self.client)
        value = await store.get()
        value.check_server = "http://check"
        value.third_email = ThirdEmail.SENDGRID
        value.banner_until = dt.datetime(2026, 9, 27, 8, 30, tzinfo=dt.UTC)
        value.limits.per_minute = 30

        await store.save(value)
        loaded = await RedisStore(CloudFlags, "cloud", client=self.client).get()

        self.assertEqual(value, loaded)
        self.assertIs(ThirdEmail.SENDGRID, loaded.third_email)
        self.assertIsInstance(loaded.limits, Limits)
        self.assertEqual(b"string", await self.connection.type(f"{NAMESPACE}:store:cloud"))

    async def test_update_changes_named_fields_and_refuses_bad_ones_without_writing(self) -> None:
        store = RedisStore(CloudFlags, "cloud", client=self.client)
        await store.update(check_server="http://check")

        updated = await store.update(allow_free_trial=True)
        with self.assertRaises(TypeError):
            await store.update(allow_trial=True)
        with self.assertRaises(msgspec.ValidationError):
            await store.update(allow_free_trial="yes")

        self.assertEqual(CloudFlags(check_server="http://check", allow_free_trial=True), updated)
        self.assertEqual(updated, await store.get())

    async def test_every_read_sees_writes_from_other_instances(self) -> None:
        """No local cache: another process's write is visible to the next get()."""
        here = RedisStore(CloudFlags, "cloud", client=self.client)
        elsewhere = RedisStore(CloudFlags, "cloud", client=self.client)
        await here.get()

        await elsewhere.update(allow_free_trial=True)

        self.assertTrue((await here.get()).allow_free_trial)

    async def test_concurrent_updates_of_different_fields_keep_both(self) -> None:
        """Without the lock around read-modify-write, both updates start from the same value and the later write drops the other's field."""

        class SlowReadStore(RedisStore[CloudFlags]):
            async def _read(self) -> CloudFlags:
                value = await super()._read()
                # Left to timing, the second read often lands after the first write and hides the race.
                await asyncio.sleep(0.05)
                return value

        store = SlowReadStore(CloudFlags, "cloud", client=self.client)

        await asyncio.gather(store.update(check_server="http://check"), store.update(allow_free_trial=True))

        self.assertEqual(CloudFlags(check_server="http://check", allow_free_trial=True), await store.get())

    async def test_a_stored_value_of_the_wrong_type_raises_instead_of_reading_as_default(self) -> None:
        await self.connection.set(f"{NAMESPACE}:store:cloud", msgspec.msgpack.encode({"allow_free_trial": "yes"}))

        with self.assertRaises(msgspec.ValidationError):
            await RedisStore(CloudFlags, "cloud", client=self.client).get()

    async def test_fields_removed_from_the_schema_are_ignored_and_new_ones_default(self) -> None:
        await self.connection.set(f"{NAMESPACE}:store:cloud", msgspec.msgpack.encode({"allow_free_trial": True, "retired_flag": 1}))

        self.assertEqual(CloudFlags(allow_free_trial=True), await RedisStore(CloudFlags, "cloud", client=self.client).get())

    async def test_construction_touches_neither_settings_nor_redis(self) -> None:
        with patch.dict(conf.__dict__, {"settings": None}):
            store = RedisStore(CloudFlags, "cloud")
            devices = RedisSet(str, "devices")

        # The global client is looked up at the first operation.
        with patch("oldman.providers.redis.redis_client", self.registry):
            await store.update(allow_free_trial=True)
            await devices.add("tv-1")

        self.assertTrue((await RedisStore(CloudFlags, "cloud", client=self.client).get()).allow_free_trial)

    def test_the_name_must_be_a_non_empty_string(self) -> None:
        for name in ("", 1):
            with self.subTest(name=name), self.assertRaises(ValueError):
                RedisStore(CloudFlags, cast(Any, name))
            with self.subTest(name=name), self.assertRaises(ValueError):
                RedisSet(str, cast(Any, name))


class RedisSetTest(RedisStoreTestCase):
    async def test_member_operations_run_on_a_native_set(self) -> None:
        devices = RedisSet(str, "allowed_devices", client=self.client)

        self.assertIsNone(await devices.random())
        self.assertTrue(await devices.add("tv-1"))
        self.assertFalse(await devices.add("tv-1"))
        self.assertTrue(await devices.add("tv-2"))
        self.assertTrue(await devices.contains("tv-1"))
        self.assertFalse(await devices.contains("tv-3"))
        self.assertIn(await devices.random(), {"tv-1", "tv-2"})
        self.assertTrue(await devices.remove("tv-2"))
        self.assertFalse(await devices.remove("tv-2"))

        self.assertEqual({"tv-1"}, await devices.members())
        self.assertEqual(b"set", await self.connection.type(f"{NAMESPACE}:store:allowed_devices"))

    async def test_members_keep_their_type(self) -> None:
        channels = RedisSet(int, "recorded_channels", client=self.client)
        await channels.add(7)

        for wrong in (True, "7", 7.0):
            with self.subTest(member=wrong), self.assertRaises(TypeError):
                await channels.add(cast(Any, wrong))

        self.assertEqual({7}, await channels.members())
        self.assertIs(int, type(await channels.random()))

    async def test_sets_named_by_a_runtime_value_are_separate(self) -> None:
        def allowed_channel_devices(tag: str) -> RedisSet[str]:
            return RedisSet(str, f"allowed_channels:{tag}", client=self.client)

        await allowed_channel_devices("nhk").add("tv-1")

        self.assertTrue(await allowed_channel_devices("nhk").contains("tv-1"))
        self.assertFalse(await allowed_channel_devices("tvb").contains("tv-1"))

    def test_members_are_str_or_int(self) -> None:
        for member_type in (bool, float, bytes):
            with self.subTest(member_type=member_type), self.assertRaises(TypeError):
                RedisSet(cast(Any, member_type), "flags")


if __name__ == "__main__":
    unittest.main()
