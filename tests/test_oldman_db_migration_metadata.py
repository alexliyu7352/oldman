"""Migration metadata ownership and managed-table tests."""

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


def _run_project(files: dict[str, str], source: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated SQLAlchemy metadata scenario."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        python_paths = [str(REPOSITORY_ROOT)]
        if existing_path := environment.get("PYTHONPATH"):
            python_paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )


def _app(label: str) -> str:
    """Return minimal App metadata for a model-owning fixture package."""
    return f"""
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = {label!r}
            display_name = {label.replace('_', ' ').title()!r}

        app = Config()
    """


def _project_source(packages: tuple[str, ...], *, user_model_path: str | None = None) -> str:
    """Return source that builds an in-memory MigrationProject fixture."""
    return textwrap.dedent(f"""
        from pathlib import Path
        from uuid import UUID

        from oldman.apps import AppRegistry
        from oldman.db.migrations import MigrationProject

        registry = AppRegistry()
        registry.register_packages({packages!r})
        project = MigrationProject(
            project_root=Path.cwd(),
            project_id=UUID({PROJECT_ID!r}),
            project_name="metadata-demo",
            database_url="sqlite+aiosqlite:///metadata.db",
            service_configs=(),
            apps=registry,
            user_model_path={user_model_path!r},
        )
    """)


