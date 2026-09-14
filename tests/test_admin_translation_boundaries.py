"""Regression tests for explicit Admin/Form/Table translation ownership."""

from __future__ import annotations

import asyncio
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.support import Translations
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from wtforms import StringField

from oldman.apps.admin.table import AdminModelTable
from oldman.i18n import bind_translations, gettext_lazy, reset_translations
from oldman.web.components.forms import TailwindForm
from oldman.web.components.tables import BaseTableView, TableResult


def make_translations(messages: dict[str, str]) -> Translations:
    """Build a real Babel catalog for translation-boundary tests."""
    catalog = Catalog(locale="zh_Hans")
    for message_id, translated in messages.items():
        catalog.add(message_id, translated)
    stream = BytesIO()
    write_mo(stream, catalog)
    stream.seek(0)
    return Translations(stream)


class TranslationBoundaryForm(TailwindForm):
    """Expose plain and explicitly lazy labels through the real renderer."""

    plain = StringField("Custom label")
    # WTForms accepts this runtime string-compatible lazy object but types it as str.
    lazy = StringField(cast(str, gettext_lazy("Framework label")))


class TranslationBoundaryTable(BaseTableView):
    """Expose a consumer-owned empty message through the real Table renderer."""

    route_path = "/records/table"
    columns = ("id",)
    page_size = 1
    page_size_options = (1,)
    empty_message = "Consumer empty text"


class AdminTranslationBoundaryTest(unittest.TestCase):
    """Keep lazy message ownership explicit at every rendering boundary."""

    def test_form_resolves_lazy_text_without_translating_plain_consumer_text(self) -> None:
        """Consumer text is data; only an explicit lazy value is a message id."""
        translations = make_translations(
            {
                "Custom label": "不应隐式翻译",
                "Framework label": "框架标签",
                "Save": "保存",
            }
        )
        token = bind_translations(translations)
        try:
            form = TranslationBoundaryForm()
            plain_html = str(asyncio.run(form.render_field("plain")))
            lazy_html = str(asyncio.run(form.render_field("lazy")))
            explicit_action_html = str(asyncio.run(form.render_actions(submit_label="Save")))
            default_action_html = str(asyncio.run(form.render_actions()))
        finally:
            reset_translations(token)

        self.assertIn("Custom label", plain_html)
        self.assertNotIn("不应隐式翻译", plain_html)
        self.assertIn("框架标签", lazy_html)
        self.assertIn(">Save</button>", explicit_action_html)
        self.assertIn(">保存</button>", default_action_html)

    def test_api_response_does_not_reinterpret_consumer_error_as_message_id(self) -> None:
        """A caller-supplied validation error must not be translated twice."""
        translations = make_translations({"Consumer error": "不应二次翻译"})
        token = bind_translations(translations)
        try:
            form = TranslationBoundaryForm()
            form.add_error("plain", "Consumer error")
            payload = form.to_api_response().to_dict()
        finally:
            reset_translations(token)

        self.assertEqual("Consumer error", payload["errors"]["plain"])

    def test_table_translates_complete_summary_but_not_consumer_empty_text(self) -> None:
        """Template copy is one message while a consumer empty value stays literal."""
        table = TranslationBoundaryTable()
        table_request = table.build_table_request(SimpleNamespace(args={}, headers={}), route_kwargs={})
        result = TableResult(rows=[], row_contexts=[], total=0, filtered_total=0, page=1, page_size=1)
        translations = make_translations(
            {
                "Consumer empty text": "不应隐式翻译",
                "Showing %(start)s to %(end)s of %(total)s entries": "共 %(total)s 条，显示 %(start)s 至 %(end)s",
            }
        )
        token = bind_translations(translations)
        try:
            fragment = str(asyncio.run(table.render_html_fragment(table_request, result)))
        finally:
            reset_translations(token)

        self.assertIn("Consumer empty text", fragment)
        self.assertNotIn("不应隐式翻译", fragment)
        self.assertIn("共 0 条，显示 0 至 0", fragment)

    def test_admin_table_does_not_reinterpret_consumer_empty_message(self) -> None:
        """The Admin adapter must preserve a ModelAdmin-owned plain string."""
        model_admin = SimpleNamespace(
            model=object,
            model_path="records",
            get_table_columns=lambda: (),
            get_search_fields=lambda: (),
            get_ordering=lambda: (),
            page_size=20,
            table_selectable=False,
            empty_message="Consumer empty text",
        )
        translations = make_translations({"Consumer empty text": "不应隐式翻译"})
        token = bind_translations(translations)
        try:
            table = AdminModelTable(
                SimpleNamespace(args={}, app=None),
                model_admin=model_admin,  # type: ignore[arg-type]
                db_manager=object(),  # type: ignore[arg-type]
                admin_prefix="/admin",
            )
        finally:
            reset_translations(token)

        self.assertEqual("Consumer empty text", table.empty_message)

    def test_password_modal_renders_long_identity_as_wrapping_text_not_a_badge(self) -> None:
        """Long identities remain readable without badge styling or overflow."""

        class FormStub:
            csrf_token = "csrf-token"

            @staticmethod
            def render_field(name: str) -> Markup:
                return Markup(f'<input name="{name}">')

        templates = Path(__file__).resolve().parents[1] / "oldman" / "web" / "templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        environment.globals["_"] = lambda message: message
        html = environment.get_template("oldman/auth/partials/password_form.html").render(
            action="/admin/users/1/password",
            form=FormStub(),
            user=SimpleNamespace(
                username="browser_superuser_guard_with_a_very_long_identity",
                email="browser-superuser-guard@example.test",
            ),
        )

        self.assertNotIn("om-badge", html)
        self.assertIn("break-all", html)
        self.assertIn("browser_superuser_guard_with_a_very_long_identity", html)


if __name__ == "__main__":
    unittest.main()
