"""The framework's own translation catalog in ``oldman/locales``."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo

from oldman.i18n import CatalogLoader
from oldman.i18n.catalogs import translation_roots

ROOT = Path(__file__).resolve().parents[1]


def framework_i18n() -> ModuleType:
    """``scripts/framework_i18n.py``, the maintenance script whose check this suite runs."""
    spec = importlib.util.spec_from_file_location("framework_i18n", ROOT / "scripts" / "framework_i18n.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrameworkTranslationsTest(unittest.TestCase):
    def test_the_catalog_matches_the_source_and_every_message_is_translated(self) -> None:
        """A message added, changed or removed in the source needs `framework_i18n.py update`, a translation and `compile`."""
        self.assertEqual([], framework_i18n().problems())

    def test_a_service_without_the_admin_gets_the_framework_text_in_its_language(self) -> None:
        """The account pages' text comes from the framework's catalog, not from whichever App happens to be installed."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            roots = translation_roots(Path(temporary_directory), ("oldman.auth", "oldman.web.messages.notifications"))
            simplified = CatalogLoader(roots).load("zh_Hans")
            traditional = CatalogLoader(roots).load("zh_Hant")

        self.assertEqual(ROOT / "oldman" / "locales", roots[-1])
        self.assertEqual("请使用你的账号登录以继续。", simplified.gettext("Sign in with your account to continue."))
        self.assertEqual("請使用你的帳號登入以繼續。", traditional.gettext("Sign in with your account to continue."))

    def test_the_project_catalog_comes_before_the_framework(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            catalog = Catalog(locale="zh_Hans")
            catalog.add("Sign in with your account to continue.", "用本站账号登录。")
            mo_path = project_root / "locales" / "zh_Hans" / "LC_MESSAGES" / "messages.mo"
            mo_path.parent.mkdir(parents=True)
            with mo_path.open("wb") as stream:
                write_mo(stream, catalog)

            translations = CatalogLoader(translation_roots(project_root, ())).load("zh_Hans")

        self.assertEqual("用本站账号登录。", translations.gettext("Sign in with your account to continue."))
        # Whatever the project leaves out still comes from the framework.
        self.assertEqual("修改密码", translations.gettext("Change Password"))


if __name__ == "__main__":
    unittest.main()
