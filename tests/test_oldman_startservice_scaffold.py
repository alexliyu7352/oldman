"""Interactive ``startservice`` contracts and cold discovery coverage."""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from oldman.cli._main import create_app
from oldman.cli.localization import CliLanguageState
from oldman.cli.scaffold import DatabaseChoice, ProjectType, start_project
from oldman.runtime.discovery import discover_service_definitions


@contextlib.contextmanager
def working_directory(path: Path):
    """Temporarily run project discovery from ``path``."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def scaffold_cli():
    """Build the cold root CLI used by scaffold commands."""
    return create_app(
        CliLanguageState(effective="en", saved=None, source="test"),
        definitions={},
    )


def create_web_project(parent: Path) -> Path:
    """Create one project in which services can be added."""
    with working_directory(parent):
        return start_project(
            "project",
            project_type=ProjectType.WEB,
            db=DatabaseChoice.SQLITE,
        )


def invoke_startservice(project: Path, name: str, service_type: str):
    """Choose one service kind while exercising upward project discovery."""
    with working_directory(project / "apps"):
        return CliRunner().invoke(
            scaffold_cli(),
            ["startservice", name],
            input=f"{service_type}\n",
        )


class StartServiceScaffoldTests(unittest.TestCase):
    """Create exactly one statically discoverable service module."""

    def test_simple_and_web_services_are_directly_discoverable(self) -> None:
        """Service choice controls only the direct Application base."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            settings_path = project / "data" / "web_settings.yaml"
            original_settings = settings_path.read_bytes()
            original_apps = {
                path.relative_to(project)
                for path in (project / "apps").rglob("*")
            }

            for name, service_type, expected_base in (
                ("music_worker", "simple", "SimpleApplication"),
                ("music_web", "web", "WebApplication"),
                ("task_worker", "taskiq_worker", "TaskiqWorkerApplication"),
                ("task_scheduler", "taskiq_scheduler", "TaskiqSchedulerApplication"),
            ):
                with self.subTest(service_type=service_type):
                    result = invoke_startservice(project, name, service_type)
                    self.assertEqual(
                        result.exit_code,
                        0,
                        result.output + repr(result.exception),
                    )
                    source = (project / "services" / f"{name}.py").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(f"({expected_base}):", source)
                    self.assertNotIn("SERVICE_ID", source)
                    self.assertNotIn("registered_apps", source)

            definitions = discover_service_definitions(project)
            self.assertEqual(definitions["music_worker"].application_base, "simple")
            self.assertEqual(definitions["music_web"].application_base, "web")
            self.assertEqual(definitions["task_worker"].application_base, "taskiq_worker")
            self.assertEqual(definitions["task_scheduler"].application_base, "taskiq_scheduler")
            self.assertEqual(settings_path.read_bytes(), original_settings)
            self.assertEqual(
                {
                    path.relative_to(project)
                    for path in (project / "apps").rglob("*")
                },
                original_apps,
            )

    def test_service_name_supports_underscores_but_rejects_invalid_modules(self) -> None:
        """Generated names use the same strict contract as cold discovery."""
        invalid_names = (
            "MusicWeb",
            "music-web",
            "music web",
            "1music",
            "_music",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            for name in invalid_names:
                with self.subTest(name=name):
                    result = invoke_startservice(project, name, "simple")
                    self.assertNotEqual(result.exit_code, 0)
            self.assertFalse(any((project / "services" / f"{name}.py").exists() for name in invalid_names))

    def test_missing_type_answer_leaves_no_partial_service(self) -> None:
        """EOF cannot silently select one former service default."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            with working_directory(project):
                result = CliRunner().invoke(
                    scaffold_cli(),
                    ["startservice", "unfinished"],
                    input="",
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse((project / "services" / "unfinished.py").exists())

    def test_existing_service_is_rejected_without_overwrite(self) -> None:
        """The command never replaces a hand-written service module."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            target = project / "services" / "music_web.py"
            target.write_text("user data", encoding="utf-8")

            result = invoke_startservice(project, "music_web", "web")

            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "user data")

    def test_help_exposes_only_the_interactive_workflow(self) -> None:
        """Removed options are absent from the new root command."""
        result = CliRunner().invoke(scaffold_cli(), ["startservice", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        for option in ("--type", "--force", "--project-root"):
            self.assertNotIn(option, result.output)


if __name__ == "__main__":
    unittest.main()
