"""Dashboard 前端框架边界门禁。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from oldman.conf.schemas import I18nConfig

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DASHBOARD = ROOT / "frontend" / "packages" / "oldman-web" / "src" / "dashboard"


class OldmanDashboardBoundaryTest(unittest.TestCase):
    """验证 Dashboard 只作为 oldman-web 前端子入口存在。"""

    def test_no_python_oldman_dashboard_package_or_import(self) -> None:
        """Dashboard 不能成为 oldman.dashboard Python 包。"""
        self.assertFalse((ROOT / "oldman" / "dashboard").exists())

        for path in (ROOT / "oldman").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("oldman.dashboard", source, path.as_posix())

    def test_no_standalone_oldman_dashboard_npm_package(self) -> None:
        """不发布独立 Dashboard npm 包。"""
        for path in ROOT.rglob("package.json"):
            if "node_modules" in path.parts or "dist" in path.parts:
                continue
            package = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(package.get("name"), {"@oldman/dashboard", "oldman-dashboard"}, path.as_posix())

    def test_dashboard_package_does_not_contain_business_components(self) -> None:
        """oldman-web/dashboard 不能包含 EPG/Admin 业务页面组件。"""
        forbidden_tokens = (
            "DashboardOverview",
            "NotificationsCenter",
            "channels-epg",
            "catalog-",
            "logo-assets",
            "match-decisions",
            "component-coverage",
            "epg_admin",
            "oldman_admin",
            "/users",
        )
        for path in PACKAGE_DASHBOARD.rglob("*.ts"):
            source = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                self.assertNotIn(token, source, f"{path.as_posix()} contains {token}")

    def test_dashboard_entry_uses_lazy_heavy_component_loaders(self) -> None:
        """dashboard 入口不得静态导入图表、select、日期选择等重依赖。"""
        forbidden_static_imports = (
            "from \"apexcharts\"",
            "from 'apexcharts'",
            "from \"choices.js\"",
            "from 'choices.js'",
            "from \"flatpickr\"",
            "from 'flatpickr'",
            "import ApexCharts",
            "import Choices",
            "import flatpickr",
        )
        for path in PACKAGE_DASHBOARD.rglob("*.ts"):
            source = path.read_text(encoding="utf-8")
            for token in forbidden_static_imports:
                self.assertNotIn(token, source, f"{path.as_posix()} contains static heavy import {token}")

    def test_framework_dashboard_locale_fallback_matches_framework_default(self) -> None:
        """抽出的通用模板不能继续硬编码 EPG 消费方原先的中文 fallback。"""
        shared_base = (ROOT / "oldman" / "web" / "templates" / "oldman" / "dashboard" / "base.html").read_text(encoding="utf-8")

        self.assertEqual(I18nConfig().default_language, "en")
        self.assertIn("locale | default('en')", shared_base)
        self.assertIn("block dashboard_language", shared_base)

    def test_theme_boot_script_reads_the_bundle_preference_key(self) -> None:
        """head 里的预绘制脚本和 oldman-web 的主题偏好必须读写同一个 localStorage 键。"""
        dashboard_templates = ROOT / "oldman" / "web" / "templates" / "oldman" / "dashboard"
        shared_base = (dashboard_templates / "base.html").read_text(encoding="utf-8")
        theme_boot = (dashboard_templates / "partials" / "theme_boot.html").read_text(encoding="utf-8")
        theme_source = (PACKAGE_DASHBOARD / "theme.ts").read_text(encoding="utf-8")
        preferences_source = (PACKAGE_DASHBOARD.parent / "core" / "services" / "preferences.ts").read_text(encoding="utf-8")

        self.assertIn('export const DASHBOARD_THEME_PREFERENCE_KEY = "dashboard.theme";', theme_source)
        self.assertIn('const namespace = options.namespace ?? "oldman";', preferences_source)
        self.assertIn('var key = "oldman:dashboard.theme";', theme_boot)
        self.assertIn("prefers-color-scheme: dark", theme_boot)
        self.assertLess(
            shared_base.index('include "oldman/dashboard/partials/theme_boot.html"'),
            shared_base.index('include "oldman/dashboard/partials/preloader_critical_css.html"'),
        )


    def test_shell_footer_partial_is_included_and_dated_per_render(self) -> None:
        """The footer is one overridable partial fed by a per-render year global."""
        from datetime import datetime

        from jinja2 import Environment

        from oldman.web.template import register_component_filters

        shared_base = (ROOT / "oldman" / "web" / "templates" / "oldman" / "dashboard" / "base.html").read_text(encoding="utf-8")
        login = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "login.html").read_text(encoding="utf-8")
        footer = (ROOT / "oldman" / "web" / "templates" / "oldman" / "dashboard" / "partials" / "footer.html").read_text(encoding="utf-8")

        self.assertIn("block dashboard_footer", shared_base)
        self.assertIn('include "oldman/dashboard/partials/footer.html"', shared_base)
        # 认证页的页脚在共享的 auth_layout 宏里，登录模板只负责调用它。
        auth_layout = (ROOT / "oldman" / "web" / "templates" / "oldman" / "auth" / "partials" / "auth_layout.html").read_text(encoding="utf-8")
        self.assertIn('include "oldman/dashboard/partials/footer.html"', auth_layout)
        self.assertIn("oldman-footer-auth", auth_layout)
        self.assertIn("auth_layout(", login)
        self.assertIn("current_year()", footer)

        environment = Environment(autoescape=True)
        register_component_filters(environment)
        year = environment.globals["current_year"]
        self.assertTrue(callable(year))
        self.assertEqual(datetime.now().year, year())


if __name__ == "__main__":
    unittest.main()
