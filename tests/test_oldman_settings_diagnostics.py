"""Settings diagnostics report warnings while validation errors remain fatal."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_fresh_python(
    script: str,
    *,
    cwd: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run one diagnostics lifecycle contract in an isolated interpreter."""
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    paths = [str(REPOSITORY_ROOT)]
    if existing_path:
        paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


class SettingsDiagnosticsTest(unittest.TestCase):
    """Separate non-fatal migration advice from invalid YAML."""

    def test_manager_collects_deprecated_key_advice_without_global_output(self) -> None:
        completed = run_fresh_python(
            """
            import contextlib
            import io
            from pathlib import Path

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition

            stderr = io.StringIO()
            definition = ServiceDefinition("worker", Path("services/worker.py"), "simple")
            with contextlib.redirect_stderr(stderr):
                manager = SettingsManager(DefaultSettings, definition, "worker_settings.yaml")
                diagnostics = manager.inspect_diagnostics({"DEBUG": True})

            assert diagnostics == ("deprecated settings key 'DEBUG'; use 'web.debug'",)
            assert stderr.getvalue() == "", stderr.getvalue()
            """
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_setup_prints_simple_admin_warning_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"settings-diagnostics\"\nversion = \"0.0.0\"\n",
                encoding="utf-8",
            )
            config = root / "config"
            config.mkdir()
            (config / "__init__.py").write_text("", encoding="utf-8")
            (config / "schemas.py").write_text(
                "from oldman.conf import DefaultSettings\n\n"
                "class Settings(DefaultSettings):\n"
                "    pass\n",
                encoding="utf-8",
            )
            services = root / "services"
            services.mkdir()
            (services / "worker.py").write_text(
                "from oldman.runtime import SimpleApplication\n\n"
                "class WorkerApplication(SimpleApplication):\n"
                "    pass\n",
                encoding="utf-8",
            )
            package = root / "fake_admin"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "apps.py").write_text(
                textwrap.dedent(
                    """
                    from oldman.apps import AppConfig

                    class AdminConfig(AppConfig):
                        label = "admin"
                        display_name = "Admin"

                    app = AdminConfig()
                    """
                ),
                encoding="utf-8",
            )
            data = root / "data"
            data.mkdir()
            settings_file = data / "worker_settings.yaml"
            settings_file.write_text(
                "apps: [fake_admin]\napp_settings: {}\n",
                encoding="utf-8",
            )
            completed = run_fresh_python(
                """
                from oldman import bootstrap_service

                bootstrap_service("worker")
                """,
                cwd=root,
            )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("Admin", completed.stderr)
        self.assertIn("SimpleApplication", completed.stderr)
        self.assertEqual(1, completed.stderr.count("SimpleApplication"))

    def test_unknown_key_is_a_validation_error_not_a_warning(self) -> None:
        completed = run_fresh_python(
            """
            import tempfile
            from pathlib import Path

            from pydantic import ValidationError

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "worker_settings.yaml"
                path.write_text("mystery: true\\n", encoding="utf-8")
                definition = ServiceDefinition("worker", root / "services/worker.py", "simple")
                manager = SettingsManager(DefaultSettings, definition, path)
                try:
                    manager.load()
                except ValidationError as exc:
                    assert "mystery" in str(exc)
                else:
                    raise AssertionError("unknown settings key was ignored")
            """
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_fatal_missing_yaml_reaches_stderr_without_logging_setup(self) -> None:
        completed = run_fresh_python(
            """
            import tempfile
            from pathlib import Path

            import oldman.conf as conf
            from oldman.conf.manager import SettingsManager
            from oldman.runtime import ServiceDefinition

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                definition = ServiceDefinition("worker", root / "services/worker.py", "simple")
                SettingsManager(
                    conf.DefaultSettings,
                    definition,
                    root / "missing.yaml",
                ).load()
            """
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("SettingsFileMissingError", completed.stderr)
        self.assertIn("missing.yaml", completed.stderr)


if __name__ == "__main__":
    unittest.main()
