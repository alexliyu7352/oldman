"""Request-local rendering for persistent notification fragments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from markupsafe import Markup
from sanic.exceptions import BadRequest

from oldman.i18n import bind_translations, reset_translations
from oldman.i18n.translations import TranslationCatalog
from oldman.web.messages.flash import MessageFormat, MessageLevel
from oldman.web.messages.notifications.payloads import (
    NotificationPayload,
    NotificationPresentation,
    NotificationState,
)
from oldman.web.messages.notifications.service import notifications
from oldman.web.request import Request, get_arg

_ROUTES_CONTEXT_ATTRIBUTE = "_oldman_notification_routes"
_TOPBAR_TEMPLATE = "oldman/messages/notifications/topbar_fragment.html"
_CENTER_TEMPLATE = "oldman/messages/notifications/center_content.html"


@dataclass(frozen=True, slots=True)
class _NotificationItemView:
    """Keep translated browser fields separate from ORM storage bytes."""

    id: int
    title: str
    body: str | Markup | None
    level: MessageLevel
    tone: str
    format: MessageFormat
    presentation: NotificationPresentation
    href: str | None
    icon: str | None
    created_at: datetime
    read: bool


@dataclass(frozen=True, slots=True)
class _NotificationTopbarView:
    """Provide the complete context for one topbar fragment."""

    items: tuple[_NotificationItemView, ...]
    unread_count: int
    center_url: str


@dataclass(frozen=True, slots=True)
class NotificationCenterView:
    """Provide one host-neutral notification-center partial context."""

    items: tuple[_NotificationItemView, ...]
    state: NotificationState
    page: int
    total_pages: int
    read_url: str
    delete_url: str
    topbar_url: str
    center_url: str
    current_url: str


def _routes_for_request(request: Request) -> Any:
    """Resolve the installed prefix whose notification path owns this request."""
    installed = getattr(
        request.app.ctx,
        _ROUTES_CONTEXT_ATTRIBUTE,
        None,
    )
    if not isinstance(installed, dict) or not installed:
        raise RuntimeError("Notification Web routes have not been installed")

    path = str(request.path)
    matches = [
        routes
        for routes in installed.values()
        if path == routes.center_url
        or path == routes.topbar_url
        or path.startswith(f"{routes.center_url}/")
    ]
    if not matches:
        raise RuntimeError(
            f"No installed notification route prefix owns request path {path!r}"
        )
    return max(matches, key=lambda routes: len(routes.center_url))


def _parse_center_query(request: Request) -> tuple[NotificationState, int]:
    """Parse the center's two public query parameters without loose coercion."""
    raw_state = get_arg(request.args, "state", NotificationState.ALL.value)
    if not isinstance(raw_state, str):
        raise BadRequest("state must be all, unread, or read")
    try:
        state = NotificationState(raw_state)
    except ValueError as exc:
        raise BadRequest("state must be all, unread, or read") from exc

    raw_page = get_arg(request.args, "page", "1")
    if not isinstance(raw_page, str) or not raw_page.isdecimal():
        raise BadRequest("page must be a positive integer")
    page = int(raw_page)
    if page < 1:
        raise BadRequest("page must be a positive integer")
    return state, page


def _translate_row(
    row: Any,
    catalog: TranslationCatalog | None,
) -> _NotificationItemView:
    """Decode one row and resolve lazy text under the request's catalog."""
    payload = NotificationPayload.from_msgpack(row.payload)
    token = bind_translations(catalog) if catalog is not None else None
    try:
        title = str(payload.title)
        translated_body = None if payload.body is None else str(payload.body)
    finally:
        if token is not None:
            reset_translations(token)

    body: str | Markup | None = translated_body
    if translated_body is not None and payload.format is MessageFormat.HTML:
        body = Markup(translated_body)
    return _NotificationItemView(
        id=row.id,
        title=title,
        body=body,
        level=payload.level,
        tone=(
            "danger"
            if payload.level is MessageLevel.ERROR
            else payload.level.value
        ),
        format=payload.format,
        presentation=payload.presentation,
        href=payload.href,
        icon=payload.icon,
        created_at=row.created_at,
        read=row.read_at is not None,
    )


def _translated_items(request: Request, rows: list[Any]) -> tuple[_NotificationItemView, ...]:
    """Translate rows explicitly even when middleware did not bind a ContextVar."""
    catalog = getattr(request.ctx, "translations", None)
    return tuple(_translate_row(row, catalog) for row in rows)


async def render_topbar_fragment(
    request: Request,
    *,
    user_id: int,
) -> Markup:
    """Render one recipient's translated topbar fragment."""
    routes = _routes_for_request(request)
    rows = await notifications.topbar_for_user(user_id, limit=5)
    unread_count = await notifications.unread_count(user_id)
    view = _NotificationTopbarView(
        items=_translated_items(request, rows),
        unread_count=unread_count,
        center_url=routes.center_url,
    )
    template = request.app.ext.environment.get_template(_TOPBAR_TEMPLATE)
    return Markup(await template.render_async(view=view))


async def _build_center_view(
    request: Request,
    *,
    user_id: int,
) -> NotificationCenterView:
    """Query, clamp, and translate one notification-center page."""
    routes = _routes_for_request(request)
    state, requested_page = _parse_center_query(request)
    result = await notifications.list_for_user(
        user_id,
        state=state,
        page=requested_page,
    )
    total_pages = result.total_pages
    page = requested_page
    if total_pages == 0:
        page = 1
    elif requested_page > total_pages:
        page = total_pages
        result = await notifications.list_for_user(
            user_id,
            state=state,
            page=page,
        )

    current_url = (
        f"{routes.center_url}?state={state.value}&page={page}"
    )
    return NotificationCenterView(
        items=_translated_items(request, result.items),
        state=state,
        page=page,
        total_pages=max(total_pages, 1),
        read_url=routes.read_url,
        delete_url=routes.delete_url,
        topbar_url=routes.topbar_url,
        center_url=routes.center_url,
        current_url=current_url,
    )


async def render_center_content(
    request: Request,
    *,
    user_id: int,
) -> Markup:
    """Parse this request and render one translated notification-center body."""
    view = await _build_center_view(request, user_id=user_id)
    template = request.app.ext.environment.get_template(_CENTER_TEMPLATE)
    return Markup(await template.render_async(view=view))


__all__ = [
    "render_center_content",
    "render_topbar_fragment",
]
