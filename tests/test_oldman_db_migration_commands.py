"""Project migration execution, downgrade, and retirement tests."""

from __future__ import annotations

import unittest

from tests.test_oldman_db_makemigrations import (
    _app,
    _joined,
    _project_source,
    _run_project,
)


def _revision(
    revision: str,
    down_revision: str | None,
    branch: str | None,
    upgrade: str,
    downgrade: str,
    *,
    depends_on: str | None = None,
) -> str:
    """Return one executable standard Alembic revision."""
    return f"""from alembic import op
import sqlalchemy as sa
revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = {(branch,) if branch else None!r}
depends_on = {depends_on!r}
def upgrade() -> None:
{upgrade}
def downgrade() -> None:
{downgrade}
"""


class MigrationCommandTests(unittest.TestCase):
    """Execute standard Alembic branches through the Oldman command boundary."""

    def test_single_app_migrate_applies_its_real_foreign_key_dependency(self) -> None:
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _app("accounts"),
                "accounts/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Account(DatabaseModel):
                        __tablename__ = "account"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "accounts/migrations/__init__.py": "",
                "accounts/migrations/a1.py": _revision(
                    "a1",
                    None,
                    "accounts",
                    "    op.create_table('account', sa.Column('id', sa.Integer(), nullable=False), sa.PrimaryKeyConstraint('id'))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('account', 'accounts', TRUE, 'a1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='account'\")\n    op.drop_table('account')",
                ),
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
                """,
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision(
                    "r1",
                    None,
                    "reports",
                    "    op.create_table('report', sa.Column('id', sa.Integer(), nullable=False), "
                    "sa.Column('account_id', sa.Integer(), nullable=False), sa.ForeignKeyConstraint(['account_id'], ['account.id']), "
                    "sa.PrimaryKeyConstraint('id'))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('report', 'reports', TRUE, 'r1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='report'\")\n    op.drop_table('report')",
                    depends_on="a1",
                ),
            },
            _joined(
                _project_source(("reports", "accounts")),
                """
                from sqlalchemy import create_engine, inspect
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.state import MigrationState
                class Answers:
                    def choose(self, prompt, choices):
                        if "internal migration state" in prompt:
                            assert choices == ("first use", "state lost", "cancel")
                            return "first use"
                        assert "reports" in choices and "all" in choices
                        return "reports"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                result = migrate(project, Answers())
                assert result.target_app == "reports"
                assert set(result.applied_revisions) == {"a1", "r1"}
                engine = create_engine(f"sqlite:///{database_path}")
                assert {"account", "report"}.issubset(inspect(engine).get_table_names())
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                assert state.revisions == ("r1",), state.revisions
                assert set(state.schema_registry) == {"account", "report"}
                assert state.owner is not None and state.owner.project_id == project.project_id
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_migrate_applies_the_other_apps_first_so_makemigrations_can_create_a_new_apps_revision(self) -> None:
        """An App added before the database was migrated: makemigrations needs the database at the source heads,
        and migrate refused while any App lacked a revision, so each asked for the other first."""
        model = """
            from sqlalchemy.orm import Mapped, mapped_column
            from oldman.db import DatabaseModel
            class {name}(DatabaseModel):
                __tablename__ = "{table}"
                id: Mapped[int] = mapped_column(primary_key=True)
        """
        completed = _run_project(
            {
                "notes/__init__.py": "",
                "notes/apps.py": _app("notes"),
                "notes/models.py": model.format(name="Note", table="notes_note"),
                "notes/migrations/__init__.py": "",
                "customers/__init__.py": "",
                "customers/apps.py": _app("customers"),
                "customers/models.py": model.format(name="Customer", table="customers_customer"),
                "customers/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("notes", "customers")),
                """
                from sqlalchemy import create_engine, inspect
                from oldman.db.migrations.commands import MissingInitialMigrationError, makemigrations, migrate

                def tables():
                    return set(inspect(create_engine(f"sqlite:///{database_path}")).get_table_names())

                class Answers:
                    def __init__(self, *, app=None, interactive=True, apply_others=None):
                        self.app, self.is_interactive, self.apply_others, self.confirmations = app, interactive, apply_others, []
                    def choose(self, prompt, choices):
                        if "first use" in choices:
                            return "first use"
                        if "all" in choices:
                            return "all"
                        assert self.app in choices, (prompt, choices)
                        return self.app
                    def confirm(self, prompt, *, default=False):
                        self.confirmations.append(prompt)
                        if self.apply_others is None:
                            raise AssertionError(prompt)
                        return self.apply_others
                    def text(self, prompt, *, default):
                        return default

                # notes gets its first revision while the database is still empty; customers has none yet.
                assert makemigrations(project, Answers(app="notes")).app_label == "notes"

                # Without a terminal the way out cannot be offered: the refusal says to run migrate in one.
                try:
                    migrate(project, Answers(interactive=False))
                except MissingInitialMigrationError as exc:
                    assert "customers" in str(exc) and "terminal" in str(exc), str(exc)
                else:
                    raise AssertionError("migrate ran without a terminal while customers had no revision")

                # In a terminal, migrate offers to apply the other Apps first; cancelling changes nothing.
                declined = Answers(apply_others=False)
                result = migrate(project, declined)
                assert result.cancelled and result.applied_revisions == () and "customers" in declined.confirmations[0]
                assert "notes_note" not in tables()

                accepted = Answers(apply_others=True)
                result = migrate(project, accepted)
                assert result.apps_without_migrations == ("customers",), result
                assert len(accepted.confirmations) == 1
                assert "notes_note" in tables() and "customers_customer" not in tables()

                # The database is at the source heads now: makemigrations can run, so migrate asks nothing and refuses.
                try:
                    migrate(project, Answers())
                except MissingInitialMigrationError as exc:
                    assert "run makemigrations and select: customers" in str(exc), str(exc)
                else:
                    raise AssertionError("migrate ran while customers had no revision and nothing else was pending")

                assert makemigrations(project, Answers(app="customers")).app_label == "customers"
                result = migrate(project, Answers())
                assert result.apps_without_migrations == ()
                assert {"notes_note", "customers_customer"} <= tables()
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_migrate_rejects_managed_app_without_initial_revision_before_connecting(self) -> None:
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
            },
            _joined(
                _project_source(("reports",)),
                """
                from oldman.db.migrations.commands import MissingInitialMigrationError, migrate
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                try:
                    migrate(project, Answers())
                except MissingInitialMigrationError as exc:
                    assert "reports" in str(exc) and "makemigrations" in str(exc)
                else:
                    raise AssertionError("managed App without revisions was accepted")
                assert not database_path.exists()
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_nontransactional_failure_keeps_original_error_and_warns_about_partial_ddl(self) -> None:
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
                "reports/migrations/r1.py": _revision("r1", None, "reports", "    pass", "    pass"),
                "reports/migrations/r2.py": _revision(
                    "r2",
                    "r1",
                    None,
                    "    op.create_table('partial_write', sa.Column('id', sa.Integer(), primary_key=True))\n"
                    "    op.execute('INSERT INTO table_that_does_not_exist VALUES (1)')",
                    "    op.drop_table('partial_write')",
                ),
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine
                from sqlalchemy.exc import OperationalError
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA, MIGRATION_OWNER_TABLE, ALEMBIC_VERSION_TABLE,
                )
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                    connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="r1"))
                class Answers:
                    def choose(self, prompt, choices): return "all"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                try:
                    migrate(project, Answers())
                except OperationalError as exc:
                    assert "table_that_does_not_exist" in str(exc)
                    assert any("partial DDL" in note for note in getattr(exc, "__notes__", ()))
                else:
                    raise AssertionError("failing revision succeeded")
                with engine.connect() as connection:
                    tables = set(connection.dialect.get_table_names(connection))
                    revisions = connection.exec_driver_sql(
                        "SELECT version_num FROM oldman_alembic_version"
                    ).fetchall()
                assert "partial_write" in tables, tables
                assert revisions == [("r1",)], revisions
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_downgrade_rejects_a_revision_required_by_an_applied_app(self) -> None:
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _app("accounts"),
                "accounts/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Account(DatabaseModel):
                        __tablename__ = "account"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "accounts/migrations/__init__.py": "",
                "accounts/migrations/a1.py": _revision(
                    "a1",
                    None,
                    "accounts",
                    "    op.create_table('account', sa.Column('id', sa.Integer(), primary_key=True))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('account', 'accounts', TRUE, 'a1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='account'\")\n    op.drop_table('account')",
                ),
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
                """,
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision(
                    "r1",
                    None,
                    "reports",
                    "    op.create_table('report', sa.Column('id', sa.Integer(), primary_key=True), "
                    "sa.Column('account_id', sa.Integer(), sa.ForeignKey('account.id')))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('report', 'reports', TRUE, 'r1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='report'\")\n    op.drop_table('report')",
                    depends_on="a1",
                ),
            },
            _joined(
                _project_source(("accounts", "reports")),
                """
                from oldman.db.migrations.commands import (
                    MigrationDependencyBlockedError, downgrade, migrate,
                )
                class MigrateAnswers:
                    def choose(self, prompt, choices):
                        return "first use" if "internal migration state" in prompt else "all"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                migrate(project, MigrateAnswers())
                class DowngradeAnswers:
                    def choose(self, prompt, choices):
                        return "accounts" if "applied App" in prompt else "base"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): raise AssertionError
                try:
                    downgrade(project, DowngradeAnswers())
                except MigrationDependencyBlockedError as exc:
                    assert "reports" in str(exc)
                else:
                    raise AssertionError("required dependency was downgraded")

                from sqlalchemy import create_engine
                from oldman.db.migrations.commands import retire
                from oldman.db.migrations.state import MigrationState
                class RetireAnswers:
                    def choose(self, prompt, choices): return "reports"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): return "reports"
                retire(project, RetireAnswers())
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                    tables = set(connection.dialect.get_table_names(connection))
                assert state.revisions == ("a1",), state.revisions
                assert set(state.schema_registry) == {"account"}
                assert {"account", "report"}.issubset(tables)
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_migrate_adopts_an_existing_exact_table_without_running_create(self) -> None:
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
            },
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from sqlalchemy import create_engine
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import MigrationState
                with sqlite3.connect(database_path) as connection:
                    connection.execute("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                class GenerateAnswers:
                    def choose(self, prompt, choices): return "adopt"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default
                generated = make_migration(project, GenerateAnswers())
                class MigrateAnswers:
                    def choose(self, prompt, choices):
                        return "first use" if "internal migration state" in prompt else "all"
                    def confirm(self, prompt, *, default=False):
                        assert "Skip CREATE" in prompt
                        return True
                    def text(self, prompt, *, default): raise AssertionError
                result = migrate(project, MigrateAnswers())
                assert result.applied_revisions == (generated.revision,)
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                    count = connection.exec_driver_sql("SELECT COUNT(*) FROM report").scalar_one()
                assert state.revisions == (generated.revision,)
                assert state.schema_registry["report"].ownership_revision == generated.revision
                assert count == 0
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_noninteractive_existing_database_migrates_all_pending_apps(self) -> None:
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
                    "    op.create_table('report', sa.Column('id', sa.Integer(), primary_key=True))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('report', 'reports', TRUE, 'r1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='report'\")\n    op.drop_table('report')",
                ),
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.commands import migrate
                from oldman.db.migrations.state import INTERNAL_METADATA, MIGRATION_OWNER_TABLE, MigrationState
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                class NoninteractiveAnswers:
                    is_interactive = False
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                result = migrate(project, NoninteractiveAnswers())
                assert result.target_app is None and result.applied_revisions == ("r1",)
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                assert state.revisions == ("r1",)
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_downgrade_to_base_runs_revision_and_registry_reverse(self) -> None:
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
                    "    op.create_table('report', sa.Column('id', sa.Integer(), nullable=False), sa.PrimaryKeyConstraint('id'))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('report', 'reports', TRUE, 'r1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='report'\")\n    op.drop_table('report')",
                ),
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine, inspect
                from oldman.db.migrations.commands import downgrade, migrate
                from oldman.db.migrations.state import MigrationState
                class MigrateAnswers:
                    def choose(self, prompt, choices):
                        return "first use" if "internal migration state" in prompt else "all"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                migrate(project, MigrateAnswers())
                class DowngradeAnswers:
                    entered = iter(("reports", "base"))
                    def choose(self, prompt, choices):
                        return "reports" if "applied App" in prompt else "base"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): return next(self.entered)
                result = downgrade(project, DowngradeAnswers())
                assert result is not None and result.target_revision == "base"
                engine = create_engine(f"sqlite:///{database_path}")
                assert "report" not in inspect(engine).get_table_names()
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                assert state.revisions == ()
                assert state.schema_registry == {}
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_retire_removes_only_branch_state_and_returns_cleanup_locations(self) -> None:
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
                    "    op.create_table('report', sa.Column('id', sa.Integer(), nullable=False), sa.PrimaryKeyConstraint('id'))\n"
                    "    op.execute(\"INSERT INTO oldman_schema_registry VALUES ('report', 'reports', TRUE, 'r1')\")",
                    "    op.execute(\"DELETE FROM oldman_schema_registry WHERE table_name='report'\")\n    op.drop_table('report')",
                ),
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine, inspect
                from oldman.db.migrations.commands import migrate, retire
                from oldman.db.migrations.state import MigrationState
                class MigrateAnswers:
                    def choose(self, prompt, choices):
                        return "first use" if "internal migration state" in prompt else "all"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                migrate(project, MigrateAnswers())
                class RetireAnswers:
                    def choose(self, prompt, choices): return "reports"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                    def enter(self, prompt): return "reports"
                result = retire(project, RetireAnswers())
                assert result is not None
                assert result.app_label == "reports"
                assert result.retained_tables == ("report",)
                assert result.package == "reports"
                engine = create_engine(f"sqlite:///{database_path}")
                assert "report" in inspect(engine).get_table_names()
                with engine.connect() as connection:
                    state = MigrationState.inspect(connection)
                assert state.revisions == () and state.schema_registry == {}
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
