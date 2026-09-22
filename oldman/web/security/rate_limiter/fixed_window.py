"""Redis-backed fixed-window HTTP path rate limiting."""

from __future__ import annotations

import time

from oldman.utils.http import sanitize_path
from oldman.web.security.rate_limiter.base import RedisConnectionClient


class RedisFixedWindowRateLimiter:
    """Apply one Redis-backed fixed request window per subject and path."""

    def __init__(self, client: RedisConnectionClient, namespace: str = "ratelimit") -> None:
        """Bind an injected client and non-empty key namespace."""
        if not isinstance(namespace, str) or not namespace:
            raise ValueError("namespace must be a non-empty string")
        self.client = client
        self.namespace = namespace

    async def is_rate_limited(
        self,
        subject: int | str,
        path: str,
        limit: int,
        period: int,
    ) -> bool:
        """Increment the current window and return whether limit was exceeded."""
        if limit < 0:
            raise ValueError("limit must not be negative")
        return await self.record(subject, path, period) > limit

    async def count(self, subject: int | str, path: str, period: int) -> int:
        """Return what the current window already holds, without counting this read.

        A caller that must turn a request away *before* doing expensive work reads the
        window first and records only the events it means to charge for. `is_rate_limited`
        cannot do that job: it charges for the very call that asks the question.
        """
        conn = await self.client.async_get_conn()
        stored = await conn.get(self._window_key(subject, path, period))
        return int(stored) if stored is not None else 0

    async def record(self, subject: int | str, path: str, period: int) -> int:
        """Count one event in the current window and return the window's new total."""
        key = self._window_key(subject, path, period)
        conn = await self.client.async_get_conn()
        count = await conn.incr(key)
        # The first count owns the fixed expiry; later requests must not slide it.
        if count == 1:
            await conn.expire(key, period)
        return count

    def _window_key(self, subject: int | str, path: str, period: int) -> str:
        """Key of the fixed window the current second falls in."""
        if period <= 0:
            raise ValueError("period must be greater than zero")
        now = int(time.time())
        return f"{self.namespace}:{subject}:{sanitize_path(path)}:{now - (now % period)}"


def window_retry_after(period: int) -> int:
    """Seconds until the current fixed window rolls over and its count starts again.

    What a turned-away caller should be told to wait, in the `Retry-After` header.
    """
    if period <= 0:
        raise ValueError("period must be greater than zero")
    return period - (int(time.time()) % period)


def redis_rate_limiter(alias: str | None = None, namespace: str | None = None) -> RedisFixedWindowRateLimiter:
    """The default limiter: a Redis fixed window on the session connection (the one a login site must have).

    The namespace carries `core.app_name`, so two services sharing one Redis keep separate counters.
    Pass a namespace per purpose as well, so that one feature's counters cannot spend another's budget.

    The concrete class comes back rather than a Protocol, so a caller can pick whichever of
    `RateLimiter` and `WindowCounter` describes the way it means to use the window.
    """
    from oldman.conf import settings
    from oldman.providers.redis import redis_client
    from oldman.web.security.store import security_redis_alias

    return RedisFixedWindowRateLimiter(
        redis_client.using(alias or security_redis_alias()),
        namespace=namespace or f"{settings.core.app_name}:ratelimit",
    )
