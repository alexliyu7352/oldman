from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oldman.storage.base import Storage
from oldman.storage.exceptions import StorageFileNotFound


class StorageContractMixin:
    storage: Storage

    if TYPE_CHECKING:
        assertEqual: Any
        assertFalse: Any
        assertNotEqual: Any
        assertRaises: Any
        assertTrue: Any

    async def test_bytes_round_trip_and_metadata(self) -> None:
        saved = await self.storage.save("folder/item.bin", b"payload")

        self.assertEqual("folder/item.bin", saved)
        async with await self.storage.open(saved) as stored:
            self.assertEqual(b"payload", await stored.read())
            self.assertEqual(7, stored.info.size)
            self.assertEqual(saved, stored.info.name)

    async def test_stream_round_trip(self) -> None:
        async def content():
            for chunk in (b"ab", b"cd", b"ef"):
                yield chunk

        saved = await self.storage.save("stream.bin", content())

        async with await self.storage.open(saved) as stored:
            self.assertEqual(b"abcdef", b"".join([chunk async for chunk in stored]))

    async def test_collision_and_overwrite(self) -> None:
        self.assertEqual("item.txt", await self.storage.save("item.txt", b"first"))
        available = await self.storage.get_available_name("item.txt")
        self.assertNotEqual("item.txt", available)

        second = await self.storage.save("item.txt", b"second")
        self.assertNotEqual("item.txt", second)
        self.assertTrue(second.startswith("item_"))

        self.assertEqual("item.txt", await self.storage.save("item.txt", b"third", overwrite=True))
        async with await self.storage.open("item.txt") as stored:
            self.assertEqual(b"third", await stored.read())

    async def test_empty_file_exists_and_stat(self) -> None:
        self.assertFalse(await self.storage.exists("empty.bin"))
        self.assertEqual("empty.bin", await self.storage.save("empty.bin", b""))
        self.assertTrue(await self.storage.exists("empty.bin"))

        info = await self.storage.stat("empty.bin")
        self.assertEqual("empty.bin", info.name)
        self.assertEqual(0, info.size)

        async with await self.storage.open("empty.bin") as stored:
            self.assertEqual(b"", await stored.read())

    async def test_delete_existing_and_missing_file_is_a_noop(self) -> None:
        await self.storage.save("delete.bin", b"payload")
        await self.storage.delete("delete.bin")

        self.assertFalse(await self.storage.exists("delete.bin"))
        await self.storage.delete("delete.bin")

    async def test_open_and_stat_missing_file_raise_storage_file_not_found(self) -> None:
        with self.assertRaises(StorageFileNotFound):
            await self.storage.open("missing.bin")
        with self.assertRaises(StorageFileNotFound):
            await self.storage.stat("missing.bin")
