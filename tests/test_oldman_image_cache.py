"""Behavior tests for the asynchronous image Cache storage consumer."""

from __future__ import annotations

import asyncio
import importlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

import oldman.conf as conf
from oldman.storage import (
    FileSystemStorage,
    InMemoryStorage,
    InvalidStorageName,
    StorageContent,
)


def _image_bytes(color: str = "red") -> bytes:
    """Return a small valid PNG payload for conversion tests."""
    output = io.BytesIO()
    with Image.new("RGB", (30, 20), color) as image:
        image.save(output, "PNG")
    return output.getvalue()


async def _run_in_thread(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Execute a patched to_thread call synchronously inside the test loop."""
    return function(*args, **kwargs)


class RecordingMemoryStorage(InMemoryStorage):
    """Expose operation ordering without replacing the real memory backend."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str]] = []

    async def save(
        self,
        name: str,
        content: StorageContent,
        *,
        overwrite: bool = False,
    ) -> str:
        self.events.append(("save-start", name))
        await asyncio.sleep(0)
        saved_name = await super().save(name, content, overwrite=overwrite)
        self.events.append(("save-end", name))
        return saved_name

    async def delete(self, name: str) -> None:
        self.events.append(("delete-start", name))
        await asyncio.sleep(0)
        await super().delete(name)
        self.events.append(("delete-end", name))


class StatefulRedisConnection:
    """Provide real sorted-set state for stale-format regression tests."""

    def __init__(self) -> None:
        self.scores: dict[str, float] = {}

    async def zscore(self, key: str, name: str) -> float | None:
        del key
        return self.scores.get(name)

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        del key
        self.scores.update(mapping)

    async def zrem(self, key: str, *names: str) -> None:
        del key
        for name in names:
            self.scores.pop(name, None)

    async def zrangebyscore(
        self,
        key: str,
        minimum: float,
        maximum: float,
    ) -> list[str]:
        del key
        return [name for name, score in self.scores.items() if minimum <= score <= maximum]

    async def zremrangebyscore(
        self,
        key: str,
        minimum: float,
        maximum: float,
    ) -> None:
        for name in await self.zrangebyscore(key, minimum, maximum):
            self.scores.pop(name, None)

    async def zcard(self, key: str) -> int:
        del key
        return len(self.scores)

    async def zrange(self, key: str, start: int, end: int) -> list[str]:
        del key
        ordered = sorted(self.scores, key=self.scores.__getitem__)
        return ordered[start : end + 1]

    async def zremrangebyrank(self, key: str, start: int, end: int) -> None:
        for name in await self.zrange(key, start, end):
            self.scores.pop(name, None)


class ImageCacheTest(unittest.IsolatedAsyncioTestCase):
    """Verify logical names, Redis metadata, and backend-specific I/O paths."""

    def setUp(self) -> None:
        """Create isolated settings and one fake Redis alias for each test."""
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.settings = SimpleNamespace(
            cache=SimpleNamespace(client="CACHE"),
        )
        self.connection = AsyncMock()
        self.alias_client = SimpleNamespace(async_get_conn=AsyncMock(return_value=self.connection))
        self.redis_registry = Mock()
        self.redis_registry.using.return_value = self.alias_client

    def _cache(self, storage: InMemoryStorage | FileSystemStorage) -> Any:
        """Construct ImageCache with one explicitly selected concrete backend."""
        from oldman.cache.images import ImageCache

        with (
            patch.dict(conf.__dict__, {"settings": self.settings}),
            patch("oldman.cache.images.redis_client", self.redis_registry),
        ):
            cache = ImageCache(storage=storage)
        return cache

    async def _read(self, storage: InMemoryStorage | FileSystemStorage, name: str) -> bytes:
        async with await storage.open(name) as stored:
            return await stored.read()

    def _stateful_connection(self) -> StatefulRedisConnection:
        """Install one stateful Redis fake behind the existing client registry."""
        connection = StatefulRedisConnection()
        self.alias_client.async_get_conn.return_value = connection
        return connection

    def _storage_with_swapped_intermediate(
        self,
    ) -> tuple[FileSystemStorage, Path]:
        """Replace a resolved location parent with a symlink to an outside tree."""
        root = Path(self.tempdir.name) / "root"
        intermediate = root / "intermediate"
        location = intermediate / "nested" / "media"
        intermediate.mkdir(parents=True)
        storage = FileSystemStorage(location)

        intermediate.rename(root / "original-intermediate")
        outside = Path(self.tempdir.name) / "outside"
        (outside / "nested" / "media").mkdir(parents=True)
        intermediate.symlink_to(outside, target_is_directory=True)
        return storage, outside / "nested" / "media"

    def test_module_import_has_no_legacy_paths_or_eager_settings_dependency(self) -> None:
        """The consumer source must not retain absolute media-root wiring."""
        module = importlib.import_module("oldman.cache.images")
        assert module.__file__ is not None
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("legacy_settings", source)
        self.assertNotIn("sync_redis", source)
        self.assertNotIn("settings.media." + "root", source)

    def test_default_storage_uses_default_alias_and_explicit_storage_skips_lookup(
        self,
    ) -> None:
        """Default construction selects default storage while injection stays concrete."""
        from oldman.cache.images import ImageCache

        selected = InMemoryStorage()
        injected = InMemoryStorage()
        storage_registry = Mock()
        storage_registry.using.return_value = selected

        with (
            patch.dict(conf.__dict__, {"settings": self.settings}),
            patch("oldman.cache.images.storages", storage_registry),
        ):
            default_cache = ImageCache()
            explicit_cache = ImageCache(storage=injected)

        self.assertIs(selected, default_cache.storage)
        self.assertIs(injected, explicit_cache.storage)
        storage_registry.using.assert_called_once_with("default")

    def test_cache_keys_are_storage_names_with_format_specific_extensions(self) -> None:
        """Every Cache and Redis reference uses the same relative logical name."""
        cache = self._cache(InMemoryStorage())

        self.assertEqual(
            {
                "original": "image_cache/829080890080bd67c2514cb5e6cf5796_original",
                "webp": "image_cache/829080890080bd67c2514cb5e6cf5796_webp.webp",
            },
            cache.get_cache_keys("https://example.test/image.png"),
        )

    async def test_get_cached_image_checks_storage_and_touches_only_real_hits_once(
        self,
    ) -> None:
        """A live Redis member is returned only while its stored object exists."""
        storage = InMemoryStorage()
        cache = self._cache(storage)
        names = cache.get_cache_keys("https://example.test/image.png")
        await storage.save(names["original"], b"image")
        self.connection.zscore.side_effect = [
            time.time() + 60,
            time.time() + 60,
        ]

        with patch("oldman.cache.images.redis_client", self.redis_registry):
            result = await cache.get_cached_image("https://example.test/image.png")

        self.redis_registry.using.assert_called_once_with("CACHE")
        self.alias_client.async_get_conn.assert_awaited_once_with()
        self.assertEqual(2, self.connection.zscore.await_count)
        self.connection.zadd.assert_awaited_once()
        touched = self.connection.zadd.await_args.args[1]
        self.assertEqual({names["original"]}, set(touched))
        self.assertEqual({"original": names["original"]}, result)

    async def test_generic_storage_encodes_off_loop_then_saves_formats_sequentially(
        self,
    ) -> None:
        """The generic path performs one encoding handoff and ordered async saves."""
        storage = RecordingMemoryStorage()
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        to_thread = AsyncMock(side_effect=_run_in_thread)
        image_content = _image_bytes()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.asyncio.to_thread", to_thread),
        ):
            result = await cache.cache_image(
                "https://example.test/image.png",
                image_content,
            )

        names = cache.get_cache_keys("https://example.test/image.png")
        cache._cleanup_expired_cache.assert_awaited_once_with(self.connection)
        cache._cleanup_old_cache.assert_awaited_once_with(self.connection)
        to_thread.assert_awaited_once_with(
            cache._encode_images,
            names,
            image_content,
        )
        self.assertEqual(
            [
                ("save-start", names["original"]),
                ("save-end", names["original"]),
                ("save-start", names["webp"]),
                ("save-end", names["webp"]),
            ],
            storage.events,
        )
        self.assertEqual(names, result)
        self.assertEqual(image_content, await self._read(storage, names["original"]))
        webp_content = await self._read(storage, names["webp"])
        with Image.open(io.BytesIO(webp_content)) as converted:
            self.assertEqual("WEBP", converted.format)
            self.assertEqual((9, 6), converted.size)

    async def test_filesystem_storage_writes_both_formats_atomically_in_one_thread(
        self,
    ) -> None:
        """The local fast path publishes readable files with one worker handoff."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        to_thread = AsyncMock(side_effect=_run_in_thread)
        image_content = _image_bytes()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.asyncio.to_thread", to_thread),
            patch("oldman.cache.images.os.replace", wraps=os.replace) as replace,
        ):
            result = await cache.cache_image(
                "https://example.test/image.png",
                image_content,
            )

        names = cache.get_cache_keys("https://example.test/image.png")
        to_thread.assert_awaited_once_with(
            cache._write_filesystem_images,
            storage.location,
            names,
            image_content,
        )
        self.assertEqual(2, replace.call_count)
        for call in replace.call_args_list:
            temporary_name, final_name = call.args
            self.assertTrue(str(temporary_name).startswith(".oldman-image-"))
            self.assertNotIn("/", str(temporary_name))
            self.assertIn(final_name, {Path(name).name for name in names.values()})
            self.assertEqual(
                call.kwargs["src_dir_fd"],
                call.kwargs["dst_dir_fd"],
            )
        self.assertEqual(names, result)
        self.assertEqual(image_content, await self._read(storage, names["original"]))
        with Image.open(io.BytesIO(await self._read(storage, names["webp"]))) as converted:
            self.assertEqual("WEBP", converted.format)
        self.assertEqual([], list(storage.location.rglob(".oldman-image-*")))

    async def test_expired_generic_cleanup_deletes_storage_names_sequentially(
        self,
    ) -> None:
        """Expired generic objects are deleted in order before Redis metadata."""
        storage = RecordingMemoryStorage()
        cache = self._cache(storage)
        expired_names = [
            "image_cache/expired_original",
            "image_cache/expired_webp.webp",
        ]
        for name in expired_names:
            await storage.save(name, b"stale")
        storage.events.clear()
        self.connection.zrangebyscore.return_value = expired_names

        await cache._cleanup_expired_cache(self.connection)

        self.assertEqual(
            [
                ("delete-start", expired_names[0]),
                ("delete-end", expired_names[0]),
                ("delete-start", expired_names[1]),
                ("delete-end", expired_names[1]),
            ],
            storage.events,
        )
        self.connection.zremrangebyscore.assert_awaited_once()
        for name in expired_names:
            self.assertFalse(await storage.exists(name))

    async def test_expired_filesystem_cleanup_uses_one_batch_thread(self) -> None:
        """One local cleanup batch removes all stale names in one worker handoff."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        expired_names = [
            "image_cache/expired_original",
            "image_cache/expired_webp.webp",
        ]
        for name in expired_names:
            await storage.save(name, b"stale")
        self.connection.zrangebyscore.return_value = expired_names
        to_thread = AsyncMock(side_effect=_run_in_thread)

        with patch("oldman.cache.images.asyncio.to_thread", to_thread):
            await cache._cleanup_expired_cache(self.connection)

        to_thread.assert_awaited_once_with(
            cache._remove_filesystem_files,
            storage.location,
            expired_names,
        )
        for name in expired_names:
            self.assertFalse(await storage.exists(name))

    async def test_capacity_cleanup_preserves_existing_eviction_policy(self) -> None:
        """Capacity cleanup evicts exactly the pre-existing oldest-entry count."""
        storage = InMemoryStorage()
        cache = self._cache(storage)
        cache.max_cache_size = 2
        old_names = [
            "image_cache/old_original",
            "image_cache/old_webp.webp",
        ]
        for name in old_names:
            await storage.save(name, b"old")
        self.connection.zcard.return_value = 3
        self.connection.zrange.return_value = old_names

        await cache._cleanup_old_cache(self.connection)

        self.connection.zcard.assert_awaited_once_with(cache.cache_set_key)
        self.connection.zrange.assert_awaited_once_with(cache.cache_set_key, 0, 1)
        self.connection.zremrangebyrank.assert_awaited_once_with(
            cache.cache_set_key,
            0,
            1,
        )
        for name in old_names:
            self.assertFalse(await storage.exists(name))

    async def test_webp_failure_keeps_and_records_only_successful_original(self) -> None:
        """A conversion failure retains original data without stale WebP metadata."""
        storage = InMemoryStorage()
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        image_content = _image_bytes()
        logger = Mock()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.logger", logger),
            patch.object(Image.Image, "save", side_effect=OSError("webp unavailable")),
        ):
            result = await cache.cache_image(
                "https://example.test/image.png",
                image_content,
            )

        original_name = cache.get_cache_keys("https://example.test/image.png")["original"]
        self.assertEqual({"original": original_name}, result)
        self.assertEqual(image_content, await self._read(storage, original_name))
        logger.error.assert_called_once()
        self.connection.zadd.assert_awaited_once()
        recorded = self.connection.zadd.await_args.args[1]
        self.assertEqual({original_name}, set(recorded))

    async def test_generic_webp_failure_removes_previous_object_and_member(self) -> None:
        """A failed generic refresh cannot expose an older derived image."""
        storage = InMemoryStorage()
        cache = self._cache(storage)
        connection = self._stateful_connection()
        url = "https://example.test/stale-generic.png"
        old_content = _image_bytes("red")
        new_content = _image_bytes("blue")
        logger = Mock()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.logger", logger),
        ):
            await cache.cache_image(url, old_content)
            with patch.object(
                Image.Image,
                "save",
                side_effect=OSError("webp unavailable"),
            ):
                refreshed = await cache.cache_image(url, new_content)
            hit = await cache.get_cached_image(url)

        names = cache.get_cache_keys(url)
        self.assertEqual({"original": names["original"]}, refreshed)
        self.assertEqual({"original": names["original"]}, hit)
        self.assertEqual(new_content, await self._read(storage, names["original"]))
        self.assertFalse(await storage.exists(names["webp"]))
        self.assertNotIn(names["webp"], connection.scores)
        logger.error.assert_called_once()

    async def test_filesystem_webp_failure_removes_previous_object_and_member(
        self,
    ) -> None:
        """A failed local refresh removes the old WebP in the same worker batch."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        connection = self._stateful_connection()
        url = "https://example.test/stale-filesystem.png"
        old_content = _image_bytes("red")
        new_content = _image_bytes("blue")
        logger = Mock()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.logger", logger),
        ):
            await cache.cache_image(url, old_content)
            with patch.object(
                Image.Image,
                "save",
                side_effect=OSError("webp unavailable"),
            ):
                refreshed = await cache.cache_image(url, new_content)
            hit = await cache.get_cached_image(url)

        names = cache.get_cache_keys(url)
        self.assertEqual({"original": names["original"]}, refreshed)
        self.assertEqual({"original": names["original"]}, hit)
        self.assertEqual(new_content, await self._read(storage, names["original"]))
        self.assertFalse(await storage.exists(names["webp"]))
        self.assertNotIn(names["webp"], connection.scores)
        self.assertEqual([], list(storage.location.rglob(".oldman-image-*")))
        logger.error.assert_called_once()

    async def test_filesystem_write_rejects_symlink_cache_directory(self) -> None:
        """The local fast path cannot publish through a symlinked parent."""
        location = Path(self.tempdir.name) / "media"
        outside = Path(self.tempdir.name) / "outside"
        location.mkdir()
        outside.mkdir()
        (location / "image_cache").symlink_to(outside, target_is_directory=True)
        storage = FileSystemStorage(location)
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            self.assertRaises(InvalidStorageName),
        ):
            await cache.cache_image(
                "https://example.test/symlink.png",
                _image_bytes(),
            )

        self.assertEqual([], list(outside.iterdir()))
        self.connection.zadd.assert_not_awaited()

    async def test_filesystem_write_rejects_swapped_intermediate_symlink(self) -> None:
        """The local writer walks every resolved location parent without symlinks."""
        storage, outside_location = self._storage_with_swapped_intermediate()
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        to_thread = AsyncMock(side_effect=_run_in_thread)

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.asyncio.to_thread", to_thread),
            self.assertRaises(InvalidStorageName),
        ):
            await cache.cache_image(
                "https://example.test/intermediate-write.png",
                _image_bytes(),
            )

        to_thread.assert_awaited_once()
        self.assertEqual([], list(outside_location.iterdir()))
        self.connection.zadd.assert_not_awaited()

    async def test_filesystem_cleanup_ignores_names_outside_cache_prefix(self) -> None:
        """A polluted Redis member cannot delete another filesystem object."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        protected_name = "other/keep.bin"
        stale_name = "image_cache/stale_original"
        await storage.save(protected_name, b"keep")
        await storage.save(stale_name, b"stale")
        self.connection.zrangebyscore.return_value = [protected_name, stale_name]
        to_thread = AsyncMock(side_effect=_run_in_thread)

        with patch("oldman.cache.images.asyncio.to_thread", to_thread):
            await cache._cleanup_expired_cache(self.connection)

        to_thread.assert_awaited_once()
        self.assertTrue(await storage.exists(protected_name))
        self.assertFalse(await storage.exists(stale_name))

    async def test_filesystem_cleanup_rejects_symlink_cache_directory(self) -> None:
        """The local cleanup worker cannot unlink through a symlinked parent."""
        location = Path(self.tempdir.name) / "media"
        outside = Path(self.tempdir.name) / "outside"
        location.mkdir()
        outside.mkdir()
        protected = outside / "protected.bin"
        protected.write_bytes(b"keep")
        (location / "image_cache").symlink_to(outside, target_is_directory=True)
        storage = FileSystemStorage(location)
        cache = self._cache(storage)
        self.connection.zrangebyscore.return_value = ["image_cache/protected.bin"]
        to_thread = AsyncMock(side_effect=_run_in_thread)

        with (
            patch("oldman.cache.images.asyncio.to_thread", to_thread),
            self.assertRaises(InvalidStorageName),
        ):
            await cache._cleanup_expired_cache(self.connection)

        to_thread.assert_awaited_once()
        self.assertEqual(b"keep", protected.read_bytes())
        self.connection.zremrangebyscore.assert_not_awaited()

    async def test_filesystem_cleanup_rejects_swapped_intermediate_symlink(
        self,
    ) -> None:
        """The local cleanup worker cannot traverse a swapped location parent."""
        storage, outside_location = self._storage_with_swapped_intermediate()
        outside_cache = outside_location / "image_cache"
        outside_cache.mkdir()
        protected = outside_cache / "protected.bin"
        protected.write_bytes(b"keep")
        cache = self._cache(storage)
        self.connection.zrangebyscore.return_value = ["image_cache/protected.bin"]
        to_thread = AsyncMock(side_effect=_run_in_thread)

        with (
            patch("oldman.cache.images.asyncio.to_thread", to_thread),
            self.assertRaises(InvalidStorageName),
        ):
            await cache._cleanup_expired_cache(self.connection)

        to_thread.assert_awaited_once()
        self.assertEqual(b"keep", protected.read_bytes())
        self.connection.zremrangebyscore.assert_not_awaited()

    async def test_filesystem_fdopen_failure_closes_descriptor_and_tempfile(self) -> None:
        """Failure to wrap a temporary fd cannot leak its file or descriptor."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        descriptors: list[int] = []
        temporary_paths: list[Path] = []
        real_mkstemp = tempfile.mkstemp

        def recording_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
            descriptor, name = real_mkstemp(*args, **kwargs)
            descriptors.append(descriptor)
            temporary_paths.append(Path(name))
            return descriptor, name

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch(
                "oldman.cache.images.tempfile.mkstemp",
                side_effect=recording_mkstemp,
            ),
            patch(
                "oldman.cache.images.os.fdopen",
                side_effect=OSError("fdopen failed"),
            ),
            self.assertRaisesRegex(OSError, "fdopen failed"),
        ):
            await cache.cache_image(
                "https://example.test/fdopen.png",
                _image_bytes(),
            )

        leaked_descriptors: list[int] = []
        for descriptor in descriptors:
            try:
                os.fstat(descriptor)
            except OSError:
                pass
            else:
                leaked_descriptors.append(descriptor)
                os.close(descriptor)
        self.assertEqual([], leaked_descriptors)
        self.assertTrue(temporary_paths)
        self.assertTrue(all(not path.exists() for path in temporary_paths))
        self.assertEqual([], list(storage.location.rglob(".oldman-image-*")))
        self.connection.zadd.assert_not_awaited()

    async def test_filesystem_webp_replace_failure_cleans_temp_and_records_original(
        self,
    ) -> None:
        """A failed WebP publication leaves no temp or derived metadata."""
        storage = FileSystemStorage(Path(self.tempdir.name) / "media")
        cache = self._cache(storage)
        cache._cleanup_expired_cache = AsyncMock()
        cache._cleanup_old_cache = AsyncMock()
        real_replace = os.replace
        replace_calls = 0
        logger = Mock()

        def fail_second_replace(*args: Any, **kwargs: Any) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("replace failed")
            real_replace(*args, **kwargs)

        with (
            patch("oldman.cache.images.redis_client", self.redis_registry),
            patch("oldman.cache.images.logger", logger),
            patch(
                "oldman.cache.images.os.replace",
                side_effect=fail_second_replace,
            ),
        ):
            result = await cache.cache_image(
                "https://example.test/replace.png",
                _image_bytes(),
            )

        names = cache.get_cache_keys("https://example.test/replace.png")
        self.assertEqual({"original": names["original"]}, result)
        self.assertTrue(await storage.exists(names["original"]))
        self.assertFalse(await storage.exists(names["webp"]))
        self.assertEqual([], list(storage.location.rglob(".oldman-image-*")))
        recorded = self.connection.zadd.await_args.args[1]
        self.assertEqual({names["original"]}, set(recorded))
        logger.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
