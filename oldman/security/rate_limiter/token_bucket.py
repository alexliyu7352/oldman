"""In-process asynchronous token-bucket rate limiting."""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    """Throttle local async work with a monotonic token bucket."""

    def __init__(self, rate_limit: int, time_unit: float = 60) -> None:
        """Create a full bucket whose capacity equals rate_limit."""
        if rate_limit <= 0:
            raise ValueError("rate_limit must be greater than zero")
        if time_unit <= 0:
            raise ValueError("time_unit must be greater than zero")
        self.rate_limit = rate_limit
        self.time_unit = float(time_unit)
        self._refill_rate = rate_limit / self.time_unit
        self._tokens = float(rate_limit)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        """Replenish tokens for elapsed monotonic time up to capacity."""
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(float(self.rate_limit), self._tokens + elapsed * self._refill_rate)
        self._updated_at = now

    async def acquire(self) -> None:
        """Wait until and then consume one token."""
        while True:
            async with self._lock:
                self._refill(time.monotonic())
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                delay = (1 - self._tokens) / self._refill_rate
            # Sleep outside the lock so another caller can consume newly available tokens.
            await asyncio.sleep(delay)


class TokenBucketRateLimiterRegistry:
    """Store named in-process token-bucket limiters."""

    def __init__(self) -> None:
        """Initialize an empty named limiter registry."""
        self._limiters: dict[str, TokenBucketRateLimiter] = {}

    def register(self, name: str, limiter: TokenBucketRateLimiter) -> None:
        """Register or replace one named limiter."""
        self._limiters[name] = limiter

    def register_rate(self, name: str, rate_limit: int, time_unit: float = 60) -> None:
        """Construct and register one limiter from its numerical rate."""
        self._limiters[name] = TokenBucketRateLimiter(rate_limit, time_unit)

    def get(self, name: str) -> TokenBucketRateLimiter:
        """Return a named limiter or raise when it is absent."""
        limiter = self._limiters.get(name)
        if limiter is None:
            raise ValueError(f"Limiter {name!r} is not registered")
        return limiter

    def remove(self, name: str) -> None:
        """Remove a named limiter when present."""
        self._limiters.pop(name, None)

    def clear(self) -> None:
        """Remove every named limiter from this registry."""
        self._limiters.clear()
