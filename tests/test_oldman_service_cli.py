"""Service-scoped CLI assembly and cold-import contracts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from ruamel.yaml import YAML

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, source: str) -> None:
    """Write one dedented project fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def _write_catalog(
    path: Path,
    locale: str,
    messages: dict[str, str],
) -> None:
    """Compile one small real gettext catalog for a project fixture."""
    catalog = Catalog(locale=locale)
    for message_id, translation in messages.items():
        catalog.add(message_id, translation)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        write_mo(stream, catalog)


def _create_project(root: Path, *, worker_settings: bool = True) -> Path:
    """Create a project with one Simple and one Web service."""
    marker = root / "service-imports.txt"
    _write(
        root / "pyproject.toml",
        "[project]\nname = 'service-cli-fixture'\nversion = '0'\n",
    )
    _write(root / "config/__init__.py", "")
    _write(
        root / "config/schemas.py",
        """
        from oldman.conf import DefaultSettings

        class Settings(DefaultSettings):
            pass
        """,
    )
    _write(
        root / "config/settings.py",
        """
        from typing import cast

        import oldman.conf as conf
        from config.schemas import Settings

        settings = cast(Settings, conf.settings)
        """,
    )
    _write(root / "services/__init__.py", "")
    _write(
        root / "services/worker.py",
        """
        import os
        from pathlib import Path

        from config.settings import settings
        from oldman.runtime import SimpleApplication

        Path(os.environ["OLDMAN_SERVICE_IMPORT_MARKER"]).open(
            "a", encoding="utf-8"
        ).write("worker\\n")

        class WorkerService(SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self) -> None:
                pass
        """,
    )
    _write(
        root / "services/music_web.py",
        """
        import os
        from pathlib import Path

        from config.settings import settings
        from oldman.runtime import WebApplication

        Path(os.environ["OLDMAN_SERVICE_IMPORT_MARKER"]).open(
            "a", encoding="utf-8"
        ).write("music_web\\n")

        class MusicWebService(WebApplication):
            def prepare_server(self, app) -> None:
                pass
        """,
    )
    _write(root / "theme_app/__init__.py", "")
    _write(
        root / "theme_app/apps.py",
        """
        from oldman.apps import AppConfig

        class ThemeAppConfig(AppConfig):
            label = "theme"
            display_name = "Theme"

        app = ThemeAppConfig()
        """,
    )
    _write(root / "theme_app/static/theme/brand.txt", "theme-asset")
    _write(root / "worker_tools/__init__.py", "")
    _write(
        root / "worker_tools/apps.py",
        """
        from oldman.apps import AppConfig
        from oldman.i18n import gettext_lazy as _

        class WorkerToolsConfig(AppConfig):
            label = "worker_tools"
            display_name = _("Worker tools")

        app = WorkerToolsConfig()
        """,
    )
    _write(
        root / "worker_tools/commands.py",
        """
        from config.settings import settings
        from oldman.cli import Command
        from oldman.i18n import gettext_lazy as _

        class ProbeCommand(Command):
            name = "probe"
            help = _("Run the worker probe.")

            async def handle(
                self,
                value: str,
                repeat: int = 1,
                uppercase: bool = False,
            ) -> str:
                output = f"{settings.core.app_name}:" + "|".join(
                    [value] * repeat
                )
                return output.upper() if uppercase else output
        """,
    )
    _write(
        root / "worker_tools/models.py",
        """
        from sqlalchemy import Integer, String
        from sqlalchemy.orm import Mapped, mapped_column

        from oldman.db import DatabaseModel

        class FixtureItem(DatabaseModel):
            __tablename__ = "fixture_item"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            name: Mapped[str] = mapped_column(String(100))
        """,
    )
    _write_catalog(
        root
        / "worker_tools/locales/zh_Hans/LC_MESSAGES/messages.mo",
        "zh_Hans",
        {
            "Worker tools": "工作工具",
            "Run the worker probe.": "运行工作探针。",
        },
    )
    if worker_settings:
        _write(
            root / "data/worker_settings.yaml",
            """
            apps:
              - worker_tools
            app_settings: {}
            core:
              app_name: cli-worker
            database:
              url: sqlite+aiosqlite:///data/worker.db
            """,
        )
    return marker


