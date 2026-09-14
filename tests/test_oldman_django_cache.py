"""Optional Django interop checks against a real, isolated Redis server.

Install Django in a temporary test environment, not Oldman's runtime dependencies.
Run: python -m unittest tests.test_oldman_django_cache -v
"""

from __future__ import annotations

import importlib.util
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import oldman.conf as conf
from oldman.cache import RedisCache
from oldman.compat.django import cache
from oldman.conf.schemas import RedisConfig, RedisConnectionConfig
from oldman.providers.redis import RedisClientRegistry
from tests.redis_support import RedisProcess, require_redis_server


@unittest.skipUnless(importlib.util.find_spec("django"), "Django is required for the optional interoperability check")
class DjangoCacheInteropTest(unittest.IsolatedAsyncioTestCase):
    """Use Django's actual backend, not a mocked assumption about its wire format."""

    async def test_cross_framework_values_expiry_and_invalidation(self) -> None:
        """Exercise both directions and keep Native Cache isolation unchanged."""
        DjangoCache = importlib.import_module("django.core.cache.backends.redis").RedisCache

        with tempfile.TemporaryDirectory(prefix="oldman-django-cache-") as directory:
            server = RedisProcess(require_redis_server(), Path(directory), "cache")
            url = f"unix://{server.socket_path}?db=0"
            registry = RedisClientRegistry(RedisConfig(CACHE=RedisConnectionConfig(redis_url=url)))
            django = DjangoCache(url, {"OPTIONS": {"protocol": 2}})
            native = RedisCache(registry.using("CACHE"), namespace="main")
            try:
                with (
                    patch.dict(conf.__dict__, {"settings": SimpleNamespace(cache=SimpleNamespace(client="CACHE"))}),
                    patch.object(cache, "redis_client", registry),
                ):
                    connection = await registry.using("CACHE").async_get_bin_conn()
                    missing = object()
                    self.assertIs(missing, await cache.get_django_cache("missing", missing))
                    self.assertIsNone(await cache.get_api_cache("missing", 1))
                    for index, value in enumerate((0, 7, -2, False, True, None, "", b"bytes", "中文", {"items": [1, 2]})):
                        with self.subTest(value=value):
                            django.set(f"from_django_{index}", value, 30)
                            received = await cache.get_django_cache(f"from_django_{index}", missing)
                            self.assertEqual(value, received)
                            self.assertIs(type(value), type(received))
                            await cache.set_api_cache("from_oldman", value, 30, index)
                            received = django.get(f"from_oldman_{index}", missing)
                            self.assertEqual(value, received)
                            self.assertIs(type(value), type(received))

                    self.assertTrue(0 < await connection.ttl(":1:from_oldman_0") <= 30)
                    await cache.set_django_cache("forever", None, None)
                    self.assertEqual(-1, await connection.ttl(":1:forever"))
                    self.assertIsNone(await cache.get_django_cache("forever", missing))
                    for timeout in (0, -1):
                        django.set("expiry", "old value", 30)
                        await cache.set_api_cache("expiry", "new value", timeout)
                        self.assertIs(missing, django.get("expiry", missing))

                    await cache.delete_api_cache("from_django", 0)
                    self.assertIs(missing, django.get("from_django_0", missing))
                    await native.set("from_oldman_0", "native")
                    await cache.delete_api_cache_many("from_oldman")
                    self.assertIs(missing, django.get("from_oldman_1", missing))
                    self.assertEqual("native", await native.get("from_oldman_0"))
                    await native.clear()
                    self.assertEqual(7, django.get("from_django_1"))

                    for value in (False, 0, {"ok": True}):
                        calls = 0

                        @cache.cache_async_response(prefix=f"probe_{type(value).__name__}")
                        async def operation(expected: Any = value) -> Any:
                            """Count misses to verify cached falsey values remain hits."""
                            nonlocal calls
                            calls += 1
                            return expected

                        self.assertEqual(value, await operation())
                        self.assertEqual(value, await operation())
                        self.assertEqual(1, calls)
                        self.assertEqual(value, django.get(f"probe_{type(value).__name__}_operation__"))

                    await connection.set(":1:corrupt", b"not a pickle")
                    with self.assertRaises(pickle.UnpicklingError):
                        await cache.get_django_cache("corrupt")
                    with self.assertRaises(pickle.UnpicklingError):
                        django.get("corrupt")
            finally:
                await registry.close()
                for pool in django._cache._pools.values():
                    pool.disconnect()
                server.stop()


if __name__ == "__main__":
    unittest.main()
