"""Real-Redis acceptance tests for the named security rate limiters."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from oldman.conf.schemas import (
    DefaultSettings,
    FingerprintRateLimitConfig,
    FingerprintSecurityConfig,
)
from oldman.providers.redis.client import RedisClientRegistry
from oldman.web.security.rate_limiter import FingerprintIPRateLimiter, RedisFixedWindowRateLimiter


class RedisRateLimiterIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Verify fixed-window and Lua policies against the configured real Redis."""

    async def asyncSetUp(self) -> None:
        """Open a test-owned DEFAULT Redis registry and exact-key ledger."""
        self.registry = RedisClientRegistry(DefaultSettings().redis)
        self.client = self.registry.using("DEFAULT")
        self.connection = await self.client.async_get_conn()
        self.keys: set[str] = set()

    async def asyncTearDown(self) -> None:
        """Delete only explicitly recorded test keys and close the registry."""
        if self.keys:
            await self.connection.delete(*self.keys)
        await self.registry.close()

    def fingerprint_keys(self, fingerprint: str, ip: str) -> set[str]:
        """Return and record the eight exact keys used by one Lua decision."""
        keys = {
            f"rate:fp:{fingerprint}",
            f"rate:ip:{ip}",
            f"relation:fp_ip:{fingerprint}",
            f"relation:ip_fp:{ip}",
            f"blacklist:fp:{fingerprint}",
            f"blacklist:ip:{ip}",
            f"violations:fp:{fingerprint}",
            f"violations:ip:{ip}",
        }
        self.keys.update(keys)
        return keys

    async def test_fixed_window_counts_and_expires_one_exact_key(self) -> None:
        """A real Redis counter should allow the limit and reject the next call."""
        now = 1_700_000_000
        period = 60
        namespace = f"oldman-test:fixed:{uuid.uuid4().hex}"
        key = f"{namespace}:subject:api_users:{now - (now % period)}"
        self.keys.add(key)
        limiter = RedisFixedWindowRateLimiter(self.client, namespace=namespace)

        with patch("oldman.web.security.rate_limiter.fixed_window.time.time", return_value=now):
            self.assertFalse(await limiter.is_rate_limited("subject", "/api/users", limit=1, period=period))
            self.assertTrue(await limiter.is_rate_limited("subject", "/api/users", limit=1, period=period))

        self.assertEqual("2", await self.connection.get(key))
        self.assertGreater(await self.connection.ttl(key), 0)

    async def test_fingerprint_limits_blacklist_and_relationship_anomalies(self) -> None:
        """The migrated Lua policy should enforce limits and relationship signals."""
        suffix = uuid.uuid4().hex
        fingerprint = f"fp-{suffix}"
        ip = f"test-ip-{suffix}"
        self.fingerprint_keys(fingerprint, ip)
        limiter = FingerprintIPRateLimiter(self.client)
        limit_config = FingerprintSecurityConfig(
            timestamp_max_diff=1,
            rate_limits={
                "default": FingerprintRateLimitConfig(),
                "/demo": FingerprintRateLimitConfig(
                    window=60,
                    fp_max=1,
                    ip_max=100,
                ),
            },
            max_fingerprints_per_ip=10,
            max_ips_per_fingerprint=10,
            blacklist_threshold=2,
            blacklist_duration=60,
            violation_ttl=60,
        )

        first = await limiter.check(fingerprint, ip, "/demo", limit_config)
        second = await limiter.check(fingerprint, ip, "/demo", limit_config)
        third = await limiter.check(fingerprint, ip, "/demo", limit_config)
        fourth = await limiter.check(fingerprint, ip, "/demo", limit_config)

        self.assertTrue(first.allowed)
        self.assertEqual("rate_limit_exceeded_fp", second.reason)
        self.assertEqual("rate_limit_exceeded_fp", third.reason)
        self.assertEqual("fingerprint_blocked", fourth.reason)

        shared_ip = f"test-shared-ip-{suffix}"
        first_fingerprint = f"first-{suffix}"
        second_fingerprint = f"second-{suffix}"
        self.fingerprint_keys(first_fingerprint, shared_ip)
        self.fingerprint_keys(second_fingerprint, shared_ip)
        anomaly_config = FingerprintSecurityConfig(
            timestamp_max_diff=1,
            rate_limits={
                "default": FingerprintRateLimitConfig(),
                "/demo": FingerprintRateLimitConfig(
                    window=60,
                    fp_max=100,
                    ip_max=100,
                ),
            },
            max_fingerprints_per_ip=1,
            max_ips_per_fingerprint=10,
            blacklist_threshold=10,
            blacklist_duration=60,
            violation_ttl=60,
        )

        await limiter.check(first_fingerprint, shared_ip, "/demo", anomaly_config)
        anomaly = await limiter.check(second_fingerprint, shared_ip, "/demo", anomaly_config)

        self.assertTrue(anomaly.allowed)
        self.assertIn("multi_fingerprint_per_ip", anomaly.anomalies)


if __name__ == "__main__":
    unittest.main()
