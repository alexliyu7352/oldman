"""Controlled recovery tests for Oldman's three internal migration tables."""

from __future__ import annotations

import unittest

from tests.test_oldman_db_makemigrations import (
    _app,
    _joined,
    _project_source,
    _run_project,
)
from tests.test_oldman_db_migration_commands import _revision


class MigrationRecoveryTests(unittest.TestCase):
    """Rebuild only framework state after proving the business schema is current."""

    def test_lost_state_recovery_stamps_heads_without_running_business_ddl(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision(
                    "r1",
                    None,
                    "reports",
                    "    raise AssertionError('recovery executed business migration')",
                    "    raise AssertionError('recovery executed business migration')",
                ),
            },
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from sqlalchemy import create_engine
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.state import MigrationState
                with sqlite3.connect(database_path) as connection:
                    connection.execute("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                    connection.execute("CREATE TABLE unrelated_external (id INTEGER PRIMARY KEY)")
                class Answers:
                    entered = iter((project.project_name, "recover migration state"))
                    def choose(self, prompt, choices):
                        assert choices == ("first use", "state lost", "cancel")
                        return "state lost"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): return next(self.entered)
                result = migrate(project, Answers())
                assert result.recovered is True
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                    tables = set(connection.dialect.get_table_names(connection))
                assert state.revisions == ("r1",)
                assert state.schema_registry["report"].ownership_revision == "__recovered__"
                assert "unrelated_external" in tables
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_partial_state_with_schema_drift_does_not_modify_internal_tables(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy import String
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        title: Mapped[str] = mapped_column(String(80))
                """,
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision("r1", None, "reports", "    pass", "    pass"),
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine, inspect
                from oldman.db.migrations.commands import MigrationRecoverySchemaError, migrate
                from oldman.db.migrations.state import MIGRATION_OWNER_TABLE
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER PRIMARY KEY)")
                    MIGRATION_OWNER_TABLE.create(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): raise AssertionError
                try:
                    migrate(project, Answers())
                except MigrationRecoverySchemaError as exc:
                    assert "report" in str(exc)
                else:
                    raise AssertionError("drifted schema was stamped")
                assert set(inspect(engine).get_table_names()) == {"report", "oldman_migration_owner"}
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_recovery_requires_explicit_unmanaged_history_choice(self) -> None:
        completed = _run_project(
            {
                "external/__init__.py": "",
                "external/apps.py": _app("external"),
                "external/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class ExternalRecord(DatabaseModel):
                        __tablename__ = "external_record"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        class Meta:
                            managed = False
                """,
                "external/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("external",)),
                """
                import sqlite3
                from sqlalchemy import create_engine
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.state import MigrationState
                with sqlite3.connect(database_path) as connection:
                    connection.execute("CREATE TABLE external_record (id INTEGER PRIMARY KEY, legacy TEXT)")
                class Answers:
                    entered = iter((project.project_name, "recover migration state"))
                    def choose(self, prompt, choices):
                        if choices == ("first use", "state lost", "cancel"):
                            return "state lost"
                        assert "always external" in choices and "released" in choices
                        return "released"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): return next(self.entered)
                migrate(project, Answers())
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                row = state.schema_registry["external_record"]
                assert row.managed is False and row.ownership_revision == "__recovered__"
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
