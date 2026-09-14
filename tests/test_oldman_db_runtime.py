"""Real SQLite session and migrated model behavior tests."""

from __future__ import annotations

import asyncio
import builtins
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy import ForeignKey, Integer, String, delete, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlmodel.ext.asyncio.session import AsyncSession

from oldman.conf.schemas import DatabaseConfig
from oldman.db.models import Base, DatabaseModel
from oldman.db.session import DatabaseManager
from oldman.db.sqlalchemy.cache import model_primary_key_value
from oldman.storage.lifecycle import OldmanWriteSession


class AlternateKeyModel(DatabaseModel):
    """Prove framework helpers do not assume an ``id`` attribute."""

    __tablename__ = "test_alternate_key_model"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    code: Mapped[str] = mapped_column(String(32), primary_key=True)


class CompositeKeyModel(DatabaseModel):
    """Prove identity helpers reject ambiguous composite keys."""

    __tablename__ = "test_composite_key_model"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    region: Mapped[str] = mapped_column(String(16), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)


class LifecycleModel(DatabaseModel):
    """Provide a real SQLite table for lifecycle and transaction tests."""

    __tablename__ = "test_database_lifecycle"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class CascadeParent(DatabaseModel):
    """Provide the parent side of a real database-level cascade."""

    __tablename__ = "test_database_cascade_parent"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class CascadeChild(DatabaseModel):
    """Require SQLite itself to delete rows whose parent is removed."""

    __tablename__ = "test_database_cascade_child"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("test_database_cascade_parent.id", ondelete="CASCADE"),
        nullable=False,
    )


class DatabaseSessionLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the retained session API against a real local SQLite database."""

    async def asyncSetUp(self) -> None:
        """Create a fresh temporary SQLite manager."""
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "oldman-test.sqlite3"
        self.manager = DatabaseManager(
            DatabaseConfig(
                url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
                echo=False,
            )
        )
        await self.manager.create_db_and_tables()

    async def asyncTearDown(self) -> None:
        """Dispose the SQLite engine before deleting its directory."""
        await self.manager.close()
        self.temp_dir.cleanup()

    async def test_write_read_rollback_and_repeat_create(self) -> None:
        """Write sessions commit, errors roll back and schema creation is idempotent."""
        async with self.manager.get_session() as session:
            session.add(LifecycleModel(id=1, name="committed"))

        class AbortWrite(RuntimeError):
            """Mark the transaction branch expected to roll back."""

        with self.assertRaises(AbortWrite):
            async with self.manager.get_session() as session:
                session.add(LifecycleModel(id=2, name="rolled-back"))
                raise AbortWrite

        async with self.manager.get_read_session() as session:
            self.assertFalse(session.autoflush)
            committed = await session.get(LifecycleModel, 1)
            rolled_back = await session.get(LifecycleModel, 2)

        assert committed is not None
        self.assertEqual((1, "committed"), (committed.id, committed.name))
        self.assertIsNone(rolled_back)
        await self.manager.create_db_and_tables()

    async def test_sqlite_enforces_foreign_keys_and_database_cascade(self) -> None:
        """Deleting a parent through SQL must cascade inside SQLite itself."""
        async with self.manager.get_session() as session:
            session.add(CascadeParent(id=1))
        async with self.manager.get_session() as session:
            session.add(CascadeChild(id=1, parent_id=1))
        async with self.manager.get_session() as session:
            await session.exec(delete(CascadeParent).where(CascadeParent.id == 1))

        async with self.manager.get_read_session() as session:
            enabled = await session.scalar(text("PRAGMA foreign_keys"))
            child = await session.get(CascadeChild, 1)

        self.assertEqual(1, enabled)
        self.assertIsNone(child)

    async def test_public_sessions_retain_sqlmodel_and_transaction_apis(
        self,
    ) -> None:
        """The migration must retain SQLModel, transaction and scoped factories."""
        async with self.manager.get_session("test:get-session") as session:
            self.assertIsInstance(session, AsyncSession)
            self.assertIsInstance(session.sync_session, OldmanWriteSession)
            self.assertTrue(callable(session.exec))
            self.assertTrue(session.in_transaction())

        async with self.manager.get_read_session() as session:
            self.assertNotIsInstance(session.sync_session, OldmanWriteSession)

        async with self.manager.transaction() as session:
            self.assertIsInstance(session, AsyncSession)
            self.assertTrue(session.in_transaction())

        async with self.manager.transaction(nested=True) as session:
            self.assertIsInstance(session, AsyncSession)
            self.assertTrue(session.in_nested_transaction())

        scoped_session = self.manager._get_async_session(scoped=True)
        self.assertIsInstance(scoped_session, AsyncSession)
        await scoped_session.close()
        assert self.manager.async_scoped_session is not None
        await self.manager.async_scoped_session.remove()

    async def test_sql_tracker_receives_request_info(self) -> None:
        """Request diagnostics must retain the caller-provided context label."""

        class FakeTracker:
            """Capture summary calls while preserving the tracker context protocol."""

            def __init__(self) -> None:
                self.performance_calls: list[tuple[list[str], str]] = []
                self.summary_calls: list[tuple[list[str], str]] = []

            @asynccontextmanager
            async def track(self):
                """Yield one synthetic query for the manager summary path."""
                yield {"queries": ["select 1"]}

            def check_performance(
                self,
                queries: list[str],
                request_info: str,
            ) -> None:
                """Capture the performance-check arguments."""
                self.performance_calls.append((queries, request_info))

            def log_summary(
                self,
                queries: list[str],
                request_info: str,
            ) -> None:
                """Capture the summary arguments."""
                self.summary_calls.append((queries, request_info))

        tracker = FakeTracker()
        self.manager._tracker = cast(Any, tracker)
        async with self.manager.get_session("GET /projects"):
            pass

        self.assertEqual(
            [(["select 1"], "GET /projects")],
            tracker.performance_calls,
        )
        self.assertEqual(
            [(["select 1"], "GET /projects")],
            tracker.summary_calls,
        )

    async def test_real_sql_tracker_uses_logging_instead_of_print(self) -> None:
        """Tracked SQL must stay inside the configured database logger pipeline."""
        manager = DatabaseManager(
            DatabaseConfig(
                url="sqlite+aiosqlite:///:memory:",
                echo=False,
                enable_sql_logging=True,
            )
        )
        with (
            patch("oldman.db.sqlalchemy.log.logger.info") as log_info,
            patch.object(builtins, "print") as direct_print,
        ):
            async with manager.get_session("SELECT probe") as session:
                await cast(Any, session).exec(text("SELECT 1"))
        await manager.close()

        self.assertTrue(log_info.called)
        direct_print.assert_not_called()


class DatabaseModelMigrationTest(unittest.TestCase):
    """Protect approved model changes while the manager is refactored."""

    def test_database_models_share_the_canonical_metadata_without_scanning(self) -> None:
        """Registry loading leaves one canonical SQLAlchemy metadata object."""
        import oldman.db as db

        self.assertIsNotNone(Base.metadata)
        self.assertTrue(issubclass(DatabaseModel, Base))
        self.assertFalse(hasattr(db, "scan_models"))

    def test_cache_identity_uses_the_mapped_primary_key(self) -> None:
        """Cache identity must remain usable with non-id primary keys."""
        self.assertEqual(
            "channel-1",
            model_primary_key_value(AlternateKeyModel(code="channel-1")),
        )

    def test_get_by_id_retains_the_source_execute_select_protocol(self) -> None:
        """The approved identity change must still use execute(select(...))."""
        expected = AlternateKeyModel(code="channel-1")

        class ExecuteOnlySession:
            """Expose only the source session method used by get_by_id."""

            def __init__(self) -> None:
                self.queries: list[object] = []

            async def execute(self, query: object) -> SimpleNamespace:
                """Capture one query and return the expected scalar adapter."""
                self.queries.append(query)
                return SimpleNamespace(scalar_one_or_none=lambda: expected)

        session = ExecuteOnlySession()
        result = asyncio.run(AlternateKeyModel.get_by_id(cast(Any, session), "channel-1"))

        self.assertIs(expected, result)
        self.assertEqual(1, len(session.queries))

    def test_identity_helpers_reject_composite_primary_keys(self) -> None:
        """Existing fail-fast behavior for composite identities must remain."""
        session = cast(Any, object())
        with self.assertRaisesRegex(ValueError, "get_by_id only supports"):
            asyncio.run(CompositeKeyModel.get_by_id(session, ("us", "channel-1")))
        with self.assertRaisesRegex(ValueError, "get_many_by_ids only supports"):
            asyncio.run(
                CompositeKeyModel.get_many_by_ids(
                    session,
                    [("us", "channel-1")],
                )
            )


if __name__ == "__main__":
    unittest.main()
