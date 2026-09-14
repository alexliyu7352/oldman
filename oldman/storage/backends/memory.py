from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime

from oldman.storage.base import Storage, StorageContent
from oldman.storage.streams import FileInfo, StoredFile


@dataclass(frozen=True, slots=True)
class _MemoryEntry:
    content: bytes
    modified_at: datetime


class MemoryStoredFile(StoredFile):
    def __init__(self, *, name: str, entry: _MemoryEntry, chunk_size: int) -> None:
        super().__init__(
            name=name,
            info=FileInfo(name=name, size=len(entry.content), modified_at=entry.modified_at),
            chunk_size=chunk_size,
        )
        self._content = entry.content
        self._offset = 0
        self._closed = False

    async def read(self, size: int = -1) -> bytes:
        if self._closed:
            raise ValueError("cannot read a closed stored file")
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self._closed = True


class InMemoryStorage(Storage):
    """Unbounded in-process storage backed by immutable byte entries."""

    def __init__(self, alias: str | None = None, chunk_size: int = 262_144) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        super().__init__(alias=alias)
        self._chunk_size = chunk_size
        self._entries: dict[str, _MemoryEntry] = {}
        self._lock = asyncio.Lock()

    async def _save(self, name: str, content: StorageContent, *, overwrite: bool) -> str:
        payload = content if isinstance(content, bytes) else await self._collect_content(content)
        entry = _MemoryEntry(content=payload, modified_at=datetime.now(UTC))

        async with self._lock:
            stored_name = name
            if not overwrite:
                while stored_name in self._entries:
                    stored_name = self.get_alternative_name(name)
            self._entries[stored_name] = entry
            return stored_name

    async def _open(self, name: str) -> StoredFile:
        entry = await self._get_entry(name)
        return MemoryStoredFile(name=name, entry=entry, chunk_size=self._chunk_size)

    async def _delete(self, name: str) -> None:
        async with self._lock:
            self._entries.pop(name, None)

    async def _exists(self, name: str) -> bool:
        async with self._lock:
            return name in self._entries

    async def _stat(self, name: str) -> FileInfo:
        entry = await self._get_entry(name)
        return FileInfo(name=name, size=len(entry.content), modified_at=entry.modified_at)

    async def _collect_content(self, content: AsyncIterable[bytes]) -> bytes:
        buffer = bytearray()
        async for chunk in content:
            if not isinstance(chunk, bytes):
                raise TypeError("content chunks must be bytes")
            if chunk:
                buffer.extend(chunk)
        return bytes(buffer)

    async def _get_entry(self, name: str) -> _MemoryEntry:
        async with self._lock:
            try:
                return self._entries[name]
            except KeyError as error:
                raise FileNotFoundError(name) from error


__all__ = ("InMemoryStorage",)
