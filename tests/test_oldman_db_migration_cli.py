"""Public project database CLI contracts."""

from __future__ import annotations

import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.test_oldman_cli_localization import run_cli

PROJECT_ID = "9714d0a3-3f2b-48aa-88d7-c0869b2a6f25"


def _write_files(root: Path, files: dict[str, str]) -> None:
    """Write one isolated CLI project fixture."""
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")


def _project_files(
    database_url: str,
    *,
    with_app: bool = False,
    with_revision: bool = False,
) -> dict[str, str]:
    """Return a minimal cold-discoverable migration project."""
    apps = "[reports]" if with_app else "[]"
    files = {
        "pyproject.toml": f"""
            [project]
            name = "migration-cli-demo"
            version = "0.1.0"

            [tool.oldman]
            project_id = "{PROJECT_ID}"
        """,
        "services/api.py": """
            class Service(WebApplication):
                pass
        """,
        "data/api_settings.yaml": f"""
            apps: {apps}
            database:
              url: {database_url!r}
        """,
    }
    if not with_app:
        return files
    files.update(
        {
            "reports/__init__.py": "",
            "reports/apps.py": """
                from oldman.apps import AppConfig

                class ReportsConfig(AppConfig):
                    label = "reports"
                    display_name = "Reports"

                app = ReportsConfig()
            """,
            "reports/models.py": """
                from sqlalchemy.orm import Mapped, mapped_column
                from oldman.db import DatabaseModel

                class Report(DatabaseModel):
                    __tablename__ = "report"

                    id: Mapped[int] = mapped_column(primary_key=True)
            """,
            "reports/migrations/__init__.py": "",
        }
    )
    if with_revision:
        files["reports/migrations/r1_initial.py"] = '''
            """Create reports."""

            revision = "r1"
            down_revision = None
            branch_labels = ("reports",)
            depends_on = None

            def upgrade() -> None:
                pass

            def downgrade() -> None:
                pass
        '''
    return files


class MigrationCliHelpTests(unittest.TestCase):
    """Expose one small project-level command surface."""

    def test_db_group_exposes_only_the_six_confirmed_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_home = root / ".config"
            group_help = run_cli(root, config_home, "db", "--help")

            self.assertEqual(group_help.returncode, 0, group_help.stderr)
            for command in (
                "makemigrations",
                "migrate",
                "downgrade",
                "retire",
                "status",
                "history",
            ):
                self.assertIn(command, group_help.stdout)
            for command in ("merge", "stamp"):
                self.assertNotIn(command, group_help.stdout)

            for command in (
                "makemigrations",
                "migrate",
                "downgrade",
                "retire",
                "status",
                "history",
            ):
                with self.subTest(command=command):
                    command_help = run_cli(
                        root,
                        config_home,
                        "db",
                        command,
                        "--help",
                    )
                    self.assertEqual(command_help.returncode, 0, command_help.stderr)
                    for option in (
                        "--service",
                        "--config",
                        "--app",
                        "--empty",
                        "--message",
                        "--to",
                    ):
                        self.assertNotIn(option, command_help.stdout)


class MigrationCliReadOnlyTests(unittest.TestCase):
    """Keep history source-only and status strictly read-only."""

    def test_history_works_when_the_configured_database_is_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_files(
                root,
                _project_files(
                    "postgresql+asyncpg://invalid.invalid/unreachable",
                    with_app=True,
                    with_revision=True,
                ),
            )
            completed = run_cli(root, root / ".config", "db", "history")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("reports", completed.stdout)
        self.assertIn("r1", completed.stdout)
        self.assertIn("Create reports", completed.stdout)

    def test_status_does_not_create_or_recover_internal_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database_path = root / "data" / "status.db"
            _write_files(
                root,
                _project_files("sqlite+aiosqlite:///data/status.db"),
            )
            completed = run_cli(root, root / ".config", "db", "status")
            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("not initialized", completed.stdout.lower())
        self.assertEqual(tables, set())


class MigrationCliSafetyTests(unittest.TestCase):
    """Reject missing intent and invalid projects before schema work."""

    def test_non_tty_makemigrations_requires_first_use_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_files(
                root,
                _project_files(
                    "sqlite+aiosqlite:///data/demo.db",
                    with_app=True,
                ),
            )
            completed = run_cli(root, root / ".config", "db", "makemigrations")
            revisions = tuple((root / "reports" / "migrations").glob("*.py"))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("interactive terminal", completed.stderr.lower())
        self.assertEqual(
            tuple(path.name for path in revisions),
            ("__init__.py",),
        )

    def test_conflicting_service_database_urls_fail_before_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            files = _project_files("sqlite+aiosqlite:///data/api.db")
            files.update(
                {
                    "services/web.py": """
                        class Service(WebApplication):
                            pass
                    """,
                    "data/web_settings.yaml": """
                        apps: []
                        database:
                          url: sqlite+aiosqlite:///data/web.db
                    """,
                }
            )
            _write_files(root, files)
            completed = run_cli(root, root / ".config", "db", "status")

            self.assertFalse((root / "data" / "api.db").exists())
            self.assertFalse((root / "data" / "web.db").exists())

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("database", completed.stderr.lower())
        self.assertNotIn("traceback", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
