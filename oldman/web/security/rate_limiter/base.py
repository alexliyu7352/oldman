"""Shared structural contracts for Redis-backed Web security limiters."""

from __future__ import annotations

from typing import Any, Protocol


class RedisConnectionClient(Protocol):
    """Provide a decoded async Redis connection to a rate limiter."""

    async def async_get_conn(self) -> Any:
        """Return the configured decoded Redis connection."""
        ...


class RateLimiter(Protocol):
    """What a flow needs from a limiter; `RedisFixedWindowRateLimiter` satisfies it."""

    async def is_rate_limited(self, subject: int | str, path: str, limit: int, period: int) -> bool:
        """Count this event and return whether the subject is now over the limit."""
        ...


class WindowCounter(Protocol):
    """A window a caller can read before deciding whether to charge anything to it."""

    async def count(self, subject: int | str, path: str, period: int) -> int:
        """Return what the current window already holds, without counting this read."""
        ...

    async def record(self, subject: int | str, path: str, period: int) -> int:
        """Count one event in the current window and return its new total."""
        ...
