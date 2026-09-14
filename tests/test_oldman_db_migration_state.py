"""Fixed migration-state table and ownership behavior tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from oldman.db.migrations import MigrationProject

PROJECT_ID = UUID("9714d0a3-3f2b-48aa-88d7-c0869b2a6f25")
OTHER_PROJECT_ID = UUID("f072370e-8f73-428d-9615-eb07f6c1f2b4")


def _project(project_id: UUID = PROJECT_ID) -> MigrationProject:
    """Build the identity fields needed by state ownership checks."""
    from oldman.apps import AppRegistry

    return MigrationProject(
        project_root=Path.cwd(),
        project_id=project_id,
        project_name="state-demo",
        database_url="sqlite+aiosqlite:///unused.db",
        service_configs=(),
        apps=AppRegistry(),
        user_model_path=None,
    )


class SQLiteStateTestCase(unittest.TestCase):
    """Provide one real temporary SQLite file per test."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "state.db"
        self.engine = create_engine(f"sqlite:///{database_path}")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()


class MigrationStateInspectionTests(SQLiteStateTestCase):
    """Inspect internal state without creating or repairing anything."""

    def test_empty_database_inspection_is_read_only(self) -> None:
        from oldman.db.migrations.state import INTERNAL_TABLE_NAMES, MigrationState

        with self.engine.connect() as connection:
            state = MigrationState.inspect(connection)

        self.assertEqual(state.present_tables, frozenset())
        self.assertEqual(state.missing_tables, INTERNAL_TABLE_NAMES)
        self.assertIsNone(state.owner)
        self.assertEqual(state.revisions, ())
        self.assertEqual(dict(state.schema_registry), {})
        self.assertEqual(inspect(self.engine).get_table_names(), [])

    def test_partial_and_complete_internal_table_sets_are_reported(self) -> None:
        from oldman.db.migrations.state import (
            ALEMBIC_VERSION_TABLE,
            INTERNAL_TABLES,
            MIGRATION_OWNER_TABLE,
            SCHEMA_REGISTRY_TABLE,
            MigrationState,
        )

        with self.engine.begin() as connection:
            MIGRATION_OWNER_TABLE.create(connection)
            connection.execute(
                MIGRATION_OWNER_TABLE.insert().values(
                    singleton_id=1,
                    project_id=str(PROJECT_ID),
                    project_name="state-demo",
                )
            )
        with self.engine.connect() as connection:
            partial = MigrationState.inspect(connection)
        self.assertTrue(partial.is_partial)
        self.assertEqual(partial.present_tables, frozenset({"oldman_migration_owner"}))

        with self.engine.begin() as connection:
            ALEMBIC_VERSION_TABLE.create(connection)
            SCHEMA_REGISTRY_TABLE.create(connection)
            connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="alpha_head"))
        with self.engine.connect() as connection:
            complete = MigrationState.inspect(connection)

        self.assertTrue(complete.is_complete)
        self.assertEqual(complete.present_tables, frozenset(INTERNAL_TABLES))
        owner = complete.owner
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.project_id, PROJECT_ID)
        self.assertEqual(complete.revisions, ("alpha_head",))

    def test_default_alembic_version_table_is_unrelated(self) -> None:
        from oldman.db.migrations.state import MigrationState

        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('foreign_head')"))
        with self.engine.connect() as connection:
            state = MigrationState.inspect(connection)

        self.assertEqual(state.present_tables, frozenset())
        self.assertEqual(state.revisions, ())
        self.assertIn("alembic_version", inspect(self.engine).get_table_names())

    def test_conflicting_reserved_table_signature_is_rejected(self) -> None:
        from oldman.db.migrations.state import MigrationState, ReservedMigrationTableError

        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE oldman_schema_registry (table_name INTEGER PRIMARY KEY)"))
        with self.engine.connect() as connection:
            with self.assertRaises(ReservedMigrationTableError) as raised:
                MigrationState.inspect(connection)

        message = str(raised.exception)
        self.assertIn("oldman_schema_registry", message)
        self.assertIn("expected", message.lower())
        self.assertIn("actual", message.lower())


