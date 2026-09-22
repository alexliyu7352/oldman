"""Shared server-rendered notification fragment contracts."""

from __future__ import annotations

import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call, patch

from markupsafe import Markup
from sanic import Sanic
from sanic.exceptions import BadRequest
from sanic_ext import Config, Extend
from sanic_ext.extensions.templating.extension import TemplatingExtension

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings
from oldman.db.schemas import PageResult
from oldman.i18n import gettext_lazy
from oldman.web.messages import MessageFormat, MessageLevel
from oldman.web.messages.notifications.payloads import (
    NotificationPayload,
    NotificationPresentation,
    NotificationState,
)
from oldman.web.messages.notifications.rendering import (
    render_center_content,
    render_topbar_fragment,
)
from oldman.web.messages.notifications.runtime import init_app
from oldman.web.messages.notifications.service import notifications


class _InstalledApps:
    def get_by_package(self, package: str) -> object:
        if package != "oldman.web.messages.notifications":
            raise LookupError(package)
        return object()


class _Catalog:
    """Translate source messages through a deterministic mapping."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def gettext(self, message: str) -> str:
        return f"{self.prefix}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        return f"{self.prefix}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        return f"{self.prefix}:{context}:{message}"


def _row(
    row_id: int,
    *,
    title: str,
    body: str | None = None,
    format: MessageFormat = MessageFormat.TEXT,
    read: bool = False,
    href: str | None = None,
) -> SimpleNamespace:
    payload = NotificationPayload(
        title=gettext_lazy(title),
        body=None if body is None else gettext_lazy(body),
        level=MessageLevel.ERROR if row_id % 2 else MessageLevel.INFO,
        format=format,
        presentation=NotificationPresentation.NONE,
        href=href,
        icon="ri-notification-3-line",
    )
    return SimpleNamespace(
        id=row_id,
        payload=payload.to_msgpack(),
        created_at=datetime(2026, 8, 15, 12, row_id, 0),
        read_at=datetime(2026, 8, 15, 13, 0, 0) if read else None,
    )


class NotificationTemplateTest(unittest.IsolatedAsyncioTestCase):
    """Render both package templates through a real async Jinja environment."""

    def setUp(self) -> None:
        self.settings = DefaultSettings.model_validate(
            {"web": {"session": {"enabled": True}}}
        )
        self.settings_patch = patch.dict(conf.__dict__, {"settings": self.settings})
        self.settings_patch.start()
        self.app = Sanic(
            f"oldman-notification-templates-{time.time_ns()}",
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
        self.app.ctx.oldman_app_registry = _InstalledApps()
        self.app.ctx.csrf = object()
        init_app(self.app)
        init_app(self.app, url_prefix="/admin")

    def tearDown(self) -> None:
        Sanic.unregister_app(self.app)
        self.settings_patch.stop()

    def request(
        self,
        *,
        path: str = "/user-notifications",
        args: dict[str, str] | None = None,
        language: str | None = "zh-Hans",
    ) -> Any:
        context = SimpleNamespace()
        if language is not None:
            context.translations = _Catalog(language)
        return SimpleNamespace(
            app=self.app,
            path=path,
            args=args or {},
            ctx=context,
        )

    async def test_topbar_translates_per_request_and_has_preview_only_dom(self) -> None:
        """One stored payload is translated late and never gains center controls."""
        row = _row(17, title="Server warning", body="Disk is full")
        with patch.object(
            notifications,
            "topbar_for_user",
            AsyncMock(return_value=[row]),
        ), patch.object(
            notifications,
            "unread_count",
            AsyncMock(return_value=3),
        ):
            simplified = await render_topbar_fragment(
                self.request(language="zh-Hans"),
                user_id=7,
            )
            traditional = await render_topbar_fragment(
                self.request(language="zh-Hant"),
                user_id=7,
            )

        self.assertIsInstance(simplified, Markup)
        self.assertIn("zh-Hans:Server warning", simplified)
        self.assertIn("zh-Hant:Server warning", traditional)
        self.assertIn('data-om-unread-count="3"', simplified)
        self.assertIn("data-om-user-notification-preview", simplified)
        self.assertIn('data-om-user-notification-id="17"', simplified)
        self.assertIn('href="/user-notifications/17/open"', simplified)
        self.assertNotIn("checkbox", simplified)
        self.assertNotIn("data-om-user-notification-select", simplified)
        self.assertNotIn("data-om-activity-notification-item", simplified)
        self.assertNotIn("notification-check", simplified)

    async def test_center_escapes_text_and_trusts_only_html_body(self) -> None:
        """Titles and text bodies autoescape while an HTML body keeps trusted tags."""
        text_row = _row(
            1,
            title="<script>title</script>",
            body="<em>plain body</em>",
        )
        html_payload = NotificationPayload(
            title=gettext_lazy("<b>HTML title</b>"),
            body=gettext_lazy(
                "<strong>%(status)s</strong>",
                status="&lt;script&gt;bad&lt;/script&gt;",
            ),
            format=MessageFormat.HTML,
            presentation=NotificationPresentation.NONE,
        )
        html_row = SimpleNamespace(
            id=2,
            payload=html_payload.to_msgpack(),
            created_at=datetime(2026, 8, 15, 12, 2, 0),
            read_at=None,
        )
        result = PageResult(
            items=[text_row, html_row],
            total=2,
            page=1,
            page_size=20,
        )
        with patch.object(
            notifications,
            "list_for_user",
            AsyncMock(return_value=result),
        ):
            rendered = await render_center_content(
                self.request(language=None),
                user_id=7,
            )

        self.assertIn("&lt;script&gt;title&lt;/script&gt;", rendered)
        self.assertNotIn("<script>title</script>", rendered)
        self.assertIn("&lt;em&gt;plain body&lt;/em&gt;", rendered)
        self.assertIn("&lt;b&gt;HTML title&lt;/b&gt;", rendered)
        self.assertIn("<strong>&lt;script&gt;bad&lt;/script&gt;</strong>", rendered)
        self.assertNotIn("<script>bad</script>", rendered)

    async def test_center_rejects_invalid_queries_and_clamps_page(self) -> None:
        """The shared renderer owns strict filters and last-page convergence."""
        for args in (
            {"state": "missing"},
            {"page": "0"},
            {"page": "-1"},
            {"page": "1.5"},
        ):
            with self.subTest(args=args), self.assertRaises(BadRequest):
                await render_center_content(self.request(args=args), user_id=7)

        first = PageResult(items=[], total=21, page=99, page_size=20)
        last = PageResult(
            items=[_row(21, title="Last")],
            total=21,
            page=2,
            page_size=20,
        )
        list_for_user = AsyncMock(side_effect=[first, last])
        with patch.object(notifications, "list_for_user", list_for_user):
            rendered = await render_center_content(
                self.request(args={"state": "unread", "page": "99"}),
                user_id=7,
            )

        self.assertEqual(
            [
                call(7, state=NotificationState.UNREAD, page=99),
                call(7, state=NotificationState.UNREAD, page=2),
            ],
            list_for_user.await_args_list,
        )
        self.assertIn('data-om-current-url="/user-notifications?state=unread&amp;page=2"', rendered)

        empty = PageResult(items=[], total=0, page=8, page_size=20)
        with patch.object(
            notifications,
            "list_for_user",
            AsyncMock(return_value=empty),
        ):
            empty_rendered = await render_center_content(
                self.request(args={"page": "8"}),
                user_id=7,
            )
        self.assertIn('data-om-current-url="/user-notifications?state=all&amp;page=1"', empty_rendered)

    async def test_center_template_freezes_management_selectors(self) -> None:
        """Both hosts can reuse one partial with controls only in the center."""
        result = PageResult(
            items=[_row(4, title="Ready", read=True, href="/jobs/4")],
            total=1,
            page=1,
            page_size=20,
        )
        with patch.object(
            notifications,
            "list_for_user",
            AsyncMock(return_value=result),
        ):
            root = await render_center_content(self.request(), user_id=7)
            admin = await render_center_content(
                self.request(path="/admin/user-notifications"),
                user_id=7,
            )

        for rendered, prefix in ((root, ""), (admin, "/admin")):
            with self.subTest(prefix=prefix):
                self.assertIn("data-om-user-notification-center", rendered)
                self.assertIn("data-om-user-notification-filters", rendered)
                self.assertIn("data-om-user-notification-list", rendered)
                self.assertIn("data-om-user-notification-center-item", rendered)
                self.assertIn("data-om-user-notification-select", rendered)
                self.assertIn("data-om-user-notification-selection-count", rendered)
                self.assertIn("data-om-user-notification-mark-selected-read", rendered)
                self.assertIn("data-om-user-notification-mark-all-read", rendered)
                self.assertIn("data-om-user-notification-delete-selected", rendered)
                self.assertIn("data-om-user-notification-refresh-center", rendered)
                self.assertIn("data-om-user-notification-pagination", rendered)
                self.assertIn(
                    f'data-om-read-url="{prefix}/user-notifications/read"',
                    rendered,
                )
                self.assertIn(
                    f'href="{prefix}/user-notifications/4/open"',
                    rendered,
                )

        template = self.app.ext.environment.get_template(
            "oldman/messages/notifications/center_content.html"
        )
        self.assertIsNotNone(template)


if __name__ == "__main__":
    unittest.main()
