"""Native Cache consumer migration boundary tests."""

from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, call, patch

from sqlalchemy.orm import Mapped, mapped_column

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

    def test_cache_writes_wait_for_the_commit_that_produced_them(self) -> None:
        """Mapper events fire during flush; a rollback after that must leave the cache alone."""
        sqlalchemy_cache = import_sqlalchemy_cache()
        session = SimpleNamespace(info={})
        target = SimpleNamespace()
        ran: list[tuple[Any, ...]] = []

        async def invalidate(value: Any) -> None:
            ran.append((value,))

        with patch.object(sqlalchemy_cache, "object_session", return_value=session):
            sqlalchemy_cache._queue_cache_task(target, invalidate, target)

        self.assertEqual([], ran, "nothing may run before the transaction commits")

        sqlalchemy_cache._discard_pending_cache_tasks(session)
        sqlalchemy_cache._flush_pending_cache_tasks(session)
        self.assertEqual([], ran, "a rolled back transaction leaves the cache untouched")

        with patch.object(sqlalchemy_cache, "object_session", return_value=session):
            sqlalchemy_cache._queue_cache_task(target, invalidate, target)
        with patch.object(sqlalchemy_cache, "_run_cache_task") as run:
            sqlalchemy_cache._flush_pending_cache_tasks(session)
        run.assert_called_once_with((invalidate, (target,)))
        self.assertEqual({}, session.info, "the queue is drained, not left to grow")

    def test_cache_writes_are_supervised_not_fire_and_forget(self) -> None:
        """A bare create_task can be collected mid-flight and swallows its own failures."""
        sqlalchemy_cache = import_sqlalchemy_cache()

        async def invalidate() -> None:
            return None

        manager = Mock()
        with patch.object(sqlalchemy_cache, "BackgroundTaskManager", return_value=manager):
            await_free = sqlalchemy_cache._run_cache_task
            with patch.object(sqlalchemy_cache.asyncio, "get_running_loop", return_value=object()):
                await_free((invalidate, ()))
        manager.spawn.assert_called_once_with(invalidate)

    def test_a_missing_loop_or_stopped_manager_cannot_break_a_committed_transaction(self) -> None:
        """The transaction already landed; a stale cache entry must not turn into an error."""
        sqlalchemy_cache = import_sqlalchemy_cache()

        async def invalidate() -> None:
            return None

        with patch.object(sqlalchemy_cache.asyncio, "get_running_loop", side_effect=RuntimeError("no loop")):
            sqlalchemy_cache._run_cache_task((invalidate, ()))

        stopping = Mock()
        stopping.spawn.side_effect = RuntimeError("BackgroundTaskManager is stopping")
        with (
            patch.object(sqlalchemy_cache.asyncio, "get_running_loop", return_value=object()),
            patch.object(sqlalchemy_cache, "BackgroundTaskManager", return_value=stopping),
        ):
            sqlalchemy_cache._run_cache_task((invalidate, ()))

    def test_database_model_json_round_trip_survives_the_cache_contract(self) -> None:
        """The ORM cache stores model_dump_json and reads it back with model_validate_json.

        A regression guard for the str(bytes) bug that made model_dump_json emit the repr
        of a bytes object ("b'{...}'"), which model_validate_json could never parse - so a
        cache hit threw instead of returning the row. This exercises the real round trip
        with a real mapped model and no mocks, exactly what the cache does.
        """
        import orjson

        from oldman.auth.models import User

        instance = User(
            id=17,
            username="cache_probe",
            password_hash="x",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        dumped = instance.model_dump_json()
        # It must be real JSON text, not the repr of a bytes object.
        self.assertIsInstance(dumped, str)
        self.assertEqual(17, orjson.loads(dumped)["id"])

        restored = User.model_validate_json(dumped)
        self.assertEqual(17, restored.id)
        self.assertEqual("cache_probe", restored.username)
        self.assertIs(True, restored.is_staff)

    def test_nothing_spawns_an_unsupervised_task(self) -> None:
        """Checked on the parsed call, not the text: prose about create_task is fine."""
        tree = ast.parse(consumer_source("db/sqlalchemy/cache.py"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertNotIn("asyncio.create_task", calls)


if __name__ == "__main__":
    unittest.main()


class DatabaseModelContractTest(unittest.IsolatedAsyncioTestCase):
    """Contracts the ORM helpers state but did not keep."""

    _cached_model: Any = None

    @classmethod
    def _model(cls) -> Any:
        """Define the throwaway model once: the declarative registry is shared."""
        if cls._cached_model is None:
            from oldman.db.sqlalchemy.models import DatabaseModel
            from oldman.db.sqlalchemy.utils import JSONText

            class ContractRow(DatabaseModel):
                # No __tablename__: Base derives it from the class name (contractrow).
                id: Mapped[int] = mapped_column(primary_key=True)
                title: Mapped[str] = mapped_column(default="")
                payload: Mapped[dict | None] = mapped_column(JSONText, nullable=True)

            cls._cached_model = ContractRow
        return cls._cached_model

    async def test_update_refuses_a_field_name_it_does_not_have(self) -> None:
        """A misspelled field used to change nothing and still report success."""
        from sqlalchemy import Table
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        model = self._model()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(cast(Table, model.__table__).create)
            async with session_factory() as session:
                row = model(id=1, title="original")
                session.add(row)
                await session.commit()

                with self.assertRaises(AttributeError) as caught:
                    await row.update(session, titel="typo")
                self.assertIn("titel", str(caught.exception))
                self.assertEqual("original", row.title, "a refused update must not have changed anything")

                await row.update(session, title="changed")
                self.assertEqual("changed", row.title)
        finally:
            await engine.dispose()

    async def test_jsontext_stores_text_not_a_blob(self) -> None:
        """impl = Text, so the column has to receive str; orjson.dumps returns bytes."""
        from sqlalchemy import Table, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        model = self._model()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(cast(Table, model.__table__).create)
            async with session_factory() as session:
                session.add(model(id=1, payload={"a": 1}))
                await session.commit()
            async with engine.begin() as connection:
                stored_type = (await connection.execute(text("SELECT typeof(payload) FROM contractrow WHERE id = 1"))).scalar()
                self.assertEqual("text", stored_type)
                # A blob never matches a text literal, so this is what the wrong type broke.
                matched = (
                    await connection.execute(text("SELECT COUNT(*) FROM contractrow WHERE payload = :want").bindparams(want='{"a":1}'))
                ).scalar()
                self.assertEqual(1, matched)
        finally:
            await engine.dispose()

    def test_invalidation_keys_name_their_model(self) -> None:
        """Without the model name, User 5 and Article 5 share one invalidation set."""
        sqlalchemy_cache = import_sqlalchemy_cache()

        class User:
            pass

        class Article:
            pass

        user_cache = sqlalchemy_cache.AsyncQueryCache(User)
        article_cache = sqlalchemy_cache.AsyncQueryCache(Article)

        self.assertEqual("rev:User:5", user_cache._get_reverse_cache_key(5))
        self.assertEqual("qs:User:5", user_cache._get_query_set_cache_key(5))
        self.assertNotEqual(user_cache._get_reverse_cache_key(5), article_cache._get_reverse_cache_key(5))
        self.assertNotEqual(user_cache._get_query_set_cache_key(5), article_cache._get_query_set_cache_key(5))

    def test_the_committing_helpers_say_that_they_commit(self) -> None:
        """save/delete/update end the caller's transaction; get_session hands one over."""
        from oldman.db.sqlalchemy.models import DatabaseModel

        for name in ("save", "delete", "update"):
            with self.subTest(method=name):
                doc = getattr(DatabaseModel, name).__doc__ or ""
                self.assertIn("提交", doc, f"{name} does not document that it commits")
