"""Behavior tests for typed AppConfig metadata and AppRegistry registration."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from oldman.i18n import bind_translations, gettext_lazy, reset_translations

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _apps_api(test_case: unittest.TestCase):
    """Return the new public App API or report a normal RED test failure."""
    module = importlib.import_module("oldman.apps")
    required = (
        "AppConfig",
        "AppNotInstalledError",
        "AppRegistry",
        "AppSettingsNotDefinedError",
        "AppSettingsNotReadyError",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        test_case.fail(f"typed App API is missing: {', '.join(missing)}")
    return module


@contextmanager
def _temporary_packages(sources: dict[str, str]) -> Iterator[Path]:
    """Expose isolated package fixtures without changing production state APIs."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        for relative_path, source in sources.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source), encoding="utf-8")

        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        try:
            yield root
        finally:
            sys.path.remove(str(root))
            package_roots = {Path(path).parts[0] for path in sources}
            for module_name in tuple(sys.modules):
                if any(module_name == package or module_name.startswith(f"{package}.") for package in package_roots):
                    sys.modules.pop(module_name, None)
            importlib.invalidate_caches()


def _run_python(project_root: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Run mapper-affecting registry cases in a fresh interpreter."""
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    python_paths = [str(PROJECT_ROOT)]
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


class _FailingCatalog:
    """Prove metadata registration does not resolve a lazy display name."""

    def gettext(self, message: str) -> str:
        raise AssertionError(f"translated too early: {message}")

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        raise AssertionError(f"translated too early: {singular}, {plural}, {n}")

    def pgettext(self, context: str, message: str) -> str:
        raise AssertionError(f"translated too early: {context}, {message}")


class ReportsSettings(BaseModel):
    """Small strongly typed App settings fixture."""

    page_size: int = 50


if TYPE_CHECKING:
    from oldman.apps import AppConfig

    class _TypedReportsConfig(AppConfig[ReportsSettings]):
        label = "typed_reports"
        display_name = "Typed reports"
        settings_model = ReportsSettings

    def _typed_page_size(app: _TypedReportsConfig) -> int:
        """Keep the concrete ``app.settings`` return type under Pyright."""
        return app.settings.page_size


class AppConfigTests(unittest.TestCase):
    """Verify AppConfig owns stable metadata and typed settings access."""

    def test_defaults_and_lazy_display_name_do_not_resolve_during_init(self) -> None:
        api = _apps_api(self)
        lazy_display_name = gettext_lazy("Reports")

        class ReportsConfig(api.AppConfig[ReportsSettings]):
            label = "acme_reports"
            display_name = lazy_display_name
            settings_model = ReportsSettings

        token = bind_translations(_FailingCatalog())
        try:
            app = ReportsConfig()
        finally:
            reset_translations(token)

        self.assertIs(app.display_name, lazy_display_name)
        self.assertEqual(app.icon, "ri-database-2-line")
        self.assertEqual(app.models_module, "models")
        self.assertEqual(app.migrations_module, "migrations")
        self.assertEqual(app.web_module, "views")
        self.assertEqual(app.commands_module, "commands")
        self.assertEqual(app.tasks_module, "tasks")
        self.assertEqual(app.events_module, "events")
        with self.assertRaises(api.AppNotInstalledError):
            _ = app.settings

    def test_rejects_invalid_labels_display_names_icons_and_modules(self) -> None:
        api = _apps_api(self)
        valid = {
            "label": "reports",
            "display_name": "Reports",
        }
        invalid_values = (
            ("label", "", "label"),
            ("label", "Reports", "label"),
            ("label", "acme-reports", "label"),
            ("display_name", "", "display_name"),
            ("display_name", 7, "display_name"),
            ("icon", "ri-file chart-line", "icon"),
            ("icon", "<i class='ri-file-line'>", "icon"),
            ("icon", "fa-file", "icon"),
            ("models_module", None, "models_module"),
            ("migrations_module", "", "migrations_module"),
            ("web_module", ".views", "web_module"),
            ("commands_module", "commands-py", "commands_module"),
            ("tasks_module", None, "tasks_module"),
            ("tasks_module", "../tasks", "tasks_module"),
            ("events_module", None, "events_module"),
            ("events_module", "../events", "events_module"),
        )

        for field, value, message in invalid_values:
            with self.subTest(field=field, value=value):
                attributes = {**valid, field: value}
                config_class = type("InvalidConfig", (api.AppConfig,), attributes)
                with self.assertRaisesRegex((TypeError, ValueError), message):
                    config_class()

    def test_accepts_supported_icon_prefixes(self) -> None:
        api = _apps_api(self)
        for icon in (
            "ri-file-chart-line",
            "mdi-database-outline",
            "bx-server",
            "bxs-user",
            "bxl-python",
        ):
            with self.subTest(icon=icon):
                config_class = type(
                    "IconConfig",
                    (api.AppConfig,),
                    {
                        "label": "icons",
                        "display_name": "Icons",
                        "icon": icon,
                    },
                )
                self.assertEqual(config_class().icon, icon)


class AppRegistryTests(unittest.TestCase):
    """Verify Registry imports only App metadata and preserves registration order."""

    def test_registers_packages_and_binds_the_typed_settings_instance(self) -> None:
        api = _apps_api(self)
        with _temporary_packages(
            {
                "acme_reports/__init__.py": "",
                "acme_reports/apps.py": """
                    from pydantic import BaseModel
                    from oldman.apps import AppConfig
                    from oldman.i18n import gettext_lazy as _

                    class ReportsSettings(BaseModel):
                        page_size: int = 50

                    class ReportsConfig(AppConfig[ReportsSettings]):
                        label = "acme_reports"
                        display_name = _("Reports")
                        icon = "ri-file-chart-line"
                        settings_model = ReportsSettings

                    app = ReportsConfig()
                """,
                "acme_reports/models.py": 'raise RuntimeError("models loaded during registration")',
                "acme_reports/views.py": 'raise RuntimeError("views loaded during registration")',
                "audit_log/__init__.py": "",
                "audit_log/apps.py": """
                    from oldman.apps import AppConfig

                    class AuditConfig(AppConfig):
                        label = "audit_log"
                        display_name = "Audit log"

                    app = AuditConfig()
                """,
            }
        ):
            registry = api.AppRegistry()
            registry.register_packages(("acme_reports", "audit_log"))

            self.assertEqual(registry.packages, ("acme_reports", "audit_log"))
            self.assertEqual(registry.labels, ("acme_reports", "audit_log"))
            reports = registry.get_by_package("acme_reports")
            self.assertIs(reports, registry.get_by_label("acme_reports"))
            self.assertEqual(reports.icon, "ri-file-chart-line")
            with self.assertRaises(api.AppSettingsNotReadyError):
                _ = reports.settings

            settings = reports.settings_model(page_size=75)
            registry.bind_settings("acme_reports", settings)

            self.assertIs(reports.settings, settings)
            self.assertEqual(reports.settings.page_size, 75)
            with self.assertRaises(api.AppSettingsNotDefinedError):
                _ = registry.get_by_label("audit_log").settings
            with self.assertRaises(api.AppNotInstalledError):
                registry.get_by_label("missing")

    def test_rejects_duplicate_packages_and_labels(self) -> None:
        api = _apps_api(self)
        with _temporary_packages(
            {
                "first_app/__init__.py": "",
                "first_app/apps.py": """
                    from oldman.apps import AppConfig

                    class FirstConfig(AppConfig):
                        label = "shared_label"
                        display_name = "First"

                    app = FirstConfig()
                """,
                "second_app/__init__.py": "",
                "second_app/apps.py": """
                    from oldman.apps import AppConfig

                    class SecondConfig(AppConfig):
                        label = "shared_label"
                        display_name = "Second"

                    app = SecondConfig()
                """,
            }
        ):
            registry = api.AppRegistry()
            with self.assertRaisesRegex(ValueError, "first_app.*more than once"):
                registry.register_packages(("first_app", "first_app"))

            with self.assertRaisesRegex(ValueError, "shared_label.*first_app.*second_app"):
                registry.register_packages(("second_app",))

    def test_rejects_missing_or_multiple_public_app_objects(self) -> None:
        api = _apps_api(self)
        cases = {
            "missing_app": """
                from oldman.apps import AppConfig

                class MissingConfig(AppConfig):
                    label = "missing"
                    display_name = "Missing"
            """,
            "multiple_apps": """
                from oldman.apps import AppConfig

                class FirstConfig(AppConfig):
                    label = "first"
                    display_name = "First"

                class SecondConfig(AppConfig):
                    label = "second"
                    display_name = "Second"

                app = FirstConfig()
                secondary_app = SecondConfig()
            """,
        }

        for package, apps_source in cases.items():
            with (
                self.subTest(package=package),
                _temporary_packages(
                    {
                        f"{package}/__init__.py": "",
                        f"{package}/apps.py": apps_source,
                    }
                ),
            ):
                registry = api.AppRegistry()
                with self.assertRaisesRegex(ValueError, rf"{package}.*one public.*app"):
                    registry.register_packages((package,))

    def test_rejects_a_settings_instance_of_the_wrong_type(self) -> None:
        api = _apps_api(self)
        with _temporary_packages(
            {
                "typed_app/__init__.py": "",
                "typed_app/apps.py": """
                    from pydantic import BaseModel
                    from oldman.apps import AppConfig

                    class TypedSettings(BaseModel):
                        enabled: bool = True

                    class TypedConfig(AppConfig[TypedSettings]):
                        label = "typed_app"
                        display_name = "Typed app"
                        settings_model = TypedSettings

                    app = TypedConfig()
                """,
            }
        ):
            registry = api.AppRegistry()
            registry.register_packages(("typed_app",))

            with self.assertRaisesRegex(TypeError, "TypedSettings"):
                registry.bind_settings("typed_app", object())

    def test_rejects_models_imported_by_the_package_root_or_apps_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            package_root = project_root / "premature_app"
            package_root.mkdir()
            (package_root / "__init__.py").write_text(
                textwrap.dedent(
                    """
                    from sqlalchemy.orm import Mapped, mapped_column
                    from oldman.db.models import DatabaseModel

                    class PrematureModel(DatabaseModel):
                        __tablename__ = "premature_app_model"

                        id: Mapped[int] = mapped_column(primary_key=True)
                    """
                ),
                encoding="utf-8",
            )
            (package_root / "apps.py").write_text(
                textwrap.dedent(
                    """
                    from oldman.apps import AppConfig

                    class PrematureConfig(AppConfig):
                        label = "premature_app"
                        display_name = "Premature app"

                    app = PrematureConfig()
                    """
                ),
                encoding="utf-8",
            )

            result = _run_python(
                project_root,
                """
                from oldman.apps import AppRegistry

                try:
                    AppRegistry().register_packages(("premature_app",))
                except RuntimeError as exc:
                    assert "premature_app_model" in str(exc)
                else:
                    raise AssertionError("App metadata imported an ORM model")
                """,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_model_loading_passes_registered_metadata_to_file_lifecycle(self) -> None:
        """模型阶段完成后应把已注册模型交给文件生命周期安装器。"""
        with _temporary_packages(
            {
                "file_app/__init__.py": "",
                "file_app/apps.py": """
                    from oldman.apps import AppConfig

                    class FileConfig(AppConfig):
                        label = "file_app"
                        display_name = "File app"

                    app = FileConfig()
                """,
                "file_app/models.py": """
                    from sqlalchemy.orm import Mapped, mapped_column

                    from oldman.db import DatabaseModel
                    from oldman.storage import file_column

                    class Asset(DatabaseModel):
                        __tablename__ = "registry_file_asset"

                        id: Mapped[int] = mapped_column(primary_key=True)
                        file: Mapped[str] = file_column(upload_to="assets")
                """,
            }
        ) as root:
            result = _run_python(
                root,
                """
                from unittest.mock import patch

                from oldman.apps import AppRegistry

                registry = AppRegistry()
                registry.register_packages(("file_app",))
                with patch("oldman.storage.lifecycle.install_model_file_lifecycle") as install:
                    registry.load_models()

                install.assert_called_once_with(registry.models)
                assert registry.models[0].model.__name__ == "Asset"
                """,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class AppTaskLoadingTests(unittest.TestCase):
    """Task discovery follows registered metadata, not directory scanning."""

    def test_tasks_are_optional_ordered_and_separate_from_views(self) -> None:
        """A configured task module loads once, after its model module."""
        with _temporary_packages({
            "task_app/__init__.py": "order = []",
            "task_app/apps.py": """
                from oldman.apps import AppConfig
                class Config(AppConfig):
                    label = "task_app"
                    display_name = "Task app"
                    tasks_module = "jobs"
                app = Config()
            """,
            "task_app/models.py": "from task_app import order; order.append('models')",
            "task_app/jobs.py": "from task_app import order; order.append('tasks')",
            "task_app/views.py": "raise AssertionError('Worker must not import views')",
            "empty_app/__init__.py": "",
            "empty_app/apps.py": """
                from oldman.apps import AppConfig
                class Config(AppConfig):
                    label = "empty_app"
                    display_name = "No tasks"
                app = Config()
            """,
        }) as root:
            result = _run_python(root, """
                import sys
                from oldman.apps import AppRegistry
                from task_app import order
                registry = AppRegistry()
                registry.register_packages(("task_app", "empty_app"))
                assert not order and "task_app.jobs" not in sys.modules
                try:
                    registry.load_tasks()
                except RuntimeError as error:
                    assert "models must be loaded" in str(error)
                else:
                    raise AssertionError("Tasks loaded before models")
                registry.load_models()
                assert order == ["models"]
                registry.load_tasks()
                registry.load_tasks()
                assert order == ["models", "tasks"]
                assert "task_app.views" not in sys.modules
            """)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_existing_task_module_errors_and_late_models_are_not_ignored(self) -> None:
        """Missing dependencies are real failures, unlike an absent tasks.py."""
        for body, exception, message in (
            ("import task_app_missing_dependency", "ModuleNotFoundError", "task_app_missing_dependency"),
            ("""
                from sqlalchemy.orm import Mapped, mapped_column
                from oldman.db import DatabaseModel
                class Late(DatabaseModel):
                    __tablename__ = "task_app_late_model"
                    id: Mapped[int] = mapped_column(primary_key=True)
            """, "RuntimeError", "Registry model stage"),
        ):
            with self.subTest(exception=exception), _temporary_packages({
                "task_app/__init__.py": "",
                "task_app/apps.py": """
                    from oldman.apps import AppConfig
                    class Config(AppConfig):
                        label = "task_app"
                        display_name = "Task app"
                    app = Config()
                """,
                "task_app/tasks.py": body,
            }) as root:
                result = _run_python(root, f"""
                    from oldman.apps import AppRegistry
                    registry = AppRegistry()
                    registry.register_packages(("task_app",))
                    registry.load_models()
                    try:
                        registry.load_tasks()
                    except {exception} as error:
                        assert {message!r} in str(error), error
                    else:
                        raise AssertionError("Task module failure was hidden")
                """)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class AppEventLoadingTests(unittest.TestCase):
    """Events use the existing precise loader, without implicit runtime startup."""

    def test_events_load_once_after_models_without_network(self) -> None:
        """Registered custom/default modules load; missing and uninstalled Apps do not."""
        with _temporary_packages({
            "event_app/__init__.py": "order = []",
            "event_app/apps.py": '''
                from oldman.apps import AppConfig
                class Config(AppConfig):
                    label = "event_app"
                    display_name = "Event app"
                    events_module = "handlers"
                app = Config()
            ''',
            "event_app/models.py": "from event_app import order; order.append('models')",
            "event_app/handlers.py": '''
                from event_app import order
                from oldman.providers.nats import bus
                order.append('events')
                @bus.subscriber("status", peer=True)
                async def status(value: int) -> int:
                    return value
            ''',
            "event_app/views.py": "raise AssertionError('Events must not import views')",
            "empty_app/__init__.py": "",
            "empty_app/apps.py": '''
                from oldman.apps import AppConfig
                class Config(AppConfig):
                    label = "empty_app"
                    display_name = "No events"
                app = Config()
            ''',
            "uninstalled/__init__.py": "",
            "uninstalled/events.py": "raise AssertionError('App is not installed')",
        }) as root:
            result = _run_python(root, '''
                import sys
                from unittest.mock import patch
                from oldman.apps import AppRegistry
                from event_app import order
                with patch("socket.socket", side_effect=AssertionError("declaration connected")):
                    registry = AppRegistry()
                    registry.register_packages(("event_app", "empty_app"))
                    assert not order
                    try:
                        registry.load_events()
                    except RuntimeError as error:
                        assert "models must be loaded" in str(error)
                    else:
                        raise AssertionError("Events loaded before models")
                    registry.load_models()
                    assert order == ["models"]
                    registry.load_events()
                    registry.load_events()
                    assert order == ["models", "events"]
                    assert "uninstalled.events" not in sys.modules
                    assert "event_app.views" not in sys.modules
            ''')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_event_import_errors_and_late_models_propagate(self) -> None:
        """An existing events module must not hide dependencies or declare tables."""
        for body, exception, message in (
            ("import missing_event_dependency", "ModuleNotFoundError", "missing_event_dependency"),
            ('''
                from sqlalchemy.orm import Mapped, mapped_column
                from oldman.db import DatabaseModel
                class Late(DatabaseModel):
                    __tablename__ = "late_event_table"
                    id: Mapped[int] = mapped_column(primary_key=True)
            ''', "RuntimeError", "Registry model stage"),
        ):
            with self.subTest(exception=exception), _temporary_packages({
                "event_app/__init__.py": "",
                "event_app/apps.py": '''
                    from oldman.apps import AppConfig
                    class Config(AppConfig):
                        label = "event_app"
                        display_name = "Event app"
                    app = Config()
                ''',
                "event_app/events.py": body,
            }) as root:
                result = _run_python(root, f'''
                    from oldman.apps import AppRegistry
                    registry = AppRegistry()
                    registry.register_packages(("event_app",))
                    registry.load_models()
                    try:
                        registry.load_events()
                    except {exception} as error:
                        assert {message!r} in str(error), error
                    else:
                        raise AssertionError("Event module failure was hidden")
                ''')
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
