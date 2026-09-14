from __future__ import annotations

import asyncio
import secrets
import string
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Awaitable
from pathlib import PurePosixPath
from typing import TypeVar

from oldman.storage.exceptions import (
    InvalidStorageName,
    StorageBackendError,
    StorageConfigurationError,
    StorageError,
    StorageFileNotFound,
)
from oldman.storage.streams import FileInfo, StoredFile

type StorageContent = bytes | AsyncIterable[bytes]

_T = TypeVar("_T")
_NAME_SUFFIX_ALPHABET = string.ascii_letters + string.digits


class _InvalidContentChunk(TypeError):
    pass


def validate_storage_name(name: str) -> str:
    """Validate and return a safe, relative POSIX storage name unchanged."""
    if not isinstance(name, str):
        raise InvalidStorageName("storage name must be a string")
    if not name:
        raise InvalidStorageName("storage name must not be empty")
    if name.startswith("/") or name.endswith("/"):
        raise InvalidStorageName("storage name must not start or end with '/'")
    if "\\" in name:
        raise InvalidStorageName("storage name must use POSIX separators")
    if "//" in name:
        raise InvalidStorageName("storage name must not contain repeated separators")
    if any(unicodedata.category(character) == "Cc" for character in name):
        raise InvalidStorageName("storage name must not contain control characters")

    if any(part in {".", ".."} for part in name.split("/")):
        raise InvalidStorageName("storage name must not contain relative path components")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise InvalidStorageName("storage name must be relative")
    return name


class Storage(ABC):
    def __init__(self, alias: str | None = None) -> None:
        self._alias = alias

    @property
    def alias(self) -> str | None:
        return self._alias

    def _bind_alias(self, alias: str) -> None:
        if self._alias is not None and self._alias != alias:
            raise StorageConfigurationError(f"storage is already bound to alias {self._alias!r}")
        self._alias = alias

    async def save(self, name: str, content: StorageContent, *, overwrite: bool = False) -> str:
        valid_name = validate_storage_name(name)
        if not isinstance(content, bytes) and not isinstance(content, AsyncIterable):
            raise TypeError("content must be bytes or AsyncIterable[bytes]")
        if not isinstance(content, bytes):
            content = self._validate_content_chunks(content)
        result = await self._call_backend("save", valid_name, self._save(valid_name, content, overwrite=overwrite))
        return validate_storage_name(result)

    async def open(self, name: str) -> StoredFile:
        valid_name = validate_storage_name(name)
        return await self._call_backend("open", valid_name, self._open(valid_name))

    async def delete(self, name: str) -> None:
        valid_name = validate_storage_name(name)
        try:
            await self._call_backend("delete", valid_name, self._delete(valid_name))
        except FileNotFoundError:
            return None

    async def exists(self, name: str) -> bool:
        valid_name = validate_storage_name(name)
        return await self._call_backend("exists", valid_name, self._exists(valid_name))

    async def stat(self, name: str) -> FileInfo:
        valid_name = validate_storage_name(name)
        return await self._call_backend("stat", valid_name, self._stat(valid_name))

    async def get_available_name(self, name: str) -> str:
        requested_name = validate_storage_name(name)
        if not await self.exists(requested_name):
            return requested_name

        while True:
            candidate = self.get_alternative_name(requested_name)
            if not await self.exists(candidate):
                return candidate

    def get_alternative_name(self, name: str) -> str:
        valid_name = validate_storage_name(name)
        path = PurePosixPath(valid_name)
        suffix = "".join(secrets.choice(_NAME_SUFFIX_ALPHABET) for _ in range(7))
        alternative = f"{path.stem}_{suffix}{path.suffix}"
        return alternative if path.parent == PurePosixPath(".") else str(path.parent / alternative)

    async def _call_backend(self, operation: str, name: str | None, awaitable: Awaitable[_T]) -> _T:
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except StorageError:
            raise
        except _InvalidContentChunk:
            raise
        except FileNotFoundError as error:
            if operation in {"open", "stat"}:
                raise StorageFileNotFound(f"stored file not found: {name}") from error
            if operation == "delete":
                raise
            wrapped = StorageBackendError(
                f"storage backend failed during {operation}",
                operation=operation,
                name=name,
                alias=self.alias,
            )
            raise wrapped from error
        except Exception as error:
            wrapped = StorageBackendError(
                f"storage backend failed during {operation}",
                operation=operation,
                name=name,
                alias=self.alias,
            )
            raise wrapped from error

    async def _validate_content_chunks(self, content: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
        async for chunk in content:
            if not isinstance(chunk, bytes):
                raise _InvalidContentChunk("content chunks must be bytes")
            yield chunk

    @abstractmethod
    async def _save(self, name: str, content: StorageContent, *, overwrite: bool) -> str:
        """Persist content under ``name`` and return its stored name."""

    @abstractmethod
    async def _open(self, name: str) -> StoredFile:
        """Return a readable stored file."""

    @abstractmethod
    async def _delete(self, name: str) -> None:
        """Delete a stored file."""

    @abstractmethod
    async def _exists(self, name: str) -> bool:
        """Return whether a stored file exists."""

    @abstractmethod
    async def _stat(self, name: str) -> FileInfo:
        """Return metadata for a stored file."""
