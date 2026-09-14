"""Private Sanic media publication contracts for async storages."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from sanic import Sanic
from sanic.exceptions import SanicException
from sanic.response import ResponseStream

from oldman.storage import (
    FileSystemStorage,
    InMemoryStorage,
    Storage,
    StorageBackendError,
)
from oldman.storage.base import StorageContent
from oldman.storage.streams import FileInfo, StoredFile


class _RouteCapture:
    """Capture the real handler installed at Oldman's Sanic boundary."""

    def __init__(self) -> None:
        self.handler: Any = None
        self.router = SimpleNamespace(
            find_route_by_view_name=lambda name: None,
        )

    def add_route(self, handler: Any, *args: Any, **kwargs: Any) -> None:
        self.handler = handler


class _ObservedStoredFile(StoredFile):
    def __init__(self, payload: bytes, events: list[str]) -> None:
        super().__init__(
            name="large.bin",
            info=FileInfo(
                name="large.bin",
                size=len(payload),
                modified_at=datetime(2026, 8, 5, 12, tzinfo=UTC),
            ),
            chunk_size=3,
        )
        self._payload = payload
        self._offset = 0
        self._events = events
        self.read_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        self._events.append(f"read:{size}")
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


class _ObservedStorage(Storage):
    def __init__(self, payload: bytes, events: list[str]) -> None:
        super().__init__()
        self._payload = payload
        self._events = events
        self.opened: _ObservedStoredFile | None = None

    async def _save(
        self,
        name: str,
        content: StorageContent,
        *,
        overwrite: bool,
    ) -> str:
        raise NotImplementedError

    async def _open(self, name: str) -> StoredFile:
        self.opened = _ObservedStoredFile(self._payload, self._events)
        return self.opened

    async def _delete(self, name: str) -> None:
        raise NotImplementedError

    async def _exists(self, name: str) -> bool:
        return name == "large.bin"

    async def _stat(self, name: str) -> FileInfo:
        if name != "large.bin":
            raise FileNotFoundError(name)
        return FileInfo(
            name=name,
            size=len(self._payload),
            modified_at=datetime(2026, 8, 5, 12, tzinfo=UTC),
        )


class _FailingOpenStorage(_ObservedStorage):
    async def _open(self, name: str) -> StoredFile:
        raise RuntimeError("backend open failed")


class _FailingReadStoredFile(_ObservedStoredFile):
    async def read(self, size: int = -1) -> bytes:
        if self._offset:
            self.read_sizes.append(size)
            raise RuntimeError("backend read failed")
        return await super().read(size)


class _FailingReadStorage(_ObservedStorage):
    async def _open(self, name: str) -> StoredFile:
        self.opened = _FailingReadStoredFile(self._payload, self._events)
        return self.opened


