"""Built-in Admin translation catalog tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from oldman.i18n.catalogs import CatalogLoader


class OldmanAdminI18nTest(unittest.TestCase):
    """Require every advertised built-in Admin language to change visible copy."""

    def test_built_in_chinese_catalogs_translate_admin_copy(self) -> None:
        """Load packaged catalogs through the same loader used by WebApplication."""
        locales = Path(__file__).resolve().parents[1] / "oldman" / "apps" / "admin" / "locales"
        loader = CatalogLoader([locales])

        simplified = loader.load("zh_Hans")
        traditional = loader.load("zh_Hant")

        self.assertEqual("修改密码", simplified.gettext("Change Password"))
        self.assertEqual("新密码", simplified.gettext("New Password"))
        self.assertEqual("用户", simplified.gettext("Users"))
        self.assertEqual("用户会话", simplified.gettext("User Session"))
        self.assertEqual("当前会话", simplified.gettext("Current Session"))
        self.assertEqual("登录时间", simplified.gettext("Login Time"))
        self.assertEqual("登录 IP", simplified.gettext("Login IP"))
        self.assertEqual("会话密码已修改", simplified.gettext("Session password changed"))
        self.assertEqual(
            "显示第 1 至 10 条，共 23 条记录",
            simplified.gettext("Showing %(start)s to %(end)s of %(total)s entries")
            % {"start": 1, "end": 10, "total": 23},
        )
        self.assertEqual("變更密碼", traditional.gettext("Change Password"))
        self.assertEqual("新密碼", traditional.gettext("New Password"))
        self.assertEqual("使用者", traditional.gettext("Users"))
        self.assertEqual("使用者工作階段", traditional.gettext("User Session"))
        self.assertEqual("目前工作階段", traditional.gettext("Current Session"))
        self.assertEqual("登入時間", traditional.gettext("Login Time"))
        self.assertEqual("登入 IP", traditional.gettext("Login IP"))
        self.assertEqual("工作階段密碼已變更", traditional.gettext("Session password changed"))
        self.assertEqual(
            "顯示第 1 至 10 筆，共 23 筆記錄",
            traditional.gettext("Showing %(start)s to %(end)s of %(total)s entries")
            % {"start": 1, "end": 10, "total": 23},
        )


if __name__ == "__main__":
    unittest.main()
