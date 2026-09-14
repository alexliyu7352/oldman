"""Programmatic Alembic configuration and App branch graph tests."""

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
    """Run one isolated Alembic graph scenario."""
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
    """Return minimal App metadata with the default migrations module."""
    return f"""
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = {label!r}
            display_name = {label.replace('_', ' ').title()!r}

        app = Config()
    """


def _revision(
    revision: str,
    *,
    down_revision: str | tuple[str, ...] | None,
    branch_labels: tuple[str, ...] | None = None,
    depends_on: str | tuple[str, ...] | None = None,
) -> str:
    """Render a standard importable Alembic revision fixture."""
    return f'''"""Revision {revision}."""

revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = {branch_labels!r}
depends_on = {depends_on!r}

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
'''


def _project_source(packages: tuple[str, ...]) -> str:
    """Build a MigrationProject without loading a service or database."""
    return textwrap.dedent(
        f"""
        from pathlib import Path
        from uuid import UUID

        from oldman.apps import AppRegistry
        from oldman.db.migrations import MigrationProject

        registry = AppRegistry()
        registry.register_packages({packages!r})
        project = MigrationProject(
            project_root=Path.cwd(),
            project_id=UUID({PROJECT_ID!r}),
            project_name="graph-demo",
            database_url="sqlite+aiosqlite:///graph.db",
            service_configs=(),
            apps=registry,
            user_model_path=None,
        )
        """
    )


