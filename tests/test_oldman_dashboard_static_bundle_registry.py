"""Oldman static bundle registry tests."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from oldman.web.staticfiles import StaticBundle, StaticBundleRegistry, app_bundle_registry, dev_mode_requested, register_project_bundle


class StaticBundleRegistryTest(unittest.TestCase):
    """验证静态资源 bundle registry 的 manifest 解析和边界。"""

    def make_registry(self, manifest: dict[str, object], *, dev_mode: bool = False) -> tuple[StaticBundleRegistry, Path]:
        """Create a registry backed by a temporary manifest."""
        temp_dir = Path(tempfile.mkdtemp())
        manifest_path = temp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        registry = StaticBundleRegistry()
        registry.register(
            StaticBundle(
                name="test:fixture",
                entry_path="src/main.ts",
                manifest_path=manifest_path,
                static_url="/static/test-dist",
                dev_server_url="http://127.0.0.1:5173",
                dev_mode=dev_mode,
            )
        )
        return registry, manifest_path

    def test_registry_renders_css_modulepreload_script_and_manifest_assets(self) -> None:
        """registry 只解析 Vite manifest 资产，不接管收集后的静态文件。"""
        registry, _manifest_path = self.make_registry(
            {
                "src/main.ts": {
                    "file": "assets/main.js",
                    "css": ["assets/main.css"],
                    "imports": ["_vendor.js"],
                },
                "_vendor.js": {
                    "file": "assets/vendor.js",
                    "css": ["assets/vendor.css"],
                },
                "src/logo.svg": {"file": "assets/logo.svg"},
            }
        )

        self.assertEqual(registry.asset_base_url("test:fixture"), "/static/test-dist/")
        self.assertEqual(registry.asset_url("test:fixture", "src/logo.svg"), "/static/test-dist/assets/logo.svg")
        self.assertEqual(
            registry.asset_url(
                "test:fixture",
                "oldman/images/flags/us.svg",
            ),
            "",
        )
        self.assertIn('/static/test-dist/assets/vendor.css', str(registry.styles_tags("test:fixture")))
        self.assertIn('/static/test-dist/assets/main.css', str(registry.styles_tags("test:fixture")))
        self.assertLess(str(registry.styles_tags("test:fixture")).index("vendor.css"), str(registry.styles_tags("test:fixture")).index("main.css"))
        self.assertIn('rel="modulepreload"', str(registry.modulepreload_tags("test:fixture")))
        self.assertIn('/static/test-dist/assets/vendor.js', str(registry.modulepreload_tags("test:fixture")))
        self.assertIn('type="module"', str(registry.script_tags("test:fixture")))
        self.assertIn('/static/test-dist/assets/main.js', str(registry.script_tags("test:fixture")))

    def test_registry_dev_mode_uses_dev_server_without_manifest_tags(self) -> None:
        """开发模式下 registry 应使用 dev server，并不输出生产 CSS/modulepreload。"""
        registry, _manifest_path = self.make_registry({}, dev_mode=True)

        self.assertEqual(registry.asset_base_url("test:fixture"), "http://127.0.0.1:5173/")
        self.assertEqual(registry.asset_url("test:fixture", "src/main.ts"), "http://127.0.0.1:5173/src/main.ts")
        self.assertIn("http://127.0.0.1:5173/@vite/client", str(registry.client_tags("test:fixture")))
        self.assertEqual(str(registry.styles_tags("test:fixture")), "")
        self.assertEqual(str(registry.modulepreload_tags("test:fixture")), "")
        self.assertIn("http://127.0.0.1:5173/src/main.ts", str(registry.script_tags("test:fixture")))

    def test_registry_fails_fast_when_production_manifest_or_entry_is_missing(self) -> None:
        """生产模式缺 manifest 或入口时必须显式失败。"""
        registry = StaticBundleRegistry()
        registry.register(
            StaticBundle(
                name="test:missing",
                entry_path="src/main.ts",
                manifest_path=Path("/tmp/oldman-missing-manifest.json"),
                static_url="/static/test-dist",
            )
        )

        with self.assertRaisesRegex(RuntimeError, "test:missing"):
            registry.ensure_build_available("test:missing")

        registry, _manifest_path = self.make_registry({})
        with self.assertRaisesRegex(RuntimeError, "src/main.ts"):
            registry.ensure_build_available("test:fixture")

    def test_registry_reads_manifest_created_after_an_initial_miss(self) -> None:
        """首次读取缺失 manifest 后，构建生成的 manifest 必须立即可见。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "manifest.json"
            registry = StaticBundleRegistry()
            registry.register(
                StaticBundle(
                    name="test:fixture",
                    entry_path="src/main.ts",
                    manifest_path=manifest_path,
                    static_url="/static/test-dist",
                )
            )

            self.assertEqual({}, registry.load_manifest("test:fixture"))
            manifest_path.write_text(json.dumps({"src/main.ts": {"file": "assets/main.js"}}), encoding="utf-8")

            self.assertEqual("assets/main.js", registry.load_manifest("test:fixture")["src/main.ts"]["file"])

    def test_registry_reloads_updated_manifest_content(self) -> None:
        """构建更新 manifest 后，registry 不得继续返回旧内容。"""
        registry, manifest_path = self.make_registry({"src/main.ts": {"file": "assets/old.js"}})

        self.assertEqual("assets/old.js", registry.load_manifest("test:fixture")["src/main.ts"]["file"])
        manifest_path.write_text(json.dumps({"src/main.ts": {"file": "assets/new.js"}}), encoding="utf-8")

        self.assertEqual("assets/new.js", registry.load_manifest("test:fixture")["src/main.ts"]["file"])

    def test_entry_tags_preserve_modulepreload_stylesheet_script_order(self) -> None:
        """生产入口标签顺序必须固定为 modulepreload、stylesheet、script。"""
        registry, _manifest_path = self.make_registry(
            {
                "src/main.ts": {
                    "file": "assets/main.js",
                    "css": ["assets/main.css"],
                    "imports": ["_vendor.js"],
                },
                "_vendor.js": {"file": "assets/vendor.js"},
            }
        )

        tags = str(registry.entry_tags("test:fixture"))

        self.assertLess(tags.index('rel="modulepreload"'), tags.index('rel="stylesheet"'))
        self.assertLess(tags.index('rel="stylesheet"'), tags.index('type="module"'))

    def test_staticfiles_package_does_not_import_project_modules(self) -> None:
        """oldman.web.staticfiles 不能依赖消费方 app、service 或项目 config。"""
        package_dir = Path("oldman/web/staticfiles")
        imported_modules: set[str] = set()
        for path in package_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.add(node.module)
                elif isinstance(node, ast.Import):
                    imported_modules.update(alias.name for alias in node.names)

        for project_module in ("apps", "services", "config"):
            self.assertFalse(
                any(
                    module == project_module
                    or module.startswith(f"{project_module}.")
                    for module in imported_modules
                ),
                project_module,
            )

    def test_dashboard_scaffold_reads_manifest_from_collected_static_root(
        self,
    ) -> None:
        """Dashboard scaffold validates and uses the collected public root."""
        source = Path("oldman/scaffolds/project/dashboard/services/{{ service_name }}.py.tpl").read_text(encoding="utf-8")

        # The scaffold registers through the framework helper instead of assembling the bundle itself.
        self.assertIn("register_project_bundle(", source)
        self.assertIn("static_root=settings.web.static.root,", source)
        self.assertIn("static_url=settings.web.static.url,", source)
        self.assertIn("dev_mode=dev_mode_requested(),", source)
        self.assertIn("registry.install_template_globals(environment)", source)
        # 启动前两道检查：前端产物在，配置里的语言也都编译过。
        self.assertIn("registry.ensure_build_available(APP_MAIN_BUNDLE)", source)
        self.assertIn("ensure_frontend_catalogs(registry, APP_MAIN_BUNDLE, source_dir=", source)
        self.assertNotIn("StaticBundle(", source)
        self.assertNotIn('settings.web.static.dir / "dist" / ".vite" / "manifest.json"', source)

    def test_project_bundle_helper_reads_the_collected_root_and_fails_without_it(self) -> None:
        """register_project_bundle 读取收集后的 static root，产品模式缺配置立即失败。"""
        registry = StaticBundleRegistry()
        with tempfile.TemporaryDirectory() as directory:
            bundle = register_project_bundle(
                registry,
                name="app:main",
                entry_path="src/main.ts",
                static_root=directory,
                static_url="/static/",
                dev_mode=False,
                passthrough_prefixes=("theme/",),
            )
        self.assertIs(bundle, registry.get("app:main"))
        self.assertEqual(Path(directory) / "dist" / ".vite" / "manifest.json", bundle.manifest_path)
        self.assertEqual("/static/dist", bundle.static_url)
        self.assertEqual(("theme/",), bundle.passthrough_prefixes)

        development = register_project_bundle(registry, name="app:dev", entry_path="src/main.ts", static_root="", static_url="", dev_mode=True, dev_server_url="http://localhost:5173/")
        self.assertEqual(("http://localhost:5173", True), (development.normalized_dev_server_url(), development.dev_mode))
        with self.assertRaisesRegex(RuntimeError, "settings.web.static.root and settings.web.static.url"):
            register_project_bundle(registry, name="app:broken", entry_path="src/main.ts", static_root="", static_url="/static", dev_mode=False)

    def test_dev_mode_flag_and_per_app_registry(self) -> None:
        """OLDMAN_DEV 决定开发模式；同一个 app 只有一个 registry，模板 globals 从它注册。"""
        for value, expected in (("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)):
            self.assertIs(expected, dev_mode_requested({"OLDMAN_DEV": value}))
        self.assertFalse(dev_mode_requested({}))
        # 只认 OLDMAN_DEV：把部署环境名当开关的话，生产进程会去连一个不存在的 Vite dev server。
        self.assertFalse(dev_mode_requested({"OLDMAN_ENV": "development"}))
        self.assertFalse(dev_mode_requested({"OLDMAN_ENV": "development", "OLDMAN_DEV": "0"}))

        app = SimpleNamespace(ctx=SimpleNamespace())
        registry = app_bundle_registry(app)
        self.assertIs(registry, app_bundle_registry(app))
        self.assertIs(registry, app.ctx.static_bundle_registry)

        environment = SimpleNamespace(globals={})
        registry.install_template_globals(environment)
        self.assertEqual(
            {"bundle_asset_base_url", "bundle_asset_url", "bundle_client", "bundle_entry", "bundle_modulepreload", "bundle_script", "bundle_styles"},
            set(environment.globals),
        )


if __name__ == "__main__":
    unittest.main()
