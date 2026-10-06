"""Project scaffold interaction and generated-source contracts."""

from __future__ import annotations

import asyncio
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
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from babel.messages.pofile import read_po
from jinja2 import Environment
from ruamel.yaml import YAML
from typer.testing import CliRunner

import oldman.conf as conf
from oldman.cli import tui
from oldman.cli._main import create_app
from oldman.cli.agent_instructions import GUIDES
from oldman.cli.i18n_commands import build_frontend_catalogs
from oldman.cli.localization import CliLanguageState
from oldman.cli.scaffold import AppType, DatabaseChoice, ProjectType, ServiceType, copy_template_tree, start_app, start_project, start_service
from oldman.conf import DefaultSettings
from oldman.i18n.commands import KEYWORDS, _extract_catalog
from oldman.version import __VERSION__
from oldman.web.template import install_template_loaders
from oldman.web.template_globals import template_globals
from tests.tui_support import without_preset_answers

ROOT = Path(__file__).resolve().parents[1]
I18N_CLI = ROOT / "frontend" / "packages" / "oldman-web" / "bin" / "oldman-web-i18n.mjs"
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
    environment["PYTHONPATH"] = str(ROOT) if not python_path else f"{ROOT}{os.pathsep}{python_path}"
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
    """Answer the public questions with preset answers through Typer's real runner."""
    answers = {"OLDMAN_ANSWER_STARTPROJECT_TYPE": project_type.value}
    if project_type != ProjectType.CLI:
        assert database is not None
        answers["OLDMAN_ANSWER_STARTPROJECT_DATABASE"] = database.value
    with working_directory(parent):
        return CliRunner().invoke(scaffold_cli(), ["startproject", name], env=answers)


