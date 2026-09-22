"""Real Jinja and DOM tests for shared inline flash message rendering."""

from __future__ import annotations

import tempfile
import time
import unittest
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from pathlib import Path
from typing import cast
from unittest.mock import patch

from jinja2 import Environment, select_autoescape
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse, html, redirect
from sanic_ext import Config, Extend
from sanic_ext.extensions.templating.extension import TemplatingExtension

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.web import messages
from oldman.web.messages._cookie_storage import FLASH_COOKIE_NAME
from oldman.web.template import build_template_loader, install_template_loaders, register_component_filters

_ROOT_SECRET = "oldman-web-message-template-test-secret"
_PAGE_TEMPLATE = """\
{% extends "oldman/dashboard/base.html" %}
{% block dashboard_preloader %}{% endblock %}
{% block dashboard_back_to_top %}{% endblock %}
{% block content %}<main id="test-page-body">PAGE BODY</main>{% endblock %}
"""


class _FlashElement:
    """Store the attributes, text, and descendants of one rendered message."""

    def __init__(self, attributes: dict[str, str | None]) -> None:
        self.attributes = attributes
        self.text: list[str] = []
        self.descendant_tags: list[str] = []


class _RenderedDOM(HTMLParser):
    """Collect semantic flash nodes from an actual rendered HTML response."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.flash_messages: list[_FlashElement] = []
        self.flash_wrapper_position: int | None = None
        self.page_body_position: int | None = None
        self._active_flash: _FlashElement | None = None
        self._active_depth = 0
        self.feed(source)
        self.close()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        position = len(self.elements)
        self.elements.append((tag, attributes))
        if "data-om-flash-messages" in attributes:
            self.flash_wrapper_position = position
        if attributes.get("id") == "test-page-body":
            self.page_body_position = position

        if self._active_flash is not None:
            self._active_depth += 1
            self._active_flash.descendant_tags.append(tag)
        elif "data-om-flash-message" in attributes:
            self._active_flash = _FlashElement(attributes)
            self._active_depth = 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._active_flash is None:
            return
        self._active_depth -= 1
        if self._active_depth == 0:
            self.flash_messages.append(self._active_flash)
            self._active_flash = None

    def handle_data(self, data: str) -> None:
        if self._active_flash is not None:
            self._active_flash.text.append(data)


class FlashTemplateTest(unittest.IsolatedAsyncioTestCase):
    """Render package templates through the real Messages Jinja global."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_templates = Path(self.temporary_directory.name)
        (self.project_templates / "page.html").write_text(
            _PAGE_TEMPLATE,
            encoding="utf-8",
        )
        (self.project_templates / "plain.html").write_text(
            "<main id=\"plain-page\">PLAIN PAGE</main>",
            encoding="utf-8",
        )
        self.settings = DefaultSettings.model_validate(
            {"web": {"security": {"secret_key": _ROOT_SECRET}}}
        )
        self.app = Sanic(
            f"oldman-web-message-templates-{time.time_ns()}",
            configure_logging=False,
        )
        Extend(
            self.app,
            config=Config(
                LOGGING=False,
                OAS=False,
                OAS_AUTODOC=False,
                TEMPLATING_ENABLE_ASYNC=True,
            ),
            extensions=[TemplatingExtension],
            built_in_extensions=False,
        )
        environment = install_template_loaders(
            self.app.ext.environment,
            self.project_templates,
        )
        environment.globals["_"] = lambda value: value
        with patch.dict(conf.__dict__, {"settings": self.settings}):
            messages.init_app(self.app)
        self._register_routes()

    def tearDown(self) -> None:
        Sanic.unregister_app(self.app)
        self.temporary_directory.cleanup()

    def _register_routes(self) -> None:
        @self.app.get("/add")
        async def add(request: Request) -> BaseHTTPResponse:
            messages.success(request, "Saved <script>alert(1)</script>")
            messages.info(request, "Import is running")
            messages.warning(request, "Some records were skipped")
            messages.add_message(
                request,
                messages.MessageLevel.ERROR,
                "<strong>Save failed</strong>",
                format=messages.MessageFormat.HTML,
            )
            return redirect("/page", status=303)

        @self.app.get("/page")
        async def page(_request: Request) -> BaseHTTPResponse:
            template = self.app.ext.environment.get_template("page.html")
            return html(await template.render_async())

        @self.app.get("/plain")
        async def plain(_request: Request) -> BaseHTTPResponse:
            template = self.app.ext.environment.get_template("plain.html")
            return html(await template.render_async())

    @staticmethod
    def _set_cookie_header(response: BaseHTTPResponse) -> str | None:
        return response.headers.get("set-cookie")

    @classmethod
    def _cookie_value(cls, response: BaseHTTPResponse) -> str:
        header = cls._set_cookie_header(response)
        if header is None:
            raise AssertionError("response did not set a Cookie")
        parsed = SimpleCookie()
        parsed.load(header)
        return parsed[FLASH_COOKIE_NAME].value

    @staticmethod
    def _request_headers(value: str) -> dict[str, str]:
        return {"cookie": f"{FLASH_COOKIE_NAME}={value}"}

    async def _add_messages(self) -> str:
        _request, response = await self.app.asgi_client.get("/add")
        self.assertEqual(303, response.status)
        return self._cookie_value(response)

    async def test_shared_base_renders_ordered_inline_dom_and_escapes_text(self) -> None:
        cookie_value = await self._add_messages()

        _request, response = await self.app.asgi_client.get(
            "/page",
            headers=self._request_headers(cookie_value),
        )
        dom = _RenderedDOM(response.text)

        self.assertEqual(
            ["success", "info", "warning", "error"],
            [
                item.attributes["data-om-message-level"]
                for item in dom.flash_messages
            ],
        )
        self.assertEqual(
            [
                "Saved <script>alert(1)</script>",
                "Import is running",
                "Some records were skipped",
                "Save failed",
            ],
            ["".join(item.text).strip() for item in dom.flash_messages],
        )
        self.assertNotIn("script", dom.flash_messages[0].descendant_tags)
        self.assertIn("strong", dom.flash_messages[3].descendant_tags)
        self.assertIsNotNone(dom.flash_wrapper_position)
        self.assertIsNotNone(dom.page_body_position)
        self.assertLess(
            cast(int, dom.flash_wrapper_position),
            cast(int, dom.page_body_position),
        )
        self.assertIn(
            "Max-Age=0",
            cast(str, self._set_cookie_header(response)),
        )

    async def test_partial_creates_no_feedback_toast_dialog_or_notification_dom(self) -> None:
        cookie_value = await self._add_messages()
        _request, response = await self.app.asgi_client.get(
            "/page",
            headers=self._request_headers(cookie_value),
        )
        dom = _RenderedDOM(response.text)

        self.assertFalse(
            any(
                attributes.get("data-om-component") == "feedback"
                or attributes.get("role") == "dialog"
                or "toast" in (attributes.get("class") or "").split()
                or "notification-item"
                in (attributes.get("class") or "").split()
                for _tag, attributes in dom.elements
            )
        )

    async def test_project_can_override_the_default_partial_by_path(self) -> None:
        override = (
            self.project_templates
            / "oldman"
            / "messages"
            / "flash_message.html"
        )
        override.parent.mkdir(parents=True)
        override.write_text(
            "{% if messages is defined and messages %}"
            "<section data-project-flash>"
            "{% for message in messages %}"
            "<p data-project-level=\"{{ message.level }}\">"
            "{{ message.content }}"
            "</p>"
            "{% endfor %}"
            "</section>"
            "{% endif %}",
            encoding="utf-8",
        )
        cookie_value = await self._add_messages()

        _request, response = await self.app.asgi_client.get(
            "/page",
            headers=self._request_headers(cookie_value),
        )
        dom = _RenderedDOM(response.text)

        self.assertTrue(
            any("data-project-flash" in attributes for _tag, attributes in dom.elements)
        )
        self.assertFalse(dom.flash_messages)
        self.assertEqual(
            ["success", "info", "warning", "error"],
            [
                attributes["data-project-level"]
                for _tag, attributes in dom.elements
                if "data-project-level" in attributes
            ],
        )

    async def test_template_without_partial_does_not_consume_messages(self) -> None:
        cookie_value = await self._add_messages()

        _request, plain_response = await self.app.asgi_client.get(
            "/plain",
            headers=self._request_headers(cookie_value),
        )
        self.assertEqual("<main id=\"plain-page\">PLAIN PAGE</main>", plain_response.text)
        self.assertIsNone(self._set_cookie_header(plain_response))

        _request, page_response = await self.app.asgi_client.get(
            "/page",
            headers=self._request_headers(cookie_value),
        )
        self.assertEqual(4, len(_RenderedDOM(page_response.text).flash_messages))

    async def test_shared_base_renders_when_messages_are_not_installed(self) -> None:
        environment = Environment(
            loader=build_template_loader(self.project_templates),
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=True,
        )
        environment.globals["_"] = lambda value: value
        # The shared base needs only the component globals (`_`, `current_year`), never the messages extension.
        register_component_filters(environment)

        rendered = await environment.get_template("page.html").render_async()
        dom = _RenderedDOM(rendered)

        self.assertFalse(dom.flash_messages)
        self.assertIsNotNone(dom.page_body_position)


if __name__ == "__main__":
    unittest.main()
