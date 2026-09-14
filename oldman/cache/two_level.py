"""Explicit composition of memory and Redis cache instances."""

from typing import Any

from oldman.cache.base import SENTINEL, BaseCache, CacheKey


class TwoLevelCache:
    """Compose process-local memory with Redis as the authoritative Cache."""

    def __init__(self, memory: BaseCache, redis: BaseCache) -> None:
        """Bind explicit memory and Redis Cache instances."""
        self.memory = memory
        self.redis = redis

    async def get(
        self,
        key: CacheKey,
        default: Any = None,
        ttl: float | None | object = SENTINEL,
    ) -> Any:
        """Read memory first and backfill it from Redis with a compatible TTL."""
        value = await self.memory.get(key)
        if value is not None:
            return value
        value = await self.redis.get(key)
        if value is None:
            return default
        if ttl is SENTINEL:
            memory_ttl = await self.redis.ttl(key)
            if memory_ttl == -1:
                await self.memory.set(key, value, ttl=None)
            elif memory_ttl > 0:
                await self.memory.set(key, value, ttl=memory_ttl)
        else:
            await self.memory.set(key, value, ttl=ttl)
        return value

    async def set(self, key: CacheKey, value: Any, ttl: float | None = None) -> None:
        """Write Redis first, then update the process-local copy."""
        await self.redis.set(key, value, ttl=ttl)
        await self.memory.set(key, value, ttl=ttl)

    async def delete(self, key: CacheKey) -> None:
        """Delete from Redis first, then from process-local memory."""
        await self.redis.delete(key)
        await self.memory.delete(key)

    async def clear(self) -> None:
        """Clear Redis first, then process-local memory."""
        await self.redis.clear()
        await self.memory.clear()


__all__ = ("TwoLevelCache",)
