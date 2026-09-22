"""Oldman database manager and migrated ORM boundary tests."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from sqlalchemy import AsyncAdaptedQueuePool
from sqlalchemy.exc import NoSuchModuleError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from oldman.conf.schemas import DatabaseConfig
from oldman.db import db_manager as public_db_manager
from oldman.db.session import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    db_manager,
)
from oldman.db.sqlalchemy.session import db_manager as sqlalchemy_db_manager


class FakeEngine:
    """Expose only the engine state needed by initialization tests."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.dispose_calls = 0
        self.sync_engine = object()

    async def dispose(self) -> None:
        """Record disposal without opening a database connection."""
        self.dispose_calls += 1


class DatabasePublicBoundaryTest(unittest.TestCase):
    """Verify the default manager and explicit custom-manager contract."""

    def test_framework_exports_one_default_manager(self) -> None:
        """All documented DB entrypoints must expose the same process object."""
        self.assertIs(public_db_manager, db_manager)
        self.assertIs(sqlalchemy_db_manager, db_manager)

    def test_database_manager_requires_an_explicit_config_source(self) -> None:
        """Calling the class without config must not recreate project-local defaults."""
        with self.assertRaises(TypeError):
            DatabaseManager()  # type: ignore[call-arg]

    def test_custom_managers_are_independent_instances(self) -> None:
        """One user-owned manager per extra database must not share hidden state."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        self.assertIsNot(DatabaseManager(config), DatabaseManager(config))

    def test_import_does_not_initialize_the_default_engine(self) -> None:
        """Importing the framework DB facade must remain safe before settings setup."""
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                ("import oldman.db as database; assert not database.db_manager.is_initialized"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, probe.returncode, probe.stderr)

    def test_admin_does_not_export_a_runtime_schema_creation_api(self) -> None:
        """部署必须使用 migrations，安装 Admin 不能再提供 create-all 后门。"""
        import oldman.apps.admin as admin
        import oldman.apps.admin.runtime as admin_runtime

        self.assertFalse(hasattr(admin, "configure_admin_database"))
        self.assertFalse(hasattr(admin_runtime, "configure_admin_database"))
        self.assertNotIn("configure_admin_database", admin.__all__)
        self.assertNotIn("configure_admin_database", admin_runtime.__all__)


class DatabaseManagerInitializationTest(unittest.IsolatedAsyncioTestCase):
    """Verify lazy, atomic and independent manager initialization."""

    async def asyncSetUp(self) -> None:
        """Create an isolated concrete manager for each test."""
        self.sqlite_listener_patcher = patch(
            "oldman.db.session._enable_sqlite_foreign_keys",
        )
        self.sqlite_listener_patcher.start()
        self.manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:", echo=False))

    async def asyncTearDown(self) -> None:
        """Close any real or fake engine published by the test."""
        await self.manager.close()
        self.sqlite_listener_patcher.stop()

    async def test_first_use_resolves_config_once_and_initializes_lazily(self) -> None:
        """Construction must not resolve settings or create an engine."""
        source_calls = 0
        engines: list[FakeEngine] = []

        def config_source() -> DatabaseConfig:
            nonlocal source_calls
            source_calls += 1
            return DatabaseConfig(url="sqlite+aiosqlite:///lazy.db", echo=False)

        def fake_create_engine(url: str, **_options: object) -> FakeEngine:
            engine = FakeEngine(url)
            engines.append(engine)
            return engine

        manager = DatabaseManager(config_source)
        self.assertEqual(0, source_calls)
        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await manager.initialize()
            await manager.initialize()
        await manager.close()

        self.assertEqual(1, source_calls)
        self.assertEqual(1, len(engines))

    async def test_concurrent_first_use_creates_one_engine(self) -> None:
        """The initialization lock must collapse concurrent first access."""
        engines: list[FakeEngine] = []

        def fake_create_engine(url: str, **_options: object) -> FakeEngine:
            engine = FakeEngine(url)
            engines.append(engine)
            return engine

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await asyncio.gather(*(self.manager.initialize() for _ in range(20)))

        self.assertEqual(1, len(engines))
        self.assertIs(self.manager.engine, engines[0])

    async def test_close_allows_reinitialization_with_the_same_config(self) -> None:
        """A closed manager must reopen its own database, not change identity."""
        engines: list[FakeEngine] = []

        def fake_create_engine(url: str, **_options: object) -> FakeEngine:
            engine = FakeEngine(url)
            engines.append(engine)
            return engine

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await self.manager.initialize()
            await self.manager.close()
            await self.manager.initialize()

        self.assertEqual(2, len(engines))
        self.assertEqual(1, engines[0].dispose_calls)
        self.assertIs(self.manager.engine, engines[1])

    async def test_closing_one_manager_does_not_touch_another(self) -> None:
        """Extra database managers must own separate engines and close paths."""
        first = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///one.db", echo=False))
        second = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///two.db", echo=False))
        engines: list[FakeEngine] = []

        def fake_create_engine(url: str, **_options: object) -> FakeEngine:
            engine = FakeEngine(url)
            engines.append(engine)
            return engine

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await first.initialize()
            await second.initialize()
            await first.close()

        self.assertEqual(1, engines[0].dispose_calls)
        self.assertEqual(0, engines[1].dispose_calls)
        self.assertIs(second.engine, engines[1])
        await second.close()

    async def test_missing_url_fails_on_use_without_creating_an_engine(self) -> None:
        """A DB-disabled settings profile must fail only when DB is requested."""
        manager = DatabaseManager(DatabaseConfig())
        with patch("oldman.db.session.create_async_engine") as create_engine:
            with self.assertRaisesRegex(
                DatabaseNotConfiguredError,
                "settings.database.url",
            ):
                await manager.initialize()
        create_engine.assert_not_called()

    async def test_invalid_config_factory_result_is_rejected(self) -> None:
        """Configuration factories must not silently return arbitrary objects."""
        manager = DatabaseManager(lambda: cast(Any, object()))
        with self.assertRaisesRegex(TypeError, "DatabaseConfig"):
            await manager.initialize()

    async def test_failed_factory_setup_does_not_publish_partial_state(self) -> None:
        """Session factory failures must dispose the candidate engine atomically."""
        engine = FakeEngine("sqlite+aiosqlite:///broken.db")
        with (
            patch(
                "oldman.db.session.create_async_engine",
                return_value=engine,
            ),
            patch(
                "oldman.db.session.async_sessionmaker",
                side_effect=RuntimeError("factory failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "factory failed"):
                await self.manager.initialize()

        self.assertEqual(1, engine.dispose_calls)
        self.assertFalse(self.manager.is_initialized)
        with self.assertRaises(DatabaseNotConfiguredError):
            _ = self.manager.engine

    async def test_server_pool_defaults_and_explicit_overrides_are_retained(
        self,
    ) -> None:
        """Server databases must keep the current pool contract."""
        captured_options: list[dict[str, object]] = []
        manager = DatabaseManager(
            DatabaseConfig(url="postgresql+asyncpg://db/oldman", echo=True),
            pool_size=23,
            max_overflow=7,
            pool_timeout=11,
            pool_recycle=120,
        )

        def fake_create_engine(url: str, **options: object) -> FakeEngine:
            captured_options.append(options)
            return FakeEngine(url)

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await manager.initialize()
        await manager.close()

        self.assertEqual(
            {
                "echo": True,
                "max_overflow": 7,
                "poolclass": AsyncAdaptedQueuePool,
                "pool_recycle": 120,
                "pool_size": 23,
                "pool_timeout": 11,
            },
            captured_options[0],
        )

    async def test_server_pool_uses_source_defaults(self) -> None:
        """Omitted server pool values must not fall back to SQLAlchemy defaults."""
        captured_options: list[dict[str, object]] = []
        manager = DatabaseManager(DatabaseConfig(url="postgresql+asyncpg://db/oldman", echo=False))

        def fake_create_engine(url: str, **options: object) -> FakeEngine:
            captured_options.append(options)
            return FakeEngine(url)

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await manager.initialize()
        await manager.close()

        self.assertEqual(
            {
                "echo": False,
                "max_overflow": 10,
                "pool_recycle": 1800,
                "pool_size": 100,
                "pool_timeout": 30,
                "poolclass": AsyncAdaptedQueuePool,
            },
            captured_options[0],
        )

    async def test_sqlite_omits_server_pool_defaults(self) -> None:
        """SQLite must retain the driver-selected pool by default."""
        captured_options: list[dict[str, object]] = []

        def fake_create_engine(url: str, **options: object) -> FakeEngine:
            captured_options.append(options)
            return FakeEngine(url)

        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await self.manager.initialize()

        self.assertEqual({"echo": False}, captured_options[0])

    async def test_echo_follows_debug_source_unless_config_overrides_it(
        self,
    ) -> None:
        """Engine echo and SQL tracking must remain separate settings."""
        captured_options: list[dict[str, object]] = []

        def fake_create_engine(url: str, **options: object) -> FakeEngine:
            captured_options.append(options)
            return FakeEngine(url)

        inherited = DatabaseManager(
            DatabaseConfig(url="sqlite+aiosqlite:///inherited.db"),
            debug=lambda: True,
        )
        overridden = DatabaseManager(
            DatabaseConfig(
                url="sqlite+aiosqlite:///overridden.db",
                echo=False,
            ),
            debug=lambda: True,
        )
        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=fake_create_engine,
        ):
            await inherited.initialize()
            await overridden.initialize()
        await inherited.close()
        await overridden.close()

        self.assertEqual([True, False], [options["echo"] for options in captured_options])

    async def test_tracker_uses_its_own_config_switch(self) -> None:
        """SQL tracking must be enabled independently of engine echo."""
        tracker = SimpleNamespace(setup_logging=Mock())
        manager = DatabaseManager(
            DatabaseConfig(
                url="sqlite+aiosqlite:///tracked.db",
                echo=False,
                enable_sql_logging=True,
            )
        )
        engine = FakeEngine("sqlite+aiosqlite:///tracked.db")
        with (
            patch(
                "oldman.db.session.create_async_engine",
                return_value=engine,
            ) as create_engine,
            patch(
                "oldman.db.sqlalchemy.log.SQLQueryTracker",
                return_value=tracker,
            ),
        ):
            await manager.initialize()
        await manager.close()

        self.assertFalse(create_engine.call_args.kwargs["echo"])
        tracker.setup_logging.assert_called_once_with(engine.sync_engine)

    async def test_success_log_redacts_the_database_password(self) -> None:
        """Initialization logs must never expose DSN credentials."""
        manager = DatabaseManager(
            DatabaseConfig(
                url="postgresql+asyncpg://alice:secret@db/oldman",
                echo=False,
            )
        )
        with (
            patch(
                "oldman.db.session.create_async_engine",
                return_value=FakeEngine("configured"),
            ),
            patch("oldman.db.session.logger.info") as log,
        ):
            await manager.initialize()
        await manager.close()

        rendered_arguments = " ".join(str(value) for value in log.call_args.args)
        self.assertIn("***", rendered_arguments)
        self.assertNotIn("secret", rendered_arguments)

    async def test_missing_known_and_unknown_drivers_are_diagnostic(self) -> None:
        """Driver failures must retain causes and identify an install target."""
        known = DatabaseManager(DatabaseConfig(url="postgresql+asyncpg://db/oldman"))
        known_error = ModuleNotFoundError(
            "No module named 'asyncpg'",
            name="asyncpg",
        )
        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=known_error,
        ):
            with self.assertRaisesRegex(RuntimeError, "asyncpg") as raised:
                await known.initialize()
        self.assertIs(raised.exception.__cause__, known_error)

        unknown = DatabaseManager(DatabaseConfig(url="unknown+driver://db/oldman"))
        unknown_error = NoSuchModuleError("Can't load plugin: unknown.driver")
        with patch(
            "oldman.db.session.create_async_engine",
            side_effect=unknown_error,
        ):
            with self.assertRaisesRegex(RuntimeError, "driver") as raised:
                await unknown.initialize()
        self.assertIs(raised.exception.__cause__, unknown_error)


if __name__ == "__main__":
    unittest.main()


class PortableMixinServerDefaultTest(unittest.IsolatedAsyncioTestCase):
    """The shipped mixins must build and insert on every dialect the framework supports.

    These are published API with no in-repo consumer, so nothing else would notice them
    breaking. They used to be hardcoded to MySQL: NativeTimestampsMixin could not even
    create its table on SQLite (current_timestamp(0) is a syntax error), and the UTC and
    UUID defaults raised "unknown function" on any write that bypassed the ORM's
    Python-side default - a raw INSERT, a migration backfill, another service.
    """

    @staticmethod
    def _models() -> tuple[Any, Any, Any]:
        """Define throwaway models on an isolated registry, once per call."""
        from oldman.db.sqlalchemy.models import (
            NativeTimestampsMixin,
            UtcTimestampsMixin,
            UUIDMixin,
        )

        class Local(DeclarativeBase):
            pass

        class NativeRow(NativeTimestampsMixin, Local):
            __tablename__ = "portable_native"
            id: Mapped[int] = mapped_column(primary_key=True)

        class UtcRow(UtcTimestampsMixin, Local):
            __tablename__ = "portable_utc"
            id: Mapped[int] = mapped_column(primary_key=True)

        class UuidRow(UUIDMixin, Local):
            __tablename__ = "portable_uuid"

        return NativeRow, UtcRow, UuidRow

    def test_every_dialect_renders_a_default_it_can_execute(self) -> None:
        from sqlalchemy import Table
        from sqlalchemy.dialects import mysql, postgresql, sqlite
        from sqlalchemy.schema import CreateTable

        native_row, utc_row, _ = self._models()
        rendered: dict[tuple[str, str], str] = {}
        for name, dialect in (("sqlite", sqlite.dialect()), ("mysql", mysql.dialect()), ("postgresql", postgresql.dialect())):
            for label, model in (("native", native_row), ("utc", utc_row)):
                rendered[(name, label)] = str(CreateTable(cast(Table, model.__table__)).compile(dialect=dialect))

        # No dialect may be handed another dialect's private function.
        for (name, label), ddl in rendered.items():
            self.assertNotIn("current_timestamp(0)", ddl, f"{name}/{label} keeps the MySQL-only precision syntax")
            if name != "mysql":
                self.assertNotIn("UTC_TIMESTAMP", ddl.upper(), f"{name}/{label} keeps the MySQL-only function")

        self.assertIn("datetime('now', 'localtime')", rendered[("sqlite", "native")])
        self.assertIn("(UTC_TIMESTAMP())", rendered[("mysql", "utc")])
        self.assertIn("NOW() AT TIME ZONE 'utc'", rendered[("postgresql", "utc")])

    async def test_sqlite_creates_the_tables_and_the_database_default_actually_fires(self) -> None:
        from sqlalchemy import Table, text
        from sqlalchemy.ext.asyncio import create_async_engine

        native_row, utc_row, uuid_row = self._models()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                for model in (native_row, utc_row, uuid_row):
                    await connection.run_sync(cast(Table, model.__table__).create)

                # A raw INSERT is the path that bypasses the Python-side default, so it is
                # the only one that proves the server_default is valid on this dialect.
                for table in ("portable_native", "portable_utc"):
                    await connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
                    stored = (await connection.execute(text(f"SELECT created_at FROM {table} WHERE id = 1"))).scalar_one()
                    self.assertTrue(stored, f"{table} stored no server-side timestamp")
        finally:
            await engine.dispose()

    def test_uuid_primary_key_is_generated_in_python_not_by_one_dialect(self) -> None:
        """gen_random_uuid() is PostgreSQL-only and yields v4, while the Python default is v7."""
        import uuid as uuid_pkg

        from sqlalchemy import Table

        _, _, uuid_row = self._models()
        column = cast(Table, uuid_row.__table__).c.uuid
        self.assertIsNone(column.server_default, "the database must not mint a second UUID flavour")
        python_default = column.default
        self.assertIsNotNone(python_default, "the primary key needs a Python-side value")
        self.assertIsInstance(cast(Any, python_default).arg(None), uuid_pkg.UUID)
