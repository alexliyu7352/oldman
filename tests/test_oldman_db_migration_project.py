"""Project-level migration context collection tests."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "9714d0a3-3f2b-48aa-88d7-c0869b2a6f25"


def _migration_api(test_case: unittest.TestCase):
    """Import the migration project API or report an ordinary RED failure."""
    try:
        module = importlib.import_module("oldman.db.migrations")
    except ModuleNotFoundError as exc:
        test_case.fail(f"migration project API is missing: {exc}")
    for name in ("MigrationProject", "ServiceMigrationConfig", "load_migration_project"):
        if not hasattr(module, name):
            test_case.fail(f"migration project API is missing {name}")
    return module


def _pyproject(*, project_id: str | None = PROJECT_ID, migration_apps: tuple[str, ...] = ()) -> str:
    """Build the minimal committed project metadata used by database commands."""
    lines = ['[project]', 'name = "migration-demo"', 'version = "0.1.0"', '', '[tool.oldman]']
    if project_id is not None:
        lines.append(f"project_id = {json.dumps(project_id)}")
    if migration_apps:
        lines.append(f"migration_apps = {json.dumps(migration_apps)}")
    return "\n".join(lines) + "\n"


def _service_source(base: str = "WebApplication") -> str:
    """Return source that cold discovery can classify without importing it."""
    return f"class Service({base}):\n    pass\n"


@contextmanager
def _temporary_project(files: dict[str, str]) -> Iterator[Path]:
    """Create one importable project fixture and remove its modules afterwards."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source), encoding="utf-8")

        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        try:
            yield root
        finally:
            sys.path.remove(str(root))
            package_roots = {
                Path(path).parts[0]
                for path in files
                if "/" in path and Path(path).parts[0] not in {"data", "services"}
            }
            for module_name in tuple(sys.modules):
                if any(module_name == package or module_name.startswith(f"{package}.") for package in package_roots):
                    sys.modules.pop(module_name, None)
            importlib.invalidate_caches()


