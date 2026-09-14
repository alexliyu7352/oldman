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


if __name__ == "__main__":
    unittest.main()
