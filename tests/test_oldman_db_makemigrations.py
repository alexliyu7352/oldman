"""Project-wide Alembic autogenerate and revision writing tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "9714d0a3-3f2b-48aa-88d7-c0869b2a6f25"


def _run_project(
    files: dict[str, str],
    source: str,
    *,
    python_paths: tuple[Path, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run one isolated model and migration scenario."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        paths = [str(REPOSITORY_ROOT), str(root), *(str(path) for path in python_paths)]
        if existing_path := environment.get("PYTHONPATH"):
            paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )


def _app(label: str) -> str:
    """Return minimal App metadata."""
    return f"""
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = {label!r}
            display_name = {label.replace("_", " ").title()!r}

        app = Config()
    """


def _project_source(packages: tuple[str, ...]) -> str:
    """Build a project context around a real temporary SQLite file."""
    return textwrap.dedent(
        f"""
        from pathlib import Path
        from uuid import UUID

        from oldman.apps import AppRegistry
        from oldman.db.migrations import MigrationProject

        registry = AppRegistry()
        registry.register_packages({packages!r})
        database_path = Path.cwd() / "migration.db"
        project = MigrationProject(
            project_root=Path.cwd(),
            project_id=UUID({PROJECT_ID!r}),
            project_name="migration-demo",
            database_url=f"sqlite+aiosqlite:///{{database_path}}",
            service_configs=(),
            apps=registry,
            user_model_path=None,
        )
        """
    )


def _joined(*sources: str) -> str:
    """Dedent separately authored source fragments before concatenating them."""
    return "".join(textwrap.dedent(source) for source in sources)


class OldmanMakemigrationsTests(unittest.TestCase):
    """Keep full-schema comparison separate from one-App revision writing."""

    def test_collects_full_schema_in_fk_order_and_ignores_external_tables(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class Parent(DatabaseModel):
                        __tablename__ = "z_parent"
                        id: Mapped[int] = mapped_column(primary_key=True)

                    class Child(DatabaseModel):
                        __tablename__ = "a_child"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        parent_id: Mapped[int] = mapped_column(ForeignKey("z_parent.id"))
                """,
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class BetaItem(DatabaseModel):
                        __tablename__ = "beta_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("beta", "alpha")),
                """
            from sqlalchemy import create_engine

            from oldman.db.migrations.autogenerate import collect_schema_changes

            engine = create_engine(f"sqlite:///{database_path}")
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE external_audit (id INTEGER PRIMARY KEY)")
                changes = collect_schema_changes(project, connection)
                physical_tables = set(connection.dialect.get_table_names(connection))

            assert tuple(changes.by_app) == ("alpha", "beta")
            assert changes.by_app["alpha"].table_names == ("z_parent", "a_child")
            assert changes.by_app["beta"].table_names == ("beta_item",)
            assert "external_audit" not in changes.table_names
            assert physical_tables == {"external_audit"}
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_groups_alter_and_managed_drop_without_mixing_other_apps(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import Index, String
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        title: Mapped[str | None] = mapped_column(String(80))
                        code: Mapped[str | None] = mapped_column(String(20), unique=True)
                        __table_args__ = (Index("ix_alpha_item_title", "title"),)
                """,
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class BetaItem(DatabaseModel):
                        __tablename__ = "beta_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha", "beta")),
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
                connection.exec_driver_sql("CREATE TABLE alpha_item (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE retired_parent (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql(
                    "CREATE TABLE retired_child ("
                    "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES retired_parent(id))"
                )
                connection.exec_driver_sql("CREATE TABLE external_log (id INTEGER PRIMARY KEY)")
                INTERNAL_METADATA.create_all(connection)
                connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                    singleton_id=1,
                    project_id=str(project.project_id),
                    project_name=project.project_name,
                ))
                connection.execute(SCHEMA_REGISTRY_TABLE.insert(), [
                    {
                        "table_name": "alpha_item",
                        "app_label": "alpha",
                        "managed": True,
                        "ownership_revision": "alpha_previous",
                    },
                    {
                        "table_name": "retired_parent",
                        "app_label": "alpha",
                        "managed": True,
                        "ownership_revision": "alpha_previous",
                    },
                    {
                        "table_name": "retired_child",
                        "app_label": "alpha",
                        "managed": True,
                        "ownership_revision": "alpha_previous",
                    },
                ])
                changes = collect_schema_changes(project, connection)

            alpha = changes.by_app["alpha"]
            assert alpha.table_names == ("retired_child", "retired_parent", "alpha_item"), alpha.table_names
            assert sum(summary.kind == "drop_table" for summary in alpha.summaries) == 2
            assert any(summary.kind == "alter_table" for summary in alpha.summaries)
            alter = next(
                operation
                for operation in alpha.upgrade_ops.ops
                if operation.__class__.__name__ == "ModifyTableOps"
                and operation.table_name == "alpha_item"
            )
            child_types = {type(operation).__name__ for operation in alter.ops}
            assert "AddColumnOp" in child_types
            assert "CreateIndexOp" in child_types
            assert "CreateUniqueConstraintOp" in child_types, child_types
            assert changes.by_app["beta"].table_names == ("beta_item",)
            assert "external_log" not in changes.table_names
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_rejects_missing_managed_physical_table_as_schema_drift(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha",)),
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
                    table_name="missing_managed",
                    app_label="alpha",
                    managed=True,
                    ownership_revision="alpha_previous",
                ))
                try:
                    collect_schema_changes(project, connection)
                except MigrationSchemaDriftError as exc:
                    assert "missing_managed" in str(exc)
                else:
                    raise AssertionError("managed schema drift was accepted")
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_custom_user_diff_extends_the_applied_auth_core(self) -> None:
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _app("accounts"),
                "accounts/models.py": """
                    from sqlalchemy import String
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.auth import AbstractUser

                    class CustomUser(AbstractUser):
                        phone: Mapped[str | None] = mapped_column(String(32), index=True)
                """,
                "accounts/migrations/__init__.py": "",
            },
            _project_source(("oldman.auth", "accounts")).replace(
                "user_model_path=None",
                'user_model_path="accounts.models.CustomUser"',
            )
            + textwrap.dedent(
                """
                from alembic import command
                from alembic.operations import ops
                from sqlalchemy import create_engine, inspect

                from oldman.db.migrations.alembic import build_alembic_config
                from oldman.db.migrations.autogenerate import collect_schema_changes
                from oldman.db.migrations.state import ensure_for_first_migrate

                engine = create_engine(f"sqlite:///{database_path}")
                config = build_alembic_config(project)
                with engine.begin() as connection:
                    ensure_for_first_migrate(connection, project)
                    config.attributes["connection"] = connection
                    command.upgrade(config, "auth@head")
                    core_columns = {
                        column["name"]
                        for column in inspect(connection).get_columns("oldman_user")
                    }
                    changes = collect_schema_changes(project, connection)

                assert "id" in core_columns
                assert "username" in core_columns
                assert "phone" not in core_columns
                assert tuple(changes.by_app) == ("accounts",)

                account_ops = changes.by_app["accounts"].upgrade_ops.ops
                assert any(
                    isinstance(operation, ops.ModifyTableOps)
                    and any(
                        isinstance(child, ops.AddColumnOp) and child.column.name == "phone"
                        for child in operation.ops
                    )
                    for operation in account_ops
                )
                """
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_make_migration_selects_one_app_and_only_writes_its_operations(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel

                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel

                    class BetaItem(DatabaseModel):
                        __tablename__ = "beta_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha", "beta")),
                """
            from oldman.db.migrations.revisions import make_migration

            class Answers:
                def choose(self, prompt, choices):
                    assert choices == ("alpha", "beta")
                    return "beta"

                def confirm(self, prompt, *, default=False):
                    raise AssertionError("no confirmation should be needed")

                def text(self, prompt, *, default):
                    assert default == "create beta_item"
                    return "add beta items"

            generated = make_migration(project, Answers())
            assert generated is not None
            assert generated.app_label == "beta"
            assert generated.message == "add beta items"
            assert generated.path.parent == Path.cwd() / "beta" / "migrations"
            source = generated.path.read_text(encoding="utf-8")
            assert "op.create_table('beta_item'" in source
            assert "alpha_item" not in source
            assert "Review upgrade() and downgrade()" in source
            assert not database_path.exists() or set(__import__("sqlite3").connect(database_path).execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )) == set()
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unique_owner_is_automatic_and_no_diff_can_create_blank_revision(self) -> None:
        unique = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel

                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha",)),
                """
            from oldman.db.migrations.revisions import make_migration

            class Answers:
                def choose(self, prompt, choices):
                    raise AssertionError("one changed App must be selected automatically")
                def confirm(self, prompt, *, default=False):
                    raise AssertionError("a normal diff needs no confirmation")
                def text(self, prompt, *, default):
                    return default

            generated = make_migration(project, Answers())
            assert generated is not None
            assert generated.app_label == "alpha"
                """,
            ),
        )
        self.assertEqual(unique.returncode, 0, unique.stdout + unique.stderr)

        blank = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel

                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha",)),
                """
            import sqlite3
            from sqlalchemy import create_engine

            from oldman.db.migrations.revisions import make_migration
            from oldman.db.migrations.state import (
                INTERNAL_METADATA,
                MIGRATION_OWNER_TABLE,
                SCHEMA_REGISTRY_TABLE,
            )

            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE alpha_item (id INTEGER NOT NULL PRIMARY KEY)")
            engine = create_engine(f"sqlite:///{database_path}")
            with engine.begin() as connection:
                INTERNAL_METADATA.create_all(connection)
                connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                    singleton_id=1,
                    project_id=str(project.project_id),
                    project_name=project.project_name,
                ))
                connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                    table_name="alpha_item",
                    app_label="alpha",
                    managed=True,
                    ownership_revision="alpha_previous",
                ))

            class Answers:
                def choose(self, prompt, choices):
                    raise AssertionError("one installed App must be selected automatically")
                def confirm(self, prompt, *, default=False):
                    assert default is False
                    return True
                def text(self, prompt, *, default):
                    assert default == "empty alpha migration"
                    return "backfill alpha data"

            generated = make_migration(project, Answers())
            assert generated is not None
            source = generated.path.read_text(encoding="utf-8")
            assert "def upgrade() -> None:\\n    pass" in source
            assert "def downgrade() -> None:\\n    pass" in source
                """,
            ),
        )
        self.assertEqual(blank.returncode, 0, blank.stdout + blank.stderr)

    def test_noninteractive_console_stops_when_user_intent_is_required(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class BetaItem(DatabaseModel):
                        __tablename__ = "beta_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha", "beta")),
                """
            import io

            from oldman.db.migrations.interaction import ConsoleMigrationInteraction, MigrationInteractionRequired
            from oldman.db.migrations.revisions import make_migration

            interaction = ConsoleMigrationInteraction(input_stream=io.StringIO(), output_stream=io.StringIO())
            try:
                make_migration(project, interaction)
            except MigrationInteractionRequired as exc:
                assert "interactive terminal" in str(exc)
            else:
                raise AssertionError("noninteractive App choice was accepted")
            assert not tuple((Path.cwd() / "alpha" / "migrations").glob("*.py"))[1:]
            assert not tuple((Path.cwd() / "beta" / "migrations").glob("*.py"))[1:]
                """,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_creates_missing_local_migration_package_and_extends_existing_branch(self) -> None:
        missing = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            _joined(
                _project_source(("alpha",)),
                """
                from oldman.db.migrations.revisions import make_migration

                class Answers:
                    def choose(self, prompt, choices):
                        raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        raise AssertionError
                    def text(self, prompt, *, default):
                        return default

                generated = make_migration(project, Answers())
                assert generated is not None
                assert generated.path.parent == Path.cwd() / "alpha" / "migrations"
                assert (generated.path.parent / "__init__.py").is_file()
                source = generated.path.read_text(encoding="utf-8")
                assert "down_revision: str | Sequence[str] | None = None" in source
                assert "branch_labels: str | Sequence[str] | None = ('alpha',)" in source
                """,
            ),
        )
        self.assertEqual(missing.returncode, 0, missing.stdout + missing.stderr)

        existing = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
                "alpha/migrations/a1_initial.py": '''
                    """Initial alpha state."""
                    revision = "a1"
                    down_revision = None
                    branch_labels = ("alpha",)
                    depends_on = None
                    def upgrade() -> None: pass
                    def downgrade() -> None: pass
                ''',
            },
            _joined(
                _project_source(("alpha",)),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA,
                    MIGRATION_OWNER_TABLE,
                    ALEMBIC_VERSION_TABLE,
                )

                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1,
                        project_id=str(project.project_id),
                        project_name=project.project_name,
                    ))
                    connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="a1"))

                class Answers:
                    def choose(self, prompt, choices):
                        raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        raise AssertionError
                    def text(self, prompt, *, default):
                        return default

                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "down_revision: str | Sequence[str] | None = 'a1'" in source
                assert "branch_labels: str | Sequence[str] | None = None" in source
                """,
            ),
        )
        self.assertEqual(existing.returncode, 0, existing.stdout + existing.stderr)

    def test_rejects_revision_writes_outside_project_or_without_write_permission(self) -> None:
        with tempfile.TemporaryDirectory() as external_directory:
            external_root = Path(external_directory)
            (external_root / "third_party" / "migrations").mkdir(parents=True)
            (external_root / "third_party" / "__init__.py").write_text("", encoding="utf-8")
            (external_root / "third_party" / "apps.py").write_text(textwrap.dedent(_app("third_party")), encoding="utf-8")
            (external_root / "third_party" / "models.py").write_text(
                textwrap.dedent(
                    """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class ThirdPartyItem(DatabaseModel):
                        __tablename__ = "third_party_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                    """
                ),
                encoding="utf-8",
            )
            (external_root / "third_party" / "migrations" / "__init__.py").write_text("", encoding="utf-8")
            outside = _run_project(
                {},
                _joined(
                    _project_source(("third_party",)),
                    """
                from oldman.db.migrations.revisions import MigrationRevisionWriteError, make_migration

                class Answers:
                    def choose(self, prompt, choices):
                        raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        raise AssertionError
                    def text(self, prompt, *, default):
                        return default

                try:
                    make_migration(project, Answers())
                except MigrationRevisionWriteError as exc:
                    assert "outside the current project" in str(exc)
                else:
                    raise AssertionError("third-party migrations were writable")
                    """,
                ),
                python_paths=(external_root,),
            )
            self.assertEqual(outside.returncode, 0, outside.stdout + outside.stderr)

        unwritable = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class AlphaItem(DatabaseModel):
                        __tablename__ = "alpha_item"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "alpha/migrations/__init__.py": "",
            },
            _joined(
                """
            from pathlib import Path
            (Path.cwd() / "alpha" / "migrations").chmod(0o555)
                """,
                _project_source(("alpha",)),
                """
            from oldman.db.migrations.revisions import MigrationRevisionWriteError, make_migration

            class Answers:
                def choose(self, prompt, choices):
                    raise AssertionError
                def confirm(self, prompt, *, default=False):
                    raise AssertionError
                def text(self, prompt, *, default):
                    return default

            try:
                make_migration(project, Answers())
            except MigrationRevisionWriteError as exc:
                assert "not writable" in str(exc)
            else:
                raise AssertionError("read-only migrations were writable")
                """,
            ),
        )
        self.assertEqual(unwritable.returncode, 0, unwritable.stdout + unwritable.stderr)


if __name__ == "__main__":
    unittest.main()