def _run_cli(
    project: Path,
    marker: Path,
    *args: str,
    input_text: str | None = None,
    language: str = "en",
) -> subprocess.CompletedProcess[str]:
    """Run one public CLI process against the fixture project."""
    environment = os.environ.copy()
    python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPOSITORY_ROOT), python_path)))
    environment["OLDMAN_CLI_LANGUAGE"] = language
    environment["OLDMAN_SERVICE_IMPORT_MARKER"] = str(marker)
    return subprocess.run(
        [sys.executable, "-m", "oldman.cli", *args],
        cwd=project,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


class ServiceCliTest(unittest.TestCase):
    """Protect one-service command dispatch without eager business imports."""

    def test_root_help_lists_services_without_importing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            completed = _run_cli(project, marker, "--help")

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("music_web", completed.stdout)
            self.assertIn("worker", completed.stdout)
            self.assertFalse(marker.exists())
            for removed in ("config", "list", "settings", "static"):
                self.assertNotIn(f"  {removed} ", completed.stdout)

    def test_settings_init_is_cold_and_uses_the_service_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            initialized = _run_cli(
                project,
                marker,
                "music_web",
                "settings",
                "init",
            )
            help_result = _run_cli(
                project,
                marker,
                "music_web",
                "settings",
                "--help",
            )

            config_file = project / "data/music_web_settings.yaml"
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            self.assertTrue(config_file.is_file())
            self.assertFalse(marker.exists())
            self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
            self.assertIn("init", help_result.stdout)
            self.assertIn("sync", help_result.stdout)
            self.assertIn("check", help_result.stdout)
            self.assertNotIn("show", help_result.stdout)
            self.assertNotIn("--overwrite", help_result.stdout)

    def test_missing_settings_blocks_service_help_without_importing_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project, worker_settings=False)

            completed = _run_cli(project, marker, "worker", "--help")

            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("data/worker_settings.yaml", completed.stderr)
            self.assertIn("worker settings init", completed.stderr)
            self.assertFalse(marker.exists())

    def test_runtime_command_imports_only_the_selected_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            help_result = _run_cli(project, marker, "worker", "--help")
            probe = _run_cli(
                project,
                marker,
                "worker",
                "probe",
                "one",
                "--repeat",
                "2",
                "--uppercase",
            )

            self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
            self.assertIn("probe", help_result.stdout)
            self.assertIn("dumpdata", help_result.stdout)
            self.assertIn("loaddata", help_result.stdout)
            self.assertIn("settings", help_result.stdout)
            self.assertIn("shell", help_result.stdout)
            self.assertNotIn("static", help_result.stdout)
            self.assertIn("Service commands", help_result.stdout)
            self.assertIn("Worker tools", help_result.stdout)
            self.assertEqual(0, probe.returncode, probe.stdout + probe.stderr)
            self.assertIn("CLI-WORKER:ONE|ONE", probe.stdout)
            self.assertEqual(
                ["worker", "worker"],
                marker.read_text(encoding="utf-8").splitlines(),
            )

    def test_app_command_cannot_replace_a_fixture_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            _write(
                project / "worker_tools/commands.py",
                """
                from oldman.cli import Command

                class DumpDataCommand(Command):
                    name = "dumpdata"
                    help = "Conflicting dump command."

                    async def handle(self) -> None:
                        return None
                """,
            )

            completed = _run_cli(project, marker, "worker", "--help")

            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("dumpdata", completed.stderr)
            self.assertIn("conflict", completed.stderr.lower())

    def test_fixture_commands_round_trip_raw_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            database_path = project / "data/worker.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE fixture_item (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL)")
                connection.execute(
                    "INSERT INTO fixture_item (id, name) VALUES (?, ?)",
                    (4, "中文 [bold]"),
                )

            dumped = _run_cli(
                project,
                marker,
                "worker",
                "dumpdata",
                "worker_tools.FixtureItem",
            )

            self.assertEqual(0, dumped.returncode, dumped.stdout + dumped.stderr)
            self.assertEqual(
                [
                    {
                        "model": "worker_tools.FixtureItem",
                        "pk": 4,
                        "fields": {"name": "中文 [bold]"},
                    }
                ],
                json.loads(dumped.stdout),
            )
            output_path = project / "exported.json"
            written = _run_cli(
                project,
                marker,
                "worker",
                "dumpdata",
                "worker_tools.FixtureItem",
                "--output",
                str(output_path),
            )
            self.assertEqual(0, written.returncode, written.stdout + written.stderr)
            self.assertEqual("", written.stdout)
            self.assertEqual(json.loads(dumped.stdout), json.loads(output_path.read_text()))
            fixture_path = project / "items.json"
            fixture_path.write_text(
                json.dumps(
                    [
                        {
                            "model": "worker_tools.FixtureItem",
                            "pk": 4,
                            "fields": {"name": "updated"},
                        },
                        {
                            "model": "worker_tools.FixtureItem",
                            "pk": 5,
                            "fields": {"name": "new"},
                        },
                    ]
                ),
                encoding="utf-8",
            )

            loaded = _run_cli(
                project,
                marker,
                "worker",
                "loaddata",
                str(fixture_path),
            )

            self.assertEqual(0, loaded.returncode, loaded.stdout + loaded.stderr)
            self.assertIn("Loaded 2 fixture records.", loaded.stdout)
            with sqlite3.connect(database_path) as connection:
                rows = connection.execute("SELECT id, name FROM fixture_item ORDER BY id").fetchall()
            self.assertEqual([(4, "updated"), (5, "new")], rows)

    def test_app_command_cannot_replace_a_service_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            _write(
                project / "worker_tools/commands.py",
                """
                from oldman.cli import Command

                class StartCommand(Command):
                    name = "start"
                    help = "Conflicting start."

                    async def handle(self) -> None:
                        return None
                """,
            )

            completed = _run_cli(project, marker, "worker", "--help")

            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("start", completed.stderr)
            self.assertIn("conflict", completed.stderr.lower())

    def test_service_help_uses_app_catalog_and_project_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            app_translation = _run_cli(
                project,
                marker,
                "worker",
                "--help",
                language="zh-Hans",
            )
            _write_catalog(
                project / "locales/zh_Hans/LC_MESSAGES/messages.mo",
                "zh_Hans",
                {
                    "Worker tools": "项目工作工具",
                    "Run the worker probe.": "运行项目工作探针。",
                },
            )
            project_override = _run_cli(
                project,
                marker,
                "worker",
                "--help",
                language="zh-Hans",
            )

            self.assertEqual(
                0,
                app_translation.returncode,
                app_translation.stdout + app_translation.stderr,
            )
            self.assertIn("工作工具", app_translation.stdout)
            self.assertIn("运行工作探针", app_translation.stdout)
            self.assertEqual(
                0,
                project_override.returncode,
                project_override.stdout + project_override.stderr,
            )
            self.assertIn("项目工作工具", project_override.stdout)
            self.assertIn("运行项目工作探针", project_override.stdout)

    def test_shell_bootstraps_models_without_importing_the_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            completed = _run_cli(
                project,
                marker,
                "worker",
                "shell",
                input_text="",
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("context", completed.stdout + completed.stderr)
            self.assertFalse(marker.exists())

    def test_web_static_collect_uses_installed_apps_without_service_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            initialized = _run_cli(
                project,
                marker,
                "music_web",
                "settings",
                "init",
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            config_file = project / "data/music_web_settings.yaml"
            yaml = YAML()
            with config_file.open(encoding="utf-8") as stream:
                data = yaml.load(stream)
            data["apps"] = ["theme_app"]
            data["app_settings"] = {}
            data["web"]["static"]["dir"] = str(project / "project_static")
            data["web"]["static"]["root"] = str(project / "public")
            data["web"]["static"]["url"] = "/static/"
            with config_file.open("w", encoding="utf-8") as stream:
                yaml.dump(data, stream)

            collected = _run_cli(
                project,
                marker,
                "music_web",
                "static",
                "collect",
            )

            self.assertEqual(0, collected.returncode, collected.stdout + collected.stderr)
            self.assertEqual(
                "theme-asset",
                (project / "public/theme/brand.txt").read_text(encoding="utf-8"),
            )
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