def read_yaml(path: Path) -> dict[str, object]:
    """Read one generated minimal service seed."""
    payload = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def setUpModule() -> None:
    unittest.enterModuleContext(without_preset_answers())


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
                        name = f"{project_type.value}_{database.value}" if database is not None else project_type.value
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
        """A Web project without a database answer stops before any file is copied."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent):
                result = CliRunner().invoke(
                    scaffold_cli(),
                    ["startproject", "unfinished"],
                    env={"OLDMAN_ANSWER_STARTPROJECT_TYPE": "web"},
                )

            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("OLDMAN_ANSWER_STARTPROJECT_DATABASE", result.output)
            self.assertFalse((parent / "unfinished").exists())

    def test_cancelled_project_choice_leaves_no_partial_project(self) -> None:
        """An interrupted first question cannot create the target directory."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent), tui.simulate_input([KeyboardInterrupt]):
                result = CliRunner().invoke(scaffold_cli(), ["startproject", "cancelled"])

            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Aborted.", result.output)
            self.assertFalse((parent / "cancelled").exists())

    def test_a_dashboard_needs_a_database(self) -> None:
        """Asked again at the terminal; a preset answer without one is an error before any write."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent), tui.simulate_input(["dashboard", "none", "sqlite", "n"]):
                result = CliRunner().invoke(scaffold_cli(), ["startproject", "asked"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Dashboard projects require a database.", result.output)

            preset = {"OLDMAN_ANSWER_STARTPROJECT_TYPE": "dashboard", "OLDMAN_ANSWER_STARTPROJECT_DATABASE": "none"}
            with working_directory(parent):
                result = CliRunner().invoke(scaffold_cli(), ["startproject", "preset"], env=preset)
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("OLDMAN_ANSWER_STARTPROJECT_DATABASE is not valid: Dashboard projects require a database.", result.output)
            self.assertFalse((parent / "preset").exists())

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
            self.assertIn("OLDMAN_ANSWER_STARTPROJECT_TYPE", completed.stderr)
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
                        config="babel.cfg",
                        output=output,
                        source=".",
                        keywords=KEYWORDS,
                        cwd=target,
                    )
                    with output.open("rb") as stream:
                        self.assertIn("Scaffold form", read_po(stream))

    def test_each_project_has_one_committed_uuid_and_flat_uv_metadata(self) -> None:
        """Project identity is valid source metadata rather than runtime state."""
        identities: set[UUID] = set()
        framework_python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type in ProjectType:
                database = DatabaseChoice.SQLITE if project_type != ProjectType.CLI else DatabaseChoice.NONE
                with working_directory(parent):
                    target = start_project(
                        project_type.value,
                        project_type=project_type,
                        db=database,
                    )
                metadata = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
                project_id = UUID(metadata["tool"]["oldman"]["project_id"])
                identities.add(project_id)
                self.assertIs(metadata["tool"]["uv"]["package"], False)
                # uv picks the recommended interpreter, not just the newest one installed.
                self.assertEqual("3.13\n", (target / ".python-version").read_text(encoding="utf-8"))
                self.assertEqual(framework_python, metadata["project"]["requires-python"])
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

                schema = (target / "config" / "schemas.py").read_text(encoding="utf-8")
                settings = (target / "config" / "settings.py").read_text(encoding="utf-8")
                service = (target / "services" / f"{service_name}.py").read_text(encoding="utf-8")
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

    def test_every_service_of_a_new_project_shares_the_projects_own_redis_namespace(self) -> None:
        """Two projects on one Redis kept their keys under the same default namespace (`oldman`); a new project's
        schema defaults core.namespace to its slug, so a service added later writes the same one into its YAML."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type in SERVICE_NAMES:
                with self.subTest(project_type=project_type), working_directory(parent):
                    target = start_project(f"billing-{project_type.value}", project_type=project_type, db=DatabaseChoice.SQLITE)
                    with working_directory(target):
                        start_service("jobs", service_type=ServiceType.TASKIQ_WORKER)
                    initialized = subprocess.run(
                        [sys.executable, "-m", "oldman.cli", "jobs", "settings", "init"],
                        cwd=target,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
                    jobs = YAML(typ="safe").load((target / "data" / "jobs_settings.yaml").read_text(encoding="utf-8"))
                    self.assertEqual(f"billing_{project_type.value}", jobs["core"]["namespace"])
                    probe = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "from config.schemas import CoreSettings; print(CoreSettings.model_validate({'site_name': 'x'}).namespace)",
                        ],
                        cwd=target,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(f"billing_{project_type.value}", probe.stdout.strip(), probe.stderr)

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
                metadata = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
                dependencies = metadata["project"]["dependencies"]
                self.assertEqual(["apps.home"], seed["apps"])
                self.assertEqual({"url": url}, seed["database"])
                self.assertEqual(stat.S_IMODE(seed_path.stat().st_mode), 0o600)
                driver = expected_drivers[database]
                self.assertEqual(
                    any(dependency.startswith(("aiomysql", "asyncpg")) for dependency in dependencies),
                    driver is not None,
                )
                if driver is not None:
                    self.assertTrue(any(item.startswith(driver) for item in dependencies))

            dashboard = start_project(
                str(parent / "dashboard"),
                project_type=ProjectType.DASHBOARD,
                db=DatabaseChoice.SQLITE,
            )
            dashboard_seed = read_yaml(dashboard / "data" / "dashboard_settings.yaml")
            # Users and the roles beside them, notifications, then the project's own accounts and home page;
            # the built-in Admin only when asked for.
            self.assertEqual(
                dashboard_seed["apps"],
                ["oldman.auth", "oldman.apps.roles", "oldman.web.messages.notifications", "apps.accounts", "apps.home"],
            )
            self.assertEqual({"site_name": "dashboard"}, dashboard_seed["core"])
            self.assertEqual({"auth": {"user_model": "apps.accounts.models.User"}}, dashboard_seed["app_settings"])
            self.assertEqual({"session": {"enabled": True}}, dashboard_seed["web"])

    def test_the_admin_choice_installs_the_admin_with_its_users_and_sessions(self) -> None:
        """Web and dashboard projects may include the built-in Admin; it needs users, roles, sessions and a database."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type, service_name in ((ProjectType.WEB, "web"), (ProjectType.DASHBOARD, "dashboard")):
                for admin in (True, False):
                    with self.subTest(project_type=project_type, admin=admin), working_directory(parent):
                        target = start_project(f"{service_name}_{admin}", project_type=project_type, db=DatabaseChoice.SQLITE, admin=admin)
                        seed = read_yaml(target / "data" / f"{service_name}_settings.yaml")
                        service = (target / "services" / f"{service_name}.py").read_text(encoding="utf-8")
                        compile(service, f"{service_name}.py", "exec")

                        if project_type == ProjectType.DASHBOARD:
                            expected = ["oldman.auth", "oldman.apps.roles", "oldman.web.messages.notifications"]
                            expected += ["oldman.apps.admin"] if admin else []
                            expected += ["apps.accounts", "apps.home"]
                            # A dashboard signs its own users in: sessions are on either way.
                            sessions = True
                        else:
                            expected = ["oldman.auth", "oldman.apps.roles", "oldman.apps.admin", "apps.accounts"] if admin else []
                            expected += ["apps.home"]
                            sessions = admin
                        self.assertEqual(expected, seed["apps"])
                        self.assertEqual(sessions, seed.get("web") == {"session": {"enabled": True}})
                        # Wherever there are users they are the project's own model, as on a dashboard.
                        has_users = sessions
                        self.assertEqual(has_users, seed.get("app_settings") == {"auth": {"user_model": "apps.accounts.models.User"}})
                        self.assertEqual(has_users, (target / "apps" / "accounts" / "models.py").is_file())
                        self.assertEqual(has_users, (target / "apps" / "accounts" / "migrations" / "__init__.py").is_file())
                        # The account pages are the dashboard's; the Admin brings its own.
                        self.assertEqual(project_type == ProjectType.DASHBOARD, (target / "apps" / "accounts" / "routes.py").is_file())
                        if has_users:
                            compile((target / "apps" / "accounts" / "models.py").read_text(encoding="utf-8"), "models.py", "exec")
                        self.assertEqual(admin, "from oldman.apps.admin import install_admin\n" in service)
                        self.assertEqual(1 if admin else 0, service.count("install_admin(app)"))

            with working_directory(parent):
                with self.assertRaisesRegex(ValueError, "Only web and dashboard"):
                    start_project("api_admin", project_type=ProjectType.API, db=DatabaseChoice.SQLITE, admin=True)
                with self.assertRaisesRegex(ValueError, "database"):
                    start_project("web_admin_no_db", project_type=ProjectType.WEB, db=DatabaseChoice.NONE, admin=True)
            self.assertFalse((parent / "api_admin").exists())

    def test_the_admin_question_is_asked_only_where_it_can_be_answered_yes(self) -> None:
        """A web project without a database is not asked; API projects never are."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            cases = (("web", "sqlite", True), ("web", "none", False), ("dashboard", "sqlite", True), ("api", "sqlite", False))
            for project_type, database, asked in cases:
                with self.subTest(project_type=project_type, database=database), working_directory(parent):
                    env = {
                        "OLDMAN_ANSWER_STARTPROJECT_TYPE": project_type,
                        "OLDMAN_ANSWER_STARTPROJECT_DATABASE": database,
                        "OLDMAN_ANSWER_STARTPROJECT_ADMIN": "yes",
                    }
                    result = CliRunner().invoke(scaffold_cli(), ["startproject", f"{project_type}_{database}"], env=env)
                self.assertEqual(0, result.exit_code, result.output)
                self.assertEqual(asked, "OLDMAN_ANSWER_STARTPROJECT_ADMIN" in result.output, result.output)
                apps = read_yaml(parent / f"{project_type}_{database}" / "data" / f"{SERVICE_NAMES[ProjectType(project_type)]}_settings.yaml")["apps"]
                self.assertIsInstance(apps, list)
                assert isinstance(apps, list)
                self.assertEqual(asked, "oldman.apps.admin" in apps)

    def test_gitignore_excludes_service_settings(self) -> None:
        """Generated projects do not commit service-specific settings, secrets, logs or pid files."""
        for project_type in (ProjectType.SERVICE, ProjectType.API, ProjectType.WEB, ProjectType.DASHBOARD):
            with self.subTest(project_type=project_type), tempfile.TemporaryDirectory() as temporary_directory:
                with working_directory(Path(temporary_directory)):
                    target = start_project("portal", project_type=project_type, db=DatabaseChoice.SQLITE)
                gitignore = (target / ".gitignore").read_text(encoding="utf-8").splitlines()

                self.assertIn("/data/*_settings.yaml", gitignore)
                self.assertNotIn("/data/settings.yaml", gitignore)
                # logging.dir and process.pid_dir default to these; the first command already creates logs/.
                self.assertIn("/logs/", gitignore)
                self.assertIn("/pids/", gitignore)

    def test_collected_static_files_stay_out_of_git(self) -> None:
        """The README's `static collect` leaves nothing untracked: the copies and the manifest are ignored."""
        from oldman.web.staticfiles import collect_project_static

        for project_type in (ProjectType.WEB, ProjectType.DASHBOARD):
            with self.subTest(project_type=project_type), tempfile.TemporaryDirectory() as temporary_directory:
                with working_directory(Path(temporary_directory)):
                    target = start_project("portal", project_type=project_type, db=DatabaseChoice.SQLITE)
                subprocess.run(["git", "init", "-q"], cwd=target, check=True)

                def untracked(project: Path) -> set[str]:
                    status = ["git", "status", "--porcelain", "--untracked-files=all"]
                    return set(subprocess.run(status, cwd=project, check=True, capture_output=True, text=True).stdout.splitlines())

                generated = untracked(target)  # the project's own files, static/.oldman_keep among them
                # The settings' default layout: the project's static folder is also where collect publishes.
                result = collect_project_static(project_directory=target / "static", destination=target / "static")

                self.assertGreater(result.copied, 0)
                self.assertEqual(set(), untracked(target) - generated)

    def test_every_project_tells_agents_how_to_work_on_it(self) -> None:
        """AGENTS.md (CLAUDE.md points at it) has the lines for what was generated, and none for what was not."""
        cases = (
            (ProjectType.CLI, DatabaseChoice.NONE, False),
            (ProjectType.SERVICE, DatabaseChoice.NONE, False),
            (ProjectType.API, DatabaseChoice.NONE, False),
            (ProjectType.WEB, DatabaseChoice.SQLITE, False),
            (ProjectType.WEB, DatabaseChoice.SQLITE, True),
            (ProjectType.DASHBOARD, DatabaseChoice.SQLITE, False),
            (ProjectType.DASHBOARD, DatabaseChoice.SQLITE, True),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for project_type, database, admin in cases:
                name = f"{project_type.value}_{admin}"
                with self.subTest(project_type=project_type, admin=admin), working_directory(parent):
                    target = start_project(name, project_type=project_type, db=database, admin=admin)
                    agents = (target / "AGENTS.md").read_text(encoding="utf-8")

                    self.assertEqual("@AGENTS.md\n", (target / "CLAUDE.md").read_text(encoding="utf-8"))
                    self.assertTrue(agents.startswith(f"# Agent instructions for {name}\n"))
                    self.assertNotIn("{{", agents)
                    self.assertNotIn("{service_name}", agents)
                    self.assertIn("/.oldman-docs/", (target / ".gitignore").read_text(encoding="utf-8").splitlines())
                    self.assertIn("[AGENTS.md](AGENTS.md)", (target / "README.md").read_text(encoding="utf-8"))

                    service = project_type != ProjectType.CLI
                    self.assertEqual(service, "`./run.sh --version`" in agents)
                    self.assertEqual(not service, "`uv run oldman --version`" in agents)
                    # A script project has no guide table, so the API index is its second step.
                    self.assertEqual(service, "\n3. Look up every `oldman` import" in agents)
                    self.assertEqual(not service, "\n2. Look up every `oldman` import" in agents)
                    if service:
                        self.assertIn(f"OLDMAN_ANSWER_STARTAPP_TEMPLATE={project_type.value} ./run.sh startapp", agents)
                    self.assertEqual(project_type == ProjectType.SERVICE, "self.task_manager.spawn" in agents)
                    self.assertEqual(
                        project_type in {ProjectType.API, ProjectType.WEB, ProjectType.DASHBOARD}, "request.app.ctx.tasks.spawn" in agents
                    )
                    self.assertEqual(project_type == ProjectType.API, "`/api/caller`" in agents)
                    self.assertEqual(project_type == ProjectType.DASHBOARD, "`templates/partials/sidebar.html`" in agents)
                    self.assertEqual(project_type == ProjectType.DASHBOARD, "en/agents/dashboard-crud.md" in agents)
                    self.assertEqual(project_type == ProjectType.DASHBOARD, "./run.sh dashboard templates copy" in agents)
                    # The Admin's guide and first account only when it was included; a dashboard always signs users in.
                    self.assertEqual(admin, "zh/agents/admin.md" in agents)
                    self.assertEqual(admin or project_type == ProjectType.DASHBOARD, "createsuperuser" in agents)
                    self.assertEqual(admin or project_type == ProjectType.DASHBOARD, "`apps/accounts/models.py`" in agents)
                    # Agents guessed `await request.json()` and created users from `shell`; the rules answer both.
                    self.assertEqual(
                        project_type in {ProjectType.API, ProjectType.WEB, ProjectType.DASHBOARD}, "the property `request.json`" in agents
                    )
                    self.assertEqual(admin or project_type == ProjectType.DASHBOARD, "createsuperuser --username <name> --noinput" in agents)
                    # `--version` prints a prerelease as its tag is written (0.6.0-rc.1), no longer the Python form.
                    self.assertNotIn("Python form", agents)
                    self.assertIn("`oldman 0.6.0-rc.1` is tag `v0.6.0-rc.1`", agents)

    def test_each_project_type_has_only_its_own_parts(self) -> None:
        """A script project has no services, an API no templates; every README says how to install and start it."""
        with tempfile.TemporaryDirectory() as temporary_directory, working_directory(Path(temporary_directory)):
            projects = {
                ProjectType.CLI: start_project("tool", project_type=ProjectType.CLI),
                ProjectType.SERVICE: start_project("worker", project_type=ProjectType.SERVICE),
                ProjectType.API: start_project("api", project_type=ProjectType.API, db=DatabaseChoice.POSTGRES),
                ProjectType.WEB: start_project("site", project_type=ProjectType.WEB, db=DatabaseChoice.SQLITE),
                ProjectType.DASHBOARD: start_project("desk", project_type=ProjectType.DASHBOARD, db=DatabaseChoice.SQLITE),
            }
            self.assertFalse((projects[ProjectType.CLI] / "services").exists())
            self.assertFalse((projects[ProjectType.API] / "templates").exists())
            for project_type, project in projects.items():
                with self.subTest(project_type=project_type):
                    readme = (project / "README.md").read_text(encoding="utf-8")
                    self.assertIn("uv sync", readme)
                    self.assertIn("uv run python main.py" if project_type == ProjectType.CLI else "./run.sh", readme)

            # startservice adds a service module beside an App the project already has.
            with working_directory(projects[ProjectType.API]):
                start_app("Report API", app_type=AppType.API, display_name="Report API")
                start_service("report_api", service_type=ServiceType.WEB)
            self.assertTrue((projects[ProjectType.API] / "apps" / "report_api" / "apps.py").is_file())
            self.assertTrue((projects[ProjectType.API] / "services" / "report_api.py").is_file())

    def test_every_guide_agents_are_sent_to_is_in_the_docs(self) -> None:
        """A generated AGENTS.md names guides by their path in the docs of the same version."""
        for _applies, row in GUIDES:
            path = row.split("`")[1]
            with self.subTest(path=path):
                self.assertTrue((ROOT / "docs" / "public" / path).is_file())

    def test_two_template_trees_never_write_the_same_file(self) -> None:
        """A path both trees produce is a scaffold bug: nothing is written rather than one copy silently winning."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for tree in ("own", "common"):
                (root / tree).mkdir()
                (root / tree / "AGENTS.md.tpl").write_text(f"from {tree}\n", encoding="utf-8")
            (root / "own" / "README.md.tpl").write_text("readme\n", encoding="utf-8")
            target = root / "project"
            target.mkdir()

            with self.assertRaisesRegex(FileExistsError, "Two template trees both write"):
                copy_template_tree((root / "own", root / "common"), target, context={})
            self.assertEqual([], list(target.iterdir()))

    def test_the_dashboard_skeleton_signs_its_users_in(self) -> None:
        """A generated dashboard has its User model, the account pages, a home page and one menu."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            for admin in (False, True):
                with self.subTest(admin=admin), working_directory(parent):
                    target = start_project(f"desk_{admin}", project_type=ProjectType.DASHBOARD, db=DatabaseChoice.SQLITE, admin=admin)

                    for module in (
                        "apps/accounts/apps.py",
                        "apps/accounts/models.py",
                        "apps/accounts/routes.py",
                        "apps/home/apps.py",
                        "apps/home/views.py",
                        "services/dashboard.py",
                    ):
                        compile((target / module).read_text(encoding="utf-8"), module, "exec")
                    self.assertTrue((target / "apps" / "accounts" / "migrations" / "__init__.py").is_file())

                    routes = (target / "apps" / "accounts" / "routes.py").read_text(encoding="utf-8")
                    for flow in ("LoginFlow(", "AccountFlow(", "UserManagementFlow("):
                        self.assertIn(flow, routes)
                    self.assertEqual(3, routes.count("template_prefix=ACCOUNT_TEMPLATES"))
                    self.assertIn("class User(AbstractUser):", (target / "apps" / "accounts" / "models.py").read_text(encoding="utf-8"))
                    home = (target / "apps" / "home" / "views.py").read_text(encoding="utf-8")
                    self.assertIn('@router.get("/", name="home")\n@login_required()', home)

                    # CSRF and sessions before notifications, notifications before the account pages that link them.
                    service = (target / "services" / "dashboard.py").read_text(encoding="utf-8")
                    order = [
                        service.index(call)
                        for call in (
                            "StatelessCSRFManager(app)",
                            "install_notifications(app)",
                            "install_dashboard_templates(app)",
                            "install_account_pages(app",
                        )
                    ]
                    self.assertEqual(sorted(order), order)
                    self.assertEqual(admin, "install_admin(app)" in service)

                    sidebar = (target / "templates" / "partials" / "sidebar.html").read_text(encoding="utf-8")
                    self.assertIn("{% if can_manage_users(request) %}", sidebar)
                    self.assertIn("account_urls(request)", sidebar)
                    # The Admin entry: only with the Admin, only for staff (its own floor), by route name rather than a path.
                    self.assertEqual(admin, 'url_for("oldman_admin_index")' in sidebar)
                    self.assertEqual(admin, "{% if request.ctx.user.is_staff %}" in sidebar)
                    self.assertNotIn('"/admin"', sidebar)

                    page = (target / "frontend" / "src" / "pages" / "base-page.ts").read_text(encoding="utf-8")
                    self.assertIn("extends DashboardPage", page)
                    self.assertIn("createDashboardComponentLoaders()", page)
                    # The frontend entry: the Tailwind entry, the public runtime, the generated page entries.
                    main = (target / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
                    for fragment in ('"./app.css"', 'from "oldman-web/core"', "import.meta.glob"):
                        self.assertIn(fragment, main)
                    # Tailwind takes the shared styles and icons, the project's generated icons, and scans the Apps' Python.
                    css = (target / "frontend" / "src" / "app.css").read_text(encoding="utf-8")
                    for fragment in ("oldman-web/styles/tailwind.css", "oldman-web/styles/icons.css", "./generated/icons.css", "../../apps/**/*.py"):
                        self.assertIn(fragment, css)
                    readme = (target / "README.md").read_text(encoding="utf-8")
                    for step in ("./run.sh db migrate", "./run.sh dashboard createsuperuser", "./run.sh dashboard static collect", "Redis"):
                        self.assertIn(step, readme)

    def test_the_api_skeleton_signs_programs_in_with_credentials_of_its_own(self) -> None:
        """`/` is open; /api/caller takes an API key, /api/ops HTTP Basic; each project gets new secrets, only in its settings."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            secrets: list[str] = []
            for name in ("first_api", "second_api"):
                with working_directory(parent):
                    target = start_project(name, project_type=ProjectType.API, db=DatabaseChoice.NONE)

                web = read_yaml(target / "data" / "api_settings.yaml")["web"]
                assert isinstance(web, dict)
                auth = web["auth"]
                self.assertEqual(["api_key", "http_basic"], auth["authenticators"])
                project_secrets = [auth["api_keys"]["example"]["secret"], auth["http_basic"]["accounts"]["ops"]]
                for secret in project_secrets:
                    self.assertGreaterEqual(len(secret), 40)
                    # The README, which a project commits, says where the secrets are, never what they are.
                    self.assertNotIn(secret, (target / "README.md").read_text(encoding="utf-8"))
                secrets += project_secrets

                views = (target / "apps" / "home" / "views.py").read_text(encoding="utf-8")
                compile(views, "views.py", "exec")
                self.assertIn('@router.get("/", name="home")\nasync def home(', views)
                self.assertIn('@router.get("/api/caller", name="api_caller")\n@authenticated_by("api_key")', views)
                self.assertIn('@router.get("/api/ops", name="api_ops")\n@authenticated_by("http_basic")', views)
            self.assertEqual(4, len(set(secrets)))

    def test_the_service_skeleton_runs_an_example_loop_until_stopped(self) -> None:
        """main() keeps the service running, a log line a round, until `stop` cancels it."""
        with tempfile.TemporaryDirectory() as temporary_directory, working_directory(Path(temporary_directory)):
            target = start_project("worker", project_type=ProjectType.SERVICE, db=DatabaseChoice.NONE)
            service = (target / "services" / "service.py").read_text(encoding="utf-8")
            readme = (target / "README.md").read_text(encoding="utf-8")

        compile(service, "service.py", "exec")
        self.assertIn("        while True:\n", service)
        self.assertIn("await asyncio.sleep(INTERVAL_SECONDS)", service)
        self.assertIn("./run.sh service stop", readme)
        self.assertNotIn("会立即返回并退出", readme)

    def test_the_web_skeleton_welcomes_at_the_root(self) -> None:
        """`/` is the project's welcome page, open to everyone; base.html takes the request's language."""
        with tempfile.TemporaryDirectory() as temporary_directory, patch.dict(conf.__dict__, {"settings": DefaultSettings()}):
            parent = Path(temporary_directory)
            for admin in (False, True):
                with self.subTest(admin=admin), working_directory(parent):
                    target = start_project(f"site_{admin}", project_type=ProjectType.WEB, db=DatabaseChoice.SQLITE, admin=admin)

                    for module in ("apps/home/apps.py", "apps/home/views.py", "services/web.py"):
                        compile((target / module).read_text(encoding="utf-8"), module, "exec")
                    home = (target / "apps" / "home" / "views.py").read_text(encoding="utf-8")
                    self.assertIn('@router.get("/", name="home")\nasync def home(', home)
                    # The pages need the framework's template lookup and globals, Admin or not.
                    service = (target / "services" / "web.py").read_text(encoding="utf-8")
                    self.assertIn("install_template_loaders(app.ext.environment, settings.web.template.dir)", service)
                    self.assertEqual(admin, "install_admin(app)" in service)

                    # Rendered the way the service's init() sets the environment up.
                    environment = install_template_loaders(Environment(enable_async=True), target / "templates")
                    template_globals(environment)["url_for"] = {"oldman_admin_index": "/control/"}.__getitem__
                    request = SimpleNamespace(ctx=SimpleNamespace(locale="zh-Hans"), cookies={})
                    page = asyncio.run(environment.get_template("home/index.html").render_async(request=request))
                    self.assertIn('<html lang="zh-Hans">', page)
                    self.assertIn(f"<h1>site_{admin}</h1>", page)
                    self.assertIn("data/web_settings.yaml", page)
                    # The Admin link only with the Admin, by route name so it follows the prefix setting.
                    self.assertEqual(admin, '<a href="/control/">' in page)

                    readme = (target / "README.md").read_text(encoding="utf-8")
                    self.assertIn("http://127.0.0.1:17998/` 是欢迎页", readme)
                    self.assertNotIn("没有自动生成页面", readme)

    def test_a_dashboard_app_page_needs_a_signed_in_user_and_the_shared_page_class(self) -> None:
        """startapp's dashboard pages require sign-in; their menu entry belongs in the one sidebar, not in each view."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with working_directory(parent):
                target = start_project("desk", project_type=ProjectType.DASHBOARD, db=DatabaseChoice.SQLITE)
            with working_directory(target):
                start_app("reports", app_type=AppType.DASHBOARD, display_name="Reports")

            view = (target / "apps" / "reports" / "views.py").read_text(encoding="utf-8")
            compile(view, "views.py", "exec")
            self.assertIn('@router.get("/reports", name="reports_index")\n@login_required()', view)
            self.assertNotIn("dashboard_menu_items", view)
            # A dashboard App is a page of the one dashboard service, not a service of its own.
            self.assertFalse((target / "services" / "reports.py").exists())
            page = (target / "frontend" / "src" / "pages" / "reports.ts").read_text(encoding="utf-8")
            self.assertIn('import { BasePage } from "./base-page";', page)
            self.assertIn('setupPage("reports", ReportsPage);', page)
            # Written like the skeleton's home page: "<page> · <site>" in the tab, the shared page head, translatable text.
            template = (target / "templates" / "reports" / "index.html").read_text(encoding="utf-8")
            Environment().parse(template)
            self.assertIn("{% block title %}{{ _('Reports') }} · {{ site_name() }}{% endblock %}", template)
            self.assertIn("{{ page_head(_('Reports')) }}", template)

    def test_dashboard_frontend_and_release_versions_are_preserved(self) -> None:
        """The settings refactor does not replace the established dashboard assets."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            with (
                working_directory(parent),
                patch(
                    "oldman.cli.scaffold.FRAMEWORK_VERSION",
                    "9.8.7",
                ),
            ):
                target = start_project(
                    "control_desk",
                    project_type=ProjectType.DASHBOARD,
                    db=DatabaseChoice.POSTGRES,
                )

            pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
            frontend = (target / "frontend" / "package.json").read_text(encoding="utf-8")
            frontend_package = json.loads(frontend)
            frontend_main = (target / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
            generated_manifest = (target / "frontend" / "src" / "i18n" / "generated.ts").read_text(encoding="utf-8")
            i18n_builder_exists = (target / "scripts" / "build_frontend_i18n.py").exists()
            template_exists = (target / "templates" / "base.html").exists()

        self.assertIn('"oldman>=9.8.7"', pyproject)
        self.assertIn('"oldman-web": "^9.8.7"', frontend)
        # The build tool oldman-web's SCSS is tested with, declared rather than left to hoisting.
        oldman_web = json.loads((ROOT / "frontend/packages/oldman-web/package.json").read_text(encoding="utf-8"))
        self.assertEqual(oldman_web["dependencies"]["sass"], frontend_package["devDependencies"]["sass"])
        self.assertEqual(
            frontend_package["scripts"]["generate:i18n"],
            "../run.sh i18n compile-frontend --service dashboard",
        )
        # 生成的项目用框架的 CLI 构建，自己不留一份编译入口，也不自带 loader 和清单抓取。
        self.assertFalse(i18n_builder_exists)
        self.assertIn('from "./i18n/generated"', frontend_main)
        # The framework's startDashboard does the starting; the entry does not keep its own copy of it.
        self.assertIn('import { startDashboard } from "oldman-web/dashboard";', frontend_main)
        self.assertIn("languagePreferencePath,", frontend_main)
        self.assertNotIn("function startDashboard", frontend_main)
        self.assertNotIn("createI18n", frontend_main)
        self.assertNotIn("loadLanguageManifest", frontend_main)
        # 语言清单是构建产物，但脚手架自带首份，新项目 install + build 就能跑。
        self.assertIn('export const defaultLanguage = "en";', generated_manifest)
        self.assertIn('export const languagePreferencePath = "/preferences/language";', generated_manifest)
        self.assertIn('catalogPath: "i18n/en.json",', generated_manifest)
        self.assertTrue(template_exists)
        root_metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
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
                po_file = target / "locales" / locale / "LC_MESSAGES" / "messages.po"
                po_file.parent.mkdir(parents=True)
                po_file.write_text(
                    "\n".join(
                        (
                            'msgid ""',
                            'msgstr ""',
                            f'"Language: {locale}\\n"',
                            "",
                            'msgid "Loading..."',
                            f'msgstr "{translation}"',
                            "",
                            'msgid "Backend only"',
                            'msgstr "Not for browsers"',
                        )
                    ),
                    encoding="utf-8",
                )

            package_bin = target / "frontend" / "node_modules" / "oldman-web" / "bin"
            package_bin.mkdir(parents=True)
            (package_bin / "oldman-web-i18n.mjs").symlink_to(I18N_CLI)
            # 生成的项目用 `oldman i18n compile-frontend` 构建，这里直接调它的实现。
            build_frontend_catalogs(project_root=target, service="dashboard")

            output = target / "frontend" / "public" / "i18n"
            manifest = (target / "frontend" / "src" / "i18n" / "generated.ts").read_text(encoding="utf-8")
            english = json.loads((output / "en.json").read_text(encoding="utf-8"))
            chinese = json.loads((output / "zh-hans.json").read_text(encoding="utf-8"))
            published = sorted(item.name for item in output.iterdir())

        self.assertIn('export const defaultLanguage = "en";', manifest)
        self.assertIn('export const languagePreferencePath = "/preferences/language";', manifest)
        self.assertIn('code: "en",', manifest)
        self.assertIn('code: "zh-Hans",', manifest)
        # 清单不在 catalog 目录里，发布目录时不会被一起换掉，也不会多出一份运行时 fetch 的文件。
        self.assertEqual(["en.json", "zh-hans.json"], published)
        self.assertEqual(english["messages"]["Loading..."], "Loading...")
        self.assertEqual(chinese["messages"]["Loading..."], "正在加载...")
        self.assertNotIn("Backend only", chinese["messages"])


if __name__ == "__main__":
    unittest.main()
