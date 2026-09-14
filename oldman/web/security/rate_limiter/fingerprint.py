"""Fingerprint and IP rate limiting backed by one atomic Redis Lua script."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

from oldman.conf.schemas import FingerprintSecurityConfig
from oldman.logging import logger
from oldman.web.security.rate_limiter.base import RedisConnectionClient
from oldman.web.security.rate_limiter.lua import FINGERPRINT_IP_RATE_LIMIT_LUA


@dataclass(slots=True)
class FingerprintRateLimitDecision:
    """Describe the security decision returned by the Redis Lua policy."""

    allowed: bool
    reason: str
    fingerprint_count: int
    ip_count: int
    anomalies: list[str]


def _decode_text(value: str | bytes) -> str:
    """Normalize text from decoded or binary Redis responses."""
    return value.decode("utf-8") if isinstance(value, bytes) else value


class FingerprintIPRateLimiter:
    """Enforce combined fingerprint/IP limits and relationship anomalies."""

    def __init__(self, client: RedisConnectionClient, *, fail_open: bool = True) -> None:
        """Bind an injected Redis client and the Redis-failure policy."""
        self.client = client
        self.fail_open = fail_open
        self._validate_script: Any | None = None
        self._script_lock = asyncio.Lock()

    async def _ensure_script(self) -> Any:
        """Register the Lua program once, including under concurrent first use."""
        if self._validate_script is not None:
            return self._validate_script

        async with self._script_lock:
            if self._validate_script is None:
                conn = await self.client.async_get_conn()
                script = conn.register_script(FINGERPRINT_IP_RATE_LIMIT_LUA)
                if script is None:
                    raise RedisError("rate limiter script was not initialized")
                self._validate_script = script
                logger.info("Fingerprint/IP rate limiter Lua script registered successfully")
        return self._validate_script

    async def check(
        self,
        fingerprint: str,
        ip: str,
        endpoint: str,
        config: FingerprintSecurityConfig,
    ) -> FingerprintRateLimitDecision:
        """Evaluate one request against fingerprint and IP security limits."""
        rate_config = config.rate_limits.get(endpoint, config.rate_limits["default"])
        keys = [
            f"rate:fp:{fingerprint}",
            f"rate:ip:{ip}",
            f"relation:fp_ip:{fingerprint}",
            f"relation:ip_fp:{ip}",
            f"blacklist:fp:{fingerprint}",
            f"blacklist:ip:{ip}",
            f"violations:fp:{fingerprint}",
            f"violations:ip:{ip}",
        ]
        current_time = int(time.time())
        request_id = f"{current_time}:{uuid.uuid4().hex[:8]}"
        args = [
            current_time,
            rate_config.window,
            rate_config.fp_max,
            rate_config.ip_max,
            config.blacklist_threshold,
            config.max_fingerprints_per_ip,
            config.max_ips_per_fingerprint,
            config.violation_ttl,
            config.blacklist_duration,
            request_id,
            ip,
            fingerprint,
        ]

        try:
            script = await self._ensure_script()
            result = await script(keys=keys, args=args)
            anomalies = _decode_text(result[4])
            return FingerprintRateLimitDecision(
                allowed=bool(result[0]),
                reason=_decode_text(result[1]),
                fingerprint_count=int(result[2]),
                ip_count=int(result[3]),
                anomalies=anomalies.split(",") if anomalies else [],
            )
        except RedisError:
            logger.exception("Redis error during fingerprint/IP rate limiting")
            if not self.fail_open:
                raise
            # A fresh value prevents callers from sharing the mutable anomalies list.
            return FingerprintRateLimitDecision(
                allowed=True,
                reason="redis_error_degraded",
                fingerprint_count=0,
                ip_count=0,
                anomalies=[],
            )
