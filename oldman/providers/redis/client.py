"""Named async Redis client registry."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from oldman.conf.schemas import RedisConfig
from oldman.providers.redis.redis import AsyncRedis

RedisConfigSource = RedisConfig | Callable[[], RedisConfig]


class RedisAliasNotConfiguredError(LookupError):
    """Raised when a requested Redis connection alias is not configured."""


class RedisAliasClient:
    """Lightweight view that binds registry operations to one alias."""

    def __init__(self, registry: RedisClientRegistry, alias: str) -> None:
        self._registry = registry
        self.alias = alias

    async def _client(self, *, binary: bool = False) -> AsyncRedis:
        return await self._registry._get_client(self.alias, binary=binary)

    async def async_get_conn(self) -> Any:
        """Return this alias's configured Redis connection."""
        return await (await self._client()).async_get_conn()

    async def async_get_bin_conn(self) -> Any:
        """Return this alias's binary Redis connection."""
        return await (await self._client(binary=True)).async_get_conn()

    async def get_db_lock(self, key: str, expire_timeout: int = 60) -> bool:
        """Delegate a presence lock to this alias's normal client."""
        return await (await self._client()).get_db_lock(key, expire_timeout=expire_timeout)

    async def is_db_lock(self, key: str) -> bool:
        """Delegate a presence-lock check to this alias's normal client."""
        return await (await self._client()).is_db_lock(key)

    async def acquire_lock(
        self,
        lock_name: str,
        acquire_timeout: int = 10,
        retry_interval: float = 0.001,
        expire_timeout: int | None = None,
    ) -> str | bool:
        """Delegate token-lock acquisition to this alias's normal client."""
        return await (await self._client()).acquire_lock(
            lock_name,
            acquire_timeout=acquire_timeout,
            retry_interval=retry_interval,
            expire_timeout=expire_timeout,
        )

    async def release_lock(self, lock_name: str, identifier: str) -> bool:
        """Delegate token-lock release to this alias's normal client."""
        return await (await self._client()).release_lock(lock_name, identifier)

    async def get_locker(
        self,
        lock_key: str,
        blocking_timeout: int = 10,
        expire_timeout: int = 60,
        sleep: float = 0.01,
    ) -> Any:
        """Return redis-py's distributed lock for this alias."""
        return await (await self._client()).get_locker(
            lock_key,
            blocking_timeout=blocking_timeout,
            expire_timeout=expire_timeout,
            sleep=sleep,
        )


class RedisClientRegistry:
    """Resolve named settings and cache normal or binary async Redis clients."""

    default_alias = "DEFAULT"

    def __init__(self, config: RedisConfigSource) -> None:
        self._config_source = config
        self._resolved_config = config if isinstance(config, RedisConfig) else None
        self._clients: dict[tuple[str, bool], AsyncRedis] = {}
        self._aliases: dict[str, RedisAliasClient] = {}
        self._client_lock = asyncio.Lock()

    def _config(self) -> RedisConfig:
        if self._resolved_config is None:
            source = self._config_source
            if not callable(source):
                raise TypeError("RedisClientRegistry requires RedisConfig or a RedisConfig factory")
            resolved = source()
            if not isinstance(resolved, RedisConfig):
                raise TypeError("Redis configuration factory must return RedisConfig")
            self._resolved_config = resolved
        return self._resolved_config

    def using(self, alias: str) -> RedisAliasClient:
        """Return a case-sensitive alias view without creating a Redis pool."""
        config = self._config()
        try:
            config[alias]
        except KeyError:
            available = ", ".join(config)
            raise RedisAliasNotConfiguredError(f"Redis connection alias {alias!r} is not configured; available aliases: {available}") from None
        bound = self._aliases.get(alias)
        if bound is None:
            bound = RedisAliasClient(self, alias)
            self._aliases[alias] = bound
        return bound

    async def _get_client(self, alias: str, *, binary: bool) -> AsyncRedis:
        config = self._config()[alias]
        decode_responses = False if binary else config.decode_responses
        cache_key = (alias, decode_responses)
        client = self._clients.get(cache_key)
        if client is not None:
            return client
        async with self._client_lock:
            client = self._clients.get(cache_key)
            if client is None:
                client = AsyncRedis(**config.client_options(decode_responses=decode_responses))
                self._clients[cache_key] = client
            return client

    async def async_get_conn(self) -> Any:
        """Return the normal connection for the DEFAULT alias."""
        return await self.using(self.default_alias).async_get_conn()

    async def async_get_bin_conn(self) -> Any:
        """Return the binary connection for the DEFAULT alias."""
        return await self.using(self.default_alias).async_get_bin_conn()

    async def get_db_lock(self, key: str, expire_timeout: int = 60) -> bool:
        """Use the DEFAULT alias for a presence lock."""
        return await self.using(self.default_alias).get_db_lock(key, expire_timeout=expire_timeout)

    async def is_db_lock(self, key: str) -> bool:
        """Use the DEFAULT alias for a presence-lock check."""
        return await self.using(self.default_alias).is_db_lock(key)

    async def acquire_lock(
        self,
        lock_name: str,
        acquire_timeout: int = 10,
        retry_interval: float = 0.001,
        expire_timeout: int | None = None,
    ) -> str | bool:
        """Use the DEFAULT alias for token-lock acquisition."""
        return await self.using(self.default_alias).acquire_lock(
            lock_name,
            acquire_timeout=acquire_timeout,
            retry_interval=retry_interval,
            expire_timeout=expire_timeout,
        )

    async def release_lock(self, lock_name: str, identifier: str) -> bool:
        """Use the DEFAULT alias for token-lock release."""
        return await self.using(self.default_alias).release_lock(lock_name, identifier)

    async def get_locker(
        self,
        lock_key: str,
        blocking_timeout: int = 10,
        expire_timeout: int = 60,
        sleep: float = 0.01,
    ) -> Any:
        """Use the DEFAULT alias for redis-py's distributed lock."""
        return await self.using(self.default_alias).get_locker(
            lock_key,
            blocking_timeout=blocking_timeout,
            expire_timeout=expire_timeout,
            sleep=sleep,
        )

    async def close(self) -> None:
        """Close every initialized client and clear the concrete-client cache."""
        async with self._client_lock:
            clients = tuple(dict.fromkeys(self._clients.values()))
            self._clients.clear()
        if not clients:
            return
        results = await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise BaseExceptionGroup("Redis clients failed to close", errors)


def _configured_redis() -> RedisConfig:
    """Resolve the concrete process settings only when the global registry is used."""
    from oldman.conf import settings

    return settings.redis


redis_client = RedisClientRegistry(_configured_redis)

__all__ = [
    "RedisAliasClient",
    "RedisAliasNotConfiguredError",
    "RedisClientRegistry",
    "redis_client",
]
