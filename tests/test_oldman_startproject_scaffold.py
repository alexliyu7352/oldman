"""Project scaffold interaction and generated-source contracts."""

from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from babel.messages.pofile import read_po
from ruamel.yaml import YAML
from typer.testing import CliRunner

from oldman.cli._main import create_app
from oldman.cli.localization import CliLanguageState
from oldman.cli.scaffold import DatabaseChoice, ProjectType, start_project
from oldman.i18n.commands import KEYWORDS, _extract_catalog
from oldman.version import __VERSION__

ROOT = Path(__file__).resolve().parents[1]
I18N_CLI = (
    ROOT
    / "frontend"
    / "packages"
    / "oldman-web"
    / "bin"
    / "oldman-web-i18n.mjs"
)
PROJECT_DATABASES = {
    ProjectType.CLI: (),
    ProjectType.SERVICE: tuple(DatabaseChoice),
    ProjectType.API: tuple(DatabaseChoice),
    ProjectType.WEB: tuple(DatabaseChoice),
    ProjectType.DASHBOARD: (
        DatabaseChoice.SQLITE,
        DatabaseChoice.MYSQL,
        DatabaseChoice.POSTGRES,
    ),
}
SERVICE_NAMES = {
    ProjectType.SERVICE: "service",
    ProjectType.API: "api",
    ProjectType.WEB: "web",
    ProjectType.DASHBOARD: "dashboard",
}
SERVICE_BASES = {
    ProjectType.SERVICE: "SimpleApplication",
    ProjectType.API: "WebApplication",
    ProjectType.WEB: "WebApplication",
    ProjectType.DASHBOARD: "WebApplication",
}


@contextlib.contextmanager
def working_directory(path: Path):
    """Temporarily use one isolated project parent directory."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def cli_env() -> dict[str, str]:
    """Return a subprocess environment that imports the working framework."""
    environment = os.environ.copy()
    python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(ROOT)
        if not python_path
        else f"{ROOT}{os.pathsep}{python_path}"
    )
    environment["OLDMAN_CLI_LANGUAGE"] = "en"
    environment["XDG_CONFIG_HOME"] = str(ROOT / ".test-cli-config")
    return environment


def scaffold_cli():
    """Build the root CLI without discovering or loading project services."""
    return create_app(
        CliLanguageState(effective="en", saved=None, source="test"),
        definitions={},
    )


def invoke_startproject(
    parent: Path,
    name: str,
    project_type: ProjectType,
    database: DatabaseChoice | None = None,
):
    """Answer the public interactive prompts through Typer's real runner."""
    answers = [project_type.value]
    if project_type != ProjectType.CLI:
        assert database is not None
        answers.append(database.value)
    with working_directory(parent):
        return CliRunner().invoke(
            scaffold_cli(),
            ["startproject", name],
            input="\n".join(answers) + "\n",
        )


def read_yaml(path: Path) -> dict[str, object]:
    """Read one generated minimal service seed."""
    payload = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


