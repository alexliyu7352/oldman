# Adapted from aiocache commit e673d62e98bf89b619e48f44cd68c96a30d95a1b.
# Original path: aiocache/backends/redis.py.
# BSD 3-Clause notice: LICENSES/aiocache-BSD-3-Clause.txt.

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any, Protocol

from oldman.cache.base import BaseCache
from oldman.conf.schemas import RedisCacheConfig
from oldman.providers.redis import redis_client
from oldman.serializers.cache import (
    BaseSerializer,
    PickleSerializer,
    create_cache_serializer,
    resolve_cache_serializer,
)


class BinaryRedisClient(Protocol):
    """Describe the provider surface required by RedisCache."""

    async def async_get_bin_conn(self) -> Any:
        """Return a binary async Redis connection."""
        ...


class RedisCache(BaseCache):
    """Redis cache backed by a lazily resolved binary provider connection."""

    NAME = "redis"

    def __init__(
        self,
        client: str | BinaryRedisClient | None = None,
        *,
        namespace: str | None = None,
        serializer: str | BaseSerializer | None = None,
        settings_source: Callable[[], RedisCacheConfig] | None = None,
        timeout: float | None = 5,
        ttl: float | None = None,
    ) -> None:
        """Bind an explicit client or defer client, namespace, and serializer settings."""
        self._client: BinaryRedisClient | None = None
        self._client_name: str | None = None
        self._settings_source = settings_source
        self._namespace: str | None = None

        if client is None:
            if settings_source is None:
                raise ValueError("RedisCache requires a client or settings_source")
            resolved_namespace = ""
            resolved_serializer: BaseSerializer = PickleSerializer()
        else:
            resolved_namespace = self._validate_namespace(namespace)
            self._namespace = resolved_namespace
            resolved_serializer = PickleSerializer() if serializer is None else resolve_cache_serializer(serializer)
            if isinstance(client, str):
                if not client.strip():
                    raise ValueError("RedisCache requires a non-empty client alias")
                self._client_name = client
            elif callable(getattr(client, "async_get_bin_conn", None)):
                self._client = client
            else:
                raise TypeError("RedisCache client must implement async_get_bin_conn()")

        self._namespace_initializing = True
        try:
            super().__init__(
                serializer=resolved_serializer,
                namespace=resolved_namespace,
                timeout=timeout,
                ttl=ttl,
            )
        finally:
            self._namespace_initializing = False

    @property
    def namespace(self) -> str:
        """Return the bound non-empty Redis namespace, or empty while unresolved."""
        return self._namespace or ""

    @namespace.setter
    def namespace(self, value: str) -> None:
        """Permit BaseCache initialization but reject later namespace mutation."""
        current = self._namespace
        if self._namespace_initializing:
            if current is None and value == "":
                return
            if value == current:
                return
        if current is None:
            raise AttributeError("RedisCache namespace is bound from settings on the first operation")
        if value != current:
            raise AttributeError("RedisCache namespace is immutable once bound")

    def _bind_namespace(self, namespace: str | None) -> None:
        """Bind a validated settings namespace once and enforce immutability."""
        validated = self._validate_namespace(namespace)
        if self._namespace is None:
            self._namespace = validated
            return
        if validated != self._namespace:
            raise AttributeError("RedisCache namespace is immutable once bound")

    @staticmethod
    def _validate_namespace(namespace: str | None) -> str:
        """Require a non-empty namespace so Cache clearing stays isolated."""
        if namespace is None or not namespace.strip():
            raise ValueError("RedisCache requires a non-empty namespace")
        return namespace

    def _prepare(self) -> None:
        """Lazily resolve settings and the provider alias before an operation."""
        if self._client is not None:
            return
        if self._client_name is not None:
            self._client = redis_client.using(self._client_name)
            return
        if self._settings_source is None:  # pragma: no cover - constructor prevents this state
            raise RuntimeError("RedisCache has no settings source")

        config = self._settings_source()
        self._bind_namespace(config.namespace)
        self.serializer = create_cache_serializer(config.serializer)
        self._client = redis_client.using(config.client)

    async def _connection(self) -> Any:
        """Return the provider-owned binary Redis connection."""
        self._prepare()
        assert self._client is not None
        return await self._client.async_get_bin_conn()

    async def _get(self, key: str) -> Any | None:
        """Read one serialized Redis value."""
        connection = await self._connection()
        return await connection.get(key)

    async def _multi_get(self, keys: list[str]) -> list[Any | None]:
        """Read serialized Redis values in key order."""
        connection = await self._connection()
        return await connection.mget(*keys)

    async def _set(self, key: str, value: Any, ttl: float | None) -> bool:
        """Store one value using second or millisecond precision as required."""
        connection = await self._connection()
        if ttl is None or ttl == 0:
            return await connection.set(key, value)
        if isinstance(ttl, float):
            return await connection.psetex(key, int(ttl * 1000), value)
        return await connection.setex(key, ttl, value)

    async def _multi_set(self, pairs: list[tuple[str, Any]], ttl: float | None) -> bool:
        """Store multiple values with MSET and an optional shared TTL."""
        connection = await self._connection()
        ttl = ttl or 0
        flattened = list(itertools.chain.from_iterable((key, value) for key, value in pairs))

        if ttl:
            await self._multi_set_with_ttl(connection, flattened, ttl)
        else:
            await connection.execute_command("MSET", *flattened)
        return True

    async def _multi_set_with_ttl(self, connection: Any, flattened: list[Any], ttl: float) -> None:
        """Atomically MSET values and expire each key in one transaction."""
        async with connection.pipeline(transaction=True) as pipeline:
            pipeline.execute_command("MSET", *flattened)
            if isinstance(ttl, float):
                expiration = int(ttl * 1000)
                expire = pipeline.pexpire
            else:
                expiration = ttl
                expire = pipeline.expire
            for key in flattened[::2]:
                expire(key, time=expiration)
            await pipeline.execute()

    async def _add(self, key: str, value: Any, ttl: float | None) -> bool:
        """Atomically add one value with Redis NX semantics."""
        connection = await self._connection()
        kwargs: dict[str, Any] = {"nx": True}
        if ttl is not None and ttl != 0:
            if isinstance(ttl, float):
                kwargs["px"] = int(ttl * 1000)
            else:
                kwargs["ex"] = ttl
        was_set = await connection.set(key, value, **kwargs)
        if not was_set:
            raise ValueError(f"Key {key} already exists, use .set to update the value")
        return was_set

    async def _exists(self, key: str) -> bool:
        """Return whether one Redis key exists."""
        connection = await self._connection()
        return bool(await connection.exists(key))

    async def _expire(self, key: str, ttl: float) -> bool:
        """Persist a zero-TTL key or update its expiry precision appropriately."""
        connection = await self._connection()
        if ttl == 0:
            return await connection.persist(key)
        if isinstance(ttl, float):
            return await connection.pexpire(key, int(ttl * 1000))
        return await connection.expire(key, ttl)

    async def _delete(self, key: str) -> int:
        """Delete one Redis key and return the deletion count."""
        connection = await self._connection()
        return await connection.delete(key)

    async def _delete_match(self, pattern: str) -> int:
        """Delete namespace-owned matches incrementally with Redis SCAN."""
        connection = await self._connection()
        namespace_prefix = f"{self.namespace}:"
        if not pattern.startswith(namespace_prefix):  # pragma: no cover - BaseCache provides this invariant
            raise ValueError("RedisCache match pattern must use the bound namespace")
        escaped_namespace = self._escape_redis_glob_literal(self.namespace)
        scan_pattern = f"{escaped_namespace}:{pattern[len(namespace_prefix) :]}"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await connection.scan(cursor=cursor, match=scan_pattern, count=100)
            if keys:
                deleted += await connection.delete(*keys)
            if cursor == 0:
                return deleted

    @staticmethod
    def _escape_redis_glob_literal(value: str) -> str:
        """Escape glob metacharacters in the literal namespace portion."""
        return "".join(f"\\{character}" if character in "\\*?[" else character for character in value)

    async def _ttl(self, key: str) -> float | int:
        """Convert positive Redis PTTL milliseconds to seconds."""
        connection = await self._connection()
        ttl = await connection.pttl(key)
        if ttl < 0:
            return ttl
        return ttl / 1000

    async def _clear(self) -> bool:
        """Clear only keys under the immutable Cache namespace."""
        await self._delete_match(self.build_key("*"))
        return True

    async def _close(self) -> None:
        """Leave connection shutdown to the shared Redis provider lifecycle."""
        return None


def _configured_cache() -> RedisCacheConfig:
    """Resolve Redis Cache settings only when the singleton first operates."""
    from oldman.conf import settings

    return settings.cache


redis_cache = RedisCache(settings_source=_configured_cache)

__all__ = ("BinaryRedisClient", "RedisCache", "redis_cache")
