"""Behavior contracts for semantically named rate limiters."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from redis.exceptions import RedisError

from oldman.conf.schemas import FingerprintSecurityConfig
from oldman.security.rate_limiter import (
    TokenBucketRateLimiter,
    TokenBucketRateLimiterRegistry,
)
from oldman.web.security.rate_limiter import (
    FingerprintIPRateLimiter,
    FingerprintRateLimitDecision,
)

DEFAULT_FINGERPRINT_CONFIG = FingerprintSecurityConfig()


class FakeClock:
    """Provide deterministic monotonic time and async sleeping."""

    def __init__(self) -> None:
        """Start the deterministic clock at zero."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return the current deterministic monotonic value."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Advance the deterministic clock."""
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        """Record a sleep and advance time without blocking the test."""
        self.sleeps.append(seconds)
        self.advance(seconds)


class FakeScriptConnection:
    """Register one fake Lua callable and expose registration counts."""

    def __init__(self, script: Any) -> None:
        """Bind the fake script returned by register_script."""
        self.script = script
        self.register_count = 0
        self.lua: str | None = None

    def register_script(self, lua: str) -> Any:
        """Record and return the configured fake script callable."""
        self.register_count += 1
        self.lua = lua
        return self.script


class FakeScriptClient:
    """Expose one decoded fake connection to the security limiter."""

    def __init__(self, script: Any) -> None:
        """Create one fake script connection."""
        self.connection = FakeScriptConnection(script)
        self.connection_count = 0

    async def async_get_conn(self) -> FakeScriptConnection:
        """Return the fake decoded connection."""
        self.connection_count += 1
        return self.connection


class FailingScriptClient:
    """Raise one configured Redis error on connection access."""

    def __init__(self, error: RedisError) -> None:
        """Store the Redis failure for the next access."""
        self.error = error

    async def async_get_conn(self) -> Any:
        """Raise the configured Redis failure."""
        raise self.error


class TokenBucketRateLimiterTest(unittest.IsolatedAsyncioTestCase):
    """Verify numerical token refill, waiting, cancellation, and registry behavior."""

    async def test_token_bucket_starts_full_and_refills_by_elapsed_time(self) -> None:
        """A new bucket serves its capacity before time-based replenishment."""
        clock = FakeClock()
        with patch("oldman.security.rate_limiter.token_bucket.time.monotonic", clock.monotonic):
            limiter = TokenBucketRateLimiter(rate_limit=2, time_unit=10)
            await limiter.acquire()
            await limiter.acquire()
            self.assertEqual(0.0, limiter._tokens)

            clock.advance(5)
            await limiter.acquire()

        self.assertEqual(0.0, limiter._tokens)

    async def test_token_bucket_waits_only_for_the_missing_fraction(self) -> None:
        """An empty bucket sleeps for the exact one-token deficit."""
        clock = FakeClock()
        with (
            patch("oldman.security.rate_limiter.token_bucket.time.monotonic", clock.monotonic),
            patch("oldman.security.rate_limiter.token_bucket.asyncio.sleep", clock.sleep),
        ):
            limiter = TokenBucketRateLimiter(rate_limit=2, time_unit=10)
            await limiter.acquire()
            await limiter.acquire()
            await limiter.acquire()

        self.assertEqual([5.0], clock.sleeps)

    async def test_token_refill_never_exceeds_capacity(self) -> None:
        """Long idle periods replenish only to the configured capacity."""
        clock = FakeClock()
        with patch("oldman.security.rate_limiter.token_bucket.time.monotonic", clock.monotonic):
            limiter = TokenBucketRateLimiter(rate_limit=2, time_unit=10)
            await limiter.acquire()
            clock.advance(100)
            await limiter.acquire()

        self.assertEqual(1.0, limiter._tokens)

    async def test_wait_cancellation_is_not_swallowed(self) -> None:
        """Cancelling a waiting acquire must retain asyncio cancellation semantics."""
        clock = FakeClock()
        cancelled_sleep = AsyncMock(side_effect=asyncio.CancelledError)
        with (
            patch("oldman.security.rate_limiter.token_bucket.time.monotonic", clock.monotonic),
            patch("oldman.security.rate_limiter.token_bucket.asyncio.sleep", cancelled_sleep),
        ):
            limiter = TokenBucketRateLimiter(rate_limit=1, time_unit=10)
            await limiter.acquire()
            with self.assertRaises(asyncio.CancelledError):
                await limiter.acquire()

        cancelled_sleep.assert_awaited_once_with(10.0)

    def test_nonpositive_rate_or_time_unit_is_rejected(self) -> None:
        """A bucket requires a positive capacity and time interval."""
        for rate_limit, time_unit in ((0, 60), (-1, 60), (1, 0), (1, -1)):
            with self.subTest(rate_limit=rate_limit, time_unit=time_unit), self.assertRaises(ValueError):
                TokenBucketRateLimiter(rate_limit, time_unit)

    def test_registry_overwrites_names_and_manages_only_registered_limiters(self) -> None:
        """The named registry preserves the original overwrite behavior."""
        registry = TokenBucketRateLimiterRegistry()
        first = TokenBucketRateLimiter(1)
        second = TokenBucketRateLimiter(2)

        registry.register("api", first)
        registry.register("api", second)
        self.assertIs(second, registry.get("api"))

        registry.register_rate("worker", 3, time_unit=5)
        self.assertEqual(3, registry.get("worker").rate_limit)
        registry.remove("api")
        registry.remove("missing")
        with self.assertRaisesRegex(ValueError, "api"):
            registry.get("api")

        registry.clear()
        with self.assertRaisesRegex(ValueError, "worker"):
            registry.get("worker")


class FingerprintIPRateLimiterTest(unittest.IsolatedAsyncioTestCase):
    """Verify result mapping, initialization, and degradation."""

    async def test_result_mapping_decodes_text_and_uses_default_endpoint_rule(self) -> None:
        """Lua output should map to semantic fields with the default endpoint config."""
        script = AsyncMock(return_value=[1, b"allowed", 3, 5, b"multi_fingerprint_per_ip"])
        client = FakeScriptClient(script)
        limiter = FingerprintIPRateLimiter(client)

        decision = await limiter.check(
            "fp",
            "127.0.0.1",
            "/demo",
            DEFAULT_FINGERPRINT_CONFIG,
        )

        self.assertEqual(
            FingerprintRateLimitDecision(
                allowed=True,
                reason="allowed",
                fingerprint_count=3,
                ip_count=5,
                anomalies=["multi_fingerprint_per_ip"],
            ),
            decision,
        )
        await_args = script.await_args
        assert await_args is not None
        args = await_args.kwargs["args"]
        default_rule = DEFAULT_FINGERPRINT_CONFIG.rate_limits["default"]
        self.assertEqual(default_rule.window, args[1])
        self.assertEqual(default_rule.fp_max, args[2])
        self.assertEqual(default_rule.ip_max, args[3])

    async def test_concurrent_first_checks_register_the_script_once(self) -> None:
        """Concurrent first use must share one registered Lua script object."""
        script = AsyncMock(return_value=[1, "allowed", 0, 0, ""])
        client = FakeScriptClient(script)
        limiter = FingerprintIPRateLimiter(client)

        decisions = await asyncio.gather(
            *(
                limiter.check(
                    f"fp-{index}",
                    "127.0.0.1",
                    "/demo",
                    DEFAULT_FINGERPRINT_CONFIG,
                )
                for index in range(20)
            )
        )

        self.assertTrue(all(decision.allowed for decision in decisions))
        self.assertEqual(1, client.connection.register_count)
        self.assertEqual(1, client.connection_count)

    async def test_redis_fail_open_returns_distinct_degradation_decisions(self) -> None:
        """Default Redis degradation should allow without sharing mutable results."""
        limiter = FingerprintIPRateLimiter(FailingScriptClient(RedisError("unavailable")))

        with patch("oldman.web.security.rate_limiter.fingerprint.logger.exception"):
            first = await limiter.check(
                "fp", "127.0.0.1", "/demo", DEFAULT_FINGERPRINT_CONFIG
            )
            second = await limiter.check(
                "fp", "127.0.0.1", "/demo", DEFAULT_FINGERPRINT_CONFIG
            )

        self.assertEqual("redis_error_degraded", first.reason)
        self.assertTrue(first.allowed)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first.anomalies, second.anomalies)

    async def test_fail_closed_propagates_redis_errors(self) -> None:
        """Explicit fail-closed mode must preserve the Redis exception."""
        limiter = FingerprintIPRateLimiter(
            FailingScriptClient(RedisError("unavailable")),
            fail_open=False,
        )

        with (
            patch("oldman.web.security.rate_limiter.fingerprint.logger.exception"),
            self.assertRaisesRegex(RedisError, "unavailable"),
        ):
            await limiter.check(
                "fp", "127.0.0.1", "/demo", DEFAULT_FINGERPRINT_CONFIG
            )

    async def test_malformed_lua_results_are_not_treated_as_redis_degradation(self) -> None:
        """Programming and wire-format errors must not silently allow traffic."""
        script = AsyncMock(return_value=[1, "allowed"])
        limiter = FingerprintIPRateLimiter(FakeScriptClient(script))

        with self.assertRaises(IndexError):
            await limiter.check(
                "fp", "127.0.0.1", "/demo", DEFAULT_FINGERPRINT_CONFIG
            )


if __name__ == "__main__":
    unittest.main()
