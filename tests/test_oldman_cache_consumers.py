"""Native Cache consumer migration boundary tests."""

from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = (
    "compat/django/cache.py",
    "contrib/proxy/base.py",
    "db/sqlalchemy/cache.py",
)


def consumer_source(relative: str) -> str:
    return (ROOT / "oldman" / relative).read_text(encoding="utf-8")


def import_sqlalchemy_cache() -> Any:
    """Import the consumer without depending on the concurrent legacy-settings migration."""
    import oldman.conf as conf

    with patch.object(conf, "legacy_settings", SimpleNamespace(), create=True):
        return importlib.import_module("oldman.db.sqlalchemy.cache")


class CacheConsumerBoundaryTest(unittest.IsolatedAsyncioTestCase):
    def test_consumers_do_not_import_deleted_clients_or_global_two_level_cache(self) -> None:
        deleted_symbols = (
            "providers.redis.async_redis",
            "cache.async_cache",
            "two_level_cache",
            "async_redis_cache_client",
            "async_redis_client",
            "sync_redis_cache_client",
        )
        for relative in CONSUMERS:
            source = consumer_source(relative)
            for symbol in deleted_symbols:
                self.assertNotIn(symbol, source, f"{relative}: {symbol}")

    def test_django_compat_has_only_async_retained_operations(self) -> None:
        from oldman.compat.django import cache as django_cache

        retained = (
            "get_django_cache",
            "set_django_cache",
            "set_api_cache",
            "get_api_cache",
            "delete_api_cache",
            "delete_api_cache_many",
            "get_cached_random_key_from_pk",
            "get_cached_id_from_random_key",
        )
        for name in retained:
            self.assertTrue(inspect.iscoroutinefunction(getattr(django_cache, name)), name)
        for removed in ("get_db_lock", "is_db_lock", "set_api_cache_lock", "delete_api_cache_lock"):
            self.assertFalse(hasattr(django_cache, removed), removed)

    async def test_django_compat_resolves_configured_binary_provider(self) -> None:
        """Read the shared Redis alias at use time, without a Native Cache prefix."""
        import oldman.conf as conf
        from oldman.compat.django import cache as django_cache

        connection = object()
        alias = Mock(async_get_bin_conn=AsyncMock(return_value=connection))
        registry = Mock()
        registry.using.return_value = alias
        with (
            patch.dict(conf.__dict__, {"settings": SimpleNamespace(cache=SimpleNamespace(client="DJANGO"))}),
            patch.object(django_cache, "redis_client", registry),
        ):
            self.assertIs(connection, await django_cache._connection())
        registry.using.assert_called_once_with("DJANGO")
        alias.async_get_bin_conn.assert_awaited_once_with()

    async def test_django_random_key_helpers_await_cache_operations(self) -> None:
        from oldman.compat.django.cache import get_cached_id_from_random_key, get_cached_random_key_from_pk

        with (
            patch("oldman.compat.django.cache.set_api_cache", new=AsyncMock()) as set_cache,
            patch("oldman.compat.django.cache.get_api_cache", new=AsyncMock(return_value="17")) as get_cache,
        ):
            random_key = await get_cached_random_key_from_pk(17, length=8, ttl=90)
            self.assertEqual(17, await get_cached_id_from_random_key(random_key))

        set_cache.assert_awaited_once_with(f"cached_random_key_{random_key}", 17, 90)
        get_cache.assert_awaited_once_with(f"cached_random_key_{random_key}")

    def test_proxy_constructs_two_level_cache_explicitly(self) -> None:
        source = consumer_source("contrib/proxy/base.py")
        self.assertIn("self._cache = TwoLevelCache(MemoryCache(), redis_cache)", source)
        tree = ast.parse(source)
        eager_settings_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "oldman.conf" and any(alias.name == "settings" for alias in node.names)
        ]
        self.assertEqual([], eager_settings_imports)

    async def test_proxy_uses_configured_decoded_provider_connection(self) -> None:
        from oldman.contrib.proxy.base import BaseStreamProxy

        connection = object()
        registry = Mock()
        registry.async_get_conn = AsyncMock(return_value=connection)
        proxy = object.__new__(BaseStreamProxy)

        with patch("oldman.contrib.proxy.base.redis_client", registry):
            result = await proxy._redis_connection()

        self.assertIs(connection, result)
        registry.async_get_conn.assert_awaited_once_with()
        registry.using.assert_not_called()

    async def test_sqlalchemy_cache_uses_configured_binary_provider_connection(self) -> None:
        sqlalchemy_cache = import_sqlalchemy_cache()

        connection = object()
        alias = Mock()
        alias.async_get_bin_conn = AsyncMock(return_value=connection)
        registry = Mock()
        registry.using.return_value = alias
        with (
            patch("oldman.db.sqlalchemy.cache.redis_client", registry),
            patch("oldman.db.sqlalchemy.cache._configured_cache_alias", return_value="CACHE"),
        ):
            result = await sqlalchemy_cache._cache_redis_connection()
        self.assertIs(connection, result)
        registry.using.assert_called_once_with("CACHE")
        alias.async_get_bin_conn.assert_awaited_once_with()

    async def test_sqlalchemy_query_cache_decodes_binary_cached_id_before_building_instance_key(self) -> None:
        sqlalchemy_cache = import_sqlalchemy_cache()

        cached_instance = object()

        class ExampleModel:
            get_by_fields = AsyncMock()
            model_validate_json = Mock(return_value=cached_instance)

        connection = AsyncMock()
        connection.get.side_effect = [b"17", b'{"id":17}']
        query_cache = sqlalchemy_cache.AsyncQueryCache(ExampleModel)

        with patch("oldman.db.sqlalchemy.cache._cache_redis_connection", new=AsyncMock(return_value=connection)):
            result = await query_cache.get_by_fields(Mock(), email="user@example.test")

        self.assertIs(cached_instance, result)
        self.assertEqual(call("i:ExampleModel:17"), connection.get.await_args_list[1])
        ExampleModel.get_by_fields.assert_not_awaited()

    def test_sqlalchemy_cache_alias_is_resolved_lazily(self) -> None:
        import oldman.conf as conf

        sqlalchemy_cache = import_sqlalchemy_cache()

        with patch.dict(conf.__dict__, {"settings": SimpleNamespace(cache=SimpleNamespace(client="MODEL_CACHE"))}):
            self.assertEqual("MODEL_CACHE", sqlalchemy_cache._configured_cache_alias())

    def test_sqlalchemy_cache_keeps_existing_generic_declarations(self) -> None:
        source = consumer_source("db/sqlalchemy/cache.py")
        self.assertIn("from typing import Any, ClassVar, Generic, TypeVar, cast", source)
        self.assertIn("class AsyncModelCache(Generic[T]):", source)
        self.assertIn("class AsyncQueryCache(Generic[T]):", source)


if __name__ == "__main__":
    unittest.main()
