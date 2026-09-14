"""Shared structural contracts for Redis-backed Web security limiters."""

from __future__ import annotations

from typing import Any, Protocol


class RedisConnectionClient(Protocol):
    """Provide a decoded async Redis connection to a rate limiter."""

    async def async_get_conn(self) -> Any:
        """Return the configured decoded Redis connection."""
        ...
