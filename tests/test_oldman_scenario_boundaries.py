"""Oldman integration scenario boundary tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OldmanScenarioBoundariesTest(unittest.TestCase):
    """Verify selected integration boundaries from the original task 10."""

    def test_media_proxy_has_no_parallel_unconsumed_implementation(self) -> None:
        from oldman.contrib.proxy import BaseStreamProxy, SimpleStreamProxy

        proxy_root = ROOT / "oldman" / "contrib" / "proxy"

        self.assertFalse((proxy_root / "core.py").exists())
        self.assertFalse((proxy_root / "web_adapter.py").exists())
        self.assertFalse((proxy_root / "web").exists())
        self.assertEqual("oldman.contrib.proxy.base", BaseStreamProxy.__module__)
        self.assertEqual("oldman.contrib.proxy.simple", SimpleStreamProxy.__module__)

    def test_redis_provider_has_no_policy_modules(self) -> None:
        """Redis provider should expose infrastructure without policy modules."""
        from oldman.cache import RedisCache
        from oldman.providers import redis
        from oldman.providers.redis.redis import AsyncRedis

        for name in (
            "ApiLimiter",
            "RateLimiter",
            "RedisRateLimitStorage",
            "RedisSettings",
        ):
            self.assertFalse(hasattr(redis, name), name)
        for module in (
            "backend",
            "rate_limit",
            "security_lua",
            "security_rate_limiter",
            "system_settings",
        ):
            self.assertIsNone(importlib.util.find_spec(f"oldman.providers.redis.{module}"))
            # The pre-provider cache namespace must not retain duplicate policies.
            self.assertFalse((ROOT / "oldman" / "cache" / "redis" / f"{module}.py").exists())
        self.assertEqual("oldman.cache.backends.redis", RedisCache.__module__)
        self.assertIs(redis.AsyncRedis, AsyncRedis)
