"""Service-scoped YAML generation and two-phase App settings tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from pydantic import ValidationError

from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings
from oldman.runtime import ServiceDefinition
from oldman.runtime.discovery import ApplicationBase

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _service(
    root: Path,
    kind: ApplicationBase,
    name: str = "service",
) -> ServiceDefinition:
    """Build static service metadata without importing a service module."""
    return ServiceDefinition(
        name,
        root / "services" / f"{name}.py",
        kind,
    )


def _run_project(
    files: dict[str, str],
    script: str,
) -> subprocess.CompletedProcess[str]:
    """Run one App/configuration combination in an isolated process."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source), encoding="utf-8")

        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        paths = [str(REPOSITORY_ROOT)]
        if existing_path:
            paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


class SettingsServiceScopeTest(unittest.TestCase):
    """Verify service type selects one fixed subset of the root Settings schema."""

    def test_simple_service_init_omits_only_web(self) -> None:
        for kind in ("simple", "taskiq_worker", "taskiq_scheduler"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                settings_file = root / "data" / "worker_settings.yaml"
                manager = SettingsManager(
                    DefaultSettings,
                    _service(root, kind, "worker"),
                    settings_file,
                )

                manager.init_config()
                raw = manager.read_config()

                self.assertNotIn("web", raw)
                self.assertEqual([], raw["apps"])
                self.assertEqual({}, raw["app_settings"])
                self.assertIn("database", raw)
                self.assertIn("redis", raw)

    def test_web_service_init_includes_web_and_persistent_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "data" / "web_settings.yaml"
            manager = SettingsManager(
                DefaultSettings,
                _service(root, "web", "web"),
                settings_file,
            )

            manager.init_config()
            raw = manager.read_config()

        self.assertIn("web", raw)
        self.assertGreaterEqual(len(raw["web"]["security"]["secret_key"]), 32)
        self.assertTrue(raw["web"]["security"]["fingerprint"]["aes_secret_key"])

    def test_simple_service_preserves_explicit_typed_web_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "worker_settings.yaml"
            settings_file.write_text(
                "web:\n"
                "  request_timeout: 9\n"
                "  security:\n"
                "    token_expire_time: 42\n"
                "  session:\n"
                "    enabled: true\n"
                "    redis_alias: PRIVATE_SESSION\n"
                "  sse:\n"
                "    enabled: true\n"
                "    redis_alias: PRIVATE_SSE\n"
                "    channel_prefix: worker-events\n",
                encoding="utf-8",
            )
            manager = SettingsManager(
                DefaultSettings,
                _service(root, "simple", "worker"),
                settings_file,
            )

            loaded = manager.load()
            manager.sync_config()
            raw = manager.read_config()

        self.assertEqual(9, loaded.web.request_timeout)
        self.assertEqual(42, loaded.web.security.token_expire_time)
        self.assertTrue(loaded.web.session.enabled)
        self.assertEqual("PRIVATE_SESSION", loaded.web.session.redis_alias)
        self.assertTrue(loaded.web.sse.enabled)
        self.assertEqual("PRIVATE_SSE", loaded.web.sse.redis_alias)
        self.assertEqual(
            {
                "request_timeout": 9,
                "security": {"token_expire_time": 42},
                "session": {
                    "enabled": True,
                    "redis_alias": "PRIVATE_SESSION",
                },
                "sse": {
                    "enabled": True,
                    "redis_alias": "PRIVATE_SSE",
                    "channel_prefix": "worker-events",
                },
            },
            raw["web"],
        )

    def test_simple_explicit_web_settings_keep_field_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "worker_settings.yaml"
            settings_file.write_text(
                "web:\n  sse:\n    queue_size: 0\n",
                encoding="utf-8",
            )
            manager = SettingsManager(
                DefaultSettings,
                _service(root, "simple", "worker"),
                settings_file,
            )

            with self.assertRaisesRegex(ValidationError, "queue_size"):
                manager.check_config()


class TwoPhaseAppSettingsTest(unittest.TestCase):
    """Verify raw App membership is resolved before strong App settings validation."""

    def test_apps_keep_yaml_order_and_bind_typed_settings(self) -> None:
        completed = _run_project(
            {
                "reports_app/__init__.py": "",
                "reports_app/apps.py": """
                    from pydantic import BaseModel, ConfigDict
                    from oldman.apps import AppConfig

                    class ReportsSettings(BaseModel):
                        model_config = ConfigDict(extra="forbid")
                        endpoint: str
                        page_size: int = 50

                    class ReportsConfig(AppConfig[ReportsSettings]):
                        label = "reports"
                        display_name = "Reports"
                        settings_model = ReportsSettings

                    app = ReportsConfig()
                """,
                "audit_app/__init__.py": "",
                "audit_app/apps.py": """
                    from oldman.apps import AppConfig

                    class AuditConfig(AppConfig):
                        label = "audit"
                        display_name = "Audit"

                    app = AuditConfig()
                """,
                "data/worker_settings.yaml": """
                    apps:
                      - reports_app
                      - audit_app
                    app_settings:
                      reports:
                        endpoint: https://reports.internal
                """,
            },
            """
            from pathlib import Path

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition
            from reports_app.apps import app as reports_app

            root = Path.cwd()
            definition = ServiceDefinition("worker", root / "services/worker.py", "simple")
            manager = SettingsManager(DefaultSettings, definition, root / "data/worker_settings.yaml")
            settings = manager.load()

            assert settings.apps == ("reports_app", "audit_app")
            assert manager.registry.packages == settings.apps
            assert manager.registry.labels == ("reports", "audit")
            assert manager.app_settings["reports"].page_size == 50
            assert reports_app.settings is manager.app_settings["reports"]
            assert reports_app.settings.endpoint == "https://reports.internal"
            assert "audit" not in manager.app_settings
            assert not hasattr(settings, "app_settings")
            assert not hasattr(settings, "for_app")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_unknown_global_and_uninstalled_app_settings_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_file = root / "worker_settings.yaml"
            manager = SettingsManager(
                DefaultSettings,
                _service(root, "simple", "worker"),
                settings_file,
            )

            settings_file.write_text("mystery: true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "mystery"):
                manager.check_config()

            settings_file.write_text(
                "apps: []\napp_settings:\n  ghost:\n    enabled: true\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "app_settings.ghost.*not installed"):
                manager.check_config()

    def test_app_unknown_and_missing_required_fields_report_the_yaml_path(self) -> None:
        completed = _run_project(
            {
                "required_app/__init__.py": "",
                "required_app/apps.py": """
                    from pydantic import BaseModel
                    from oldman.apps import AppConfig

                    class RequiredSettings(BaseModel):
                        endpoint: str

                    class RequiredConfig(AppConfig[RequiredSettings]):
                        label = "required"
                        display_name = "Required"
                        settings_model = RequiredSettings

                    app = RequiredConfig()
                """,
                "data/worker_settings.yaml": """
                    apps: [required_app]
                    app_settings:
                      required:
                        endpoint: https://example.test
                        mystery: true
                """,
            },
            """
            from pathlib import Path

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition

            root = Path.cwd()
            path = root / "data/worker_settings.yaml"
            definition = ServiceDefinition("worker", root / "services/worker.py", "simple")
            manager = SettingsManager(DefaultSettings, definition, path)

            try:
                manager.check_config()
            except ValueError as exc:
                assert "app_settings.required.mystery" in str(exc), exc
            else:
                raise AssertionError("unknown App field was ignored")

            path.write_text("apps: [required_app]\\napp_settings: {}\\n", encoding="utf-8")
            try:
                manager.check_config()
            except ValueError as exc:
                assert "app_settings.required" in str(exc), exc
                assert "endpoint" in str(exc), exc
            else:
                raise AssertionError("required App field was defaulted")
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


class WebSettingsIntegrationTest(unittest.TestCase):
    """Verify the two explicit Web/App configuration interactions."""

    def test_admin_sync_enables_messages_only_when_user_omitted_the_value(self) -> None:
        completed = _run_project(
            {
                "fake_admin/__init__.py": "",
                "fake_admin/apps.py": """
                    from oldman.apps import AppConfig

                    class AdminConfig(AppConfig):
                        label = "admin"
                        display_name = "Admin"

                    app = AdminConfig()
                """,
                "data/web_settings.yaml": "apps: [fake_admin]\napp_settings: {}\nweb: {}\n",
            },
            """
            from pathlib import Path

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition

            root = Path.cwd()
            path = root / "data/web_settings.yaml"
            definition = ServiceDefinition("web", root / "services/web.py", "web")
            manager = SettingsManager(DefaultSettings, definition, path)

            manager.sync_config()
            assert manager.read_config()["web"]["messages"]["enabled"] is True

            path.write_text(
                "apps: [fake_admin]\\napp_settings: {}\\nweb:\\n  messages:\\n    enabled: false\\n",
                encoding="utf-8",
            )
            manager.sync_config()
            assert manager.read_config()["web"]["messages"]["enabled"] is False
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_admin_on_simple_service_is_a_warning_not_an_error(self) -> None:
        completed = _run_project(
            {
                "fake_admin_simple/__init__.py": "",
                "fake_admin_simple/apps.py": """
                    from oldman.apps import AppConfig

                    class AdminConfig(AppConfig):
                        label = "admin"
                        display_name = "Admin"

                    app = AdminConfig()
                """,
                "data/worker_settings.yaml": "apps: [fake_admin_simple]\napp_settings: {}\n",
            },
            """
            from pathlib import Path

            from oldman.conf.manager import SettingsManager
            from oldman.conf.schemas import DefaultSettings
            from oldman.runtime import ServiceDefinition

            root = Path.cwd()
            path = root / "data/worker_settings.yaml"
            definition = ServiceDefinition("worker", root / "services/worker.py", "simple")
            manager = SettingsManager(DefaultSettings, definition, path)

            manager.check_config()
            assert any("Admin" in message and "SimpleApplication" in message for message in manager.diagnostics)
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_session_and_sse_aliases_are_validated_without_connecting_redis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "web_settings.yaml"
            manager = SettingsManager(
                DefaultSettings,
                _service(root, "web", "web"),
                path,
            )

            path.write_text(
                "web:\n  session:\n    enabled: true\n    redis_alias: MISSING\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "web.session.redis_alias.*MISSING"):
                manager.check_config()

            path.write_text(
                "web:\n  sse:\n    enabled: true\n    redis_alias: MISSING\n    channel_prefix: test\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "web.sse.redis_alias.*MISSING"):
                manager.check_config()

            path.write_text(
                "redis:\n"
                "  MISSING:\n"
                "    redis_url: redis://127.0.0.1:1/0\n"
                "web:\n"
                "  session:\n"
                "    enabled: true\n"
                "    redis_alias: MISSING\n"
                "  sse:\n"
                "    enabled: true\n"
                "    redis_alias: MISSING\n"
                "    channel_prefix: test\n",
                encoding="utf-8",
            )
            manager.sync_config()
            loaded = manager.load()

        self.assertTrue(loaded.web.session.enabled)
        self.assertTrue(loaded.web.sse.enabled)


if __name__ == "__main__":
    unittest.main()
