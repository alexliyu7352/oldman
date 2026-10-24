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


class FormCoreMessagesTest(unittest.IsolatedAsyncioTestCase):
    """The form core's field and validator messages are in the framework catalog, so a Chinese form shows them in Chinese."""

    def test_the_framework_template_carries_the_form_core_messages(self) -> None:
        template_ids = {message.id for message in framework_i18n().build_template() if message.id}
        for message_id in (
            "Not a valid integer value.",
            "Number must be at least %(min)s.",
            ("Field must be at least %(min)d character long.", "Field must be at least %(min)d characters long."),
            "Invalid URL.",
        ):
            with self.subTest(message_id=message_id):
                self.assertIn(message_id, template_ids)

    async def test_validation_messages_follow_the_request_language(self) -> None:
        from oldman.i18n.translations import current_translations
        from oldman.web.components.forms import IntegerField, StringField, TailwindForm
        from oldman.web.components.forms.validators import Length, NumberRange

        class Profile(TailwindForm):
            name = StringField("Name", validators=[Length(min=3)])
            age = IntegerField("Age", validators=[NumberRange(min=1)])

        with tempfile.TemporaryDirectory() as temporary_directory:
            roots = translation_roots(Path(temporary_directory), ())
            for language in ("zh_Hans", "zh_Hant"):
                with self.subTest(language=language):
                    token = current_translations.set(CatalogLoader(roots).load(language))
                    try:
                        short = Profile(data={"name": "x", "age": "0"})
                        await short.validate()
                        not_a_number = Profile(data={"name": "Ann", "age": "abc"})
                        await not_a_number.validate()
                    finally:
                        current_translations.reset(token)
                    for message in (*short.errors["name"], *short.errors["age"], not_a_number.errors["age"][0]):
                        self.assertRegex(str(message), r"[一-鿿]", f"{language}: {message!r} is not translated")
