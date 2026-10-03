"""What the auth flows share: how a page is rendered and who counts as signed in by default.

PasswordResetFlow, LoginFlow and AccountFlow each render pages either through the host's own
renderer (the built-in Admin adds its menu and prefix) or through the templates under a prefix
(a dashboard's `oldman/dashboard/account`).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from sanic.response import HTTPResponse

from oldman.web.session import SessionData
from oldman.web.template import render_template


class PageRenderer(Protocol):
    """Renders one page of a flow, named by `page`, with the given context."""

    def __call__(self, request: Any, page: str, /, **context: Any) -> Awaitable[HTTPResponse]: ...


def resolve_page_renderer(render: PageRenderer | None, template_prefix: str | None) -> PageRenderer:
    """The host's `render`, or one that renders `<template_prefix>/<page>.html`; exactly one of the two is given."""
    if (render is None) == (template_prefix is None):
        raise ValueError("register_routes takes exactly one of render= or template_prefix=")
    if render is not None:
        return render
    page_prefix = str(template_prefix).rstrip("/")

    async def render_page(request: Any, page: str, /, **context: Any) -> HTTPResponse:
        return await render_template(f"{page_prefix}/{page}.html", context={"request": request, **context})

    return render_page


def session_is_authenticated(request: Any) -> bool:
    """Whether the request carries a signed-in Session; the default for "already signed in, skip this page"."""
    session = getattr(getattr(request, "ctx", None), "session", None)
    return isinstance(session, SessionData) and session.is_authenticated()


__all__ = ["PageRenderer", "resolve_page_renderer", "session_is_authenticated"]
