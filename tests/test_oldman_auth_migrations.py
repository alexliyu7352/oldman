"""Installed Auth migration structure and empty-database execution contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_auth_scenario(
    source: str,
    *,
    files: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated Auth registry and migration scenario."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        fixture_root = Path(temporary_directory)
        for relative_path, content in (files or {}).items():
            path = fixture_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content), encoding="utf-8")

        environment = os.environ.copy()
        python_paths = [str(fixture_root), str(ROOT)]
        if existing_path := environment.get("PYTHONPATH"):
            python_paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        environment["OLDMAN_AUTH_TEST_DATABASE"] = str(fixture_root / "auth-migration.db")
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )


def migration_project_source(
    packages: tuple[str, ...],
    *,
    user_model_path: str,
) -> str:
    """Build a real Auth migration project in a fresh interpreter."""
    return f"""
        import os
        from pathlib import Path
        from uuid import UUID

        from oldman.apps import AppRegistry
        from oldman.auth.settings import AuthSettings
        from oldman.db.migrations import MigrationProject

        registry = AppRegistry()
        registry.register_packages({packages!r})
        registry.bind_settings(
            "auth",
            AuthSettings(user_model={user_model_path!r}),
        )
        database_path = Path(os.environ["OLDMAN_AUTH_TEST_DATABASE"])
        project = MigrationProject(
            project_root=Path.cwd(),
            project_id=UUID("9714d0a3-3f2b-48aa-88d7-c0869b2a6f25"),
            project_name="oldman-auth-test",
            database_url=f"sqlite+aiosqlite:///{{database_path}}",
            service_configs=(),
            apps=registry,
            user_model_path={user_model_path!r},
        )
    """


def joined(*sources: str) -> str:
    """Dedent independently authored source fragments before joining them."""
    return "".join(textwrap.dedent(source) for source in sources)


class AuthMigrationTests(unittest.TestCase):
    """Ship one replayable Auth branch containing only the fixed User schema."""

    def test_empty_database_upgrade_and_downgrade_preserve_auth_contract(self) -> None:
        """The framework migration owns, creates, and removes ``oldman_user``."""
        completed = run_auth_scenario(
            joined(
                migration_project_source(
                    ("oldman.auth",),
                    user_model_path="oldman.auth.models.User",
                ),
                """
            from sqlalchemy import create_engine, inspect, text

            from oldman.db.migrations.alembic import load_migration_graph
            from oldman.db.migrations.commands import downgrade, migrate
            from oldman.db.migrations.state import MigrationState

            graph = load_migration_graph(project)
            branch = graph.branches["auth"]
            assert len(branch.revisions) == 1
            revision = branch.revisions[0]
            assert revision.down_revision is None
            assert tuple(revision.branch_labels) == ("auth",)
            assert revision.dependencies is None

            class MigrateAnswers:
                is_interactive = False

                def choose(self, prompt, choices):
                    assert "internal migration state" in prompt
                    assert choices == ("first use", "state lost", "cancel")
                    return "first use"

                def confirm(self, prompt, *, default=False):
                    raise AssertionError(prompt)

                def text(self, prompt, *, default):
                    raise AssertionError(prompt)

            result = migrate(project, MigrateAnswers())
            assert result.applied_revisions == (revision.revision,)

            engine = create_engine(f"sqlite:///{database_path}")
            inspector = inspect(engine)
            columns = {item["name"]: item for item in inspector.get_columns("oldman_user")}
            assert tuple(columns) == (
                "id",
                "username",
                "email",
                "password_hash",
                "display_name",
                "is_active",
                "is_staff",
                "is_superuser",
                "last_login_at",
                "created_at",
                "updated_at",
            )
            assert inspector.get_pk_constraint("oldman_user")["constrained_columns"] == ["id"]
            indexes = {item["name"]: item for item in inspector.get_indexes("oldman_user")}
            assert {
                "ix_oldman_user_username",
                "ix_oldman_user_is_active",
                "ix_oldman_user_is_staff",
                "ix_oldman_user_is_superuser",
            }.issubset(indexes)
            unique_columns = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("oldman_user")
            }
            assert ("email",) in unique_columns
            checks = {item["name"] for item in inspector.get_check_constraints("oldman_user")}
            assert "ck_oldman_user_superuser_is_staff" in checks

            with engine.begin() as connection:
                for username in ("first", "second"):
                    connection.execute(
                        text(
                            "INSERT INTO oldman_user "
                            "(username, password_hash, is_active, is_staff, is_superuser) "
                            "VALUES (:username, 'hash', TRUE, FALSE, FALSE)"
                        ),
                        {"username": username},
                    )
                assert connection.execute(
                    text("SELECT id FROM oldman_user ORDER BY id")
                ).scalars().all() == [1, 2]
                state = MigrationState.inspect(connection)
                ownership = state.schema_registry["oldman_user"]
                assert ownership.app_label == "auth"
                assert ownership.managed is True
                assert ownership.ownership_revision == revision.revision

            class DowngradeAnswers:
                entered = iter(("auth", "base"))

                def choose(self, prompt, choices):
                    return "auth" if "applied App" in prompt else "base"

                def confirm(self, prompt, *, default=False):
                    raise AssertionError(prompt)

                def text(self, prompt, *, default):
                    raise AssertionError(prompt)

                def enter(self, prompt):
                    return next(self.entered)

            downgraded = downgrade(project, DowngradeAnswers())
            assert downgraded is not None
            assert downgraded.target_revision == "base"
            assert "oldman_user" not in inspect(engine).get_table_names()
            with engine.connect() as connection:
                state = MigrationState.inspect(connection)
            assert state.revisions == ()
            assert state.schema_registry == {}
            """,
            )
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_custom_user_metadata_does_not_change_the_auth_revision(self) -> None:
        """Project User extensions remain outside the framework-owned revision."""
        completed = run_auth_scenario(
            joined(
                migration_project_source(
                    ("oldman.auth", "accounts"),
                    user_model_path="accounts.models.User",
            ),
            """
            import ast

            from oldman.db.migrations.alembic import load_migration_graph
            from oldman.db.migrations.metadata import load_migration_metadata

            metadata = load_migration_metadata(project)
            assert metadata.user is not None
            assert "phone" in metadata.user.table.c

            auth_revision = load_migration_graph(project).branches["auth"].revisions[0]
            source = Path(auth_revision.path).read_text(encoding="utf-8")
            tree = ast.parse(source)
            created_tables = [
                call.args[0].value
                for call in ast.walk(tree)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "create_table"
                and call.args
                and isinstance(call.args[0], ast.Constant)
            ]
            assert created_tables == ["oldman_user"]
            assert "phone" not in source
            """,
            ),
            files={
                "accounts/__init__.py": "",
                "accounts/apps.py": """
                    from oldman.apps import AppConfig

                    class AccountsConfig(AppConfig):
                        label = "accounts"
                        display_name = "Accounts"

                    app = AccountsConfig()
                """,
                "accounts/models.py": """
                    from sqlalchemy import String
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.auth import AbstractUser

                    class User(AbstractUser):
                        phone: Mapped[str | None] = mapped_column(String(32), index=True)
                """,
            },
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