class MigrationMetadataOwnershipTests(unittest.TestCase):
    """Resolve model and table owners from real definition modules."""

    def test_models_and_standalone_tables_keep_real_app_owners(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import Column, ForeignKey, Integer, Table
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import Base, DatabaseModel

                    alpha_tags = Table(
                        "migration_alpha_tags",
                        Base.metadata,
                        Column("alpha_id", ForeignKey("migration_alpha.id"), primary_key=True),
                        Column("tag_id", Integer, primary_key=True),
                    )

                    class Record(DatabaseModel):
                        __tablename__ = "migration_alpha"

                        id: Mapped[int] = mapped_column(primary_key=True)

                    class Auxiliary(DatabaseModel):
                        __tablename__ = "migration_alpha_auxiliary"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from alpha.models import Record as AlphaRecord
                    from oldman.db import DatabaseModel

                    class Record(DatabaseModel):
                        __tablename__ = "migration_beta"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            _project_source(("beta", "alpha"))
            + textwrap.dedent("""
            from oldman.db import Base
            from oldman.db.migrations.metadata import load_migration_metadata

            migration = load_migration_metadata(project)
            from alpha.models import Auxiliary, Record as AlphaRecord
            from beta.models import Record as BetaRecord

            assert migration.metadata is Base.metadata
            assert migration.models[AlphaRecord].app_label == "alpha"
            assert migration.models[BetaRecord].app_label == "beta"
            assert migration.models[Auxiliary].app_label == "alpha"
            assert migration.tables[Base.metadata.tables["migration_alpha"]].app_label == "alpha"
            assert migration.tables[Base.metadata.tables["migration_alpha_auxiliary"]].app_label == "alpha"
            association = migration.tables[Base.metadata.tables["migration_alpha_tags"]]
            assert association.app_label == "alpha"
            assert association.managed is True
            assert tuple(table.name for table in migration.metadata.sorted_tables) == (
                "migration_alpha",
                "migration_alpha_auxiliary",
                "migration_beta",
                "migration_alpha_tags",
            )
            """),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_managed_false_is_recorded_but_excluded_from_managed_tables(self) -> None:
        completed = _run_project(
            {
                "external_app/__init__.py": "",
                "external_app/apps.py": _app("external_app"),
                "external_app/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class ManagedRecord(DatabaseModel):
                        __tablename__ = "migration_managed_record"

                        id: Mapped[int] = mapped_column(primary_key=True)

                    class ExternalRecord(DatabaseModel):
                        __tablename__ = "migration_external_record"
                        __table_args__ = {"schema": "external"}

                        id: Mapped[int] = mapped_column(primary_key=True)

                        class Meta:
                            managed = False
                """,
            },
            _project_source(("external_app",))
            + textwrap.dedent("""
            from oldman.db.migrations.metadata import load_migration_metadata
            from external_app.models import ExternalRecord, ManagedRecord

            migration = load_migration_metadata(project)
            assert migration.models[ExternalRecord].managed is False
            assert migration.tables[ExternalRecord.__table__].managed is False
            assert migration.tables[ManagedRecord.__table__].managed is True
            assert migration.managed_tables == (ManagedRecord.__table__,)
            """),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_managed_table_cannot_use_an_explicit_schema(self) -> None:
        completed = _run_project(
            {
                "schema_app/__init__.py": "",
                "schema_app/apps.py": _app("schema_app"),
                "schema_app/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class ScopedRecord(DatabaseModel):
                        __tablename__ = "migration_scoped_record"
                        __table_args__ = {"schema": "tenant"}

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            _project_source(("schema_app",))
            + textwrap.dedent("""
            from oldman.db.migrations.metadata import load_migration_metadata

            try:
                load_migration_metadata(project)
            except ValueError as exc:
                assert "migration_scoped_record" in str(exc), str(exc)
                assert "schema" in str(exc).lower(), str(exc)
            else:
                raise AssertionError("managed schema-qualified table was accepted")
            """),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_standalone_table_owner_must_match_its_real_model_module(self) -> None:
        completed = _run_project(
            {
                "owner_app/__init__.py": "",
                "owner_app/apps.py": _app("owner_app"),
                "owner_app/models.py": """
                    from sqlalchemy import Column, Integer, Table

                    from oldman.db import Base

                    association = Table(
                        "migration_owner_conflict",
                        Base.metadata,
                        Column("id", Integer, primary_key=True),
                        info={"oldman_app_label": "different_app"},
                    )
                """,
                "different_app/__init__.py": "",
                "different_app/apps.py": _app("different_app"),
            },
            _project_source(("owner_app", "different_app"))
            + textwrap.dedent("""
            from oldman.db.migrations.metadata import load_migration_metadata

            try:
                load_migration_metadata(project)
            except RuntimeError as exc:
                assert "migration_owner_conflict" in str(exc), str(exc)
                assert "different_app" in str(exc), str(exc)
                assert "owner_app" in str(exc), str(exc)
            else:
                raise AssertionError("conflicting standalone Table owner was accepted")
            """),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unregistered_models_and_unbound_tables_are_rejected(self) -> None:
        cases = {
            "mapper": {
                "rogue.py": """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel

                    class Rogue(DatabaseModel):
                        __tablename__ = "migration_rogue_model"
                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
            },
            "table": {
                "rogue.py": """
                    from sqlalchemy import Column, Integer, Table
                    from oldman.db import Base

                    rogue = Table(
                        "migration_rogue_table",
                        Base.metadata,
                        Column("id", Integer, primary_key=True),
                    )
                """,
            },
        }
        for name, extra_files in cases.items():
            with self.subTest(name=name):
                completed = _run_project(
                    {
                        "empty_app/__init__.py": "",
                        "empty_app/apps.py": _app("empty_app"),
                        **extra_files,
                    },
                    "import rogue\n"
                    + _project_source(("empty_app",))
                    + textwrap.dedent("""
                    from oldman.db.migrations.metadata import load_migration_metadata

                    try:
                        load_migration_metadata(project)
                    except RuntimeError as exc:
                        assert "rogue" in str(exc).lower(), str(exc)
                    else:
                        raise AssertionError("unowned SQLAlchemy state was accepted")
                    """),
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_framework_internal_table_names_are_reserved(self) -> None:
        for table_name in (
            "oldman_migration_owner",
            "oldman_alembic_version",
            "oldman_schema_registry",
        ):
            with self.subTest(table_name=table_name):
                completed = _run_project(
                    {
                        "reserved_app/__init__.py": "",
                        "reserved_app/apps.py": _app("reserved_app"),
                        "reserved_app/models.py": f"""
                            from sqlalchemy.orm import Mapped, mapped_column
                            from oldman.db import DatabaseModel

                            class Reserved(DatabaseModel):
                                __tablename__ = {table_name!r}
                                id: Mapped[int] = mapped_column(primary_key=True)
                        """,
                    },
                    _project_source(("reserved_app",))
                    + textwrap.dedent(f"""
                    from oldman.db.migrations.metadata import load_migration_metadata

                    try:
                        load_migration_metadata(project)
                    except ValueError as exc:
                        assert {table_name!r} in str(exc), str(exc)
                        assert "reserved" in str(exc).lower(), str(exc)
                    else:
                        raise AssertionError("reserved internal table name was accepted")
                    """),
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class MigrationUserMetadataTests(unittest.TestCase):
    """Keep Auth's table owner separate from a custom User extension owner."""

    def test_custom_user_records_core_and_extension_ownership_without_binding_settings(self) -> None:
        completed = _run_project(
            {
                "accounts/__init__.py": "",
                "accounts/apps.py": _app("accounts"),
                "accounts/models.py": """
                    from sqlalchemy import String, UniqueConstraint
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.auth import AbstractUser

                    class ProjectUser(AbstractUser):
                        phone: Mapped[str | None] = mapped_column(String(32), index=True)

                        __table_args__ = (
                            UniqueConstraint("phone", name="uq_oldman_user_phone"),
                        )
                """,
            },
            _project_source(("oldman.auth", "accounts"), user_model_path="accounts.models.ProjectUser")
            + textwrap.dedent("""
            from oldman.auth.apps import app as auth_app
            from oldman.apps import AppSettingsNotReadyError
            from oldman.db.migrations.metadata import load_migration_metadata

            migration = load_migration_metadata(project)
            from accounts.models import ProjectUser

            user = migration.user
            assert user is not None
            assert user.model is ProjectUser
            assert user.table is ProjectUser.__table__
            assert migration.models[ProjectUser].app_label == "accounts"
            assert migration.tables[ProjectUser.__table__].app_label == "auth"
            assert user.app_label == "accounts"
            assert "id" in user.core.column_names
            assert "username" in user.core.column_names
            assert "phone" not in user.core.column_names
            assert user.core.primary_key_column_names == ("id",)
            assert "ix_oldman_user_username" in user.core.index_names
            assert "ix_oldman_user_phone" not in user.core.index_names
            assert "ck_oldman_user_superuser_is_staff" in user.core.check_constraint_names
            assert ("email",) in user.core.unique_column_sets
            assert ("phone",) not in user.core.unique_column_sets
            try:
                _ = auth_app.settings
            except AppSettingsNotReadyError:
                pass
            else:
                raise AssertionError("migration metadata bound runtime Auth settings")
            """),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
