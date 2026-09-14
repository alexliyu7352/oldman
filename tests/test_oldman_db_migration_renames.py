"""Interactive table/column rename and deletion tests."""

from __future__ import annotations

import unittest

from tests.test_oldman_db_makemigrations import (
    _app,
    _joined,
    _project_source,
    _run_project,
)

_STATE_IMPORTS = """
from oldman.db.migrations.state import (
    INTERNAL_METADATA,
    MIGRATION_OWNER_TABLE,
    SCHEMA_REGISTRY_TABLE,
)
"""


class MigrationRenameTests(unittest.TestCase):
    """Resolve destructive Alembic add/drop candidates before writing source."""

    def test_confirmed_table_rename_preserves_data_and_registry_in_both_directions(self) -> None:
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
                _STATE_IMPORTS,
                """
                from alembic import command
                from sqlalchemy import create_engine
                from oldman.db.migrations.alembic import build_alembic_config
                from oldman.db.migrations.revisions import make_migration

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE TABLE legacy_report (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR(80))"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO legacy_report (id, title) VALUES (1, 'kept')"
                    )
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="legacy_report",
                        app_label="reports",
                        managed=True,
                        ownership_revision="legacy_revision",
                    ))

                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        assert "legacy_report" in prompt and "report" in prompt
                        assert default is False
                        return True
                    def enter(self, prompt): raise AssertionError
                    def text(self, prompt, *, default): return "rename report table"

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "op.rename_table('legacy_report', 'report')" in source
                assert "op.rename_table('report', 'legacy_report')" in source
                assert "op.create_table('report'" not in source
                assert "op.drop_table('legacy_report'" not in source

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "heads")
                    assert connection.exec_driver_sql("SELECT id, title FROM report").fetchall() == [(1, "kept")]
                    assert connection.exec_driver_sql(
                        "SELECT table_name, ownership_revision FROM oldman_schema_registry"
                    ).fetchall() == [("report", generated.revision)]

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.downgrade(config, "base")
                    assert connection.exec_driver_sql("SELECT id, title FROM legacy_report").fetchall() == [(1, "kept")]
                    assert connection.exec_driver_sql(
                        "SELECT table_name, ownership_revision FROM oldman_schema_registry"
                    ).fetchall() == [("legacy_report", "legacy_revision")]
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_table_delete_requires_the_complete_managed_table_name(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class CurrentReport(DatabaseModel):
                        __tablename__ = "current_report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                _STATE_IMPORTS,
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import MigrationDeletionCancelled
                from oldman.db.migrations.revisions import make_migration

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE retired_report (id INTEGER PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="retired_report",
                        app_label="reports",
                        managed=True,
                        ownership_revision="old_revision",
                    ))

                class WrongAnswer:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        assert "retired_report" in prompt and "current_report" in prompt
                        return False
                    def enter(self, prompt): return "report"
                    def text(self, prompt, *, default): raise AssertionError

                try:
                    make_migration(project, WrongAnswer())
                except MigrationDeletionCancelled as exc:
                    assert "retired_report" in str(exc)
                else:
                    raise AssertionError("partial table name confirmed deletion")

                class CorrectAnswer:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): return False
                    def enter(self, prompt): return "retired_report"
                    def text(self, prompt, *, default): return default

                generated = make_migration(project, CorrectAnswer())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "op.drop_table('retired_report')" in source
                assert "op.create_table('current_report'" in source
                assert "DELETE FROM oldman_schema_registry" in source
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_confirmed_column_rename_preserves_sqlite_data_and_reverses_name(self) -> None:
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
                        title: Mapped[str | None] = mapped_column(String(80), index=True)
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                _STATE_IMPORTS,
                """
                from alembic import command
                from sqlalchemy import create_engine
                from oldman.db.migrations.alembic import build_alembic_config
                from oldman.db.migrations.revisions import make_migration

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, legacy_title VARCHAR(80))"
                    )
                    connection.exec_driver_sql("CREATE INDEX ix_report_legacy_title ON report (legacy_title)")
                    connection.exec_driver_sql(
                        "INSERT INTO report (id, legacy_title) VALUES (1, 'kept')"
                    )
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
                        ownership_revision="initial_revision",
                    ))

                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        assert "legacy_title" in prompt and "title" in prompt
                        return True
                    def enter(self, prompt): raise AssertionError
                    def text(self, prompt, *, default): return "rename report title"

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "new_column_name='title'" in source
                assert "new_column_name='legacy_title'" in source
                assert "add_column" not in source
                assert "drop_column" not in source
                downgrade_source = source.split("def downgrade() -> None:", 1)[1]
                assert downgrade_source.index("ix_report_title") < downgrade_source.index("new_column_name='legacy_title'") < downgrade_source.index("ix_report_legacy_title"), source

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.upgrade(config, "heads")
                    assert connection.exec_driver_sql("SELECT id, title FROM report").fetchall() == [(1, "kept")]

                config = build_alembic_config(project)
                with engine.begin() as connection:
                    config.attributes["connection"] = connection
                    command.downgrade(config, "base")
                    assert connection.exec_driver_sql("SELECT id, legacy_title FROM report").fetchall() == [(1, "kept")]
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_column_delete_requires_full_name_and_noninteractive_input_stops(self) -> None:
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
                _STATE_IMPORTS,
                """
                import io
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import MigrationDeletionCancelled
                from oldman.db.migrations.interaction import ConsoleMigrationInteraction, MigrationInteractionRequired
                from oldman.db.migrations.revisions import make_migration

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, obsolete TEXT)"
                    )
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
                        ownership_revision="initial_revision",
                    ))

                class WrongAnswer:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def enter(self, prompt): return "obsolete"
                    def text(self, prompt, *, default): raise AssertionError

                try:
                    make_migration(project, WrongAnswer())
                except MigrationDeletionCancelled as exc:
                    assert "report.obsolete" in str(exc)
                else:
                    raise AssertionError("partial column name confirmed deletion")

                console = ConsoleMigrationInteraction(
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                try:
                    make_migration(project, console)
                except MigrationInteractionRequired:
                    pass
                else:
                    raise AssertionError("noninteractive deletion was accepted")
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_multiple_column_renames_use_explicit_one_to_one_choices_and_keep_attribute_changes(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy import String, text
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Report(DatabaseModel):
                        __tablename__ = "report"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        title: Mapped[str | None] = mapped_column(String(80))
                        rating: Mapped[str] = mapped_column(
                            String(20), nullable=False, server_default=text("'0'")
                        )
                """,
                "reports/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("reports",)),
                _STATE_IMPORTS,
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.revisions import make_migration

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE TABLE report ("
                        "id INTEGER NOT NULL PRIMARY KEY, legacy_title VARCHAR(80), score INTEGER)"
                    )
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
                        ownership_revision="initial_revision",
                    ))

                class Answers:
                    def choose(self, prompt, choices):
                        if "legacy_title" in prompt:
                            assert "title" in choices
                            return "title"
                        if "score" in prompt:
                            assert "rating" in choices
                            return "rating"
                        raise AssertionError(prompt)
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def enter(self, prompt): raise AssertionError
                    def text(self, prompt, *, default): return default

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "new_column_name='title'" in source
                assert "new_column_name='rating'" in source
                assert "type_=sa.String(length=20)" in source
                assert "nullable=False" in source
                assert "server_default=sa.text" in source
                assert "new_column_name='legacy_title'" in source
                assert "new_column_name='score'" in source
                assert "add_column" not in source
                assert "drop_column" not in source
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
