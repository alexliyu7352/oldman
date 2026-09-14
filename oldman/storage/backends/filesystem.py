from __future__ import annotations

import asyncio
import errno
import os
import stat
import sys
import tempfile
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Literal, TypeVar, cast

import aiofiles
from aiofiles.threadpool.binary import AsyncBufferedIOBase

from oldman import conf
from oldman.storage.base import Storage, StorageContent, validate_storage_name
from oldman.storage.exceptions import InvalidStorageName
from oldman.storage.streams import FileInfo, StoredFile

_TEMPORARY_PREFIX = ".oldman-storage-"
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_INVALID_PATH_ERRNOS = {errno.ELOOP, errno.ENOTDIR}
_T = TypeVar("_T")


class _CancellationDeferrer:
    def __init__(self) -> None:
        self._cancellation: asyncio.CancelledError | None = None
        self._task = asyncio.current_task()
        self._initial_cancelling = self._task.cancelling() if self._task is not None else 0

    @property
    def cancelled(self) -> bool:
        return self._cancellation is not None

    async def wait(
        self,
        future: asyncio.Future[_T],
        *,
        cancellation_wins_on_error: bool = True,
    ) -> _T:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError as cancellation:
                if self._cancellation is None:
                    self._cancellation = cancellation
            except BaseException:
                break

        try:
            return future.result()
        except BaseException:
            if self._cancellation is not None and cancellation_wins_on_error:
                raise self._cancellation from None
            raise

    def discard_cancellation(self) -> None:
        if self._cancellation is None or self._task is None:
            return
        while self._task.cancelling() > self._initial_cancelling:
            self._task.uncancel()
        self._cancellation = None

    def raise_if_cancelled(self) -> None:
        if self._cancellation is not None:
            raise self._cancellation


async def _coalesce_chunks(content: AsyncIterable[bytes], chunk_size: int) -> AsyncIterator[bytes | memoryview]:
    """Combine small input chunks without buffering already-large chunks."""
    buffer = bytearray()
    async for chunk in content:
        if not isinstance(chunk, bytes):
            raise TypeError("content chunks must be bytes")
        if not chunk:
            continue
        if not buffer and len(chunk) >= chunk_size:
            yield chunk
            continue

        view = memoryview(chunk)
        offset = 0
        if buffer:
            needed = chunk_size - len(buffer)
            buffer.extend(view[:needed])
            offset = min(needed, len(view))
            if len(buffer) == chunk_size:
                yield bytes(buffer)
                buffer.clear()

        remainder = view[offset:]
        if len(remainder) >= chunk_size:
            yield remainder
        elif remainder:
            buffer.extend(remainder)

    if buffer:
        yield bytes(buffer)


@dataclass(slots=True)
class _SaveResources:
    parent_descriptor: int | None
    target_name: str
    temporary_descriptor: int | None
    temporary_name: str | None


class _FileSystemStoredFile(StoredFile):
    def __init__(
        self,
        *,
        name: str,
        file: AsyncBufferedIOBase,
        info: FileInfo,
        chunk_size: int,
    ) -> None:
        super().__init__(name=name, info=info, chunk_size=chunk_size)
        self._file = file

    async def read(self, size: int = -1) -> bytes:
        return await self._file.read(size)

    async def close(self) -> None:
        await self._file.close()