class MigrationOwnershipTests(SQLiteStateTestCase):
    """Acquire ownership only on the explicit first-migrate path."""

    def test_first_migrate_creates_owner_and_registry_before_business_ddl(self) -> None:
        from oldman.db.migrations.state import MigrationState, ensure_for_first_migrate

        with self.engine.begin() as connection:
            ensure_for_first_migrate(connection, _project())

        table_names = set(inspect(self.engine).get_table_names())
        self.assertEqual(
            table_names,
            {"oldman_migration_owner", "oldman_schema_registry"},
        )
        self.assertNotIn("oldman_alembic_version", table_names)
        with self.engine.connect() as connection:
            state = MigrationState.inspect(connection)
        owner = state.owner
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.project_id, PROJECT_ID)
        self.assertTrue(state.is_partial)

    def test_owner_survives_a_later_business_ddl_failure(self) -> None:
        from oldman.db.migrations.state import MigrationState, ensure_for_first_migrate

        with self.engine.begin() as connection:
            ensure_for_first_migrate(connection, _project())

        with self.assertRaises(OperationalError):
            with self.engine.begin() as connection:
                connection.execute(text("CREATE TABLE duplicate_name (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE duplicate_name (id INTEGER PRIMARY KEY)"))

        with self.engine.connect() as connection:
            state = MigrationState.inspect(connection)
        owner = state.owner
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.project_id, PROJECT_ID)

    def test_other_project_and_partial_state_are_never_claimed(self) -> None:
        from oldman.db.migrations.state import (
            MIGRATION_OWNER_TABLE,
            MigrationOwnershipError,
            MigrationStateRecoveryRequired,
            ensure_for_first_migrate,
        )

        with self.engine.begin() as connection:
            MIGRATION_OWNER_TABLE.create(connection)
            connection.execute(
                MIGRATION_OWNER_TABLE.insert().values(
                    singleton_id=1,
                    project_id=str(OTHER_PROJECT_ID),
                    project_name="other-project",
                )
            )
        with self.engine.begin() as connection:
            with self.assertRaises(MigrationStateRecoveryRequired):
                ensure_for_first_migrate(connection, _project())

        from oldman.db.migrations.state import ALEMBIC_VERSION_TABLE, SCHEMA_REGISTRY_TABLE

        with self.engine.begin() as connection:
            ALEMBIC_VERSION_TABLE.create(connection)
            SCHEMA_REGISTRY_TABLE.create(connection)
        with self.engine.connect() as connection:
            with self.assertRaises(MigrationOwnershipError) as raised:
                ensure_for_first_migrate(connection, _project())
        self.assertIn("other-project", str(raised.exception))
        self.assertIn(str(OTHER_PROJECT_ID), str(raised.exception))


class SchemaRegistryTests(SQLiteStateTestCase):
    """Persist only table-level ownership at revision boundaries."""

    def _initialize(self) -> None:
        from oldman.db.migrations.state import (
            ALEMBIC_VERSION_TABLE,
            ensure_for_first_migrate,
        )

        with self.engine.begin() as connection:
            ensure_for_first_migrate(connection, _project())
            ALEMBIC_VERSION_TABLE.create(connection)

    def test_records_managed_and_unmanaged_rows_and_updates_ownership_revision(self) -> None:
        from oldman.db.migrations.state import MigrationState, set_table_ownership

        self._initialize()
        with self.engine.begin() as connection:
            set_table_ownership(
                connection,
                table_name="report",
                app_label="reports",
                managed=True,
                ownership_revision="reports_001",
            )
            set_table_ownership(
                connection,
                table_name="external_customer",
                app_label="customers",
                managed=False,
                ownership_revision="customers_003",
            )
            set_table_ownership(
                connection,
                table_name="report",
                app_label="reports",
                managed=False,
                ownership_revision="reports_004",
            )

        with self.engine.connect() as connection:
            state = MigrationState.inspect(connection)
        self.assertFalse(state.schema_registry["report"].managed)
        self.assertEqual(state.schema_registry["report"].ownership_revision, "reports_004")
        self.assertFalse(state.schema_registry["external_customer"].managed)

    def test_cannot_silently_transfer_a_table_to_another_app(self) -> None:
        from oldman.db.migrations.state import SchemaOwnershipError, set_table_ownership

        self._initialize()
        with self.engine.begin() as connection:
            set_table_ownership(
                connection,
                table_name="report",
                app_label="reports",
                managed=True,
                ownership_revision="reports_001",
            )
        with self.engine.begin() as connection:
            with self.assertRaises(SchemaOwnershipError):
                set_table_ownership(
                    connection,
                    table_name="report",
                    app_label="billing",
                    managed=True,
                    ownership_revision="billing_001",
                )


if __name__ == "__main__":
    unittest.main()
