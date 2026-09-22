"""Oldman Admin static bundle tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from oldman.apps.admin.staticfiles import (
    ADMIN_BUNDLE_NAME,
    ADMIN_STATIC_PATH,
    register_admin_static_bundle,
)
from oldman.web.staticfiles import StaticBundleRegistry


class OldmanAdminStaticBundleTest(unittest.TestCase):
    """验证内置 Admin 静态资源边界。"""

    def test_admin_static_bundle_points_to_collected_directory(self) -> None:
        """oldman:admin bundle 只解析收集后的公开目录。"""
        registry = StaticBundleRegistry()
        collected_root = Path("/srv/example/static")
        bundle = register_admin_static_bundle(
            registry,
            static_root=collected_root,
            static_url="/assets",
        )

        self.assertEqual(ADMIN_BUNDLE_NAME, bundle.name)
        self.assertEqual("/assets/oldman/admin", bundle.static_url)
        self.assertEqual(
            collected_root
            / ADMIN_STATIC_PATH
            / ".vite"
            / "manifest.json",
            bundle.manifest_path,
        )

    def test_admin_dev_bundle_does_not_require_production_static_settings(self) -> None:
        """开发模式只依赖显式 Vite 地址，不应伪造生产静态目录。"""
        registry = StaticBundleRegistry()

        bundle = register_admin_static_bundle(
            registry,
            dev_mode=True,
            dev_server_url="http://127.0.0.1:5173/",
        )

        self.assertEqual("", bundle.static_url)
        self.assertEqual("http://127.0.0.1:5173", bundle.dev_server_url)
        self.assertTrue(bundle.dev_mode)

    def test_admin_dev_bundle_rejects_missing_or_invalid_server_url(self) -> None:
        """开发模式必须提供明确且可用的 HTTP(S) Vite 地址。"""
        for dev_server_url in (
            "",
            "127.0.0.1:5173",
            "ftp://127.0.0.1:5173",
            "http://bad host:5173",
            "http://127.0.0.1:not-a-port",
            "http://127.0.0.1:0",
        ):
            with self.subTest(dev_server_url=dev_server_url):
                with self.assertRaisesRegex(RuntimeError, "dev_server_url"):
                    register_admin_static_bundle(
                        StaticBundleRegistry(),
                        dev_mode=True,
                        dev_server_url=dev_server_url,
                    )

    def test_admin_production_bundle_requires_root_and_url(self) -> None:
        """生产模式缺少收集目录或公开 URL 时必须在注册阶段失败。"""
        with self.assertRaisesRegex(RuntimeError, "settings.web.static.root"):
            register_admin_static_bundle(
                StaticBundleRegistry(),
                static_url="/static",
            )
        with self.assertRaisesRegex(RuntimeError, "settings.web.static.root"):
            register_admin_static_bundle(
                StaticBundleRegistry(),
                static_root=" ",
                static_url="/static",
            )
        with self.assertRaisesRegex(RuntimeError, "settings.web.static.root"):
            register_admin_static_bundle(
                StaticBundleRegistry(),
                static_root=Path("/srv/example/static"),
            )

    def test_admin_frontend_build_contract(self) -> None:
        """Admin npm app 必须输出到框架静态命名空间并使用 oldman-web。"""
        package = json.loads(Path("frontend/apps/admin/package.json").read_text(encoding="utf-8"))
        vite_config = Path("frontend/apps/admin/vite.config.ts").read_text(encoding="utf-8")
        main_source = Path("frontend/apps/admin/src/main.ts").read_text(encoding="utf-8")
        css_source = Path("frontend/apps/admin/src/admin.css").read_text(encoding="utf-8")

        self.assertEqual("oldman-admin", package["name"])
        self.assertTrue(package["private"])
        self.assertIn(
            "rm -rf ../../../oldman/apps/admin/static/oldman/admin",
            package["scripts"]["clean"],
        )
        self.assertIn(
            "oldman/apps/admin/static/oldman/admin",
            vite_config,
        )
        self.assertIn('base: "./"', vite_config)
        self.assertIn("oldman-web/dashboard", main_source)
        self.assertIn('import "./admin.css"', main_source)
        self.assertIn('oldman-web/styles/tailwind.css', css_source)
        self.assertIn('oldman-web/styles/icons.css', css_source)
        self.assertIn("oldman/apps/admin/templates", css_source)
        # 设计的字重只有 400/500/600（--om-font-weight-regular/medium/semibold），不发没人用的字体文件。
        for weight in (400, 500, 600):
            self.assertIn(f'@fontsource/dm-sans/latin-{weight}.css', css_source)
        for weight in (300, 700):
            self.assertNotIn(f'@fontsource/dm-sans/latin-{weight}.css', css_source)
        self.assertNotIn("/static/oldman-admin/", main_source)

    def test_built_admin_static_manifest_is_allowlisted(self) -> None:
        """构建后的内置 Admin 静态资源不得包含业务页面资产。"""
        static_dir = Path("oldman/apps/admin/static") / ADMIN_STATIC_PATH
        manifest_path = static_dir / ".vite" / "manifest.json"
        self.assertTrue(manifest_path.exists(), "run pnpm --filter oldman-admin build before this gate")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("src/main.ts", manifest)

        files = [path.relative_to(static_dir).as_posix() for path in static_dir.rglob("*") if path.is_file()]
        # manifest 闭包和业务 token 是稳定边界；字体与合法共享 chunk
        # 会改变总字节数，因此不再以单一体积阈值代替来源校验。
        self.assertTrue(any("date-time-picker" in file for file in files))
        self.assertTrue(
            any(
                Path(file).name.startswith("form-")
                and not Path(file).name.startswith("form-validator-")
                for file in files
            )
        )
        self.assertFalse(any("form-modal" in file for file in files))
        self.assertTrue(any("form-validator" in file for file in files))
        self.assertTrue(any("table-filter-form" in file for file in files))
        self.assertTrue(any("dropdown-" in file for file in files))
        for file in files:
            self.assertTrue(file == ".vite/manifest.json" or file.startswith("assets/"), file)
            lower = file.lower()
            for token in ("epg", "channels", "catalog", "logo", "match-decisions", "component-coverage"):
                self.assertNotIn(token, lower)
            self.assertNotIn("apex-chart", lower)

        built_css = "\n".join(path.read_text(encoding="utf-8") for path in static_dir.glob("assets/*.css"))
        built_javascript = "\n".join(path.read_text(encoding="utf-8") for path in static_dir.glob("assets/*.js"))
        self.assertNotIn("/static/oldman-admin/", built_css)
        self.assertNotIn("/static/oldman-admin/", built_javascript)
        self.assertIn(".app-menu", built_css)
        self.assertIn(".oldman-auth-page", built_css)
        self.assertIn(".om-button-primary", built_css)
