from __future__ import annotations

import asyncio
import tracemalloc
import unittest
from collections.abc import AsyncIterator

from oldman.storage.backends.memory import InMemoryStorage
from tests.storage_contract import StorageContractMixin


class InMemoryStorageContractTest(StorageContractMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.storage = InMemoryStorage()

    async def test_open_snapshot_survives_overwrite_and_delete(self) -> None:
        await self.storage.save("snapshot.bin", b"before")
        stored = await self.storage.open("snapshot.bin")

        await self.storage.save("snapshot.bin", b"after", overwrite=True)
        await self.storage.delete("snapshot.bin")

        async with stored:
            self.assertEqual(b"before", await stored.read())

    async def test_concurrent_same_name_saves_are_unique(self) -> None:
        names = await asyncio.gather(*(self.storage.save("item.bin", f"payload-{index}".encode()) for index in range(32)))

        self.assertEqual(32, len(set(names)))
        self.assertTrue(all(await asyncio.gather(*(self.storage.exists(name) for name in names))))

    async def test_reading_closed_file_raises_value_error(self) -> None:
        await self.storage.save("closed.bin", b"payload")
        stored = await self.storage.open("closed.bin")
        await stored.close()

        with self.assertRaises(ValueError):
            await stored.read()

    async def test_stream_content_is_pulled_sequentially_without_prefetch(self) -> None:
        chunks = (b"ab", b"cd", b"ef")

        class GatedProducer:
            def __init__(self) -> None:
                self.requested = [asyncio.Event() for _chunk in chunks]
                self.release = [asyncio.Event() for _chunk in chunks]
                self.index = 0
                self.pending = 0
                self.max_pending = 0

            def __aiter__(self) -> AsyncIterator[bytes]:
                return self

            async def __anext__(self) -> bytes:
                if self.index == len(chunks):
                    raise StopAsyncIteration
                index = self.index
                self.index += 1
                self.pending += 1
                self.max_pending = max(self.max_pending, self.pending)
                self.requested[index].set()
                await self.release[index].wait()
                self.pending -= 1
                return chunks[index]

        producer = GatedProducer()
        saving = asyncio.create_task(self.storage.save("gated.bin", producer))
        for index, requested in enumerate(producer.requested):
            await asyncio.wait_for(requested.wait(), timeout=5)
            await asyncio.sleep(0)
            self.assertEqual(index + 1, producer.index)
            self.assertEqual(1, producer.pending)
            producer.release[index].set()

        saved = await asyncio.wait_for(saving, timeout=5)

        self.assertEqual(1, producer.max_pending)
        async with await self.storage.open(saved) as stored:
            self.assertEqual(b"abcdef", await stored.read())

    async def test_stream_buffer_peak_scales_with_payload_size(self) -> None:
        chunk = b"x" * (64 * 1024)
        chunk_count = 16
        expected = chunk * chunk_count
        structural_peak_limit = len(expected) * 4 + len(chunk)

        async def content() -> AsyncIterator[bytes]:
            for _index in range(chunk_count):
                yield chunk

        tracemalloc.start()
        try:
            saved = await self.storage.save("buffered.bin", content())
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLessEqual(peak, structural_peak_limit)
        async with await self.storage.open(saved) as stored:
            self.assertEqual(expected, await stored.read())