class FileSystemStorage(Storage):
    """Local storage with streamed writes and inode-anchored atomic publication."""

    def __init__(
        self,
        location: str | Path,
        alias: str | None = None,
        chunk_size: int = 262_144,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        super().__init__(alias=alias)
        configured = Path(location).expanduser()
        self._location = (configured if configured.is_absolute() else Path(conf.PROJECT_BASE_PATH) / configured).resolve()
        self._chunk_size = chunk_size

    @property
    def location(self) -> Path:
        return self._location

    async def _save(self, name: str, content: StorageContent, *, overwrite: bool) -> str:
        resources = await self._prepare_save(name)
        file: AsyncBufferedIOBase | None = None
        committed = False
        try:
            descriptor = resources.temporary_descriptor
            assert descriptor is not None
            resources.temporary_descriptor = None
            file = await self._open_aiofile(
                descriptor,
                mode="wb",
                owned_descriptor=descriptor,
            )
            if isinstance(content, bytes):
                await file.write(content)
            else:
                async for chunk in _coalesce_chunks(content, self._chunk_size):
                    await file.write(chunk)
            await file.close()
            file = None

            if overwrite:
                assert resources.parent_descriptor is not None
                assert resources.temporary_name is not None
                await self._run_commit_operation(
                    partial(
                        os.replace,
                        resources.temporary_name,
                        resources.target_name,
                        src_dir_fd=resources.parent_descriptor,
                        dst_dir_fd=resources.parent_descriptor,
                    )
                )
                committed = True
                resources.temporary_name = None
                return name

            candidate_name = name
            candidate_basename = resources.target_name
            while True:
                try:
                    assert resources.parent_descriptor is not None
                    assert resources.temporary_name is not None
                    await self._run_commit_operation(
                        partial(
                            os.link,
                            resources.temporary_name,
                            candidate_basename,
                            src_dir_fd=resources.parent_descriptor,
                            dst_dir_fd=resources.parent_descriptor,
                            follow_symlinks=False,
                        )
                    )
                except FileExistsError as collision:
                    candidate_name = validate_storage_name(self.get_alternative_name(name))
                    candidate_path = PurePosixPath(candidate_name)
                    if candidate_path.parent != PurePosixPath(name).parent:
                        raise InvalidStorageName("alternative storage name must keep the requested parent directory") from collision
                    candidate_basename = candidate_path.name
                else:
                    committed = True
                    return candidate_name
        finally:
            await self._finish_save_cleanup(
                file=file,
                resources=resources,
                active_error=sys.exception(),
                committed=committed,
            )

    async def _open(self, name: str) -> StoredFile:
        file_descriptor, status = await self._open_file(name)
        file = await self._open_aiofile(
            file_descriptor,
            mode="rb",
            owned_descriptor=file_descriptor,
        )
        info = self._file_info(name, status)
        return _FileSystemStoredFile(
            name=name,
            file=file,
            info=info,
            chunk_size=self._chunk_size,
        )

    async def _delete(self, name: str) -> None:
        await self._run_fd_operation(partial(self._run_with_parent, name, False, self._delete_entry))

    async def _exists(self, name: str) -> bool:
        try:
            return await self._run_fd_operation(partial(self._run_with_parent, name, False, self._entry_exists))
        except FileNotFoundError:
            return False

    async def _stat(self, name: str) -> FileInfo:
        status = await self._run_fd_operation(partial(self._run_with_parent, name, False, self._stat_entry))
        return self._file_info(name, status)

    async def _open_file(self, name: str) -> tuple[int, os.stat_result]:
        cancellation = _CancellationDeferrer()
        opening = asyncio.create_task(
            asyncio.to_thread(
                self._run_with_parent,
                name,
                False,
                self._open_file_entry,
            )
        )
        descriptor, status = await cancellation.wait(opening)
        if cancellation.cancelled:
            try:
                await self._close_if_open(descriptor)
            finally:
                cancellation.raise_if_cancelled()
        return descriptor, status

    @staticmethod
    async def _run_fd_operation(operation: Callable[[], _T]) -> _T:
        cancellation = _CancellationDeferrer()
        worker = asyncio.create_task(asyncio.to_thread(operation))
        result = await cancellation.wait(worker)
        cancellation.raise_if_cancelled()
        return result

    @staticmethod
    async def _run_commit_operation(operation: Callable[[], _T]) -> _T:
        await asyncio.sleep(0)
        cancellation = _CancellationDeferrer()
        worker = asyncio.create_task(asyncio.to_thread(operation))
        result = await cancellation.wait(worker)
        cancellation.discard_cancellation()
        return result

    def _run_with_parent(
        self,
        name: str,
        create: bool,
        operation: Callable[[int, str], _T],
    ) -> _T:
        parent_descriptor, basename = self._open_parent_directory(name, create)
        try:
            return operation(parent_descriptor, basename)
        finally:
            os.close(parent_descriptor)

    def _open_parent_directory(self, name: str, create: bool) -> tuple[int, str]:
        descriptor = os.open(self.location.anchor, _DIRECTORY_OPEN_FLAGS)
        components = (*self.location.parts[1:], *PurePosixPath(name).parts[:-1])
        try:
            for component in components:
                next_descriptor = self._open_directory_component(descriptor, component, create)
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor, PurePosixPath(name).name
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _open_directory_component(parent_descriptor: int, name: str, create: bool) -> int:
        try:
            return os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, dir_fd=parent_descriptor)
            except FileExistsError:
                pass
            try:
                return os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
            except OSError as error:
                FileSystemStorage._translate_unsafe_path(error)
                raise
        except OSError as error:
            FileSystemStorage._translate_unsafe_path(error)
            raise

    @staticmethod
    def _translate_unsafe_path(error: OSError) -> None:
        if error.errno in _INVALID_PATH_ERRNOS:
            raise InvalidStorageName("storage path contains a symlink or non-directory") from error

    @staticmethod
    def _reject_existing_symlink(parent_descriptor: int, name: str) -> None:
        try:
            status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(status.st_mode):
            raise InvalidStorageName("storage target must not be a symlink")

    @staticmethod
    def _open_file_entry(parent_descriptor: int, name: str) -> tuple[int, os.stat_result]:
        try:
            descriptor = os.open(name, _FILE_OPEN_FLAGS, dir_fd=parent_descriptor)
        except OSError as error:
            FileSystemStorage._translate_unsafe_path(error)
            raise
        try:
            return descriptor, os.fstat(descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _stat_entry(parent_descriptor: int, name: str) -> os.stat_result:
        status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(status.st_mode):
            raise InvalidStorageName("storage target must not be a symlink")
        return status

    @staticmethod
    def _entry_exists(parent_descriptor: int, name: str) -> bool:
        try:
            FileSystemStorage._stat_entry(parent_descriptor, name)
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _delete_entry(parent_descriptor: int, name: str) -> None:
        try:
            FileSystemStorage._stat_entry(parent_descriptor, name)
            os.unlink(name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            return

    async def _prepare_save(self, name: str) -> _SaveResources:
        cancellation = _CancellationDeferrer()
        preparation = asyncio.create_task(asyncio.to_thread(self._prepare_save_resources, name))
        resources = await cancellation.wait(preparation)
        if cancellation.cancelled:
            try:
                cleanup = asyncio.create_task(asyncio.to_thread(self._cleanup_save_entries, resources))
                await cancellation.wait(cleanup)
            finally:
                cancellation.raise_if_cancelled()
        return resources

    def _prepare_save_resources(self, name: str) -> _SaveResources:
        parent_descriptor, target_name = self._open_parent_directory(name, True)
        temporary_descriptor: int | None = None
        temporary_name: str | None = None
        try:
            self._reject_existing_symlink(parent_descriptor, target_name)
            temporary_descriptor, temporary_path = tempfile.mkstemp(
                prefix=_TEMPORARY_PREFIX,
                dir=f"/proc/self/fd/{parent_descriptor}",
            )
            temporary_name = Path(temporary_path).name
            return _SaveResources(
                parent_descriptor=parent_descriptor,
                target_name=target_name,
                temporary_descriptor=temporary_descriptor,
                temporary_name=temporary_name,
            )
        except BaseException:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    pass
            os.close(parent_descriptor)
            raise

    async def _open_aiofile(
        self,
        file: int,
        *,
        mode: Literal["rb", "wb"],
        owned_descriptor: int,
    ) -> AsyncBufferedIOBase:
        cancellation = _CancellationDeferrer()
        opening = asyncio.ensure_future(aiofiles.open(file, mode, closefd=True))
        try:
            opened = cast(AsyncBufferedIOBase, await cancellation.wait(opening))
        except BaseException:
            try:
                await self._close_if_open(owned_descriptor)
            finally:
                cancellation.raise_if_cancelled()
            raise
        if cancellation.cancelled:
            closing = asyncio.ensure_future(opened.close())
            try:
                await cancellation.wait(closing)
            finally:
                cancellation.raise_if_cancelled()
        return opened

    async def _cleanup_save(
        self,
        *,
        file: AsyncBufferedIOBase | None,
        resources: _SaveResources,
        active_error: BaseException | None,
    ) -> None:
        cleanup_error: BaseException | None = None
        if file is not None:
            try:
                await file.close()
            except BaseException as error:
                cleanup_error = error
        try:
            await self._run_fd_operation(partial(self._cleanup_save_entries, resources))
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
        if active_error is None and cleanup_error is not None:
            raise cleanup_error

    async def _finish_save_cleanup(
        self,
        *,
        file: AsyncBufferedIOBase | None,
        resources: _SaveResources,
        active_error: BaseException | None,
        committed: bool,
    ) -> None:
        cleanup = self._cleanup_save(
            file=file,
            resources=resources,
            active_error=active_error,
        )
        if not committed:
            await cleanup
            return

        cancellation = _CancellationDeferrer()
        cleanup_task = asyncio.create_task(cleanup)
        try:
            await cancellation.wait(
                cleanup_task,
                cancellation_wins_on_error=False,
            )
        finally:
            cancellation.discard_cancellation()

    @staticmethod
    def _cleanup_save_entries(resources: _SaveResources) -> None:
        cleanup_error: BaseException | None = None
        if resources.temporary_descriptor is not None:
            try:
                os.close(resources.temporary_descriptor)
            except BaseException as error:
                cleanup_error = error
            resources.temporary_descriptor = None
        if resources.temporary_name is not None and resources.parent_descriptor is not None:
            try:
                os.unlink(resources.temporary_name, dir_fd=resources.parent_descriptor)
            except FileNotFoundError:
                pass
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
            resources.temporary_name = None
        if resources.parent_descriptor is not None:
            try:
                os.close(resources.parent_descriptor)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
            resources.parent_descriptor = None
        if cleanup_error is not None:
            raise cleanup_error

    @staticmethod
    async def _close_if_open(descriptor: int) -> None:
        try:
            await FileSystemStorage._run_fd_operation(partial(os.close, descriptor))
        except OSError as error:
            if error.errno != errno.EBADF:
                raise

    @staticmethod
    def _file_info(name: str, status: os.stat_result) -> FileInfo:
        return FileInfo(
            name=name,
            size=status.st_size,
            modified_at=datetime.fromtimestamp(status.st_mtime, UTC),
        )


__all__ = ("FileSystemStorage",)
