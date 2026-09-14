"""Unified service bootstrap behavior in isolated project processes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_project(
    source: str,
    *,
    extra_files: dict[str, str] | None = None,
    include_default_settings: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one complete process-scoped bootstrap contract."""
    files = {
        "pyproject.toml": "[project]\nname = 'bootstrap-fixture'\nversion = '0'\n",
        "services/__init__.py": "",
        "services/worker.py": """
            from oldman.runtime import SimpleApplication

            class WorkerApplication(SimpleApplication):
                pass

            raise RuntimeError("bootstrap imported the service module")
        """,
        "config/__init__.py": "",
        "config/schemas.py": """
            from oldman.conf import DefaultSettings

            class Settings(DefaultSettings):
                project_marker: str = "schema-default"
        """,
        "config/settings.py": """
            from typing import cast

            import oldman.conf as conf
            from config.schemas import Settings

            settings = cast(Settings, conf.settings)
        """,
        "reports_app/__init__.py": "",
        "reports_app/apps.py": """
            from pydantic import BaseModel

            from oldman.apps import AppConfig

            class ReportsSettings(BaseModel):
                page_size: int = 20

            class ReportsConfig(AppConfig[ReportsSettings]):
                label = "reports"
                display_name = "Reports"
                settings_model = ReportsSettings

            app = ReportsConfig()
        """,
        "reports_app/models.py": """
            from sqlalchemy.orm import Mapped, mapped_column

            from config.settings import settings
            from oldman.db import DatabaseModel
            from reports_app.apps import app

            assert settings.project_marker == "yaml-value"
            assert app.settings.page_size == 41

            class Report(DatabaseModel):
                __tablename__ = "bootstrap_report"

                id: Mapped[int] = mapped_column(primary_key=True)
        """,
        "reports_app/views.py": 'raise RuntimeError("bootstrap imported views")\n',
    }
    if include_default_settings:
        files["data/worker_settings.yaml"] = """
            apps:
              - reports_app
            app_settings:
              reports:
                page_size: 41
            core:
              app_name: bootstrap-worker
            project_marker: yaml-value
        """
    files.update(extra_files or {})

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        paths = [str(REPOSITORY_ROOT)]
        if existing_path:
            paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


class ServiceBootstrapTest(unittest.TestCase):
    """Protect the one-process, one-service initialization contract."""

    def test_default_bootstrap_publishes_settings_and_loads_only_models(self) -> None:
        completed = _run_project(
            """
            import sys
            from pathlib import Path

            import oldman.conf as conf

            try:
                import config.settings
            except RuntimeError as exc:
                assert "not configured" in str(exc)
            else:
                raise AssertionError("config.settings loaded before bootstrap")

            from oldman import bootstrap_service
            from reports_app.apps import app as reports_app

            context = bootstrap_service("worker")

            assert context.service_module == "worker"
            assert context.config_file == Path.cwd() / "data/worker_settings.yaml"
            assert context.settings is conf.settings
            assert context.settings.core.app_name == "bootstrap-worker"
            assert context.settings.project_marker == "yaml-value"
            assert context.apps.packages == ("reports_app",)
            assert context.apps.get_by_label("reports") is reports_app
            assert reports_app.settings.page_size == 41
            assert "bootstrap_report" in __import__("oldman.db").db.Base.metadata.tables
            table = __import__("oldman.db").db.Base.metadata.tables["bootstrap_report"]
            assert table.info["oldman_app_label"] == "reports"
            assert "reports_app.models" in sys.modules
            assert "reports_app.views" not in sys.modules
            assert "services.worker" not in sys.modules

            from config.settings import settings

            assert settings is context.settings
            assert bootstrap_service("worker") is context
            """
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_explicit_config_path_is_used_for_ide_and_diagnostics(self) -> None:
        completed = _run_project(
            """
            from pathlib import Path

            from oldman import bootstrap_service

            config_file = Path.cwd() / "temporary" / "worker.yaml"
            context = bootstrap_service("worker", config_file=config_file)

            assert context.config_file == config_file
            assert context.settings.core.app_name == "explicit-worker"
            """,
            extra_files={
                "temporary/worker.yaml": """
                    apps: []
                    app_settings: {}
                    core:
                      app_name: explicit-worker
                """,
            },
            include_default_settings=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_missing_default_config_reports_the_service_path(self) -> None:
        completed = _run_project(
            """
            from oldman import bootstrap_service

            try:
                bootstrap_service("worker")
            except RuntimeError as exc:
                assert "data/worker_settings.yaml" in str(exc), str(exc)
            else:
                raise AssertionError("missing settings file was accepted")
            """,
            include_default_settings=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_bootstrapped_process_rejects_another_service_or_config(self) -> None:
        completed = _run_project(
            """
            from pathlib import Path

            from oldman import bootstrap_service

            context = bootstrap_service("worker")
            assert bootstrap_service(
                "worker",
                config_file=Path.cwd() / "data/worker_settings.yaml",
            ) is context

            for service, config_file in (
                ("worker", Path.cwd() / "temporary/worker.yaml"),
                ("other_worker", None),
            ):
                try:
                    bootstrap_service(service, config_file=config_file)
                except RuntimeError as exc:
                    assert "already bootstrapped" in str(exc), str(exc)
                else:
                    raise AssertionError((service, config_file))
            """,
            extra_files={
                "services/other_worker.py": """
                    from oldman.runtime import SimpleApplication

                    class OtherWorkerApplication(SimpleApplication):
                        pass
                """,
                "data/other_worker_settings.yaml": "apps: []\napp_settings: {}\n",
                "temporary/worker.yaml": "apps: []\napp_settings: {}\n",
            },
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
