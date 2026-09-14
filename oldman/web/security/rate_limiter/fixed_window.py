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
        if period <= 0:
            raise ValueError("period must be greater than zero")
        if limit < 0:
            raise ValueError("limit must not be negative")

        now = int(time.time())
        window_start = now - (now % period)
        key = f"{self.namespace}:{subject}:{sanitize_path(path)}:{window_start}"
        conn = await self.client.async_get_conn()
        count = await conn.incr(key)
        # The first count owns the fixed expiry; later requests must not slide it.
        if count == 1:
            await conn.expire(key, period)
        return count > limit
