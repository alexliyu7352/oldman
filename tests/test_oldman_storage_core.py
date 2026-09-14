from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from collections.abc import AsyncIterable

from oldman.storage.base import Storage, validate_storage_name
from oldman.storage.exceptions import InvalidStorageName, StorageBackendError, StorageFileNotFound
from oldman.storage.streams import FileInfo, StoredFile


class BytesStoredFile(StoredFile):
    def __init__(self, payload: bytes, *, chunk_size: int = 4) -> None:
        super().__init__(
            name="probe.bin",
            info=FileInfo("probe.bin", len(payload), dt.datetime.now(dt.UTC)),
            chunk_size=chunk_size,
        )
        self.payload = payload
        self.offset = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


class FailingStorage(Storage):
    async def _save(self, name: str, content: bytes | AsyncIterable[bytes], *, overwrite: bool) -> str:
        raise PermissionError("denied")

    async def _open(self, name: str) -> StoredFile:
        raise FileNotFoundError(name)

    async def _delete(self, name: str) -> None:
        return None

    async def _exists(self, name: str) -> bool:
        return False

    async def _stat(self, name: str) -> FileInfo:
        raise FileNotFoundError(name)


class InvalidNameStorage(FailingStorage):
    async def _save(self, name: str, content: bytes | AsyncIterable[bytes], *, overwrite: bool) -> str:
        return "invalid/"


class CancelledStorage(FailingStorage):
    async def _exists(self, name: str) -> bool:
        raise asyncio.CancelledError()


class ContentReadingStorage(FailingStorage):
    async def _save(self, name: str, content: bytes | AsyncIterable[bytes], *, overwrite: bool) -> str:
        if isinstance(content, bytes):
            return name
        async for _chunk in content:
            pass
        return name


class MissingFileStorage(FailingStorage):
    async def _save(self, name: str, content: bytes | AsyncIterable[bytes], *, overwrite: bool) -> str:
        raise FileNotFoundError(name)

    async def _exists(self, name: str) -> bool:
        raise FileNotFoundError(name)


class StorageCoreContractTest(unittest.IsolatedAsyncioTestCase):
    def test_public_package_exports_model_file_column(self) -> None:
        from oldman import storage

        self.assertTrue(callable(storage.file_column))

    def test_validate_storage_name_accepts_a_normal_relative_posix_path(self) -> None:
        self.assertEqual("avatars/2026/user.png", validate_storage_name("avatars/2026/user.png"))

    def test_validate_storage_name_rejects_unsafe_paths(self) -> None:
        invalid_names = (
            "",
            "/root",
            "a//b",
            "a/./b",
            "a/../b",
            "a\\b",
            "a/",
            "a\x00b",
            "a\x1fb",
            "a\x7fb",
        )

        for name in invalid_names:
            with self.subTest(name=repr(name)):
                with self.assertRaises(InvalidStorageName):
                    validate_storage_name(name)

    async def test_stored_file_iteration_reads_fixed_chunks_and_context_exit_closes(self) -> None:
        stored_file = BytesStoredFile(b"abcdefgh", chunk_size=3)

        async with stored_file as opened_file:
            chunks = [chunk async for chunk in opened_file]

        self.assertEqual([b"abc", b"def", b"gh"], chunks)
        self.assertTrue(stored_file.closed)

    def test_stored_file_rejects_non_positive_chunk_sizes(self) -> None:
        with self.assertRaises(ValueError):
            BytesStoredFile(b"data", chunk_size=0)

    async def test_save_wraps_backend_errors_with_context_and_cause(self) -> None:
        storage = FailingStorage(alias="private")

        with self.assertRaises(StorageBackendError) as context:
            await storage.save("x", b"x")

        error = context.exception
        self.assertEqual("save", error.operation)
        self.assertEqual("x", error.name)
        self.assertEqual("private", error.alias)
        self.assertIsInstance(error.__cause__, PermissionError)

    async def test_open_and_stat_translate_missing_files(self) -> None:
        storage = FailingStorage()

        with self.assertRaises(StorageFileNotFound):
            await storage.open("missing")
        with self.assertRaises(StorageFileNotFound):
            await storage.stat("missing")

    async def test_save_and_exists_wrap_missing_backend_files(self) -> None:
        storage = MissingFileStorage(alias="private")

        with self.assertRaises(StorageBackendError) as save_context:
            await storage.save("missing", b"data")
        self.assertEqual("save", save_context.exception.operation)
        self.assertEqual("missing", save_context.exception.name)
        self.assertIsInstance(save_context.exception.__cause__, FileNotFoundError)

        with self.assertRaises(StorageBackendError) as exists_context:
            await storage.exists("missing")
        self.assertEqual("exists", exists_context.exception.operation)
        self.assertEqual("missing", exists_context.exception.name)
        self.assertIsInstance(exists_context.exception.__cause__, FileNotFoundError)

    async def test_cancelled_error_is_not_wrapped(self) -> None:
        storage = CancelledStorage()

        with self.assertRaises(asyncio.CancelledError):
            await storage.exists("x")

    async def test_save_revalidates_a_backend_returned_name(self) -> None:
        storage = InvalidNameStorage()

        with self.assertRaises(InvalidStorageName):
            await storage.save("x", b"x")

    async def test_save_rejects_async_content_chunks_that_are_not_bytes(self) -> None:
        async def invalid_content() -> AsyncIterable[bytes]:
            yield "not bytes"  # type: ignore[misc]

        storage = ContentReadingStorage()
        with self.assertRaises(TypeError):
            await storage.save("x", invalid_content())
