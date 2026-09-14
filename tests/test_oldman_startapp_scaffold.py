"""Interactive ``startapp`` contracts and generated App metadata."""

from __future__ import annotations

import ast
import contextlib
import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from oldman.cli._main import create_app
from oldman.cli.localization import CliLanguageState
from oldman.cli.scaffold import AppType, DatabaseChoice, ProjectType, start_project


@contextlib.contextmanager
def working_directory(path: Path):
    """Temporarily run scaffold discovery from ``path``."""
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
    """Create one project with Web-shaped directories for App templates."""
    with working_directory(parent):
        return start_project(
            "project",
            project_type=ProjectType.WEB,
            db=DatabaseChoice.SQLITE,
        )


def invoke_startapp(
    project: Path,
    name: str,
    app_type: AppType,
    display_name: str,
):
    """Answer both public prompts from a nested project directory."""
    with working_directory(project / "apps"):
        return CliRunner().invoke(
            scaffold_cli(),
            ["startapp", name],
            input=f"{app_type.value}\n{display_name}\n",
        )


class StartAppScaffoldTests(unittest.TestCase):
    """Generate reusable Apps without creating services or changing settings."""

    def test_each_template_creates_app_metadata_and_no_service(self) -> None:
        """All four choices share App identity and migration boundaries."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            settings_path = project / "data" / "web_settings.yaml"
            original_settings = settings_path.read_bytes()
            original_services = set((project / "services").iterdir())

            for app_type in AppType:
                app_name = f"{app_type.value}_reports"
                display_name = f"{app_type.value.title()} Reports"
                with self.subTest(app_type=app_type):
                    result = invoke_startapp(
                        project,
                        app_name,
                        app_type,
                        display_name,
                    )
                    self.assertEqual(
                        result.exit_code,
                        0,
                        result.output + repr(result.exception),
                    )
                    app_root = project / "apps" / app_name
                    metadata = (app_root / "apps.py").read_text(encoding="utf-8")
                    self.assertIn(f'label = "{app_name}"', metadata)
                    self.assertIn("display_name = _(", metadata)
                    self.assertIn(display_name, metadata)
                    self.assertNotIn("icon =", metadata)
                    self.assertTrue((app_root / "migrations" / "__init__.py").is_file())
                    self.assertEqual(
                        [path.name for path in (app_root / "migrations").iterdir()],
                        ["__init__.py"],
                    )

            self.assertEqual(set((project / "services").iterdir()), original_services)
            self.assertEqual(settings_path.read_bytes(), original_settings)

    def test_enter_explicitly_accepts_humanized_display_name(self) -> None:
        """The suggested name is visible and only accepted by answering Enter."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            result = invoke_startapp(
                project,
                "server_monitor",
                AppType.SERVICE,
                "",
            )

            self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
            metadata = (
                project / "apps" / "server_monitor" / "apps.py"
            ).read_text(encoding="utf-8")
            self.assertIn("Server Monitor", result.output)
            self.assertIn("display_name = _('Server Monitor')", metadata)

    def test_custom_display_name_is_safely_rendered_as_python(self) -> None:
        """Quotes in a human-facing name cannot corrupt generated source."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            display_name = "Team's \"Reports\""
            result = invoke_startapp(
                project,
                "reports",
                AppType.WEB,
                display_name,
            )

            self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
            source = (project / "apps" / "reports" / "apps.py").read_text(
                encoding="utf-8"
            )
            ast.parse(source)
            self.assertIn(repr(display_name), source)

    def test_missing_display_name_answer_leaves_no_partial_app(self) -> None:
        """EOF after the template choice occurs before filesystem writes."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            with working_directory(project):
                result = CliRunner().invoke(
                    scaffold_cli(),
                    ["startapp", "unfinished"],
                    input="api\n",
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse((project / "apps" / "unfinished").exists())

    def test_existing_app_is_rejected_without_partial_overwrite(self) -> None:
        """A target conflict is detected before copying any App file."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = create_web_project(Path(temporary_directory))
            app_root = project / "apps" / "reports"
            app_root.mkdir()
            marker = app_root / "keep.py"
            marker.write_text("user data", encoding="utf-8")

            result = invoke_startapp(
                project,
                "reports",
                AppType.DASHBOARD,
                "Reports",
            )

            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "user data")
            self.assertEqual(tuple(app_root.iterdir()), (marker,))

    def test_help_exposes_only_the_interactive_workflow(self) -> None:
        """Removed startapp options have no compatibility path."""
        result = CliRunner().invoke(scaffold_cli(), ["startapp", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        for option in ("--type", "--force", "--project-root"):
            self.assertNotIn(option, result.output)


if __name__ == "__main__":
    unittest.main()
