"""The Python entries that render one dashboard Modal fragment."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from oldman.web.components import render_modal, render_modal_sync

TEMPLATES = Path(__file__).resolve().parents[1] / "oldman" / "web" / "templates"


def make_environment(*, is_async: bool) -> Environment:
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, enable_async=is_async)
    environment.globals["_"] = lambda message: message
    return environment


def make_owner(*, is_async: bool) -> Any:
    return SimpleNamespace(app=SimpleNamespace(ext=SimpleNamespace(environment=make_environment(is_async=is_async))))


OPTIONS: dict[str, Any] = {
    "modal_id": "evidence-7",
    "title": "Evidence JSON",
    "body": Markup("<pre>{}</pre>"),
    "close_label": "Close",
    "footer_close_label": "Close",
    "dialog_class": "om-modal-dialog-lg",
}


class ModalRenderTest(unittest.TestCase):
    def test_sync_render_embeds_an_unmanaged_visible_modal(self) -> None:
        html = str(render_modal_sync(make_owner(is_async=True), **OPTIONS))

        self.assertIn('id="evidence-7"', html)
        self.assertIn('data-om-component="modal"', html)
        self.assertIn("Evidence JSON", html)
        self.assertIn("<pre>{}</pre>", html)
        self.assertIn("om-modal-dialog-lg", html)
        # A fragment sitting in a table cell is opened by its trigger, not created by the manager.
        self.assertNotIn("data-om-modal-managed", html)
        self.assertNotIn("hidden>", html)

    def test_async_render_matches_the_sync_one(self) -> None:
        request = make_owner(is_async=True)
        rendered = asyncio.run(render_modal(request, **OPTIONS))

        self.assertEqual(str(render_modal_sync(request, **OPTIONS)), str(rendered))

    def test_the_default_close_label_is_translated(self) -> None:
        """默认值会进 aria-label，屏幕阅读器读到的不能永远是英文。"""
        from oldman.web.components.modals import modal_fragment_context

        context = modal_fragment_context(modal_id="probe", title="Probe", body=Markup("<p></p>"))

        self.assertNotIsInstance(context["modal_close_label"], str)
        self.assertEqual("Close", str(context["modal_close_label"]))

    def test_managed_and_hidden_are_opt_in(self) -> None:
        html = str(render_modal_sync(make_owner(is_async=True), **OPTIONS, managed=True, hidden=True))

        self.assertIn('data-om-modal-managed="true"', html)
        # 精确匹配那个布尔属性：页面上恒定有 aria-hidden="true"，assertIn("hidden") 删掉模板里的
        # {% if hidden %} 也照样通过。
        self.assertRegex(html, r"\n\s+hidden\n")


if __name__ == "__main__":
    unittest.main()