def _run_python(project_root: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Run Auth and Registry isolation cases in a fresh interpreter."""
    environment = os.environ.copy()
    python_paths = [str(PROJECT_ROOT), str(project_root)]
    existing_path = environment.get("PYTHONPATH")
    if existing_path:
        python_paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _app_source(label: str) -> str:
    """Return a minimal installable AppConfig module."""
    return f"""
        from oldman.apps import AppConfig

        class Config(AppConfig):
            label = {label!r}
            display_name = {label.replace('_', ' ').title()!r}

        app = Config()
    """


class MigrationProjectCollectionTests(unittest.TestCase):
    """Collect all real service Apps without bootstrapping a service."""

    def test_collects_services_deduplicates_apps_and_adds_migration_apps(self) -> None:
        api = _migration_api(self)
        files = {
            "pyproject.toml": _pyproject(migration_apps=("audit_app", "shared_app")),
            "services/api.py": _service_source(),
            "services/web.py": _service_source(),
            "data/api_settings.yaml": "apps: [shared_app, api_app]\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            "data/web_settings.yaml": "apps: [shared_app, web_app]\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
        }
        for package in ("shared_app", "api_app", "web_app", "audit_app"):
            files[f"{package}/__init__.py"] = ""
            files[f"{package}/apps.py"] = _app_source(package)

        with _temporary_project(files) as root:
            project = api.load_migration_project(root)

        self.assertEqual(project.project_root, root.resolve())
        self.assertEqual(project.project_id, UUID(PROJECT_ID))
        self.assertEqual(project.project_name, "migration-demo")
        self.assertEqual(project.database_url, "sqlite+aiosqlite:///data/demo.db")
        self.assertEqual(tuple(item.module_name for item in project.service_configs), ("api", "web"))
        self.assertEqual(set(project.apps.packages), {"shared_app", "api_app", "web_app", "audit_app"})
        self.assertEqual(project.apps.packages.count("shared_app"), 1)
        self.assertIsNone(project.user_model_path)

    def test_lists_every_missing_service_config_at_once(self) -> None:
        api = _migration_api(self)
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(),
                "services/api.py": _service_source(),
                "services/music_web.py": _service_source(),
            }
        ) as root:
            with self.assertRaises(ValueError) as raised:
                api.load_migration_project(root)

        message = str(raised.exception)
        self.assertIn("data/api_settings.yaml", message)
        self.assertIn("data/music_web_settings.yaml", message)

    def test_requires_a_real_service_and_one_nonempty_database_url(self) -> None:
        api = _migration_api(self)
        cases = (
            ({"pyproject.toml": _pyproject()}, "service"),
            (
                {
                    "pyproject.toml": _pyproject(),
                    "services/worker.py": _service_source("SimpleApplication"),
                    "data/worker_settings.yaml": "apps: []\ndatabase:\n  url: ''\n",
                },
                "database.url",
            ),
        )
        for files, expected in cases:
            with self.subTest(expected=expected), _temporary_project(files) as root:
                with self.assertRaisesRegex(ValueError, expected):
                    api.load_migration_project(root)

    def test_rejects_conflicting_urls_without_disclosing_credentials(self) -> None:
        api = _migration_api(self)
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(),
                "services/api.py": _service_source(),
                "services/web.py": _service_source(),
                "data/api_settings.yaml": "apps: []\ndatabase:\n  url: postgresql+asyncpg://alice:api-secret@db/api\n",
                "data/web_settings.yaml": "apps: []\ndatabase:\n  url: postgresql+asyncpg://alice:web-secret@db/web\n",
            }
        ) as root:
            with self.assertRaises(ValueError) as raised:
                api.load_migration_project(root)

        message = str(raised.exception)
        self.assertIn("api", message)
        self.assertIn("web", message)
        self.assertIn("api_settings.yaml", message)
        self.assertIn("web_settings.yaml", message)
        self.assertNotIn("api-secret", message)
        self.assertNotIn("web-secret", message)

    def test_registry_reports_package_and_label_conflicts(self) -> None:
        api = _migration_api(self)
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(),
                "services/api.py": _service_source(),
                "data/api_settings.yaml": "apps: [first_app, second_app]\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
                "first_app/__init__.py": "",
                "first_app/apps.py": _app_source("shared_label"),
                "second_app/__init__.py": "",
                "second_app/apps.py": _app_source("shared_label"),
            }
        ) as root:
            with self.assertRaisesRegex(ValueError, "shared_label.*first_app.*second_app"):
                api.load_migration_project(root)


class MigrationProjectMetadataTests(unittest.TestCase):
    """Read committed project identity without mutating pyproject.toml."""

    def test_reports_missing_project_id_with_a_copyable_uuid_snippet(self) -> None:
        api = _migration_api(self)
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(project_id=None),
                "services/api.py": _service_source(),
                "data/api_settings.yaml": "apps: []\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            }
        ) as root:
            before = (root / "pyproject.toml").read_text(encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                api.load_migration_project(root)
            after = (root / "pyproject.toml").read_text(encoding="utf-8")

        message = str(raised.exception)
        self.assertIn("[tool.oldman]", message)
        marker = 'project_id = "'
        generated = message.split(marker, 1)[1].split('"', 1)[0]
        self.assertIsInstance(UUID(generated), UUID)
        self.assertEqual(before, after)

    def test_rejects_invalid_and_duplicate_project_id_definitions(self) -> None:
        api = _migration_api(self)
        invalid_project = _pyproject(project_id="not-a-uuid")
        duplicate_project = _pyproject() + f'project_id = "{PROJECT_ID}"\n'
        for source, expected in ((invalid_project, "UUID"), (duplicate_project, "project_id")):
            with (
                self.subTest(expected=expected),
                _temporary_project(
                    {
                        "pyproject.toml": source,
                        "services/api.py": _service_source(),
                        "data/api_settings.yaml": "apps: []\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
                    }
                ) as root,
            ):
                with self.assertRaisesRegex(ValueError, expected):
                    api.load_migration_project(root)


class MigrationProjectAuthTests(unittest.TestCase):
    """Resolve the sole schema-changing App setting across all services."""

    def test_accepts_default_and_explicit_equivalent_user_models(self) -> None:
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(),
                "services/api.py": _service_source(),
                "services/web.py": _service_source(),
                "data/api_settings.yaml": "apps: [oldman.auth]\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
                "data/web_settings.yaml": "apps: [oldman.auth]\napp_settings:\n  auth:\n    user_model: ' oldman.auth.models.User '\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            }
        ) as root:
            result = _run_python(
                root,
                """
                from pathlib import Path
                from oldman.db.migrations import load_migration_project

                project = load_migration_project(Path.cwd())
                assert project.user_model_path == "oldman.auth.models.User"
                assert project.apps.packages == ("oldman.auth",)
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_inconsistent_or_orphan_auth_configuration(self) -> None:
        cases = {
            "inconsistent": {
                "services/api.py": _service_source(),
                "services/web.py": _service_source(),
                "data/api_settings.yaml": "apps: [oldman.auth]\napp_settings:\n  auth:\n    user_model: oldman.auth.models.User\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
                "data/web_settings.yaml": "apps: [oldman.auth, custom_users]\napp_settings:\n  auth:\n    user_model: custom_users.models.User\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            },
            "orphan": {
                "services/api.py": _service_source(),
                "data/api_settings.yaml": "apps: []\napp_settings:\n  auth:\n    user_model: oldman.auth.models.User\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            },
        }
        for name, extra_files in cases.items():
            files = {"pyproject.toml": _pyproject(), **extra_files}
            if name == "inconsistent":
                files["custom_users/__init__.py"] = ""
                files["custom_users/apps.py"] = _app_source("custom_users")
            with self.subTest(name=name), _temporary_project(files) as root:
                result = _run_python(
                    root,
                    """
                    from pathlib import Path
                    from oldman.db.migrations import load_migration_project

                    try:
                        load_migration_project(Path.cwd())
                    except ValueError as exc:
                        assert "auth" in str(exc).lower(), str(exc)
                    else:
                        raise AssertionError("invalid Auth project configuration was accepted")
                    """,
                )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_user_model_must_belong_to_each_auth_service_app_list(self) -> None:
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(migration_apps=("custom_users",)),
                "services/api.py": _service_source(),
                "data/api_settings.yaml": "apps: [oldman.auth]\napp_settings:\n  auth:\n    user_model: custom_users.models.User\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
                "custom_users/__init__.py": "",
                "custom_users/apps.py": _app_source("custom_users"),
            }
        ) as root:
            result = _run_python(
                root,
                """
                from pathlib import Path
                from oldman.db.migrations import load_migration_project

                try:
                    load_migration_project(Path.cwd())
                except ValueError as exc:
                    assert "custom_users" in str(exc), str(exc)
                    assert "api" in str(exc), str(exc)
                else:
                    raise AssertionError("custom User App absent from service was accepted")
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_migration_apps_cannot_be_the_only_auth_installation(self) -> None:
        with _temporary_project(
            {
                "pyproject.toml": _pyproject(migration_apps=("oldman.auth",)),
                "services/api.py": _service_source(),
                "data/api_settings.yaml": "apps: []\ndatabase:\n  url: sqlite+aiosqlite:///data/demo.db\n",
            }
        ) as root:
            result = _run_python(
                root,
                """
                from pathlib import Path
                from oldman.db.migrations import load_migration_project

                try:
                    load_migration_project(Path.cwd())
                except ValueError as exc:
                    assert "oldman.auth" in str(exc), str(exc)
                    assert "service" in str(exc).lower(), str(exc)
                else:
                    raise AssertionError("migration-only Auth installation was accepted")
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
