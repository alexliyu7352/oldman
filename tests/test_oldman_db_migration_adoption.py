"""External-table adoption and managed ownership transition tests."""

from __future__ import annotations

import unittest

from tests.test_oldman_db_makemigrations import (
    _app,
    _joined,
    _project_source,
    _run_project,
)


class MigrationAdoptionTests(unittest.TestCase):
    """Keep physical DDL management distinct from ordinary ORM mapping."""

    def test_collects_create_release_and_reacquire_as_distinct_changes(self) -> None:
        create = _run_project(
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
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import collect_schema_changes

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    changes = collect_schema_changes(project, connection)

                reports = changes.by_app["reports"]
                assert reports.table_names == ("report",)
                assert [(change.table_name, change.kind) for change in reports.ownership_changes] == [
                    ("report", "create")
                ]
                """,
            ),
        )
        self.assertEqual(create.returncode, 0, create.stdout + create.stderr)

        release = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        class Meta:
                            managed = False
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import collect_schema_changes
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA,
                    MIGRATION_OWNER_TABLE,
                    SCHEMA_REGISTRY_TABLE,
                )

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="report",
                        app_label="reports",
                        managed=True,
                        ownership_revision="old_revision",
                    ))
                    changes = collect_schema_changes(project, connection)

                reports = changes.by_app["reports"]
                assert reports.upgrade_ops.ops == []
                assert reports.summaries[0].kind == "release_ownership"
                change = reports.ownership_changes[0]
                assert change.kind == "release"
                assert change.before is not None and change.before.managed is True
                assert change.after_managed is False
                """,
            ),
        )
        self.assertEqual(release.returncode, 0, release.stdout + release.stderr)

        reacquire = _run_project(
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
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import collect_schema_changes
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA,
                    MIGRATION_OWNER_TABLE,
                    SCHEMA_REGISTRY_TABLE,
                )

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="report",
                        app_label="reports",
                        managed=False,
                        ownership_revision="released_revision",
                    ))
                    changes = collect_schema_changes(project, connection)

                reports = changes.by_app["reports"]
                assert reports.upgrade_ops.ops == []
                assert reports.ownership_changes[0].kind == "reacquire"
                assert reports.ownership_changes[0].after_managed is True
                """,
            ),
        )
        self.assertEqual(reacquire.returncode, 0, reacquire.stdout + reacquire.stderr)

    def test_unmanaged_external_tables_need_no_registry_or_migration(self) -> None:
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
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import collect_schema_changes

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE external_record (id INTEGER PRIMARY KEY, legacy TEXT)")
                    connection.exec_driver_sql("CREATE TABLE no_model_at_all (id INTEGER PRIMARY KEY)")
                    changes = collect_schema_changes(project, connection)

                assert changes.by_app == {}
                assert changes.summaries == ()
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_release_revision_updates_only_registry_and_downgrade_restores_history(self) -> None:
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
                        class Meta:
                            managed = False
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                """
                from alembic import command
                from sqlalchemy import create_engine
                from oldman.db.migrations.alembic import build_alembic_config
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA,
                    MIGRATION_OWNER_TABLE,
                    SCHEMA_REGISTRY_TABLE,
                )

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="report",
                        app_label="reports",
                        managed=True,
                        ownership_revision="original_revision",
                    ))

                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "CREATE TABLE report" not in source
                assert "DROP TABLE report" not in source
                assert "managed = FALSE" in source
                assert "managed = TRUE" in source
                assert "original_revision" in source

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "heads")
                    assert connection.exec_driver_sql(
                        "SELECT managed, ownership_revision FROM oldman_schema_registry WHERE table_name='report'"
                    ).fetchone() == (0, generated.revision)
                    assert "report" in connection.dialect.get_table_names(connection)

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.downgrade(config, "base")
                    assert connection.exec_driver_sql(
                        "SELECT managed, ownership_revision FROM oldman_schema_registry WHERE table_name='report'"
                    ).fetchone() == (1, "original_revision")
                    assert "report" in connection.dialect.get_table_names(connection)
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_rejects_adoption_or_reacquire_when_physical_schema_is_not_exact(self) -> None:
        adoption = _run_project(
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
            },
            _joined(
                _project_source(("reports",)),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import MigrationAdoptionConflict, collect_schema_changes

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE report (id INTEGER PRIMARY KEY, legacy TEXT)")
                    try:
                        collect_schema_changes(project, connection)
                    except MigrationAdoptionConflict as exc:
                        assert "report" in str(exc)
                    else:
                        raise AssertionError("incompatible external table was accepted")
                """,
            ),
        )
        self.assertEqual(adoption.returncode, 0, adoption.stdout + adoption.stderr)

        reacquire = _run_project(
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
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import MigrationSchemaDriftError, collect_schema_changes
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA,
                    MIGRATION_OWNER_TABLE,
                    SCHEMA_REGISTRY_TABLE,
                )

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="report",
                        app_label="reports",
                        managed=False,
                        ownership_revision="released_revision",
                    ))
                    try:
                        collect_schema_changes(project, connection)
                    except MigrationSchemaDriftError as exc:
                        assert "report" in str(exc)
                    else:
                        raise AssertionError("missing released table was recreated")

                    connection.exec_driver_sql(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, legacy TEXT)"
                    )
                    from oldman.db.migrations.autogenerate import MigrationAdoptionConflict
                    try:
                        collect_schema_changes(project, connection)
                    except MigrationAdoptionConflict as exc:
                        assert "report" in str(exc)
                    else:
                        raise AssertionError("incompatible released table was reacquired")
                """,
            ),
        )
        self.assertEqual(reacquire.returncode, 0, reacquire.stdout + reacquire.stderr)

    def test_adoption_intent_controls_generation_and_writes_a_guarded_revision(self) -> None:
        files = {
            "reports/__init__.py": "",
            "reports/apps.py": _app("reports"),
            "reports/models.py": """
                from sqlalchemy import String
                from sqlalchemy.orm import Mapped, mapped_column
                from oldman.db import DatabaseModel
                class Report(DatabaseModel):
                    __tablename__ = "report"
                    id: Mapped[int] = mapped_column(primary_key=True)
                    title: Mapped[str | None] = mapped_column(String(80))

                class Audit(DatabaseModel):
                    __tablename__ = "report_audit"
                    id: Mapped[int] = mapped_column(primary_key=True)
            """,
            "reports/migrations/__init__.py": "",
        }
        adopted = _run_project(
            files,
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from oldman.db.migrations.revisions import make_migration

                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(80))"
                    )

                class Answers:
                    def choose(self, prompt, choices):
                        assert choices == ("keep external", "adopt", "cancel")
                        return "adopt"
                    def confirm(self, prompt, *, default=False):
                        raise AssertionError("makemigrations adoption needs no second confirmation")
                    def text(self, prompt, *, default):
                        return "adopt report table"

                generated = make_migration(project, Answers())
                assert generated is not None
                assert generated.adoption_tables == ("report",)
                source = generated.path.read_text(encoding="utf-8")
                assert "oldman_adoption_tables" in source
                assert "oldman_adoption_upgrade_sha256" in source
                assert "op.create_table('report'" in source
                assert "report_audit" not in source
                assert "INSERT INTO oldman_schema_registry" in source
                with sqlite3.connect(database_path) as connection:
                    assert connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall() == [("report",)]
                """,
            ),
        )
        self.assertEqual(adopted.returncode, 0, adopted.stdout + adopted.stderr)

        kept_external = _run_project(
            files,
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from oldman.db.migrations.autogenerate import MigrationModelChangeRequired
                from oldman.db.migrations.revisions import make_migration

                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(80))"
                    )

                class Answers:
                    def choose(self, prompt, choices): return "keep external"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError

                try:
                    make_migration(project, Answers())
                except MigrationModelChangeRequired as exc:
                    assert "Meta.managed=False" in str(exc)
                else:
                    raise AssertionError("external-management choice wrote a revision")
                """,
            ),
        )
        self.assertEqual(kept_external.returncode, 0, kept_external.stdout + kept_external.stderr)

        cancelled = _run_project(
            files,
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from oldman.db.migrations.revisions import make_migration

                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(80))"
                    )

                class Answers:
                    def choose(self, prompt, choices): return "cancel"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError

                assert make_migration(project, Answers()) is None
                assert tuple((__import__("pathlib").Path.cwd() / "reports" / "migrations").glob("*.py")) == (
                    __import__("pathlib").Path.cwd() / "reports" / "migrations" / "__init__.py",
                )
                """,
            ),
        )
        self.assertEqual(cancelled.returncode, 0, cancelled.stdout + cancelled.stderr)

    def test_adoption_revision_runs_on_empty_database_and_plans_existing_database_skip(self) -> None:
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
                        title: Mapped[str | None] = mapped_column(String(80))
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                """
                import sqlite3
                from alembic import command
                from pathlib import Path
                from sqlalchemy import create_engine
                from oldman.db.migrations.alembic import build_alembic_config, load_migration_graph
                from oldman.db.migrations.revisions import make_migration, plan_adoption_execution
                from oldman.db.migrations.state import INTERNAL_METADATA

                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(80))"
                    )

                class GenerateAnswers:
                    def choose(self, prompt, choices): return "adopt"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default

                generated = make_migration(project, GenerateAnswers())
                assert generated is not None
                graph = load_migration_graph(project, config=build_alembic_config(project))
                script = graph.branches["reports"].heads[0]

                class ConfirmExisting:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        assert default is False
                        return True
                    def text(self, prompt, *, default): raise AssertionError

                existing_engine = create_engine(f"sqlite:///{database_path}")
                with existing_engine.connect() as connection:
                    plan = plan_adoption_execution(project, script, connection, ConfirmExisting())
                assert plan.adoption_tables == ("report",)
                assert plan.skip_schema is True

                empty_path = Path.cwd() / "empty.db"
                empty_engine = create_engine(f"sqlite:///{empty_path}")
                with empty_engine.begin() as connection:
                    INTERNAL_METADATA.create_all(connection)
                empty_project = project.__class__(
                    project_root=project.project_root,
                    project_id=project.project_id,
                    project_name=project.project_name,
                    database_url=f"sqlite+aiosqlite:///{empty_path}",
                    service_configs=project.service_configs,
                    apps=project.apps,
                    user_model_path=project.user_model_path,
                )
                empty_graph = load_migration_graph(empty_project, config=build_alembic_config(empty_project))
                with empty_engine.connect() as connection:
                    empty_plan = plan_adoption_execution(
                        empty_project,
                        empty_graph.branches["reports"].heads[0],
                        connection,
                        ConfirmExisting(),
                    )
                assert empty_plan.skip_schema is False

                empty_config = build_alembic_config(empty_project)
                with empty_engine.begin() as connection:
                    empty_config.attributes["connection"] = connection
                    command.upgrade(empty_config, "heads")
                    assert connection.exec_driver_sql(
                        "SELECT table_name, app_label, managed FROM oldman_schema_registry"
                    ).fetchall() == [("report", "reports", 1)]
                    assert "report" in connection.dialect.get_table_names(connection)
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_modified_adoption_revision_and_later_schema_drift_are_rejected(self) -> None:
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
                from oldman.db.migrations.alembic import build_alembic_config, load_migration_graph
                from oldman.db.migrations.autogenerate import MigrationAdoptionConflict
                from oldman.db.migrations.revisions import (
                    AdoptionRevisionError,
                    make_migration,
                    plan_adoption_execution,
                )

                with sqlite3.connect(database_path) as connection:
                    connection.execute("CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY)")

                class Answers:
                    def choose(self, prompt, choices): return "adopt"
                    def confirm(self, prompt, *, default=False): return True
                    def text(self, prompt, *, default): return default

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                generated.path.write_text(
                    source.replace("def upgrade() -> None:", "def upgrade() -> None:\\n    op.execute('SELECT 1')"),
                    encoding="utf-8",
                )
                graph = load_migration_graph(project, config=build_alembic_config(project))
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.connect() as connection:
                    try:
                        plan_adoption_execution(project, graph.branches["reports"].heads[0], connection, Answers())
                    except AdoptionRevisionError:
                        pass
                    else:
                        raise AssertionError("modified adoption revision was accepted")

                generated.path.write_text(source, encoding="utf-8")
                graph = load_migration_graph(project, config=build_alembic_config(project))
                with sqlite3.connect(database_path) as connection:
                    connection.execute("ALTER TABLE report ADD COLUMN legacy TEXT")
                with engine.connect() as connection:
                    try:
                        plan_adoption_execution(project, graph.branches["reports"].heads[0], connection, Answers())
                    except MigrationAdoptionConflict as exc:
                        assert "report" in str(exc)
                    else:
                        raise AssertionError("post-generation schema drift was accepted")
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
