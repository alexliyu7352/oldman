from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import unittest
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from concurrent.futures import Executor
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiofiles
from aiofiles.threadpool.binary import AsyncBufferedIOBase

from oldman import conf
from oldman.storage.backends.filesystem import FileSystemStorage, _coalesce_chunks
from oldman.storage.exceptions import InvalidStorageName, StorageBackendError
from tests.storage_contract import StorageContractMixin


class FileSystemStorageContractTest(StorageContractMixin, unittest.IsolatedAsyncioTestCase):
    storage: FileSystemStorage

    async def asyncSetUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.location = self.root / "storage"
        self.storage = FileSystemStorage(self.location, chunk_size=4)

    def _temporary_files(self) -> list[Path]:
        if not self.location.exists():
            return []
        return list(self.location.rglob(".oldman-storage-*"))

    async def test_relative_location_uses_project_base_and_save_lazily_creates_it(self) -> None:
        project_base = self.root / "project"

        with patch.object(conf, "PROJECT_BASE_PATH", project_base):
            storage = FileSystemStorage("uploads")

        expected_location = (project_base / "uploads").resolve()
        self.assertEqual(expected_location, storage.location)
        self.assertFalse(expected_location.exists())
        with self.assertRaises(AttributeError):
            storage.location = self.root  # type: ignore[misc]

        await storage.save("item.bin", b"payload")
        self.assertTrue(expected_location.is_dir())

    async def test_coalesce_chunks_emits_bounded_deterministic_chunks(self) -> None:
        async def content() -> AsyncIterable[bytes]:
            for chunk in (b"a", b"b", b"cdefgh", b"ij"):
                yield chunk

        chunks = [chunk async for chunk in _coalesce_chunks(content(), 4)]

        self.assertEqual([b"abcd", b"efgh", b"ij"], chunks)

    async def test_coalesce_chunks_skips_empty_chunks(self) -> None:
        async def content() -> AsyncIterable[bytes]:
            for chunk in (b"", b"abcd", b"", b"ef"):
                yield chunk

        chunks = [chunk async for chunk in _coalesce_chunks(content(), 4)]

        self.assertEqual([b"abcd", b"ef"], chunks)

    async def test_coalesce_chunks_keeps_large_remainder_as_a_view(self) -> None:
        large_chunk = b"b" * 64

        async def content() -> AsyncIterable[bytes]:
            yield b"a"
            yield large_chunk

        chunks = [chunk async for chunk in _coalesce_chunks(content(), 8)]

        self.assertEqual(b"a" + (b"b" * 7), chunks[0])
        remainder = chunks[1]
        if not isinstance(remainder, memoryview):
            self.fail(f"large remainder was copied into {type(remainder).__name__}")
        self.assertIs(large_chunk, remainder.obj)
        self.assertEqual(b"b" * 57, remainder)

    async def test_stream_content_is_pulled_sequentially_without_prefetch(self) -> None:
        chunk_size = 64 * 1024
        chunks = (b"a" * chunk_size, b"b" * chunk_size)
        storage = FileSystemStorage(self.location, chunk_size=chunk_size)
        first_write_started = asyncio.Event()
        release_first_write = asyncio.Event()
        timeline: list[str] = []
        real_write = AsyncBufferedIOBase.write

        class GatedProducer:
            def __init__(self) -> None:
                self.requested = [asyncio.Event() for _chunk in chunks]
                self.index = 0

            def __aiter__(self) -> AsyncIterator[bytes]:
                return self

            async def __anext__(self) -> bytes:
                if self.index == len(chunks):
                    raise StopAsyncIteration
                index = self.index
                self.index += 1
                timeline.append(f"request-{index}")
                self.requested[index].set()
                return chunks[index]

        write_count = 0

        async def gated_write(file: AsyncBufferedIOBase, data: bytes) -> int:
            nonlocal write_count
            index = write_count
            write_count += 1
            timeline.append(f"write-start-{index}")
            if index == 0:
                first_write_started.set()
                await release_first_write.wait()
            result = await real_write(file, data)
            timeline.append(f"write-end-{index}")
            return result

        producer = GatedProducer()
        with patch.object(AsyncBufferedIOBase, "write", new=gated_write):
            saving = asyncio.create_task(storage.save("gated.bin", producer))
            try:
                await asyncio.wait_for(first_write_started.wait(), timeout=5)
                self.assertTrue(producer.requested[0].is_set())
                self.assertFalse(producer.requested[1].is_set())
                self.assertEqual(["request-0", "write-start-0"], timeline)
                release_first_write.set()
                saved = await asyncio.wait_for(asyncio.shield(saving), timeout=5)
            finally:
                release_first_write.set()
                if not saving.done():
                    done, _pending = await asyncio.wait({saving}, timeout=5)
                    if not done:
                        saving.cancel()
                await asyncio.gather(saving, return_exceptions=True)

        self.assertEqual(
            [
                "request-0",
                "write-start-0",
                "write-end-0",
                "request-1",
                "write-start-1",
                "write-end-1",
            ],
            timeline,
        )
        async with await storage.open(saved) as stored:
            self.assertEqual(b"".join(chunks), await stored.read())

    async def test_one_byte_streams_are_coalesced_into_bounded_data_writes(self) -> None:
        total_size = 1024 * 1024
        chunk_size = 64 * 1024
        expected_writes = total_size // chunk_size
        storage = FileSystemStorage(self.location, chunk_size=chunk_size)
        real_write = AsyncBufferedIOBase.write
        write_count = 0
        write_lengths: list[int] = []

        async def counted_write(
            file: AsyncBufferedIOBase,
            data: bytes,
        ) -> int:
            nonlocal write_count
            write_count += 1
            if write_count > expected_writes:
                # Bound real I/O for a broken coalescer; the count assertion still fails.
                return len(data)
            write_lengths.append(len(data))
            return await real_write(file, data)

        async def content() -> AsyncIterable[bytes]:
            for _index in range(total_size):
                yield b"x"

        with patch.object(AsyncBufferedIOBase, "write", new=counted_write):
            saved = await storage.save("tiny-chunks.bin", content())

        self.assertEqual(expected_writes, write_count)
        self.assertEqual([chunk_size] * expected_writes, write_lengths)
        self.assertEqual(total_size, (await storage.stat(saved)).size)

    async def test_bytes_payload_is_written_with_one_data_write(self) -> None:
        payload = b"x" * (4 * 1024 * 1024)
        storage = FileSystemStorage(self.location, chunk_size=64 * 1024)
        real_write = AsyncBufferedIOBase.write
        write_count = 0

        async def counted_write(
            file: AsyncBufferedIOBase,
            data: bytes,
        ) -> int:
            nonlocal write_count
            write_count += 1
            return await real_write(file, data)

        with patch.object(AsyncBufferedIOBase, "write", new=counted_write):
            saved = await storage.save("bytes.bin", payload)

        self.assertEqual(1, write_count)
        self.assertEqual(len(payload), (await storage.stat(saved)).size)

    async def test_save_reuses_mkstemp_descriptor_with_bounded_executor_calls(self) -> None:
        self.location.mkdir()
        loop = asyncio.get_running_loop()
        real_run_in_executor = loop.run_in_executor
        real_mkstemp = tempfile.mkstemp
        real_aiofiles_open = aiofiles.open
        created_descriptor: int | None = None
        opened_files: list[str | int] = []
        executor_calls = 0

        def recorded_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
            nonlocal created_descriptor
            descriptor, path = real_mkstemp(*args, **kwargs)
            created_descriptor = descriptor
            return descriptor, path

        def recorded_open(file: str | int, *args: Any, **kwargs: Any) -> Any:
            opened_files.append(file)
            return real_aiofiles_open(file, *args, **kwargs)

        def counted_run_in_executor(
            executor: Executor | None,
            function: Callable[..., Any],
            *args: Any,
        ) -> asyncio.Future[Any]:
            nonlocal executor_calls
            executor_calls += 1
            return real_run_in_executor(executor, function, *args)

        with (
            patch(
                "oldman.storage.backends.filesystem.tempfile.mkstemp",
                side_effect=recorded_mkstemp,
            ),
            patch(
                "oldman.storage.backends.filesystem.aiofiles.open",
                side_effect=recorded_open,
            ),
            patch.object(loop, "run_in_executor", new=counted_run_in_executor),
        ):
            await self.storage.save("item.bin", b"payload")

        self.assertEqual([created_descriptor], opened_files)
        self.assertLessEqual(executor_calls, 6)

    async def test_concurrent_same_name_saves_are_unique_and_complete(self) -> None:
        payloads = [f"payload-{index}".encode() for index in range(32)]

        names = await asyncio.gather(*(self.storage.save("item.bin", payload) for payload in payloads))

        self.assertEqual(32, len(set(names)))
        for name, payload in zip(names, payloads, strict=True):
            async with await self.storage.open(name) as stored:
                self.assertEqual(payload, await stored.read())

    async def test_link_collision_retries_without_reconsuming_stream(self) -> None:
        chunks = (b"a", b"b", b"c")
        yields = 0

        async def content() -> AsyncIterable[bytes]:
            nonlocal yields
            for chunk in chunks:
                yields += 1
                yield chunk

        real_link = os.link
        calls = 0

        def collide_once(
            source: str | os.PathLike[str],
            destination: str | os.PathLike[str],
            **kwargs: object,
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FileExistsError(destination)
            real_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with patch("oldman.storage.backends.filesystem.os.link", side_effect=collide_once):
            saved_name = await self.storage.save("collision.bin", content())

        self.assertNotEqual("collision.bin", saved_name)
        self.assertEqual(len(chunks), yields)
        async with await self.storage.open(saved_name) as stored:
            self.assertEqual(b"abc", await stored.read())

    async def test_open_file_keeps_old_inode_across_overwrite(self) -> None:
        await self.storage.save("snapshot.bin", b"before")
        opened = await self.storage.open("snapshot.bin")

        await self.storage.save("snapshot.bin", b"after", overwrite=True)

        async with opened:
            self.assertEqual(b"before", await opened.read())
        async with await self.storage.open("snapshot.bin") as current:
            self.assertEqual(b"after", await current.read())

    async def test_parent_scoped_operations_use_one_worker_transaction(self) -> None:
        await self.storage.save("item.bin", b"payload")
        loop = asyncio.get_running_loop()
        real_run_in_executor = loop.run_in_executor

        async def executor_calls(operation: Callable[[], Awaitable[Any]]) -> int:
            calls = 0

            def counted(
                executor: Executor | None,
                function: Callable[..., Any],
                *args: Any,
            ) -> asyncio.Future[Any]:
                nonlocal calls
                calls += 1
                return real_run_in_executor(executor, function, *args)

            with patch.object(loop, "run_in_executor", new=counted):
                await operation()
            return calls

        self.assertEqual(1, await executor_calls(lambda: self.storage.stat("item.bin")))
        self.assertEqual(1, await executor_calls(lambda: self.storage.exists("item.bin")))
        self.assertEqual(1, await executor_calls(lambda: self.storage.delete("item.bin")))

    async def test_open_uses_one_path_worker_before_aiofiles_wrap(self) -> None:
        await self.storage.save("item.bin", b"payload")
        loop = asyncio.get_running_loop()
        real_run_in_executor = loop.run_in_executor
        calls = 0

        def counted(
            executor: Executor | None,
            function: Callable[..., Any],
            *args: Any,
        ) -> asyncio.Future[Any]:
            nonlocal calls
            calls += 1
            return real_run_in_executor(executor, function, *args)

        with patch.object(loop, "run_in_executor", new=counted):
            stored = await self.storage.open("item.bin")
        self.assertEqual(2, calls)
        await stored.close()

    async def test_stream_failure_keeps_target_and_removes_temporary_file(self) -> None:
        await self.storage.save("item.bin", b"original")

        async def failing_content() -> AsyncIterable[bytes]:
            yield b"partial"
            raise RuntimeError("producer failed")

        with self.assertRaises(StorageBackendError) as context:
            await self.storage.save("item.bin", failing_content(), overwrite=True)

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        async with await self.storage.open("item.bin") as stored:
            self.assertEqual(b"original", await stored.read())
        self.assertEqual([], self._temporary_files())

    async def test_cancellation_keeps_target_and_removes_temporary_file(self) -> None:
        await self.storage.save("item.bin", b"original")
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_content() -> AsyncIterable[bytes]:
            yield b"partial"
            started.set()
            await release.wait()
            yield b"unreachable"

        task = asyncio.create_task(self.storage.save("item.bin", blocking_content(), overwrite=True))
        await started.wait()
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        async with await self.storage.open("item.bin") as stored:
            self.assertEqual(b"original", await stored.read())
        self.assertEqual([], self._temporary_files())

    async def test_cancellation_during_temporary_creation_removes_temporary_file(self) -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        real_mkstemp = tempfile.mkstemp

        def delayed_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
            started.set()
            release.wait()
            try:
                return real_mkstemp(*args, **kwargs)  # type: ignore[arg-type]
            finally:
                finished.set()

        with patch(
            "oldman.storage.backends.filesystem.tempfile.mkstemp",
            side_effect=delayed_mkstemp,
        ):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await asyncio.to_thread(started.wait)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.to_thread(finished.wait)

        self.assertEqual([], self._temporary_files())

    async def test_cancellation_wins_if_temporary_creation_later_fails(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def failing_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
            del args, kwargs
            started.set()
            release.wait()
            raise PermissionError("temporary creation failed")

        with patch(
            "oldman.storage.backends.filesystem.tempfile.mkstemp",
            side_effect=failing_mkstemp,
        ):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await asyncio.to_thread(started.wait)
            task.cancel()
            release.set()

            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual([], self._temporary_files())

    async def test_handled_old_cancellation_does_not_mask_worker_failure(self) -> None:
        current_task = asyncio.current_task()
        assert current_task is not None
        current_task.cancel("old cancellation")
        try:
            with self.assertRaises(asyncio.CancelledError) as cancellation:
                await asyncio.sleep(0)
            self.assertEqual(("old cancellation",), cancellation.exception.args)
            self.assertGreater(current_task.cancelling(), 0)

            def fail() -> None:
                raise RuntimeError("worker failure")

            with self.assertRaisesRegex(RuntimeError, "worker failure"):
                await self.storage._run_fd_operation(fail)
        finally:
            current_task.uncancel()

    async def test_cancelled_parent_directory_open_closes_returned_descriptor(self) -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        descriptor: int | None = None
        real_open_parent = self.storage._open_parent_directory

        def delayed_open_parent(name: str, create: bool) -> tuple[int, str]:
            nonlocal descriptor
            started.set()
            release.wait()
            try:
                descriptor, basename = real_open_parent(name, create)
                return descriptor, basename
            finally:
                finished.set()

        with patch.object(
            self.storage,
            "_open_parent_directory",
            side_effect=delayed_open_parent,
        ):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await asyncio.to_thread(started.wait)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.to_thread(finished.wait)

        self.assertIsNotNone(descriptor)
        with self.assertRaises(OSError):
            os.fstat(descriptor)  # type: ignore[arg-type]

    async def test_repeated_cancellation_closes_returned_parent_descriptor(self) -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        descriptor: int | None = None
        real_open_parent = self.storage._open_parent_directory

        def delayed_open_parent(name: str, create: bool) -> tuple[int, str]:
            nonlocal descriptor
            started.set()
            release.wait()
            try:
                descriptor, basename = real_open_parent(name, create)
                return descriptor, basename
            finally:
                finished.set()

        with patch.object(
            self.storage,
            "_open_parent_directory",
            side_effect=delayed_open_parent,
        ):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await asyncio.to_thread(started.wait)
            task.cancel("first cancellation")
            asyncio.get_running_loop().call_soon(task.cancel, "second cancellation")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError) as context:
                await task
            await asyncio.to_thread(finished.wait)

        self.assertEqual(("first cancellation",), context.exception.args)
        self.assertIsNotNone(descriptor)
        with self.assertRaises(OSError):
            os.fstat(descriptor)  # type: ignore[arg-type]

    async def test_cancelled_file_open_closes_returned_descriptor(self) -> None:
        await self.storage.save("item.bin", b"payload")
        started = threading.Event()
        release = threading.Event()
        file_descriptor: int | None = None
        real_open_entry = self.storage._open_file_entry

        def delayed_open_entry(
            parent_descriptor: int,
            name: str,
        ) -> tuple[int, os.stat_result]:
            nonlocal file_descriptor
            result = real_open_entry(parent_descriptor, name)
            file_descriptor = result[0]
            started.set()
            release.wait()
            return result

        with patch.object(
            self.storage,
            "_open_file_entry",
            side_effect=delayed_open_entry,
        ):
            task = asyncio.create_task(self.storage.open("item.bin"))
            await asyncio.to_thread(started.wait)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertIsNotNone(file_descriptor)
        with self.assertRaises(OSError):
            os.fstat(file_descriptor)  # type: ignore[arg-type]

    async def test_repeated_cancellation_closes_returned_file_descriptor(self) -> None:
        await self.storage.save("item.bin", b"payload")
        started = threading.Event()
        release = threading.Event()
        file_descriptor: int | None = None
        real_open_entry = self.storage._open_file_entry

        def delayed_open_entry(
            parent_descriptor: int,
            name: str,
        ) -> tuple[int, os.stat_result]:
            nonlocal file_descriptor
            result = real_open_entry(parent_descriptor, name)
            file_descriptor = result[0]
            started.set()
            release.wait()
            return result

        with patch.object(
            self.storage,
            "_open_file_entry",
            side_effect=delayed_open_entry,
        ):
            task = asyncio.create_task(self.storage.open("item.bin"))
            await asyncio.to_thread(started.wait)
            task.cancel("first cancellation")
            asyncio.get_running_loop().call_soon(task.cancel, "second cancellation")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError) as context:
                await task

        self.assertEqual(("first cancellation",), context.exception.args)
        self.assertIsNotNone(file_descriptor)
        with self.assertRaises(OSError):
            os.fstat(file_descriptor)  # type: ignore[arg-type]

    async def test_cancelled_delete_cannot_reuse_parent_descriptor_outside_location(self) -> None:
        await self.storage.save("nested/victim.bin", b"inside")
        outside = self.root / "outside"
        outside.mkdir()
        outside_victim = outside / "victim.bin"
        outside_victim.write_bytes(b"outside")
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        parent_descriptor: int | None = None
        real_delete_entry = self.storage._delete_entry

        def delayed_delete_entry(descriptor: int, name: str) -> None:
            nonlocal parent_descriptor
            parent_descriptor = descriptor
            started.set()
            release.wait()
            try:
                real_delete_entry(descriptor, name)
            finally:
                finished.set()

        with patch.object(
            self.storage,
            "_delete_entry",
            side_effect=delayed_delete_entry,
        ):
            task = asyncio.create_task(self.storage.delete("nested/victim.bin"))
            await asyncio.to_thread(started.wait)
            task.cancel()
            await asyncio.wait({task}, timeout=0.1)

            self.assertIsNotNone(parent_descriptor)
            outside_descriptor = os.open(outside, os.O_RDONLY | os.O_DIRECTORY)
            try:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.to_thread(finished.wait)
            finally:
                os.close(outside_descriptor)

        self.assertEqual(b"outside", outside_victim.read_bytes())

    async def test_repeated_cancellation_cannot_reuse_delete_parent_descriptor(self) -> None:
        await self.storage.save("nested/victim.bin", b"inside")
        outside = self.root / "outside"
        outside.mkdir()
        outside_victim = outside / "victim.bin"
        outside_victim.write_bytes(b"outside")
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        real_delete_entry = self.storage._delete_entry

        def delayed_delete_entry(descriptor: int, name: str) -> None:
            started.set()
            release.wait()
            try:
                real_delete_entry(descriptor, name)
            finally:
                finished.set()

        with patch.object(
            self.storage,
            "_delete_entry",
            side_effect=delayed_delete_entry,
        ):
            task = asyncio.create_task(self.storage.delete("nested/victim.bin"))
            await asyncio.to_thread(started.wait)
            task.cancel("first cancellation")
            asyncio.get_running_loop().call_soon(task.cancel, "second cancellation")
            await asyncio.wait({task}, timeout=0.1)

            outside_descriptor = os.open(outside, os.O_RDONLY | os.O_DIRECTORY)
            try:
                release.set()
                with self.assertRaises(asyncio.CancelledError) as context:
                    await task
                await asyncio.to_thread(finished.wait)
            finally:
                os.close(outside_descriptor)

        self.assertEqual(("first cancellation",), context.exception.args)
        self.assertEqual(b"outside", outside_victim.read_bytes())

    async def test_repeated_cancellation_during_mkstemp_cleans_temporary_file(self) -> None:
        started = threading.Event()
        release = threading.Event()
        real_mkstemp = tempfile.mkstemp

        def delayed_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
            started.set()
            release.wait()
            return real_mkstemp(*args, **kwargs)  # type: ignore[arg-type]

        with patch(
            "oldman.storage.backends.filesystem.tempfile.mkstemp",
            side_effect=delayed_mkstemp,
        ):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await asyncio.to_thread(started.wait)
            task.cancel("first cancellation")
            asyncio.get_running_loop().call_soon(task.cancel, "second cancellation")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError) as context:
                await task

        self.assertEqual(("first cancellation",), context.exception.args)
        self.assertEqual([], self._temporary_files())

    async def test_repeated_cancellation_during_aiofiles_open_closes_descriptor(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        descriptor: int | None = None

        async def delayed_open(
            file: int,
            mode: str,
            *,
            closefd: bool,
            **kwargs: object,
        ) -> AsyncBufferedIOBase:
            nonlocal descriptor
            del kwargs
            self.assertEqual("wb", mode)
            self.assertTrue(closefd)
            descriptor = file
            started.set()
            await release.wait()
            raw_file = os.fdopen(file, "wb", closefd=closefd)
            return aiofiles.threadpool.wrap(raw_file)

        with patch("oldman.storage.backends.filesystem.aiofiles.open", side_effect=delayed_open):
            task = asyncio.create_task(self.storage.save("item.bin", b"payload"))
            await started.wait()
            task.cancel("first cancellation")
            asyncio.get_running_loop().call_soon(task.cancel, "second cancellation")
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError) as context:
                await task

        self.assertEqual(("first cancellation",), context.exception.args)
        self.assertIsNotNone(descriptor)
        with self.assertRaises(OSError):
            os.fstat(descriptor)  # type: ignore[arg-type]
        self.assertEqual([], self._temporary_files())

    async def test_cancellation_waits_for_stat_and_exists_workers(self) -> None:
        await self.storage.save("item.bin", b"payload")

        cases = (
            ("stat", "_stat_entry"),
            ("exists", "_entry_exists"),
        )
        for operation_name, worker_name in cases:
            with self.subTest(operation=operation_name):
                started = threading.Event()
                release = threading.Event()
                real_worker = getattr(self.storage, worker_name)

                def delayed_worker(
                    *args: object,
                    _started: threading.Event = started,
                    _release: threading.Event = release,
                    _worker=real_worker,
                ):
                    _started.set()
                    _release.wait()
                    return _worker(*args)

                with patch.object(self.storage, worker_name, side_effect=delayed_worker):
                    operation = getattr(self.storage, operation_name)
                    task = asyncio.create_task(operation("item.bin"))
                    await asyncio.to_thread(started.wait)
                    task.cancel()
                    done, _pending = await asyncio.wait({task}, timeout=0.02)
                    self.assertEqual(set(), done)
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

    async def test_successful_link_and_replace_commits_win_over_cancellation(self) -> None:
        await self.storage.save("replace.bin", b"original")

        cases = (
            ("link.bin", False, "link"),
            ("replace.bin", True, "replace"),
        )
        for name, overwrite, operation_name in cases:
            with self.subTest(operation=operation_name):
                started = threading.Event()
                release = threading.Event()
                real_operation = getattr(os, operation_name)

                def delayed_operation(
                    *args: object,
                    _started: threading.Event = started,
                    _release: threading.Event = release,
                    _operation=real_operation,
                    **kwargs: object,
                ) -> None:
                    _started.set()
                    _release.wait()
                    _operation(*args, **kwargs)

                with patch(
                    f"oldman.storage.backends.filesystem.os.{operation_name}",
                    side_effect=delayed_operation,
                ):
                    task = asyncio.create_task(self.storage.save(name, b"replacement", overwrite=overwrite))
                    await asyncio.to_thread(started.wait)
                    task.cancel()
                    done, _pending = await asyncio.wait({task}, timeout=0.02)
                    self.assertEqual(set(), done)
                    release.set()
                    saved_name = await task

                self.assertEqual(name, saved_name)
                self.assertFalse(task.cancelled())
                self.assertEqual(0, task.cancelling())
                async with await self.storage.open(saved_name) as stored:
                    self.assertEqual(b"replacement", await stored.read())
                self.assertEqual([], self._temporary_files())

    async def test_alternative_name_cannot_change_parent_directory(self) -> None:
        class RedirectingAlternativeStorage(FileSystemStorage):
            def get_alternative_name(self, name: str) -> str:
                del name
                return "other/item.bin"

        storage = RedirectingAlternativeStorage(self.location, chunk_size=4)
        real_link = os.link
        calls = 0
        yields = 0

        async def content() -> AsyncIterable[bytes]:
            nonlocal yields
            yields += 1
            yield b"payload"

        def collide_once(
            source: str | os.PathLike[str],
            destination: str | os.PathLike[str],
            **kwargs: object,
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FileExistsError(destination)
            real_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with (
            patch("oldman.storage.backends.filesystem.os.link", side_effect=collide_once),
            self.assertRaises(InvalidStorageName),
        ):
            await storage.save("item.bin", content())

        self.assertEqual(1, yields)
        self.assertFalse((self.location / "item.bin").exists())
        self.assertFalse((self.location / "other" / "item.bin").exists())
        self.assertEqual([], self._temporary_files())

    async def test_close_failure_does_not_mask_producer_error_or_skip_cleanup(self) -> None:
        async def failing_content() -> AsyncIterable[bytes]:
            yield b"partial"
            raise RuntimeError("producer failed")

        real_close = AsyncBufferedIOBase.close

        async def close_then_fail(file: AsyncBufferedIOBase) -> None:
            await real_close(file)
            raise OSError("close failed")

        with (
            patch.object(
                AsyncBufferedIOBase,
                "close",
                new=close_then_fail,
            ),
            self.assertRaises(StorageBackendError) as context,
        ):
            await self.storage.save("item.bin", failing_content())

        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        self.assertEqual([], self._temporary_files())

    async def test_directory_swap_cannot_redirect_save_outside_location(self) -> None:
        parent = self.location / "nested"
        parent.mkdir(parents=True)
        detached = self.location / "detached"
        outside = self.root / "outside"
        outside.mkdir()
        real_mkstemp = tempfile.mkstemp

        def swap_then_create(*args: object, **kwargs: object) -> tuple[int, str]:
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            return real_mkstemp(*args, **kwargs)  # type: ignore[arg-type]

        with patch(
            "oldman.storage.backends.filesystem.tempfile.mkstemp",
            side_effect=swap_then_create,
        ):
            await self.storage.save("nested/item.bin", b"payload", overwrite=True)

        self.assertEqual([], list(outside.iterdir()))
        self.assertEqual(b"payload", (detached / "item.bin").read_bytes())

    async def test_directory_swap_cannot_redirect_link_outside_location(self) -> None:
        parent = self.location / "nested"
        parent.mkdir(parents=True)
        detached = self.location / "detached"
        outside = self.root / "outside"
        outside.mkdir()
        real_link = os.link

        def swap_then_link(
            source: str | os.PathLike[str],
            destination: str | os.PathLike[str],
            **kwargs: object,
        ) -> None:
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            (outside / Path(source).name).write_bytes(b"outside")
            real_link(source, destination, **kwargs)  # type: ignore[arg-type]

        with patch("oldman.storage.backends.filesystem.os.link", side_effect=swap_then_link):
            await self.storage.save("nested/item.bin", b"payload")

        self.assertFalse((outside / "item.bin").exists())
        self.assertEqual(b"payload", (detached / "item.bin").read_bytes())

    async def test_directory_swap_cannot_redirect_open_outside_location(self) -> None:
        await self.storage.save("nested/item.bin", b"inside")
        parent = self.location / "nested"
        detached = self.location / "detached"
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "item.bin").write_bytes(b"outside")
        real_open = aiofiles.open

        def swap_then_open(*args: object, **kwargs: object):
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            return real_open(*args, **kwargs)  # type: ignore[arg-type]

        with patch("oldman.storage.backends.filesystem.aiofiles.open", side_effect=swap_then_open):
            stored = await self.storage.open("nested/item.bin")

        self.assertTrue(parent.is_symlink())
        async with stored:
            self.assertEqual(b"inside", await stored.read())

    async def test_directory_swap_cannot_redirect_stat_outside_location(self) -> None:
        await self.storage.save("nested/item.bin", b"inside")
        parent = self.location / "nested"
        detached = self.location / "detached"
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "item.bin").write_bytes(b"outside payload")
        real_stat_entry = FileSystemStorage._stat_entry

        def swap_then_stat(parent_descriptor: int, name: str):
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            return real_stat_entry(parent_descriptor, name)

        with patch.object(FileSystemStorage, "_stat_entry", side_effect=swap_then_stat):
            info = await self.storage.stat("nested/item.bin")

        self.assertEqual(6, info.size)

    async def test_directory_swap_cannot_redirect_delete_outside_location(self) -> None:
        await self.storage.save("nested/item.bin", b"inside")
        parent = self.location / "nested"
        detached = self.location / "detached"
        outside = self.root / "outside"
        outside.mkdir()
        outside_file = outside / "item.bin"
        outside_file.write_bytes(b"outside")
        real_delete_entry = FileSystemStorage._delete_entry

        def swap_then_delete(parent_descriptor: int, name: str) -> None:
            parent.rename(detached)
            parent.symlink_to(outside, target_is_directory=True)
            real_delete_entry(parent_descriptor, name)

        with patch.object(FileSystemStorage, "_delete_entry", side_effect=swap_then_delete):
            await self.storage.delete("nested/item.bin")

        self.assertEqual(b"outside", outside_file.read_bytes())
        self.assertFalse((detached / "item.bin").exists())

    async def test_internal_file_symlink_is_rejected_instead_of_followed(self) -> None:
        await self.storage.save("target.bin", b"original")
        (self.location / "alias.bin").symlink_to(self.location / "target.bin")

        with self.assertRaises(InvalidStorageName):
            await self.storage.save("alias.bin", b"replacement", overwrite=True)

        self.assertEqual(b"original", (self.location / "target.bin").read_bytes())

    async def test_replace_failure_keeps_target_and_removes_temporary_file(self) -> None:
        await self.storage.save("item.bin", b"original")

        with (
            patch(
                "oldman.storage.backends.filesystem.os.replace",
                side_effect=OSError("replace failed"),
            ),
            self.assertRaises(StorageBackendError) as context,
        ):
            await self.storage.save("item.bin", b"replacement", overwrite=True)

        self.assertIsInstance(context.exception.__cause__, OSError)
        async with await self.storage.open("item.bin") as stored:
            self.assertEqual(b"original", await stored.read())
        self.assertEqual([], self._temporary_files())

    async def test_file_symlink_outside_location_is_rejected_by_every_operation(self) -> None:
        self.location.mkdir()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"outside")
        (self.location / "escape.bin").symlink_to(outside)

        operations = (
            lambda: self.storage.save("escape.bin", b"new"),
            lambda: self.storage.save("escape.bin", b"new", overwrite=True),
            lambda: self.storage.open("escape.bin"),
            lambda: self.storage.stat("escape.bin"),
            lambda: self.storage.exists("escape.bin"),
            lambda: self.storage.delete("escape.bin"),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(InvalidStorageName):
                    await operation()

        self.assertEqual(b"outside", outside.read_bytes())

    async def test_directory_symlink_outside_location_is_rejected_before_save(self) -> None:
        self.location.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.location / "escape").symlink_to(outside, target_is_directory=True)

        operations = (
            lambda: self.storage.save("escape/item.bin", b"new"),
            lambda: self.storage.open("escape/item.bin"),
            lambda: self.storage.stat("escape/item.bin"),
            lambda: self.storage.exists("escape/item.bin"),
            lambda: self.storage.delete("escape/item.bin"),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(InvalidStorageName):
                    await operation()

        self.assertEqual([], list(outside.iterdir()))
        self.assertEqual([], self._temporary_files())

    async def test_absolute_and_parent_names_are_rejected(self) -> None:
        for name in (str(self.root / "absolute.bin"), "../escape.bin", "a/../../escape.bin"):
            with self.subTest(name=name):
                with self.assertRaises(InvalidStorageName):
                    await self.storage.save(name, b"payload")

    async def test_open_file_info_comes_from_open_file_and_uses_utc(self) -> None:
        await self.storage.save("metadata.bin", b"metadata")

        stored = await self.storage.open("metadata.bin")
        try:
            os.replace(self.location / "metadata.bin", self.location / "moved.bin")
            (self.location / "metadata.bin").write_bytes(b"different contents")

            self.assertEqual("metadata.bin", stored.info.name)
            self.assertEqual(8, stored.info.size)
            self.assertIs(UTC, stored.info.modified_at.tzinfo)
            self.assertEqual(b"metadata", await stored.read())
        finally:
            await stored.close()

    async def test_stat_returns_name_size_and_utc_modified_at(self) -> None:
        await self.storage.save("metadata.bin", b"metadata")

        info = await self.storage.stat("metadata.bin")

        self.assertEqual("metadata.bin", info.name)
        self.assertEqual(8, info.size)
        self.assertIs(UTC, info.modified_at.tzinfo)

    async def test_save_and_overwrite_never_fsync(self) -> None:
        with patch("oldman.storage.backends.filesystem.os.fsync") as fsync:
            await self.storage.save("item.bin", b"first")
            await self.storage.save("item.bin", b"second", overwrite=True)

        fsync.assert_not_called()