class AlembicAppGraphTests(unittest.TestCase):
    """Keep each App's standard revisions in one independent branch."""

    def test_programmatic_environment_runs_autogenerate_with_async_sqlite(self) -> None:
        completed = _run_project(
            {
                "reports/__init__.py": "",
                "reports/apps.py": _app("reports"),
                "reports/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel

                    class Report(DatabaseModel):
                        __tablename__ = "migration_report"

                        id: Mapped[int] = mapped_column(primary_key=True)
                """,
                "reports/migrations/__init__.py": "",
            },
            _project_source(("reports",)).replace(
                'database_url="sqlite+aiosqlite:///graph.db"',
                'database_url=f"sqlite+aiosqlite:///{Path.cwd() / \'graph.db\'}"',
            )
            + textwrap.dedent(
                """
                from alembic import command

                from oldman.db.migrations.alembic import build_alembic_config, load_migration_graph

                config = build_alembic_config(project)
                location = Path.cwd() / "reports" / "migrations"
                generated = command.revision(
                    config,
                    message="initial reports",
                    autogenerate=True,
                    head="base",
                    branch_label="reports",
                    version_path=str(location),
                )
                assert generated is not None
                source = Path(generated.path).read_text(encoding="utf-8")
                assert "op.create_table(" in source
                assert "migration_report" in source
                assert "Review upgrade() and downgrade()" in source

                graph = load_migration_graph(project, config=build_alembic_config(project))
                assert len(graph.branches["reports"].revisions) == 1
                assert graph.branches["reports"].heads[0].revision == generated.revision
                """
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_builds_programmatic_config_and_multiple_app_branches(self) -> None:
        completed = _run_project(
            {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/migrations/__init__.py": "",
                "alpha/migrations/a1_initial.py": _revision("a1", down_revision=None, branch_labels=("alpha",)),
                "alpha/migrations/a2_more.py": _revision("a2", down_revision="a1"),
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/migrations/__init__.py": "",
                "beta/migrations/b1_initial.py": _revision("b1", down_revision=None, branch_labels=("beta",), depends_on="a1"),
            },
            _project_source(("beta", "alpha"))
            + textwrap.dedent(
                """
                from pathlib import Path

                from oldman.db.migrations.alembic import (
                    build_alembic_config,
                    load_migration_graph,
                )

                config = build_alembic_config(project)
                assert config.config_file_name is None
                assert config.get_main_option("version_table") == "oldman_alembic_version"
                assert config.get_main_option("sqlalchemy.url") == project.database_url
                assert Path(config.get_main_option("script_location")).name == "templates"
                assert config.attributes["oldman_project"] is project
                assert config.attributes["oldman_metadata"].metadata is not None

                graph = load_migration_graph(project, config=config)
                assert set(graph.branches) == {"alpha", "beta"}
                assert tuple(item.revision for item in graph.branches["alpha"].revisions) == ("a1", "a2")
                assert tuple(item.revision for item in graph.branches["alpha"].heads) == ("a2",)
                assert tuple(item.revision for item in graph.branches["beta"].revisions) == ("b1",)
                assert tuple(item.revision for item in graph.branches["beta"].heads) == ("b1",)
                assert graph.branches["alpha"].location.path == Path.cwd() / "alpha" / "migrations"
                assert graph.script_directory.get_revision("alpha@head").revision == "a2"
                assert graph.script_directory.get_revision("beta@head").revision == "b1"
                """
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_empty_missing_and_read_only_locations_remain_readable(self) -> None:
        completed = _run_project(
            {
                "empty_app/__init__.py": "",
                "empty_app/apps.py": _app("empty_app"),
                "empty_app/migrations/__init__.py": "",
                "missing_app/__init__.py": "",
                "missing_app/apps.py": _app("missing_app"),
                "third_party/__init__.py": "",
                "third_party/apps.py": _app("third_party"),
                "third_party/migrations/__init__.py": "",
                "third_party/migrations/t1_initial.py": _revision("t1", down_revision=None, branch_labels=("third_party",)),
            },
            textwrap.dedent(
                """
                from pathlib import Path

                path = Path.cwd() / "third_party" / "migrations"
                path.chmod(0o555)
                """
            )
            + _project_source(("empty_app", "missing_app", "third_party"))
            + textwrap.dedent(
                """
                from oldman.db.migrations.alembic import load_migration_graph

                graph = load_migration_graph(project)
                assert graph.branches["empty_app"].revisions == ()
                assert graph.branches["missing_app"].revisions == ()
                assert graph.branches["missing_app"].location.exists is False
                assert graph.branches["third_party"].heads[0].revision == "t1"
                """
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        missing_only = _run_project(
            {
                "missing_only/__init__.py": "",
                "missing_only/apps.py": _app("missing_only"),
            },
            _project_source(("missing_only",))
            + textwrap.dedent(
                """
                from oldman.db.migrations.alembic import load_migration_graph

                graph = load_migration_graph(project)
                assert graph.branches["missing_only"].revisions == ()
                assert graph.branches["missing_only"].location.exists is False
                """
            ),
        )
        self.assertEqual(missing_only.returncode, 0, missing_only.stdout + missing_only.stderr)

    def test_reports_multiple_heads_without_using_app_order(self) -> None:
        files = {
            "alpha/__init__.py": "",
            "alpha/apps.py": _app("alpha"),
            "alpha/migrations/__init__.py": "",
            "alpha/migrations/a1_initial.py": _revision("a1", down_revision=None, branch_labels=("alpha",)),
            "alpha/migrations/a2_left.py": _revision("a2", down_revision="a1"),
            "alpha/migrations/a3_right.py": _revision("a3", down_revision="a1"),
            "beta/__init__.py": "",
            "beta/apps.py": _app("beta"),
            "beta/migrations/__init__.py": "",
            "beta/migrations/b1_initial.py": _revision("b1", down_revision=None, branch_labels=("beta",)),
        }
        outputs = []
        for packages in (("alpha", "beta"), ("beta", "alpha")):
            completed = _run_project(
                files,
                _project_source(packages)
                + textwrap.dedent(
                    """
                    from oldman.db.migrations.alembic import load_migration_graph

                    graph = load_migration_graph(project)
                    for label in sorted(graph.branches):
                        heads = ",".join(sorted(item.revision for item in graph.branches[label].heads))
                        print(f"{label}:{heads}")
                    """
                ),
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            outputs.append(completed.stdout)

        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("alpha:a2,a3", outputs[0])

    def test_rejects_duplicate_revision_ids_and_branch_labels(self) -> None:
        cases = {
            "revision": {
                "alpha/migrations/a1.py": _revision("same", down_revision=None, branch_labels=("alpha",)),
                "beta/migrations/b1.py": _revision("same", down_revision=None, branch_labels=("beta",)),
            },
            "branch": {
                "alpha/migrations/a1.py": _revision("a1", down_revision=None, branch_labels=("alpha",)),
                "beta/migrations/b1.py": _revision("b1", down_revision=None, branch_labels=("alpha",)),
            },
        }
        for name, revisions in cases.items():
            files = {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/migrations/__init__.py": "",
                **revisions,
            }
            with self.subTest(name=name):
                completed = _run_project(
                    files,
                    _project_source(("alpha", "beta"))
                    + textwrap.dedent(
                        """
                        from oldman.db.migrations.alembic import MigrationGraphError, load_migration_graph

                        try:
                            load_migration_graph(project)
                        except MigrationGraphError as exc:
                            assert "revision" in str(exc).lower() or "branch" in str(exc).lower(), str(exc)
                        else:
                            raise AssertionError("invalid Alembic graph was accepted")
                        """
                    ),
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_rejects_wrong_base_labels_repeated_labels_and_cross_app_down_revision(self) -> None:
        cases = {
            "wrong_base": {
                "alpha/migrations/a1.py": _revision("a1", down_revision=None, branch_labels=("wrong",)),
            },
            "repeated_label": {
                "alpha/migrations/a1.py": _revision("a1", down_revision=None, branch_labels=("alpha",)),
                "alpha/migrations/a2.py": _revision("a2", down_revision="a1", branch_labels=("alpha",)),
            },
            "cross_app_down": {
                "alpha/migrations/a1.py": _revision("a1", down_revision=None, branch_labels=("alpha",)),
                "beta/migrations/b1.py": _revision("b1", down_revision="a1", branch_labels=("beta",)),
            },
        }
        for name, revisions in cases.items():
            files = {
                "alpha/__init__.py": "",
                "alpha/apps.py": _app("alpha"),
                "alpha/migrations/__init__.py": "",
                "beta/__init__.py": "",
                "beta/apps.py": _app("beta"),
                "beta/migrations/__init__.py": "",
                **revisions,
            }
            with self.subTest(name=name):
                completed = _run_project(
                    files,
                    _project_source(("alpha", "beta"))
                    + textwrap.dedent(
                        """
                        from oldman.db.migrations.alembic import MigrationGraphError, load_migration_graph

                        try:
                            load_migration_graph(project)
                        except MigrationGraphError:
                            pass
                        else:
                            raise AssertionError("invalid App branch was accepted")
                        """
                    ),
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
