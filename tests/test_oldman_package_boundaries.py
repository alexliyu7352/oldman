"""Oldman 包边界门禁测试。"""

from __future__ import annotations

import ast
import asyncio
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hatchling.builders.sdist import SdistBuilder
from hatchling.builders.wheel import WheelBuilder

from scripts import verify_oldman_boundaries

ROOT = Path(__file__).resolve().parents[1]


class OldmanPackageBoundariesTest(unittest.TestCase):
    """验证 Oldman 命名空间和静态边界。"""

    def test_boundary_gate_passes(self) -> None:
        """当前包骨架必须满足任务 2 的边界规则。"""
        self.assertEqual([], verify_oldman_boundaries.validate_boundaries())

    def test_public_runtime_exports_cover_bootstrap_without_sanic_names(self) -> None:
        """Runtime 入口同时提供生命周期与服务启动能力，但不泄漏 Sanic 命名。"""
        from oldman.runtime import __all__ as runtime_exports

        self.assertEqual(
            [
                "BaseApplication",
                "ServiceBootstrapContext",
                "ServiceDefinition",
                "SimpleApplication",
                "TaskiqWorkerApplication",
                "TaskiqSchedulerApplication",
                "WebApplication",
                "bootstrap_service",
                "discover_service_definitions",
                "get_service_definition",
                "load_service_class",
            ],
            runtime_exports,
        )
        self.assertFalse(any("Sanic" in name for name in runtime_exports))

    def test_simple_application_preserves_cache_lifecycle(self) -> None:
        """Service 和 command 钩子必须按所有权顺序关闭 Cache 资源。"""
        import oldman.conf as conf

        with patch.object(conf, "legacy_settings", SimpleNamespace(), create=True):
            from oldman.runtime import simple

        class SimpleApplicationProbe(simple.SimpleApplication):
            def prepare(self) -> None:
                pass

            async def main(self, *args: object, **kwargs: object) -> None:
                pass

        application = object.__new__(SimpleApplicationProbe)
        application.app_name = "cache-command-lifecycle"
        order: list[str] = []
        with (
            patch.object(simple.memory_cache, "close", new=AsyncMock(side_effect=lambda: order.append("memory"))),
            patch.object(simple.redis_client, "close", new=AsyncMock(side_effect=lambda: order.append("redis"))),
        ):
            asyncio.run(application.before_start())
            asyncio.run(application.before_command("probe"))
            asyncio.run(application.after_stop())
            asyncio.run(application.after_command("probe"))

        self.assertEqual(["memory", "redis", "memory", "redis"], order)

    def test_cli_discovery_uses_services_convention(self) -> None:
        """公开 inspection helper 必须委托正式 CLI 使用的冷 discovery。"""
        from oldman.cli.discovery import discover_services

        definition = SimpleNamespace(module_name="demo")
        with patch(
            "oldman.cli._service_discovery.discover_service_definitions",
            return_value={"demo": definition},
        ) as discover:
            self.assertEqual(discover_services(), {"demo": definition})
        discover.assert_called_once()
        source = (verify_oldman_boundaries.OLDMAN_ROOT / "cli" / "discovery.py").read_text(encoding="utf-8")
        self.assertNotIn("importlib", source)
        self.assertNotIn("pkgutil", source)

    def test_dashboard_python_package_is_absent(self) -> None:
        """Dashboard 只能是前端入口或脚手架类型，不能是 Python 包。"""
        self.assertFalse((verify_oldman_boundaries.OLDMAN_ROOT / "dashboard").exists())

    def test_web_auth_is_the_only_public_permission_module(self) -> None:
        """Web Auth must own permission decorators without a reverse alias module."""
        from oldman.web.auth import login_required, staff_required, superuser_required
        from oldman.web.auth.decorators import login_required as implementation_login_required

        self.assertIs(login_required, implementation_login_required)
        self.assertTrue(callable(staff_required))
        self.assertTrue(callable(superuser_required))
        self.assertFalse((verify_oldman_boundaries.OLDMAN_ROOT / "web" / "permissions.py").exists())

    def test_static_data_and_staticfiles_code_are_separate(self) -> None:
        """Static data has no Python package while staticfiles owns the API."""
        from oldman.web.staticfiles import StaticBundle, StaticBundleRegistry

        static_directory = verify_oldman_boundaries.OLDMAN_ROOT / "web" / "static"
        self.assertTrue(static_directory.is_dir())
        self.assertFalse((static_directory / "__init__.py").exists())
        self.assertEqual("StaticBundle", StaticBundle.__name__)
        self.assertEqual("StaticBundleRegistry", StaticBundleRegistry.__name__)

    def test_storage_core_does_not_depend_on_sanic_or_oldman_web(self) -> None:
        """Only the private media installer may cross into the Web framework."""
        storage_root = verify_oldman_boundaries.OLDMAN_ROOT / "storage"
        violations: list[str] = []

        for path in sorted(storage_root.rglob("*.py")):
            if path.name == "_web.py":
                continue
            relative = path.relative_to(verify_oldman_boundaries.OLDMAN_ROOT)
            package_parts = relative.with_suffix("").parts
            package = ".".join(("oldman", *package_parts[:-1]))
            imports = verify_oldman_boundaries.imported_modules(
                ast.parse(path.read_text(encoding="utf-8")),
                package=package,
            )
            forbidden = sorted(
                dependency
                for dependency in imports
                if dependency == "sanic" or dependency.startswith("sanic.") or dependency == "oldman.web" or dependency.startswith("oldman.web.")
            )
            if forbidden:
                violations.append(f"{relative}: {', '.join(forbidden)}")

        self.assertEqual([], violations)

    def test_storage_modules_ship_in_wheel_and_source_distribution(self) -> None:
        required = {
            "oldman/storage/__init__.py",
            "oldman/storage/_web.py",
            "oldman/storage/base.py",
            "oldman/storage/exceptions.py",
            "oldman/storage/registry.py",
            "oldman/storage/streams.py",
            "oldman/storage/backends/__init__.py",
            "oldman/storage/backends/filesystem.py",
            "oldman/storage/backends/memory.py",
        }
        project_root = verify_oldman_boundaries.ROOT

        with tempfile.TemporaryDirectory() as output_directory:
            wheel_path = Path(
                next(
                    WheelBuilder(str(project_root)).build(
                        directory=output_directory,
                        versions=["standard"],
                    )
                )
            )
            source_path = Path(
                next(
                    SdistBuilder(str(project_root)).build(
                        directory=output_directory,
                        versions=["standard"],
                    )
                )
            )

            with zipfile.ZipFile(wheel_path) as archive:
                wheel_files = set(archive.namelist())
            with tarfile.open(source_path, mode="r:gz") as archive:
                source_files = {"/".join(Path(name).parts[1:]) for name in archive.getnames()}

        self.assertLessEqual(required, wheel_files)
        self.assertLessEqual(required, source_files)

    def test_relative_import_is_not_misclassified_as_a_consumer_root(self) -> None:
        """An internal ``.services`` import is not the project's top-level services package."""
        tree = ast.parse("from .services import load_user\n")

        self.assertEqual(set(), verify_oldman_boundaries.imported_modules(tree))
        self.assertEqual(set(), verify_oldman_boundaries.top_level_imports(tree))
        self.assertEqual(
            {"oldman.admin.auth.services"},
            verify_oldman_boundaries.imported_modules(tree, package="oldman.admin.auth"),
        )

    def test_absolute_consumer_root_import_remains_visible(self) -> None:
        """The boundary gate must still detect genuine convention-package imports."""
        tree = ast.parse("from services.users import load_user\n")

        self.assertEqual({"services.users"}, verify_oldman_boundaries.imported_modules(tree))
        self.assertEqual({"services.users"}, verify_oldman_boundaries.top_level_imports(tree))

    def test_relative_imports_resolve_for_cross_package_boundary_checks(self) -> None:
        """Relative syntax must not become a loophole around framework layer checks."""
        tree = ast.parse("from ...admin import AdminSite\n")

        self.assertEqual(
            {"oldman.admin"},
            verify_oldman_boundaries.imported_modules(tree, package="oldman.web.forms"),
        )

    def test_core_safe_layers_reject_recursive_and_relative_web_cache_dependencies(self) -> None:
        tampered_cases = (
            ("conf/schemas.py", "from oldman.cache.redis import RedisCache\n", "oldman.cache.redis"),
            ("i18n/registry.py", "from ..web import response\n", "oldman.web"),
            ("utils/collections_utils.py", "from PIL import Image\n", "PIL"),
        )
        for relative, source, dependency in tampered_cases:
            with self.subTest(relative=relative):
                path = verify_oldman_boundaries.OLDMAN_ROOT / relative
                tampered = verify_oldman_boundaries.PythonFile(path=path, tree=ast.parse(source))
                with patch.object(verify_oldman_boundaries, "iter_python_files", return_value=[tampered]):
                    errors = verify_oldman_boundaries.validate_boundaries()
                self.assertTrue(any(dependency in error for error in errors), errors)

    def test_moved_capabilities_have_no_legacy_reverse_aliases(self) -> None:
        for relative in verify_oldman_boundaries.FORBIDDEN_MISPLACED_FILES:
            self.assertFalse((verify_oldman_boundaries.ROOT / relative).exists(), relative)

    def test_sse_and_websocket_have_real_public_contracts(self) -> None:
        """SSE 与 WebSocket 入口必须重新导出实际实现，而不是空壳包。"""
        from oldman.web.sse import ServerSentEvent, SSEPublisher, SSEStream
        from oldman.web.websocket import WebSocket, websocket

        self.assertTrue(callable(SSEPublisher))
        self.assertTrue(callable(SSEStream))
        self.assertTrue(callable(ServerSentEvent))
        self.assertTrue(callable(websocket))
        self.assertIsNotNone(WebSocket)

    def test_unconsumed_planning_skeletons_do_not_ship_as_framework_apis(self) -> None:
        removed = (
            "oldman/core/exceptions.py",
            "oldman/core/registry.py",
            "oldman/db/registry.py",
            "oldman/http_client/proxy.py",
            "oldman/http_client/retry.py",
        )

        for relative in removed:
            self.assertFalse((verify_oldman_boundaries.ROOT / relative).exists(), relative)
            self.assertNotIn(relative, verify_oldman_boundaries.REQUIRED_FILES)

    def test_db_services_is_only_an_alias_to_the_migrated_service(self) -> None:
        from oldman.db.services import BaseModelService
        from oldman.db.sqlalchemy.services import BaseModelService as MigratedBaseModelService

        self.assertIs(BaseModelService, MigratedBaseModelService)

    def test_db_schemas_keeps_the_symbols_that_have_consumers(self) -> None:
        """Replaces a migration-completeness guard whose migration finished long ago.

        The old assertion demanded thirteen symbols exist, under a name that read like it
        protected a public API. Its docstring said otherwise - it was there to stop the
        conventional source path being swapped for a reduced facade during a port - and
        once that port landed, its only remaining effect was to pin dead code in place.

        The RateLimit* family it guarded had nothing to do with the framework's actual
        rate limiter, which is Redis and Lua under web/security/rate_limiter: one concept
        with two unrelated representations. It is gone.
        """
        from oldman.db import schemas

        for name in ("PageResult", "TimezoneModel", "UTCDatetimeMixin", "TokenBlacklistBase", "tz_manager"):
            self.assertTrue(hasattr(schemas, name), name)

        for removed in ("RateLimit", "RateLimitBase", "RateLimitCreate", "RateLimitDelete"):
            self.assertFalse(hasattr(schemas, removed), f"{removed} duplicates the real rate limiter")

        self.assertFalse(hasattr(schemas, "Page"))
        self.assertFalse((verify_oldman_boundaries.OLDMAN_ROOT / "db" / "foundation_schemas.py").exists())

    def test_timezone_model_does_not_use_a_removed_pydantic_feature(self) -> None:
        """json_encoders is deprecated since Pydantic 2.0 and goes away in V3."""
        import warnings
        from datetime import UTC, datetime

        from oldman.db.schemas import TimezoneModel

        class Moment(TimezoneModel):
            at: datetime

        self.assertNotIn("json_encoders", TimezoneModel.model_config)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            rendered = Moment(at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC)).model_dump_json()
        self.assertIn("2026-09-20T12:00:00", rendered)

    def test_table_api_is_exported_from_its_component_package(self) -> None:
        import oldman.web as oldman_web
        import oldman.web.components.tables.views as oldman_table_views
        from oldman.web.components.tables import SQLAlchemyTableView

        self.assertIs(SQLAlchemyTableView, oldman_table_views.SQLAlchemyTableView)
        self.assertFalse(hasattr(oldman_web, "SQLAlchemyTableView"))

    def test_package_templates_include_server_component_defaults(self) -> None:
        self.assertTrue((ROOT / "oldman" / "web" / "templates" / "oldman" / "tables" / "default" / "shell.html").is_file())
        self.assertTrue((ROOT / "oldman" / "web" / "templates" / "oldman" / "charts" / "default" / "shell.html").is_file())


if __name__ == "__main__":
    unittest.main()
