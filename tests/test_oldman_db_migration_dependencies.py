"""Cross-App foreign-key dependencies and merge revision tests."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.test_oldman_db_makemigrations import _app, _joined, _project_source, _run_project


def _revision(revision: str, down_revision: str | None, branch: str | None = None) -> str:
    """Return one standard graph-only revision."""
    return f"""revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = {(branch,) if branch else None!r}
depends_on = None
def upgrade() -> None: pass
def downgrade() -> None: pass
"""


class MigrationDependencyTests(unittest.TestCase):
    """Derive revision edges only from schema operations that create real FKs."""

    def test_new_cross_app_foreign_key_depends_on_applied_unique_head(self) -> None:
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
                "accounts/migrations/a1_initial.py": _revision("a1", None, "accounts"),
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
            },
            _joined(
                _project_source(("reports", "accounts")),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA, MIGRATION_OWNER_TABLE,
                    ALEMBIC_VERSION_TABLE, SCHEMA_REGISTRY_TABLE,
                )
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE account (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                    connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="a1"))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="account", app_label="accounts", managed=True, ownership_revision="a1",
                    ))
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default
                generated = make_migration(project, Answers())
                source = generated.path.read_text(encoding="utf-8")
                assert "depends_on: str | Sequence[str] | None = 'a1'" in source
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_coinstalled_app_without_new_foreign_key_has_no_dependency(self) -> None:
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
                "accounts/migrations/a1_initial.py": _revision("a1", None, "accounts"),
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
                _project_source(("accounts", "reports")),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA, MIGRATION_OWNER_TABLE,
                    ALEMBIC_VERSION_TABLE, SCHEMA_REGISTRY_TABLE,
                )
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE account (id INTEGER NOT NULL PRIMARY KEY)")
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                    connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="a1"))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert().values(
                        table_name="account", app_label="accounts", managed=True, ownership_revision="a1",
                    ))
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default
                generated = make_migration(project, Answers())
                source = generated.path.read_text(encoding="utf-8")
                assert "depends_on: str | Sequence[str] | None = None" in source
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_dependency_head_remains_applied_when_a_dependent_is_the_only_version_row(self) -> None:
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
                "accounts/migrations/a1.py": _revision("a1", None, "accounts"),
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
                "reports/migrations/r1.py": _revision("r1", None, "reports").replace("depends_on = None", "depends_on = 'a1'"),
                "audit/__init__.py": "",
                "audit/apps.py": _app("audit"),
                "audit/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Audit(DatabaseModel):
                        __tablename__ = "audit"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
                """,
                "audit/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("audit", "reports", "accounts")),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import (
                    INTERNAL_METADATA, MIGRATION_OWNER_TABLE,
                    ALEMBIC_VERSION_TABLE, SCHEMA_REGISTRY_TABLE,
                )
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE account (id INTEGER NOT NULL PRIMARY KEY)")
                    connection.exec_driver_sql(
                        "CREATE TABLE report (id INTEGER NOT NULL PRIMARY KEY, account_id INTEGER NOT NULL, "
                        "FOREIGN KEY(account_id) REFERENCES account(id))"
                    )
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                    connection.execute(ALEMBIC_VERSION_TABLE.insert().values(version_num="r1"))
                    connection.execute(SCHEMA_REGISTRY_TABLE.insert(), [
                        {"table_name": "account", "app_label": "accounts", "managed": True, "ownership_revision": "a1"},
                        {"table_name": "report", "app_label": "reports", "managed": True, "ownership_revision": "r1"},
                    ])
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): return default
                generated = make_migration(project, Answers())
                source = generated.path.read_text(encoding="utf-8")
                assert "depends_on: str | Sequence[str] | None = 'a1'" in source
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_unapplied_referenced_head_is_rejected_before_generation(self) -> None:
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
                "accounts/migrations/a1_initial.py": _revision("a1", None, "accounts"),
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
            },
            _joined(
                _project_source(("reports", "accounts")),
                """
                from sqlalchemy import create_engine
                from oldman.db.migrations.autogenerate import MigrationRevisionStateError
                from oldman.db.migrations.revisions import make_migration
                from oldman.db.migrations.state import INTERNAL_METADATA, MIGRATION_OWNER_TABLE
                engine = create_engine(f"sqlite:///{database_path}")
                with engine.begin() as connection:
                    INTERNAL_METADATA.create_all(connection)
                    connection.execute(MIGRATION_OWNER_TABLE.insert().values(
                        singleton_id=1, project_id=str(project.project_id), project_name=project.project_name,
                    ))
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                try:
                    make_migration(project, Answers())
                except MigrationRevisionStateError as exc:
                    assert "migrate" in str(exc)
                else:
                    raise AssertionError("unapplied source head was accepted")
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_missing_referenced_head_and_two_new_apps_are_rejected(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Alpha(DatabaseModel):
                        __tablename__ = "alpha"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        beta_id: Mapped[int] = mapped_column(ForeignKey("beta.id"))
                """,
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/models.py": """
                    from sqlalchemy import ForeignKey
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db import DatabaseModel
                    class Beta(DatabaseModel):
                        __tablename__ = "beta"
                        id: Mapped[int] = mapped_column(primary_key=True)
                        alpha_id: Mapped[int] = mapped_column(ForeignKey("alpha.id"))
                """,
                "beta/migrations/__init__.py": "",
            },
            _joined(
                _project_source(("alpha", "beta")),
                """
                from oldman.db.migrations.autogenerate import MigrationDependencyError
                from oldman.db.migrations.revisions import make_migration
                class Answers:
                    def choose(self, prompt, choices): return "alpha"
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                try:
                    make_migration(project, Answers())
                except MigrationDependencyError as exc:
                    assert "beta" in str(exc) and "head" in str(exc)
                else:
                    raise AssertionError("cross-App FK without a referenced head was accepted")
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_multiple_heads_generate_one_local_merge_revision_and_stop(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision("r1", None, "reports"),
                "reports/migrations/r2.py": _revision("r2", "r1"),
                "reports/migrations/r3.py": _revision("r3", "r1"),
            },
            _joined(
                _project_source(("reports",)),
                """
                from oldman.db.migrations.revisions import make_migration
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False):
                        assert "r2" in prompt and "r3" in prompt
                        return True
                    def text(self, prompt, *, default):
                        assert default == "merge reports heads"
                        return default
                generated = make_migration(project, Answers())
                assert generated is not None
                source = generated.path.read_text(encoding="utf-8")
                assert "down_revision: str | Sequence[str] | None = ('r2', 'r3')" in source
                assert "def upgrade() -> None:\\n    pass" in source
                assert not database_path.exists()
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_noninteractive_input_never_merges_multiple_heads(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/migrations/__init__.py": "",
                "reports/migrations/r1.py": _revision("r1", None, "reports"),
                "reports/migrations/r2.py": _revision("r2", "r1"),
                "reports/migrations/r3.py": _revision("r3", "r1"),
            },
            _joined(
                _project_source(("reports",)),
                """
                import io
                from oldman.db.migrations.interaction import (
                    ConsoleMigrationInteraction, MigrationInteractionRequired,
                )
                from oldman.db.migrations.revisions import make_migration
                interaction = ConsoleMigrationInteraction(
                    input_stream=io.StringIO(), output_stream=io.StringIO(),
                )
                try:
                    make_migration(project, interaction)
                except MigrationInteractionRequired:
                    pass
                else:
                    raise AssertionError("noninteractive input merged migration heads")
                assert len(tuple((Path.cwd() / "reports" / "migrations").glob("*.py"))) == 4
                assert not database_path.exists()
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_revision_dependency_cycle_is_rejected(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/migrations/__init__.py": "",
                "alpha/migrations/a1.py": _revision("a1", None, "alpha").replace("depends_on = None", "depends_on = 'b1'"),
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/migrations/__init__.py": "",
                "beta/migrations/b1.py": _revision("b1", None, "beta").replace("depends_on = None", "depends_on = 'a1'"),
            },
            _joined(
                _project_source(("alpha", "beta")),
                """
                from oldman.db.migrations.alembic import MigrationGraphError
                from oldman.db.migrations.revisions import make_migration
                class Answers:
                    def choose(self, prompt, choices): raise AssertionError
                    def confirm(self, prompt, *, default=False): raise AssertionError
                    def text(self, prompt, *, default): raise AssertionError
                try:
                    make_migration(project, Answers())
                except MigrationGraphError as exc:
                    assert "cycle" in str(exc).casefold()
                else:
                    raise AssertionError("revision dependency cycle was accepted")
                """,
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_third_party_multiple_heads_cannot_be_merged_by_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as external_directory:
            root = Path(external_directory)
            files = {
                "vendor/__init__.py": "",
                "vendor/apps.py": _app("vendor"),
                "vendor/migrations/__init__.py": "",
                "vendor/migrations/v1.py": _revision("v1", None, "vendor"),
                "vendor/migrations/v2.py": _revision("v2", "v1"),
                "vendor/migrations/v3.py": _revision("v3", "v1"),
            }
            for relative, source in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(source), encoding="utf-8")
            completed = _run_project(
                {},
                _joined(
                    _project_source(("vendor",)),
                    """
                    from oldman.db.migrations.revisions import MigrationRevisionWriteError, make_migration
                    class Answers:
                        def choose(self, prompt, choices): raise AssertionError
                        def confirm(self, prompt, *, default=False): return True
                        def text(self, prompt, *, default): return default
                    try:
                        make_migration(project, Answers())
                    except MigrationRevisionWriteError as exc:
                        assert "outside the current project" in str(exc)
                        assert "upgrade" in str(exc).casefold()
                    else:
                        raise AssertionError("consumer merged third-party heads")
                    """,
                ),
                python_paths=(root,),
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
