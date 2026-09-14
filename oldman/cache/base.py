# Adapted from aiocache commit ae5948b2d99dcaa68fe02fd3086a3351a867c85b.
# Original path: aiocache/base.py.
# BSD 3-Clause notice: LICENSES/aiocache-BSD-3-Clause.txt.

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable
from types import TracebackType
from typing import Any, Self, TypeVar, cast

from oldman.serializers.cache import BaseSerializer, NullSerializer

logger = logging.getLogger(__name__)

CacheKey = str | int
SENTINEL = object()

_T = TypeVar("_T")


class BaseCache(ABC):
    """Common orchestration for asynchronous cache backends."""

    def __init__(
        self,
        serializer: BaseSerializer | None = None,
        namespace: str = "",
        timeout: float | None = 5,
        ttl: float | None = None,
    ) -> None:
        """Configure serialization, namespace, operation timeout, and default TTL."""
        self.timeout = float(timeout) if timeout is not None else None
        self._default_ttl = float(ttl) if ttl is not None else None
        self.namespace = namespace
        self._serializer = serializer if serializer is not None else NullSerializer()

    @property
    def serializer(self) -> BaseSerializer:
        """Return the serializer applied by operations without a custom codec."""
        return self._serializer

    @serializer.setter
    def serializer(self, value: BaseSerializer) -> None:
        """Replace the serializer used by subsequent operations."""
        self._serializer = value

    async def add(
        self,
        key: CacheKey,
        value: Any,
        ttl: float | None | object = SENTINEL,
        dumps_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> bool:
        """Add a value only when its namespaced key does not already exist."""
        self._prepare()

        async def operation() -> bool:
            """Serialize and delegate one atomic add to the backend."""
            start = time.monotonic()
            dumps = dumps_fn or self.serializer.dumps
            namespaced_key = self.build_key(key)
            await self._add(namespaced_key, dumps(value), self._get_ttl(ttl))
            logger.debug("ADD %s %s (%.4f)s", namespaced_key, True, time.monotonic() - start)
            return True

        return await self._run_with_timeout(operation(), timeout)

    async def get(
        self,
        key: CacheKey,
        default: Any = None,
        loads_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> Any:
        """Return a decoded value or the supplied default for a Cache miss."""
        self._prepare()

        async def operation() -> Any:
            """Read and decode one namespaced backend value."""
            start = time.monotonic()
            loads = loads_fn or self.serializer.loads
            namespaced_key = self.build_key(key)
            value = loads(await self._get(namespaced_key))
            logger.debug("GET %s %s (%.4f)s", namespaced_key, value is not None, time.monotonic() - start)
            return value if value is not None else default

        return await self._run_with_timeout(operation(), timeout)

    async def multi_get(
        self,
        keys: Iterable[CacheKey],
        loads_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> list[Any | None]:
        """Return decoded values for multiple keys while preserving input order."""
        self._prepare()

        async def operation() -> list[Any | None]:
            """Namespace, fetch, and decode the requested key sequence."""
            start = time.monotonic()
            loads = loads_fn or self.serializer.loads
            namespaced_keys = [self.build_key(key) for key in keys]
            values = [loads(value) for value in await self._multi_get(namespaced_keys)]
            logger.debug(
                "MULTI_GET %s %d (%.4f)s",
                namespaced_keys,
                sum(value is not None for value in values),
                time.monotonic() - start,
            )
            return values

        return await self._run_with_timeout(operation(), timeout)

    async def set(
        self,
        key: CacheKey,
        value: Any,
        ttl: float | None | object = SENTINEL,
        dumps_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> bool:
        """Serialize and store one value using the selected TTL and timeout."""
        self._prepare()

        async def operation() -> bool:
            """Namespace and delegate one serialized write to the backend."""
            start = time.monotonic()
            dumps = dumps_fn or self.serializer.dumps
            namespaced_key = self.build_key(key)
            result = await self._set(namespaced_key, dumps(value), self._get_ttl(ttl))
            logger.debug("SET %s %s (%.4f)s", namespaced_key, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def multi_set(
        self,
        pairs: Iterable[tuple[CacheKey, Any]],
        ttl: float | None | object = SENTINEL,
        dumps_fn: Callable[[Any], Any] | None = None,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> bool:
        """Serialize and store multiple key-value pairs with one TTL policy."""
        self._prepare()

        async def operation() -> bool:
            """Namespace and serialize all pairs before the backend write."""
            start = time.monotonic()
            dumps = dumps_fn or self.serializer.dumps
            namespaced_pairs = [(self.build_key(key), dumps(value)) for key, value in pairs]
            await self._multi_set(namespaced_pairs, self._get_ttl(ttl))
            logger.debug(
                "MULTI_SET %s %d (%.4f)s",
                [key for key, _ in namespaced_pairs],
                len(namespaced_pairs),
                time.monotonic() - start,
            )
            return True

        return await self._run_with_timeout(operation(), timeout)

    async def delete(self, key: CacheKey, *, timeout: float | None | object = SENTINEL) -> int:
        """Delete one namespaced key and return the backend deletion count."""
        self._prepare()

        async def operation() -> int:
            """Namespace and delete one backend key."""
            start = time.monotonic()
            namespaced_key = self.build_key(key)
            result = await self._delete(namespaced_key)
            logger.debug("DELETE %s %d (%.4f)s", namespaced_key, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def delete_match(self, pattern: str, *, timeout: float | None | object = SENTINEL) -> int:
        """Delete namespaced keys matching a backend-safe pattern."""
        self._prepare()

        async def operation() -> int:
            """Namespace and delegate one pattern deletion."""
            start = time.monotonic()
            namespaced_pattern = self.build_key(pattern)
            result = await self._delete_match(namespaced_pattern)
            logger.debug("DELETE_MATCH %s %d (%.4f)s", namespaced_pattern, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def exists(self, key: CacheKey, *, timeout: float | None | object = SENTINEL) -> bool:
        """Return whether one namespaced key exists."""
        self._prepare()

        async def operation() -> bool:
            """Namespace and test one backend key."""
            start = time.monotonic()
            namespaced_key = self.build_key(key)
            result = await self._exists(namespaced_key)
            logger.debug("EXISTS %s %s (%.4f)s", namespaced_key, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def expire(
        self,
        key: CacheKey,
        ttl: float,
        *,
        timeout: float | None | object = SENTINEL,
    ) -> bool:
        """Set, replace, or remove the expiry for one key."""
        self._prepare()

        async def operation() -> bool:
            """Namespace and update one backend expiry."""
            start = time.monotonic()
            namespaced_key = self.build_key(key)
            result = await self._expire(namespaced_key, ttl)
            logger.debug("EXPIRE %s %s (%.4f)s", namespaced_key, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def ttl(self, key: CacheKey, *, timeout: float | None | object = SENTINEL) -> float | int:
        """Return seconds remaining, or the backend's negative TTL sentinel."""
        self._prepare()

        async def operation() -> float | int:
            """Namespace and read one backend TTL."""
            start = time.monotonic()
            namespaced_key = self.build_key(key)
            result = await self._ttl(namespaced_key)
            logger.debug("TTL %s %s (%.4f)s", namespaced_key, result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def clear(self, *, timeout: float | None | object = SENTINEL) -> bool:
        """Delete every entry owned by this Cache instance."""
        self._prepare()

        async def operation() -> bool:
            """Delegate Cache-scoped clearing to the backend."""
            start = time.monotonic()
            result = await self._clear()
            logger.debug("CLEAR %s (%.4f)s", result, time.monotonic() - start)
            return result

        return await self._run_with_timeout(operation(), timeout)

    async def close(self, *, timeout: float | None | object = SENTINEL) -> None:
        """Release backend-owned resources within the selected timeout."""
        self._prepare()

        async def operation() -> None:
            """Delegate resource release to the backend."""
            start = time.monotonic()
            await self._close()
            logger.debug("CLOSE (%.4f)s", time.monotonic() - start)

        await self._run_with_timeout(operation(), timeout)

    def _prepare(self) -> None:
        """Bind lazily resolved backend settings before an operation."""
        return None

    def build_key(self, key: CacheKey) -> str:
        """Prefix a key with this instance's namespace when configured."""
        key_string = str(key)
        return f"{self.namespace}:{key_string}" if self.namespace else key_string

    def _get_ttl(self, ttl: float | None | object) -> float | None:
        """Resolve the omitted-TTL sentinel without conflating it with None or zero."""
        return self._default_ttl if ttl is SENTINEL else cast(float | None, ttl)

    async def _run_with_timeout(self, operation: Awaitable[_T], timeout: float | None | object) -> _T:
        """Run one operation with its override or the instance default timeout."""
        effective_timeout = self.timeout if timeout is SENTINEL else cast(float | None, timeout)
        if effective_timeout in (0, None):
            return await operation
        return await asyncio.wait_for(operation, effective_timeout)

    @abstractmethod
    async def _add(self, key: str, value: Any, ttl: float | None) -> bool:
        """Atomically add one already serialized backend value."""
        raise NotImplementedError

    @abstractmethod
    async def _get(self, key: str) -> Any | None:
        """Read one raw backend value."""
        raise NotImplementedError

    @abstractmethod
    async def _multi_get(self, keys: list[str]) -> list[Any | None]:
        """Read raw backend values in key order."""
        raise NotImplementedError

    @abstractmethod
    async def _set(self, key: str, value: Any, ttl: float | None) -> bool:
        """Store one already serialized backend value."""
        raise NotImplementedError

    @abstractmethod
    async def _multi_set(self, pairs: list[tuple[str, Any]], ttl: float | None) -> bool:
        """Store multiple already serialized backend values."""
        raise NotImplementedError

    @abstractmethod
    async def _delete(self, key: str) -> int:
        """Delete one raw backend key."""
        raise NotImplementedError

    @abstractmethod
    async def _delete_match(self, pattern: str) -> int:
        """Delete raw backend keys matching a Cache-owned pattern."""
        raise NotImplementedError

    @abstractmethod
    async def _exists(self, key: str) -> bool:
        """Return whether one raw backend key exists."""
        raise NotImplementedError

    @abstractmethod
    async def _expire(self, key: str, ttl: float) -> bool:
        """Update expiry for one raw backend key."""
        raise NotImplementedError

    @abstractmethod
    async def _ttl(self, key: str) -> float | int:
        """Return the raw backend key's TTL in seconds or a negative sentinel."""
        raise NotImplementedError

    @abstractmethod
    async def _clear(self) -> bool:
        """Clear only entries owned by this Cache instance."""
        raise NotImplementedError

    @abstractmethod
    async def _close(self) -> None:
        """Release resources owned directly by the backend."""
        raise NotImplementedError

    async def __aenter__(self) -> Self:
        """Return this Cache for asynchronous context management."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close this Cache when leaving an asynchronous context."""
        await self.close()


__all__ = ("BaseCache", "CacheKey", "SENTINEL")
