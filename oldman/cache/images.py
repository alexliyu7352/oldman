"""
@author:alex
@date:2025/8/10
@time:04:15
"""

__author__ = "alex"

import asyncio
import errno
import hashlib
import io
import os
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from PIL import Image, ImageOps

from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.storage import (
    FileSystemStorage,
    InvalidStorageName,
    Storage,
    storages,
    validate_storage_name,
)

_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_INVALID_DIRECTORY_ERRNOS = {errno.ELOOP, errno.ENOTDIR}


class ImageCache:
    """Coordinate image files with expiry metadata stored in async Redis."""

    def __init__(self, storage: Storage | None = None) -> None:
        """Resolve current settings and retain the image Cache policy."""
        from oldman.conf import settings

        self.storage = storage or storages.using("default")
        self.redis_alias = settings.cache.client
        self.cache_prefix = "image_cache"
        self.max_cache_size = 10000
        self.cache_timeout = 30
        self.resize_percent = 30
        self.cache_set_key = "image_cache_zset"
        self.cache_formats = {"original": "", "webp": ".webp"}

    async def _connection(self) -> Any:
        """Return the configured decoded async Redis connection."""
        return await redis_client.using(self.redis_alias).async_get_conn()

    def get_cache_keys(self, url: str) -> dict[str, str]:
        """生成不同格式的缓存key"""
        base_key = hashlib.md5(url.encode()).hexdigest()
        return {fmt: f"{self.cache_prefix}/{base_key}_{fmt}{extension}" for fmt, extension in self.cache_formats.items()}

    async def get_cached_image(self, url: str) -> dict[str, str] | None:
        """Return existing non-expired image formats and extend their expiry."""
        redis_conn = await self._connection()
        cache_keys = self.get_cache_keys(url)
        result: dict[str, str] = {}
        touched: dict[str, float] = {}
        now = time.time()

        for fmt, cache_name in cache_keys.items():
            score = await redis_conn.zscore(self.cache_set_key, cache_name)
            if score is not None and float(score) > now and await self.storage.exists(cache_name):
                result[fmt] = cache_name
                touched[cache_name] = now + self.cache_timeout

        if touched:
            await redis_conn.zadd(self.cache_set_key, touched)

        return result if result else None

    async def cache_image(self, url: str, image_content: bytes) -> dict[str, str]:
        """Cache original and WebP files without blocking the event-loop thread."""
        redis_conn = await self._connection()
        await self._cleanup_expired_cache(redis_conn)
        await self._cleanup_old_cache(redis_conn)
        cache_names = self.get_cache_keys(url)
        if isinstance(self.storage, FileSystemStorage):
            result = await asyncio.to_thread(
                self._write_filesystem_images,
                self.storage.location,
                cache_names,
                image_content,
            )
        else:
            encoded = await asyncio.to_thread(
                self._encode_images,
                cache_names,
                image_content,
            )
            result = {}
            for fmt, name in cache_names.items():
                payload = encoded.get(name)
                if payload is None:
                    continue
                stored_name = await self.storage.save(
                    name,
                    payload,
                    overwrite=True,
                )
                result[fmt] = stored_name

        failed_names = [name for name in cache_names.values() if name not in result.values()]
        if failed_names:
            if not isinstance(self.storage, FileSystemStorage):
                for name in failed_names:
                    await self.storage.delete(name)
            await redis_conn.zrem(self.cache_set_key, *failed_names)

        expire_time = time.time() + self.cache_timeout
        await redis_conn.zadd(
            self.cache_set_key,
            dict.fromkeys(result.values(), expire_time),
        )
        return result

    def _encode_images(
        self,
        cache_names: dict[str, str],
        image_content: bytes,
    ) -> dict[str, bytes]:
        """Encode image payloads without performing Storage operations."""
        result = {cache_names["original"]: image_content}
        try:
            with Image.open(io.BytesIO(image_content)) as source_image:
                need_width = int(source_image.width * self.resize_percent / 100)
                need_height = int(source_image.height * self.resize_percent / 100)
                resized_image = self.resize_image(source_image, need_width, need_height)
                output_image = resized_image or source_image
                try:
                    webp_content = io.BytesIO()
                    output_image.save(webp_content, "WEBP")
                    result[cache_names["webp"]] = webp_content.getvalue()
                finally:
                    if resized_image is not None:
                        resized_image.close()
        except Exception as error:
            logger.error("WebP conversion failed: %s", error)
        return result

    def _write_filesystem_images(
        self,
        location: Path,
        cache_names: dict[str, str],
        image_content: bytes,
    ) -> dict[str, str]:
        """Encode and atomically publish local image files in one worker."""
        original_name = self._cache_basename(cache_names["original"])
        webp_name = self._cache_basename(cache_names["webp"])
        cache_descriptor = self._open_filesystem_cache(location, create=True)
        assert cache_descriptor is not None
        try:
            self._publish_atomic(
                cache_descriptor,
                original_name,
                partial(self._write_bytes, content=image_content),
            )
            result = {"original": cache_names["original"]}

            try:
                with Image.open(io.BytesIO(image_content)) as source_image:
                    need_width = int(source_image.width * self.resize_percent / 100)
                    need_height = int(source_image.height * self.resize_percent / 100)
                    resized_image = self.resize_image(
                        source_image,
                        need_width,
                        need_height,
                    )
                    output_image = resized_image or source_image
                    try:
                        self._publish_atomic(
                            cache_descriptor,
                            webp_name,
                            partial(output_image.save, format="WEBP"),
                        )
                        result["webp"] = cache_names["webp"]
                    finally:
                        if resized_image is not None:
                            resized_image.close()
            except Exception as error:
                logger.error("WebP conversion failed: %s", error)
                self._unlink_at(cache_descriptor, webp_name)
            return result
        finally:
            os.close(cache_descriptor)

    @staticmethod
    def _write_bytes(file: BinaryIO, *, content: bytes) -> None:
        """Write one byte payload to an already anchored temporary file."""
        file.write(content)

    @staticmethod
    def _publish_atomic(
        parent_descriptor: int,
        target_name: str,
        writer: Callable[[BinaryIO], object],
    ) -> None:
        """Publish one sibling temporary file through an anchored directory fd."""
        descriptor: int | None = None
        temporary_name: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".oldman-image-",
                dir=f"/proc/self/fd/{parent_descriptor}",
            )
            temporary_name = Path(temporary_path).name
            temporary_file = os.fdopen(descriptor, "wb")
            descriptor = None
            with temporary_file:
                writer(temporary_file)
                temporary_file.flush()
            os.replace(
                temporary_name,
                target_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_name = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_name is not None:
                ImageCache._unlink_at(parent_descriptor, temporary_name)

    def _cache_basename(self, name: str) -> str:
        """Return a Cache filename only for the exact logical Cache parent."""
        valid_name = validate_storage_name(name)
        path = PurePosixPath(valid_name)
        if path.parent != PurePosixPath(self.cache_prefix):
            raise InvalidStorageName(f"image Cache name must be inside {self.cache_prefix!r}")
        return path.name

    def _open_filesystem_cache(
        self,
        location: Path,
        *,
        create: bool,
    ) -> int | None:
        """Walk from the filesystem anchor without following any symlinks."""
        descriptor: int | None = os.open(location.anchor, _DIRECTORY_OPEN_FLAGS)
        try:
            components = (*location.parts[1:], self.cache_prefix)
            for component in components:
                next_descriptor = self._open_directory_component(
                    descriptor,
                    component,
                    create=create,
                )
                if next_descriptor is None:
                    return None
                try:
                    os.close(descriptor)
                except BaseException:
                    os.close(next_descriptor)
                    raise
                descriptor = next_descriptor
            result = descriptor
            descriptor = None
            return result
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _open_directory_component(
        self,
        parent_descriptor: int,
        name: str,
        *,
        create: bool,
    ) -> int | None:
        """Open or create one anchored directory path component safely."""
        try:
            return os.open(
                name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            if not create:
                return None
            try:
                os.mkdir(name, dir_fd=parent_descriptor)
            except FileExistsError:
                pass
            try:
                return os.open(
                    name,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=parent_descriptor,
                )
            except OSError as error:
                self._translate_unsafe_directory(error)
                raise
        except OSError as error:
            self._translate_unsafe_directory(error)
            raise

    @staticmethod
    def _translate_unsafe_directory(error: OSError) -> None:
        """Normalize non-directory and symlink parents to the Storage contract."""
        if error.errno in _INVALID_DIRECTORY_ERRNOS:
            raise InvalidStorageName("image Cache path contains a symlink or non-directory") from error

    @staticmethod
    def _unlink_at(parent_descriptor: int, name: str) -> None:
        """Unlink one anchored entry while tolerating concurrent disappearance."""
        try:
            os.unlink(name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass

    def resize_image(self, src_image: Image.Image, need_width: int, need_height: int) -> Image.Image | None:
        """Resize proportionally and pad when dimensions differ materially."""
        width, height = src_image.size
        # if width < need_width or height < need_height:
        #     raise forms.ValidationError(_(u'Image don\'t have correct size %dpx x %dpx' % (need_width, need_height)))
        if abs(width - need_width) > 10 or abs(height - need_height) > 10:
            # 这里需要考虑图片的宽高比例, 缩放时需要保持比例, 不足的地方用透明色填充,
            # 最终生成的图片大小为指定的大小, 宽为need_width, 高为need_height
            # 1. 先计算出图片的宽高比例
            ratio = float(width) / float(height)
            # 2. 等比例缩放图片, 计算出缩放后的宽高, 高度最高为need_height, 宽度最高为need_width
            # 最终计算出来的宽高为命名为resize_height和resize_width
            resize_height = int(need_width / ratio)
            resize_width = int(need_height * ratio)
            if resize_height > need_height:
                resize_height = need_height
                resize_width = int(need_height * ratio)
            elif resize_width > need_width:
                resize_width = need_width
                resize_height = int(need_width / ratio)
            # 3. 缩放图片, 最终生成的图片大小为need_width和need_height,
            cropped_image = src_image.resize((resize_width, resize_height), Image.Resampling.LANCZOS)
            # 4. 如果缩放后的图片宽度或者高度小于指定的宽度或者高度, 则需要用透明色填充
            if resize_width < need_width:
                # 宽度不足, 需要用透明色填充
                # 4.1 计算出需要填充的宽度
                fill_width = need_width - resize_width
                # 4.2 计算出需要填充的高度
                fill_height = need_height - resize_height
                # 4.3 填充图片
                # 这里判断是否是jpeg格式, 如果是jpeg格式, 则需要将图片转换成RGB模式
                if cropped_image.mode != "RGBA":
                    cropped_image = cropped_image.convert("RGBA")
                cropped_image = cropped_image.crop((0, 0, resize_width, resize_height))
                cropped_image = ImageOps.expand(cropped_image, border=(fill_width, fill_height), fill=(255, 255, 255, 0))
            elif resize_height < need_height:
                # 高度不足, 需要用透明色填充
                # 4.1 计算出需要填充的宽度
                fill_width = need_width - resize_width
                # 4.2 计算出需要填充的高度
                fill_height = need_height - resize_height
                # 4.3 填充图片
                # 这里判断是否是jpeg格式, 如果是jpeg格式, 则需要将图片转换成RGB模式
                if cropped_image.mode != "RGBA":
                    cropped_image = cropped_image.convert("RGBA")
                cropped_image = cropped_image.crop((0, 0, resize_width, resize_height))
                cropped_image = ImageOps.expand(cropped_image, border=(fill_width, fill_height), fill=(255, 255, 255, 0))
            return cropped_image
        else:
            return None

    async def _cleanup_expired_cache(self, redis_conn: Any) -> None:
        """Remove expired image files and their sorted-set entries."""
        now = time.time()
        expired_keys = await redis_conn.zrangebyscore(self.cache_set_key, 0, now)

        if expired_keys:
            await self._delete_cache_names(expired_keys)
            await redis_conn.zremrangebyscore(self.cache_set_key, 0, now)

    async def _cleanup_old_cache(self, redis_conn: Any) -> None:
        """Apply the existing oldest-entry policy when the Cache reaches its limit."""
        cache_size = int(await redis_conn.zcard(self.cache_set_key))
        if cache_size >= self.max_cache_size:
            remove_count = cache_size - self.max_cache_size + 1
            old_keys = await redis_conn.zrange(self.cache_set_key, 0, remove_count - 1)
            await self._delete_cache_names(old_keys)
            await redis_conn.zremrangebyrank(self.cache_set_key, 0, remove_count - 1)

    async def _delete_cache_names(self, cache_names: list[str]) -> None:
        """Delete one cleanup batch through the backend-appropriate path."""
        if isinstance(self.storage, FileSystemStorage):
            await asyncio.to_thread(
                self._remove_filesystem_files,
                self.storage.location,
                cache_names,
            )
            return
        for name in cache_names:
            await self.storage.delete(name)

    def _remove_filesystem_files(self, location: Path, cache_names: list[str]) -> None:
        """Remove local Cache files while tolerating concurrent disappearance."""
        basenames: list[str] = []
        for name in cache_names:
            try:
                basenames.append(self._cache_basename(name))
            except InvalidStorageName:
                continue
        if not basenames:
            return

        cache_descriptor = self._open_filesystem_cache(location, create=False)
        if cache_descriptor is None:
            return
        try:
            for basename in basenames:
                self._unlink_at(cache_descriptor, basename)
        finally:
            os.close(cache_descriptor)