class StartProjectInteractionTests(unittest.TestCase):
    """Collect every choice before the first filesystem write."""

    def test_cli_interaction_covers_every_supported_project_database_pair(self) -> None:
        """Project and database choices have no hidden default or missing pair."""
        generated = 0
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type, databases in PROJECT_DATABASES.items():
                cases = databases or (None,)
                for database in cases:
                    with self.subTest(
                        project_type=project_type,
                        database=database,
                    ):
                        name = (
                            f"{project_type.value}_{database.value}"
                            if database is not None
                            else project_type.value
                        )
                        result = invoke_startproject(
                            parent,
                            name,
                            project_type,
                            database,
                        )
                        self.assertEqual(
                            result.exit_code,
                            0,
                            result.output + repr(result.exception),
                        )
                        self.assertTrue((parent / name).is_dir())
                        generated += 1

        self.assertEqual(generated, 16)

    def test_missing_database_answer_leaves_no_partial_project(self) -> None:
        """EOF after choosing a Web template cannot leave copied files behind."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent):
                result = CliRunner().invoke(
                    scaffold_cli(),
                    ["startproject", "unfinished"],
                    input="web\n",
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse((parent / "unfinished").exists())

    def test_cancelled_project_choice_leaves_no_partial_project(self) -> None:
        """An interrupted first prompt cannot create the target directory."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent):
                result = CliRunner().invoke(
                    scaffold_cli(),
                    ["startproject", "cancelled"],
                    input="\x03",
                )

            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse((parent / "cancelled").exists())

    def test_non_tty_without_answers_leaves_no_partial_project(self) -> None:
        """Automation cannot silently receive the former Web defaults."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            completed = subprocess.run(
                [sys.executable, "-m", "oldman.cli", "startproject", "unattended"],
                cwd=parent,
                env=cli_env(),
                input="",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((parent / "unattended").exists())

    def test_nonempty_target_is_rejected_without_overwriting_it(self) -> None:
        """The removed force path cannot replace an existing project."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            target = parent / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("user data", encoding="utf-8")
            result = invoke_startproject(
                parent,
                "existing",
                ProjectType.API,
                DatabaseChoice.SQLITE,
            )

            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "user data")
            self.assertEqual(tuple(target.iterdir()), (marker,))

    def test_help_has_no_legacy_selection_or_overwrite_options(self) -> None:
        """One interactive workflow replaces the old parallel option API."""
        result = CliRunner().invoke(
            scaffold_cli(),
            ["startproject", "--help"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        for option in ("--type", "--db", "--force"):
            self.assertNotIn(option, result.output)


class StartProjectGeneratedSourceTests(unittest.TestCase):
    """Generate the new Settings, service, identity, and seed contracts."""

    def test_web_scaffolds_extract_templates_with_csrf(self) -> None:
        """Generated Babel configs must parse real CSRF-enabled templates."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type in (ProjectType.API, ProjectType.WEB, ProjectType.DASHBOARD):
                with self.subTest(project_type=project_type):
                    target = start_project(
                        str(parent / project_type.value),
                        project_type=project_type,
                        db=DatabaseChoice.SQLITE,
                    )
                    template = target / "templates" / "probe.html"
                    template.parent.mkdir(exist_ok=True)
                    template.write_text(
                        '<form>{% csrf_token %}{{ _("Scaffold form") }}</form>',
                        encoding="utf-8",
                    )
                    output = target / "messages.pot"
                    _extract_catalog(
                        config="babel.cfg", output=output, source=".",
                        keywords=KEYWORDS, cwd=target,
                    )
                    with output.open("rb") as stream:
                        self.assertIn("Scaffold form", read_po(stream))

    def test_each_project_has_one_committed_uuid_and_flat_uv_metadata(self) -> None:
        """Project identity is valid source metadata rather than runtime state."""
        identities: set[UUID] = set()
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type in ProjectType:
                database = (
                    DatabaseChoice.SQLITE
                    if project_type != ProjectType.CLI
                    else DatabaseChoice.NONE
                )
                with working_directory(parent):
                    target = start_project(
                        project_type.value,
                        project_type=project_type,
                        db=database,
                    )
                metadata = tomllib.loads(
                    (target / "pyproject.toml").read_text(encoding="utf-8")
                )
                project_id = UUID(metadata["tool"]["oldman"]["project_id"])
                identities.add(project_id)
                self.assertIs(metadata["tool"]["uv"]["package"], False)
                self.assertNotIn("migration_apps", metadata["tool"]["oldman"])

        self.assertEqual(len(identities), len(ProjectType))

    def test_non_cli_projects_use_one_settings_type_and_fixed_service_module(self) -> None:
        """Generated sources follow service bootstrap without aliases or old hooks."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type, service_name in SERVICE_NAMES.items():
                with self.subTest(project_type=project_type), working_directory(parent):
                    target = start_project(
                        project_type.value,
                        project_type=project_type,
                        db=DatabaseChoice.SQLITE,
                    )

                schema = (target / "config" / "schemas.py").read_text(
                    encoding="utf-8"
                )
                settings = (target / "config" / "settings.py").read_text(
                    encoding="utf-8"
                )
                service = (
                    target / "services" / f"{service_name}.py"
                ).read_text(encoding="utf-8")
                run_script = target / "run.sh"

                self.assertIn("class Settings(DefaultSettings):", schema)
                self.assertNotIn("include_framework_configs", schema)
                self.assertNotIn("SETTINGS_FILE", schema)
                self.assertIn("settings = cast(Settings, conf.settings)", settings)
                self.assertNotIn("setup(", settings)
                self.assertIn(f"({SERVICE_BASES[project_type]}):", service)
                self.assertNotIn("SERVICE_ID", service)
                self.assertNotIn("registered_apps", service)
                self.assertTrue(run_script.is_file())
                self.assertEqual(stat.S_IMODE(run_script.stat().st_mode), 0o755)
                self.assertIn('exec "$OLDMAN_BIN" "$@"', run_script.read_text(encoding="utf-8"))
                self.assertFalse((target / "main.py").exists())

    def test_minimal_seed_and_readme_follow_the_selected_database(self) -> None:
        """Scaffold writes only known choices before settings sync expands them."""
        expected_urls = {
            DatabaseChoice.NONE: None,
            DatabaseChoice.SQLITE: "sqlite+aiosqlite:///data/app.db",
            DatabaseChoice.MYSQL: "mysql+aiomysql://user:password@127.0.0.1:3306/app",
            DatabaseChoice.POSTGRES: "postgresql+asyncpg://user:password@127.0.0.1:5432/app",
        }
        expected_drivers = {
            DatabaseChoice.NONE: None,
            DatabaseChoice.SQLITE: None,
            DatabaseChoice.MYSQL: "aiomysql",
            DatabaseChoice.POSTGRES: "asyncpg",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for database, url in expected_urls.items():
                with self.subTest(database=database), working_directory(parent):
                    target = start_project(
                        f"api_{database.value}",
                        project_type=ProjectType.API,
                        db=database,
                    )

                seed_path = target / "data" / "api_settings.yaml"
                seed = read_yaml(seed_path)
                metadata = tomllib.loads(
                    (target / "pyproject.toml").read_text(encoding="utf-8")
                )
                dependencies = metadata["project"]["dependencies"]
                self.assertEqual(seed, {"apps": [], "database": {"url": url}})
                self.assertEqual(stat.S_IMODE(seed_path.stat().st_mode), 0o600)
                driver = expected_drivers[database]
                self.assertEqual(
                    any(
                        dependency.startswith(("aiomysql", "asyncpg"))
                        for dependency in dependencies
                    ),
                    driver is not None,
                )
                if driver is not None:
                    self.assertTrue(
                        any(item.startswith(driver) for item in dependencies)
                    )

            dashboard = start_project(
                str(parent / "dashboard"),
                project_type=ProjectType.DASHBOARD,
                db=DatabaseChoice.SQLITE,
            )
            dashboard_seed = read_yaml(
                dashboard / "data" / "dashboard_settings.yaml"
            )
            self.assertEqual(
                dashboard_seed["apps"],
                ["oldman.auth", "oldman.apps.admin"],
            )

    def test_gitignore_excludes_service_settings(self) -> None:
        """Generated projects do not commit service-specific settings and secrets."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            with working_directory(Path(temporary_directory)):
                target = start_project(
                    "portal",
                    project_type=ProjectType.WEB,
                    db=DatabaseChoice.SQLITE,
                )

            gitignore = (target / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("/data/*_settings.yaml", gitignore)
        self.assertNotIn("/data/settings.yaml", gitignore)

    def test_dashboard_frontend_and_release_versions_are_preserved(self) -> None:
        """The settings refactor does not replace the established dashboard assets."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent), patch(
                "oldman.cli.scaffold.FRAMEWORK_VERSION",
                "9.8.7",
            ):
                target = start_project(
                    "control_desk",
                    project_type=ProjectType.DASHBOARD,
                    db=DatabaseChoice.POSTGRES,
                )

            pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
            frontend = (target / "frontend" / "package.json").read_text(
                encoding="utf-8"
            )
            frontend_package = json.loads(frontend)
            frontend_main = (
                target / "frontend" / "src" / "main.ts"
            ).read_text(encoding="utf-8")
            i18n_builder = (
                target / "scripts" / "build_frontend_i18n.py"
            ).read_text(encoding="utf-8")
            template_exists = (target / "templates" / "base.html").exists()

        self.assertIn('"oldman>=9.8.7"', pyproject)
        self.assertIn('"oldman-web": "^9.8.7"', frontend)
        self.assertEqual(
            frontend_package["scripts"]["generate:i18n"],
            "../.venv/bin/python ../scripts/build_frontend_i18n.py",
        )
        self.assertIn("loadLanguageManifest", frontend_main)
        self.assertNotIn("initialCatalog", frontend_main)
        self.assertIn("compile_project_frontend_catalog", i18n_builder)
        self.assertNotIn("js_messages", i18n_builder)
        self.assertTrue(template_exists)
        root_metadata = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(__VERSION__, root_metadata["project"]["version"])

    def test_dashboard_builds_filtered_catalogs_from_messages_po(self) -> None:
        """A generated Dashboard publishes configured browser catalogs atomically."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent):
                target = start_project(
                    "translated_dashboard",
                    project_type=ProjectType.DASHBOARD,
                    db=DatabaseChoice.SQLITE,
                )

            settings_file = target / "data" / "dashboard_settings.yaml"
            settings = read_yaml(settings_file)
            settings.update(
                {
                    "i18n": {
                        "default_language": "en",
                        "languages": {"en": {}, "zh-Hans": {}},
                        "use_i18n": True,
                    },
                    "web": {"static": {"url": "/static/"}},
                }
            )
            yaml = YAML()
            with settings_file.open("w", encoding="utf-8") as stream:
                yaml.dump(settings, stream)

            for locale, translation in (
                ("en", "Loading..."),
                ("zh_Hans", "正在加载..."),
            ):
                po_file = (
                    target
                    / "locales"
                    / locale
                    / "LC_MESSAGES"
                    / "messages.po"
                )
                po_file.parent.mkdir(parents=True)
                po_file.write_text(
                    '\n'.join(
                        (
                            'msgid ""',
                            'msgstr ""',
                            f'"Language: {locale}\\n"',
                            '',
                            'msgid "Loading..."',
                            f'msgstr "{translation}"',
                            '',
                            'msgid "Backend only"',
                            'msgstr "Not for browsers"',
                        )
                    ),
                    encoding="utf-8",
                )

            package_bin = (
                target
                / "frontend"
                / "node_modules"
                / "oldman-web"
                / "bin"
            )
            package_bin.mkdir(parents=True)
            (package_bin / "oldman-web-i18n.mjs").symlink_to(I18N_CLI)
            subprocess.run(
                [sys.executable, str(target / "scripts" / "build_frontend_i18n.py")],
                cwd=target,
                check=True,
            )

            output = target / "frontend" / "public" / "i18n"
            manifest = json.loads(
                (output / "languages.json").read_text(encoding="utf-8")
            )
            english = json.loads(
                (output / "en.json").read_text(encoding="utf-8")
            )
            chinese = json.loads(
                (output / "zh-hans.json").read_text(encoding="utf-8")
            )

        self.assertEqual(manifest["defaultLanguage"], "en")
        self.assertEqual(
            [language["code"] for language in manifest["languages"]],
            ["en", "zh-Hans"],
        )
        self.assertEqual(english["messages"]["Loading..."], "Loading...")
        self.assertEqual(chinese["messages"]["Loading..."], "正在加载...")
        self.assertNotIn("Backend only", chinese["messages"])


if __name__ == "__main__":
    unittest.main()
