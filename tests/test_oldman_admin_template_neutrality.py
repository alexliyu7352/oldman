"""Oldman Admin template neutrality tests."""

from __future__ import annotations

import unittest
from pathlib import Path

FORBIDDEN_TOKENS = (
    "EPG",
    "channels-epg",
    "catalog-",
    "logo-assets",
    "match-decisions",
    'href="/notifications"',
    "topbar_dashboard_notifications",
    "component-coverage",
    "catalog",
    "ingestion",
    "upstream",
)


class OldmanAdminTemplateNeutralityTest(unittest.TestCase):
    """验证内置 Admin 模板不包含当前业务项目内容。"""

    def test_admin_templates_are_business_neutral(self) -> None:
        """Admin shell、登录页和 CRUD 模板必须只来自 registry。"""
        template_dir = Path("oldman/apps/admin/templates")
        source = "\n".join(path.read_text(encoding="utf-8") for path in template_dir.rglob("*.html"))

        self.assertIn("menu_items", source)
        self.assertIn("bundle_asset_base_url(admin_bundle_name)", source)
        self.assertIn("item.app_display_name", source)
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, source)

    def test_admin_crud_templates_do_not_assume_id_primary_key(self) -> None:
        """CRUD 模板必须通过 ModelAdmin 读取对象主键。"""
        model_template_dir = Path("oldman/apps/admin/templates/admin/model")
        source = "\n".join(path.read_text(encoding="utf-8") for path in model_template_dir.rglob("*.html"))

        self.assertIn("model_admin.get_object_url(object", source)
        self.assertNotIn("object.id", source)

    def test_admin_shell_composes_shared_dashboard_controls(self) -> None:
        """Admin 必须组合共享 Dashboard 壳层，不得复制业务通知界面。"""
        source = Path("oldman/apps/admin/templates/admin/base.html").read_text(encoding="utf-8")
        topbar = Path("oldman/apps/admin/templates/admin/partials/topbar.html").read_text(encoding="utf-8")

        self.assertLess(source.index("bundle_modulepreload(admin_bundle_name)"), source.index("bundle_styles(admin_bundle_name)"))
        self.assertLess(source.index("bundle_styles(admin_bundle_name)"), source.index("bundle_script(admin_bundle_name)"))
        self.assertIn('{% extends "oldman/dashboard/base.html" %}', source)
        self.assertIn("dashboard_sidebar", source)
        self.assertIn("dashboard_main_frame", source)
        self.assertIn("group.icon", source)
        self.assertNotIn('class="ri-database-2-line oldman-menu-icon"', source)
        self.assertIn('{% include "admin/partials/topbar.html" %}', source)
        self.assertIn("{% block dashboard_back_to_top %}", source)
        self.assertIn("{{ super() }}", source)
        self.assertIn("dashboard_topbar", topbar)
        self.assertIn("admin_language_switcher", topbar)
        self.assertIn("admin_account_controls", topbar)
        for business_notification_token in (
            "removeNotificationModal",
            "NotificationModalbtn-close",
            "delete-notification",
        ):
            self.assertNotIn(business_notification_token, source)
