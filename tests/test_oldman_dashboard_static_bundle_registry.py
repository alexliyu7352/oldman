"""Oldman static bundle registry tests."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from oldman.web.staticfiles import StaticBundle, StaticBundleRegistry


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
        consumer_paths = (
            (
                Path(
                    "oldman/scaffolds/project/dashboard/services/"
                    "{{ service_name }}.py.tpl"
                ),
                'manifest_path=Path(static_root) / "dist" / ".vite" / "manifest.json"',
                "Dashboard production assets require web.static.root",
            ),
        )

        for consumer_path, manifest_expression, error_message in consumer_paths:
            with self.subTest(consumer_path=consumer_path):
                source = consumer_path.read_text(encoding="utf-8")
                self.assertIn(
                    "static_root = str(settings.web.static.root).strip()",
                    source,
                )
                self.assertIn(
                    "static_url = str(settings.web.static.url).strip()",
                    source,
                )
                self.assertIn(
                    "if not dev_mode and (not static_root or not static_url):",
                    source,
                )
                self.assertIn(error_message, source)
                self.assertIn(manifest_expression, source)
                self.assertNotIn(
                    'settings.web.static.dir / "dist" / ".vite" / "manifest.json"',
                    source,
                )


if __name__ == "__main__":
    unittest.main()
