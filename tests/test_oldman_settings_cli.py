"""Service-level settings CLI contracts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from tests.test_oldman_service_cli import _create_project, _run_cli


class OldmanSettingsCliTest(unittest.TestCase):
    """Verify init, sync and check remain explicit cold service commands."""

    def test_task_worker_settings_are_cold_and_disabled_by_default(self) -> None:
        """The dedicated service does not turn settings management into startup."""
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            marker = _create_project(project, worker_settings=False)
            source = project / "services/worker.py"
            source.write_text(source.read_text().replace("SimpleApplication", "TaskiqWorkerApplication"))
            (project / "worker_tools/tasks.py").write_text("raise RuntimeError('Tasks must not be imported here')\n")
            for action in ("init", "sync", "check"):
                result = _run_cli(project, marker, "worker", "settings", action)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            raw = YAML(typ="safe").load(project / "data/worker_settings.yaml")
            self.assertNotIn("web", raw)
            self.assertFalse(raw["taskiq"]["enabled"])
            self.assertFalse(marker.exists())
            result = _run_cli(project, marker, "worker", "start")
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("settings.taskiq.enabled=true", result.stdout + result.stderr)
            self.assertNotIn("Tasks must not be imported", result.stdout + result.stderr)

    def test_init_sync_and_check_use_one_service_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project, worker_settings=False)

            initialized = _run_cli(
                project,
                marker,
                "worker",
                "settings",
                "init",
            )
            synchronized = _run_cli(
                project,
                marker,
                "worker",
                "settings",
                "sync",
            )
            checked = _run_cli(
                project,
                marker,
                "worker",
                "settings",
                "check",
            )
            config_file = project / "data/worker_settings.yaml"
            source = config_file.read_text(encoding="utf-8")

            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            self.assertEqual(0, synchronized.returncode, synchronized.stdout + synchronized.stderr)
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.assertIn("Settings OK", checked.stdout)
            self.assertIn("apps:", source)
            self.assertIn("database:", source)
            self.assertNotIn("_schema_hash", source)
            self.assertFalse(marker.exists())

    def test_init_never_overwrites_an_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            config_file = project / "data/worker_settings.yaml"
            original = config_file.read_text(encoding="utf-8")

            completed = _run_cli(
                project,
                marker,
                "worker",
                "settings",
                "init",
            )

            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("already exists", completed.stderr)
            self.assertEqual(original, config_file.read_text(encoding="utf-8"))
            self.assertFalse(marker.exists())

    def test_explicit_config_is_limited_to_the_selected_service_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            alternate = project / "temporary/worker.yaml"
            alternate.parent.mkdir()
            alternate.write_text(
                "apps: []\napp_settings: {}\ncore:\n  app_name: alternate\n",
                encoding="utf-8",
            )

            checked = _run_cli(
                project,
                marker,
                "worker",
                "settings",
                "check",
                "--config",
                str(alternate),
            )

            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.assertIn(str(alternate), checked.stdout)
            self.assertFalse(marker.exists())

    def test_web_init_writes_nested_web_settings_and_persistent_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)

            completed = _run_cli(
                project,
                marker,
                "music_web",
                "settings",
                "init",
            )
            config_file = project / "data/music_web_settings.yaml"
            parsed = YAML(typ="safe").load(config_file.read_text(encoding="utf-8"))

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("session", parsed["web"])
            self.assertIn("sse", parsed["web"])
            self.assertIn("static", parsed["web"])
            self.assertTrue(parsed["web"]["security"]["secret_key"])
            self.assertTrue(
                parsed["web"]["security"]["fingerprint"]["aes_secret_key"]
            )
            for old_key in ("session", "sse", "template", "static", "frontend"):
                self.assertNotIn(old_key, parsed)
            self.assertFalse(marker.exists())

    def test_init_uses_the_service_example_as_its_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            marker = _create_project(project)
            example = project / "data/music_web_settings.example.yaml"
            example.write_text(
                "apps:\n"
                "  - theme_app\n"
                "core:\n"
                "  app_name: seeded-web\n"
                "web:\n"
                "  listen_port: 18080\n",
                encoding="utf-8",
            )

            completed = _run_cli(
                project,
                marker,
                "music_web",
                "settings",
                "init",
            )
            config_file = project / "data/music_web_settings.yaml"
            parsed = YAML(typ="safe").load(config_file.read_text(encoding="utf-8"))

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(["theme_app"], parsed["apps"])
            self.assertEqual({}, parsed["app_settings"])
            self.assertEqual("seeded-web", parsed["core"]["app_name"])
            self.assertEqual(18080, parsed["web"]["listen_port"])
            self.assertIn("database", parsed)
            self.assertTrue(parsed["web"]["security"]["secret_key"])
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
