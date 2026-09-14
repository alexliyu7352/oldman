from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Self


@dataclass(frozen=True, slots=True)
class FileInfo:
    name: str
    size: int
    modified_at: datetime


class StoredFile(ABC):
    def __init__(self, *, name: str, info: FileInfo, chunk_size: int = 64 * 1024) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.name = name
        self.info = info
        self.chunk_size = chunk_size

    @abstractmethod
    async def read(self, size: int = -1) -> bytes:
        """Read up to ``size`` bytes from the file."""

    @abstractmethod
    async def close(self) -> None:
        """Release backend resources held by the file."""

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iter_chunks()

    async def _iter_chunks(self) -> AsyncIterator[bytes]:
        while chunk := await self.read(self.chunk_size):
            yield chunk

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
