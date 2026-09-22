"""Oldman Admin boundary tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OldmanAdminBoundaryTest(unittest.TestCase):
    """验证内置 Admin 的包边界。"""

    def test_oldman_web_and_db_do_not_depend_on_admin(self) -> None:
        """oldman.web 和 oldman.db 不能反向导入内置 Admin 应用。"""
        for package_dir in (ROOT / "oldman" / "web", ROOT / "oldman" / "db"):
            source = "\n".join(path.read_text(encoding="utf-8") for path in package_dir.rglob("*.py"))
            self.assertNotIn("from oldman.apps.admin", source, f"{package_dir} must not import oldman.apps.admin")
            self.assertNotIn("import oldman.apps.admin", source, f"{package_dir} must not import oldman.apps.admin")

    def test_admin_is_not_an_extra_or_standalone_dashboard_package(self) -> None:
        """内置 Admin 不应表现为 Python extra 或独立 dashboard npm 包。"""
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        admin_package = json.loads((ROOT / "frontend" / "apps" / "admin" / "package.json").read_text(encoding="utf-8"))

        self.assertNotIn("oldman[admin]", pyproject)
        self.assertNotIn("[project.optional-dependencies]", pyproject)
        self.assertEqual("oldman-admin", admin_package["name"])
        self.assertTrue(admin_package["private"])
        self.assertNotEqual("@oldman/dashboard", admin_package["name"])

    def test_admin_frontend_consumes_oldman_web_public_entries(self) -> None:
        """Admin 前端必须通过 oldman-web 入口消费框架能力。"""
        source = (ROOT / "frontend" / "apps" / "admin" / "src" / "main.ts").read_text(encoding="utf-8")
        css_source = (ROOT / "frontend" / "apps" / "admin" / "src" / "admin.css").read_text(encoding="utf-8")

        self.assertIn('from "oldman-web/core"', source)
        self.assertIn('from "oldman-web/dashboard"', source)
        self.assertIn("createDashboardCrudComponentLoaders", source)
        self.assertIn("componentLoaders: createDashboardCrudComponentLoaders({", source)
        self.assertIn('"table-filter-form"', source)
        self.assertIn('"date-time-picker"', source)
        self.assertIn('"form-validator"', source)
        self.assertIn("feedback:", source)
        self.assertIn('form: async () => (await import("oldman-web/components/form")).Form', source)
        self.assertNotIn("form-modal", source)
        self.assertIn(
            'modal: async () => (await import("oldman-web/dashboard/modal")).DashboardModal',
            source,
        )
        self.assertIn('feedback: async () => (await import("oldman-web/dashboard/feedback")).DashboardFeedback', source)
        self.assertNotIn("class AdminFormModal", source)
        self.assertFalse((ROOT / "frontend" / "packages" / "oldman-web" / "src" / "components" / "form-modal.ts").exists())
        self.assertFalse((ROOT / "frontend" / "packages" / "oldman-web" / "src" / "dashboard" / "form-modal.ts").exists())
        self.assertIn("dropdown:", source)
        self.assertIn("emptyNotificationTemplate: adminNotificationEmptyState", source)
        self.assertIn('class="empty-notification-elem om-empty om-empty-sm"', source)
        self.assertIn('"oldman-web/styles/tailwind.css"', css_source)
        self.assertNotIn('"oldman-web/components/sidebar-menu"', source)
        self.assertNotIn("@app/", source)

        admin_base = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "base.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="oldman-admin-base" content="{{ admin_prefix }}">', admin_base)

    def test_admin_uses_framework_dashboard_ui_ownership(self) -> None:
        """Admin 只能拥有场景组合，不能维护第二套 Dashboard 基础组件。"""
        admin_css = (ROOT / "frontend" / "apps" / "admin" / "src" / "admin.css").read_text(encoding="utf-8")
        shared_css = (ROOT / "frontend" / "packages" / "oldman-web" / "src" / "styles" / "tailwind.css").read_text(encoding="utf-8")

        self.assertIn("oldman-web/styles/tailwind.css", admin_css)
        self.assertNotIn(".om-table {", admin_css)
        self.assertNotIn(".oldman-sidebar {", admin_css)
        self.assertIn('@source inline("{sm:,md:,lg:,xl:}col-span-', shared_css)

        list_template = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "model" / "list.html").read_text(encoding="utf-8")
        table_adapter = (ROOT / "oldman" / "apps" / "admin" / "table.py").read_text(encoding="utf-8")
        self.assertIn("table_html", list_template)
        self.assertNotIn("<table", list_template)
        self.assertIn("SQLAlchemyTableView", table_adapter)
        self.assertIn("TailwindTableRenderer", table_adapter)

        form_template = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "model" / "form.html").read_text(encoding="utf-8")
        model_admin_source = (ROOT / "oldman" / "apps" / "admin" / "model_admin.py").read_text(encoding="utf-8")
        self.assertIn("form_html", form_template)
        self.assertNotIn("{% for field in fields %}", form_template)
        self.assertIn("TailwindModelForm", model_admin_source)

        admin_base = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "base.html").read_text(encoding="utf-8")
        self.assertIn('{% extends "oldman/dashboard/base.html" %}', admin_base)

    def test_admin_site_owns_login_routes_without_business_auth_views(self) -> None:
        """内置 Admin 必须有自己的登录闭环，不依赖业务侧 /login。"""
        source = (ROOT / "oldman" / "apps" / "admin" / "site.py").read_text(encoding="utf-8")

        self.assertIn('login_path = f"{prefix}/login"', source)
        self.assertIn("authenticate_user(", source)
        self.assertIn("has_staff_access(", source)
        # The session steps themselves belong to the framework's login helpers, which the Admin calls.
        self.assertIn("login_user(", source)
        self.assertIn("logout_user(", source)
        login_helpers = (ROOT / "oldman" / "web" / "auth" / "login.py").read_text(encoding="utf-8")
        self.assertIn("session_data_for_user(", login_helpers)
        self.assertIn("exclusive_login(", login_helpers)
        self.assertIn("logout_session(", login_helpers)
        self.assertIn("admin_login_url(login_path, request)", source)
        self.assertIn("ApiErrorCode.AUTHENTICATION_REQUIRED", source)
        self.assertIn('data={"login_url": login_path}', source)
        self.assertIn("status=401", source)
        self.assertNotIn('redirect("/login")', source)

    def test_admin_user_modals_reuse_source_validation_and_feedback_contracts(self) -> None:
        """Admin user actions must keep the source FormValidator and page Feedback composition."""
        template_root = ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "model"
        list_template = (template_root / "list.html").read_text(encoding="utf-8")
        auth_partials = ROOT / "oldman" / "web" / "templates" / "oldman" / "auth" / "partials"
        password_template = (auth_partials / "password_form.html").read_text(encoding="utf-8")
        delete_template = (auth_partials / "user_delete_form.html").read_text(encoding="utf-8")

        self.assertIn('data-om-component="feedback"', list_template)
        self.assertNotIn("form-modal", list_template)
        self.assertIn('"user-delete-modal"', list_template)
        self.assertIn('data-om-component="form"', password_template)
        self.assertIn('data-om-component="form-validator"', password_template)
        self.assertIn("data-om-form-validate", password_template)
        self.assertIn('data-om-form-mode="json"', password_template)
        self.assertIn('data-om-component="form"', delete_template)
        self.assertIn('data-om-form-mode="json"', delete_template)
        self.assertIn("data-om-form-message", delete_template)
        self.assertIn("data-om-modal-close", delete_template)

    def test_admin_model_templates_do_not_assume_an_id_primary_key(self) -> None:
        """Form actions must use ModelAdmin identity metadata for custom keys."""
        template_root = ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "model"
        form_template = (template_root / "form.html").read_text(encoding="utf-8")

        self.assertIn("model_admin.get_object_url(object", form_template)
        self.assertNotIn("object.id", form_template)

    def test_delete_confirmation_cancel_uses_shared_history_contract(self) -> None:
        """删除确认页 Cancel 必须后退，并保留列表地址作为无历史 fallback。"""
        source = (ROOT / "oldman" / "apps" / "admin" / "templates" / "admin" / "model" / "confirm_delete.html").read_text(encoding="utf-8")

        self.assertIn("data-om-history-back", source)
        self.assertIn('data-om-history-fallback="{{ admin_prefix }}/{{ model_admin.model_path }}"', source)
