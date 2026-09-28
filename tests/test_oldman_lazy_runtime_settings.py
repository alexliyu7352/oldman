"""Settings consumers must read the object published by service bootstrap."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_fresh_project(source: str, settings_yaml: str) -> subprocess.CompletedProcess[str]:
    """Run one settings lifecycle in an isolated project and interpreter."""
    files = {
        "pyproject.toml": "[project]\nname = 'lazy-settings-fixture'\nversion = '0'\n",
        "services/__init__.py": "",
        "services/worker.py": """
            from oldman.runtime import SimpleApplication

            class WorkerApplication(SimpleApplication):
                pass
        """,
        "config/__init__.py": "",
        "config/schemas.py": """
            from oldman.conf import DefaultSettings

            class Settings(DefaultSettings):
                pass
        """,
        "data/worker_settings.yaml": settings_yaml,
    }
    with tempfile.TemporaryDirectory() as temporary_directory:
        project_root = Path(temporary_directory)
        for relative_path, file_source in files.items():
            path = project_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(file_source), encoding="utf-8")

        environment = os.environ.copy()
        existing_path = environment.get("PYTHONPATH")
        paths = [str(ROOT)]
        if existing_path:
            paths.append(existing_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            (sys.executable, "-c", textwrap.dedent(source)),
            cwd=project_root,
            env=environment,
            capture_output=True,
            check=False,
            text=True,
        )


class RuntimeSettingsBindingTest(unittest.TestCase):
    """Protect the eager, single-object settings import contract."""

    def test_bootstrap_publishes_the_same_object_for_both_import_forms(self) -> None:
        completed = run_fresh_project(
            """
            import oldman.conf as conf

            try:
                conf.settings
            except RuntimeError as exc:
                assert "not configured" in str(exc)
            else:
                raise AssertionError("settings must not exist before bootstrap")

            from oldman import bootstrap_service

            context = bootstrap_service("worker")
            from oldman.conf import settings

            assert context.settings is conf.settings
            assert settings is conf.settings
            assert settings.core.app_name == "configured-app"
            """,
            """
                apps: []
                app_settings: {}
                core:
                  app_name: configured-app
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_module_imported_before_bootstrap_reads_settings_published_after(self) -> None:
        """框架模块在 bootstrap 之前被导入,函数体里仍要读到之后发布的设置。

        这是全框架用 `import oldman.conf as conf` + `conf.settings.x` 而不用
        `from oldman.conf import settings` 的原因:后者在导入时就把名字绑死了。
        载体原先是 `oldman.utils.headers`(已删除),换成同一写法的 TimezoneManager。
        """
        completed = run_fresh_project(
            """
            from oldman.utils.timezone import TimezoneManager
            from oldman import bootstrap_service

            manager = TimezoneManager()
            bootstrap_service("worker")

            assert str(manager.get_timezone(None)) == "Asia/Tokyo"
            """,
            """
                apps: []
                app_settings: {}
                core:
                  time_zone: Asia/Tokyo
            """,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
