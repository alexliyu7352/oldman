# Adapted from aiocache commit ae5948b2d99dcaa68fe02fd3086a3351a867c85b.
# Original path: aiocache/backends/memory.py.
# BSD 3-Clause notice: LICENSES/aiocache-BSD-3-Clause.txt.

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from oldman.cache.base import BaseCache
from oldman.serializers.cache import NullSerializer

_MISSING = object()


class MemoryCache(BaseCache):
    """Unbounded in-process cache backed by a dictionary."""

    NAME = "memory"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize unbounded process-local storage and expiry timers."""
        kwargs.setdefault("serializer", NullSerializer())
        super().__init__(**kwargs)
        self._cache: dict[str, Any] = {}
        self._handlers: dict[str, asyncio.TimerHandle] = {}

    async def _get(self, key: str) -> Any | None:
        """Read one value from process-local storage."""
        return self._cache.get(key)

    async def _multi_get(self, keys: list[str]) -> list[Any | None]:
        """Read process-local values in key order."""
        return [self._cache.get(key) for key in keys]

    async def _set(self, key: str, value: Any, ttl: float | None) -> bool:
        """Store a value and replace any previous expiry timer."""
        self._cancel_timer(key)
        self._cache[key] = value
        if ttl:
            loop = asyncio.get_running_loop()
            self._handlers[key] = loop.call_later(ttl, self._delete_now, key)
        return True

    async def _multi_set(self, pairs: list[tuple[str, Any]], ttl: float | None) -> bool:
        """Store each pair using the same process-local TTL policy."""
        for key, value in pairs:
            await self._set(key, value, ttl)
        return True

    async def _add(self, key: str, value: Any, ttl: float | None) -> bool:
        """Add a value only when the process-local key is absent."""
        if key in self._cache:
            raise ValueError(f"Key {key} already exists, use .set to update")
        return await self._set(key, value, ttl)

    async def _exists(self, key: str) -> bool:
        """Return whether a process-local key exists."""
        return key in self._cache

    async def _expire(self, key: str, ttl: float) -> bool:
        """Replace a key's timer, with zero making it persistent."""
        if key not in self._cache:
            return False

        self._cancel_timer(key)
        if ttl:
            loop = asyncio.get_running_loop()
            self._handlers[key] = loop.call_later(ttl, self._delete_now, key)
        return True

    async def _ttl(self, key: str) -> float | int:
        """Return timer seconds or Redis-compatible negative sentinels."""
        if key not in self._cache:
            return -2
        handle = self._handlers.get(key)
        if handle is None:
            return -1
        return max(0.0, handle.when() - asyncio.get_running_loop().time())

    async def _delete(self, key: str) -> int:
        """Delete one process-local key immediately."""
        return self._delete_now(key)

    async def _delete_match(self, pattern: str) -> int:
        """Delete keys matching a case-sensitive shell pattern."""
        keys = [key for key in self._cache if fnmatch.fnmatchcase(key, pattern)]
        return sum(self._delete_now(key) for key in keys)

    async def _clear(self) -> bool:
        """Cancel all timers and clear unbounded process-local storage."""
        for handle in self._handlers.values():
            handle.cancel()
        self._handlers.clear()
        self._cache.clear()
        return True

    async def _close(self) -> None:
        """Clear process-local storage because no external resource is owned."""
        await self._clear()

    def _cancel_timer(self, key: str) -> None:
        """Cancel and forget one key's active expiry timer."""
        handle = self._handlers.pop(key, None)
        if handle is not None:
            handle.cancel()

    def _delete_now(self, key: str) -> int:
        """Delete a key synchronously for timer callbacks and Cache methods."""
        value = self._cache.pop(key, _MISSING)
        if value is _MISSING:
            return 0
        self._cancel_timer(key)
        return 1


memory_cache = MemoryCache()

__all__ = ("MemoryCache", "memory_cache")