class InstallMediaTest(unittest.IsolatedAsyncioTestCase):
    async def test_filesystem_media_uses_sanic_static_with_streaming_options(self) -> None:
        from oldman.storage._web import install_media

        with tempfile.TemporaryDirectory() as tmp:
            storage = FileSystemStorage(Path(tmp))
            app = Mock()
            app.router.find_route_by_view_name.return_value = None

            install_media(app, storage=storage, url="/media/")

        app.static.assert_called_once_with(
            "/media/",
            storage.location,
            name="media",
            use_content_range=True,
            stream_large_files=True,
        )
        app.add_route.assert_not_called()

    async def test_empty_media_url_installs_no_static_or_generic_route(self) -> None:
        from oldman.storage._web import install_media

        app = Mock()

        install_media(app, storage=InMemoryStorage(), url="")

        app.static.assert_not_called()
        app.add_route.assert_not_called()

    async def test_generic_get_and_head_publish_metadata_and_only_get_reads(self) -> None:
        from oldman.storage._web import install_media

        app = Sanic("storage-generic-get-head")
        storage = InMemoryStorage(chunk_size=2)
        await storage.save("folder/report.txt", b"payload")
        info = await storage.stat("folder/report.txt")
        install_media(app, storage=storage, url="/media/")

        try:
            _, get_response = await app.asgi_client.get("/media/folder/report.txt")
            _, head_response = await app.asgi_client.head("/media/folder/report.txt")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual(200, get_response.status)
        self.assertEqual(b"payload", get_response.body)
        self.assertEqual("7", get_response.headers["content-length"])
        self.assertEqual("text/plain", get_response.headers["content-type"])
        self.assertEqual(
            info.modified_at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            get_response.headers["last-modified"],
        )
        self.assertEqual(200, head_response.status)
        self.assertEqual(b"", head_response.body)
        self.assertEqual("7", head_response.headers["content-length"])
        self.assertEqual("text/plain", head_response.headers["content-type"])
        self.assertEqual(get_response.headers["last-modified"], head_response.headers["last-modified"])

    async def test_generic_unknown_mime_falls_back_to_binary(self) -> None:
        from oldman.storage._web import install_media

        app = Sanic("storage-generic-mime-fallback")
        storage = InMemoryStorage()
        await storage.save("artifact.unknown-oldman-type", b"data")
        install_media(app, storage=storage, url="/media/")

        try:
            _, response = await app.asgi_client.get("/media/artifact.unknown-oldman-type")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual(200, response.status)
        self.assertEqual("application/octet-stream", response.headers["content-type"])

    async def test_generic_missing_and_escaping_names_are_not_found(self) -> None:
        from oldman.storage._web import install_media

        app = Sanic("storage-generic-not-found")
        storage = InMemoryStorage()
        install_media(app, storage=storage, url="/media/")

        try:
            _, missing = await app.asgi_client.get("/media/missing.txt")
            _, escaping = await app.asgi_client.get("/media/%2E%2E/private.txt")
        finally:
            Sanic.unregister_app(app)

        self.assertEqual(404, missing.status)
        self.assertEqual(404, escaping.status)

    async def test_generic_stream_reads_finite_chunks_after_each_write_finishes(self) -> None:
        from oldman.storage._web import install_media

        events: list[str] = []
        storage = _ObservedStorage(b"abcdefgh", events)
        app = _RouteCapture()
        install_media(cast(Any, app), storage=storage, url="/media/")

        response = await app.handler(
            cast(Any, SimpleNamespace(method="GET")),
            "large.bin",
        )
        self.assertIsInstance(response, ResponseStream)

        first_write_started = asyncio.Event()
        release_first_write = asyncio.Event()

        class Writer:
            async def write(self, chunk: bytes) -> None:
                events.append(f"write-start:{chunk.decode()}")
                if not first_write_started.is_set():
                    first_write_started.set()
                    await release_first_write.wait()
                events.append(f"write-end:{chunk.decode()}")

        streaming = asyncio.create_task(response.streaming_fn(cast(Any, Writer())))
        try:
            await asyncio.wait_for(first_write_started.wait(), timeout=1)
            for _ in range(3):
                await asyncio.sleep(0)
            assert storage.opened is not None
            self.assertEqual([3], storage.opened.read_sizes)
            self.assertEqual(["read:3", "write-start:abc"], events)
            self.assertFalse(streaming.done())
        finally:
            release_first_write.set()
        await streaming

        self.assertEqual(
            [
                "read:3",
                "write-start:abc",
                "write-end:abc",
                "read:3",
                "write-start:def",
                "write-end:def",
                "read:3",
                "write-start:gh",
                "write-end:gh",
                "read:3",
            ],
            events,
        )
        assert storage.opened is not None
        self.assertEqual([3, 3, 3, 3], storage.opened.read_sizes)
        self.assertNotIn(-1, storage.opened.read_sizes)
        self.assertTrue(storage.opened.closed)

    async def test_non_not_found_backend_error_propagates(self) -> None:
        from oldman.storage._web import install_media

        storage = _FailingOpenStorage(b"payload", [])
        app = _RouteCapture()
        install_media(cast(Any, app), storage=storage, url="/media/")

        with self.assertRaisesRegex(
            StorageBackendError,
            "storage backend failed during open",
        ):
            await app.handler(
                cast(Any, SimpleNamespace(method="GET")),
                "large.bin",
            )

    async def test_read_error_propagates_and_closes_stored_file(self) -> None:
        from oldman.storage._web import install_media

        storage = _FailingReadStorage(b"payload", [])
        app = _RouteCapture()
        install_media(cast(Any, app), storage=storage, url="/media/")
        response = await app.handler(
            cast(Any, SimpleNamespace(method="GET")),
            "large.bin",
        )

        class Writer:
            async def write(self, chunk: bytes) -> None:
                del chunk

        with self.assertRaisesRegex(RuntimeError, "backend read failed"):
            await response.streaming_fn(cast(Any, Writer()))

        assert storage.opened is not None
        self.assertTrue(storage.opened.closed)

    async def test_write_error_propagates_and_closes_stored_file(self) -> None:
        from oldman.storage._web import install_media

        storage = _ObservedStorage(b"payload", [])
        app = _RouteCapture()
        install_media(cast(Any, app), storage=storage, url="/media/")
        response = await app.handler(
            cast(Any, SimpleNamespace(method="GET")),
            "large.bin",
        )

        class FailingWriter:
            async def write(self, chunk: bytes) -> None:
                del chunk
                raise RuntimeError("response write failed")

        with self.assertRaisesRegex(RuntimeError, "response write failed"):
            await response.streaming_fn(cast(Any, FailingWriter()))

        assert storage.opened is not None
        self.assertTrue(storage.opened.closed)

    async def test_head_stats_without_opening_the_stored_file(self) -> None:
        from oldman.storage._web import install_media

        storage = _ObservedStorage(b"payload", [])
        app = _RouteCapture()
        install_media(cast(Any, app), storage=storage, url="/media/")

        response = await app.handler(
            cast(Any, SimpleNamespace(method="HEAD")),
            "large.bin",
        )

        self.assertIsInstance(response, ResponseStream)
        self.assertIsNone(storage.opened)

    async def test_route_name_conflict_is_reported_by_sanic(self) -> None:
        from oldman.storage._web import install_media

        app = Sanic("storage-media-route-conflict")

        async def occupied(request: Any) -> None:
            del request

        app.add_route(occupied, "/occupied", name="media")
        try:
            with self.assertRaisesRegex(SanicException, "media"):
                install_media(app, storage=InMemoryStorage(), url="/media/")
        finally:
            Sanic.unregister_app(app)


if __name__ == "__main__":
    unittest.main()
