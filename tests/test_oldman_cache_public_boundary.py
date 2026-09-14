"""Public Cache API and runtime lifecycle boundary tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


class CachePublicBoundaryTest(unittest.IsolatedAsyncioTestCase):
    def test_cache_package_exports_only_native_cache_api(self) -> None:
        import oldman.cache as cache_package

        expected = (
            "BaseCache",
            "MemoryCache",
            "RedisCache",
            "TwoLevelCache",
            "cache_response",
            "cache_async_response",
            "memory_cache",
            "redis_cache",
        )
        self.assertEqual(expected, cache_package.__all__)
        self.assertFalse(hasattr(cache_package, "cache"))
        for removed in (
            "AsyncRedisClient",
            "BinaryRedisClient",
            "SyncRedisClient",
            "SettingsBoundRedisCache",
            "async_cache",
            "cache_sync_response",
            "close_cache",
            "get_db_lock",
            "init_cache",
            "two_level_cache",
        ):
            self.assertFalse(hasattr(cache_package, removed), removed)

    def test_legacy_async_cache_module_is_removed(self) -> None:
        self.assertFalse((ROOT / "oldman" / "cache" / "async_cache.py").exists())

    async def test_runtime_shutdown_closes_memory_before_redis_provider(self) -> None:
        import oldman.conf as conf

        with patch.object(conf, "legacy_settings", SimpleNamespace(), create=True):
            from oldman.runtime.simple import SimpleApplication

        class DemoApplication(SimpleApplication):
            def prepare(self) -> None:
                return None

            async def main(self, *args: Any, **kwargs: Any) -> None:
                return None

        application = object.__new__(DemoApplication)
        application.app_name = "cache-lifecycle"
        order: list[str] = []
        with (
            patch(
                "oldman.runtime.simple.memory_cache.close",
                new=AsyncMock(side_effect=lambda: order.append("memory")),
            ),
            patch(
                "oldman.runtime.simple.redis_client.close",
                new=AsyncMock(side_effect=lambda: order.append("redis")),
            ),
        ):
            await application.after_stop()
        self.assertEqual(["memory", "redis"], order)

    async def test_web_runtime_shutdown_closes_memory_before_redis_provider(self) -> None:
        import oldman.conf as conf

        with (
            patch.object(conf, "legacy_settings", SimpleNamespace(), create=True),
            patch.dict(conf.__dict__, {"settings": SimpleNamespace()}),
        ):
            from oldman.runtime.web import WebApplication

        class DemoWebApplication(WebApplication):
            def prepare_server(self, app: Any) -> None:
                return None

        application = object.__new__(DemoWebApplication)
        application.app_name = "web-cache-lifecycle"
        order: list[str] = []
        with (
            patch(
                "oldman.runtime.web.memory_cache.close",
                new=AsyncMock(side_effect=lambda: order.append("memory")),
            ),
            patch(
                "oldman.runtime.web.redis_client.close",
                new=AsyncMock(side_effect=lambda: order.append("redis")),
            ),
        ):
            await application.after_server_stop(cast(Any, SimpleNamespace()))
        self.assertEqual(["memory", "redis"], order)

    def test_runtime_has_no_eager_cache_initialization(self) -> None:
        for relative in ("simple.py", "web.py"):
            source = (ROOT / "oldman" / "runtime" / relative).read_text(encoding="utf-8")
            self.assertNotIn("async_cache", source, relative)
            self.assertNotIn("init_cache", source, relative)
            self.assertNotIn("REDIS_CONFIG", source, relative)
            self.assertLess(source.index("await memory_cache.close()"), source.index("await redis_client.close()"))


if __name__ == "__main__":
    unittest.main()
