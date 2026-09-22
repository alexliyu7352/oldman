"""Sanic HTTP runtime for persistent user notifications."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from sanic import Sanic
from sanic.exceptions import BadRequest, NotFound

import oldman.conf as conf
from oldman.apps.config import AppNotInstalledError
from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.auth import api_login_required, login_required
from oldman.web.messages.notifications.payloads import NotificationPayload
from oldman.web.messages.notifications.rendering import (
    _ROUTES_CONTEXT_ATTRIBUTE,
    render_topbar_fragment,
)
from oldman.web.messages.notifications.service import (
    notifications,
)
from oldman.web.messages.paths import is_same_site_path
from oldman.web.request import Request
from oldman.web.response import (
    Response,
    api_response,
    html_response,
    redirect_response,
)
from oldman.web.security.csrf import csrf_protect
from oldman.web.template import install_template_loaders

_NOTIFICATIONS_PACKAGE = "oldman.web.messages.notifications"


@dataclass(frozen=True, slots=True)
class NotificationRoutes:
    """Stable notification URLs derived for one host prefix."""

    topbar_url: str
    read_url: str
    delete_url: str
    center_url: str


def _normalize_prefix(value: str) -> str:
    """Return one absolute route prefix without a trailing slash."""
    if not isinstance(value, str):
        raise TypeError("url_prefix must be a string")
    if value in {"", "/"}:
        return ""
    if not value.startswith("/") or "//" in value or "\\" in value or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError("url_prefix must be a safe absolute path")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("url_prefix must contain only an absolute path")
    return value.rstrip("/")


def _route_name(prefix: str, action: str) -> str:
    """Derive collision-free internal Sanic names from the normalized prefix."""
    owner = "root" if not prefix else hashlib.sha256(prefix.encode()).hexdigest()[:12]
    return f"oldman_notifications_{owner}_{action}"


def _validate_dependencies(app: Sanic) -> None:
    """Fail before route registration when the host runtime is incomplete."""
    registry = getattr(app.ctx, "oldman_app_registry", None)
    if registry is None:
        raise RuntimeError("Notification Web routes require app.ctx.oldman_app_registry")
    try:
        registry.get_by_package(_NOTIFICATIONS_PACKAGE)
    except (AppNotInstalledError, LookupError) as exc:
        raise RuntimeError("Notification Web routes require the notifications App to be installed") from exc
    if not conf.settings.web.session.enabled:
        raise RuntimeError("Notification Web routes require Web Session to be enabled")
    environment = getattr(getattr(app, "ext", None), "environment", None)
    if environment is None:
        raise RuntimeError("Notification Web routes require the Sanic-Ext template environment")
    if getattr(app.ctx, "csrf", None) is None:
        raise RuntimeError("Notification Web routes require an installed CSRF manager")


def _parse_ids(value: object) -> tuple[int, ...]:
    """Validate a non-empty JSON integer array and deduplicate in request order."""
    if not isinstance(value, list) or not value:
        raise ValueError("ids must be a non-empty array")
    normalized: dict[int, None] = {}
    for notification_id in value:
        if type(notification_id) is not int or notification_id <= 0:
            raise ValueError("ids must contain positive integers")
        normalized[notification_id] = None
    return tuple(normalized)


def _read_operation(value: object) -> tuple[str, tuple[int, ...]]:
    """Return the one exact read operation represented by a JSON object."""
    if not isinstance(value, dict):
        raise ValueError("request body must be an object")
    if set(value) == {"ids"}:
        return "selected", _parse_ids(value["ids"])
    if set(value) == {"all"} and value["all"] is True:
        return "all", ()
    raise ValueError("request body must contain only ids or all=true")


def _delete_ids(value: object) -> tuple[int, ...]:
    """Return the exact selected-delete shape accepted by the endpoint."""
    if not isinstance(value, dict) or set(value) != {"ids"}:
        raise ValueError("request body must contain only ids")
    return _parse_ids(value["ids"])


def _invalid_request(message: str) -> Response:
    """Return the framework's established API error envelope."""
    return api_response(
        DefaultApiResponse(
            error_code=ApiErrorCode.INVALID_REQUEST,
            message=message,
        ),
        status=400,
    )


def init_app(app: Sanic, *, url_prefix: str = "") -> NotificationRoutes:
    """Install shared endpoints once and return shared and host-wrapper URLs."""
    prefix = _normalize_prefix(url_prefix)
    installed = getattr(app.ctx, _ROUTES_CONTEXT_ATTRIBUTE, None)
    if isinstance(installed, dict) and prefix in installed:
        return installed[prefix]

    _validate_dependencies(app)
    environment = app.ext.environment
    install_template_loaders(environment)

    center_url = f"{prefix}/user-notifications"
    routes = NotificationRoutes(
        topbar_url=f"{center_url}/topbar",
        read_url=f"{center_url}/read",
        delete_url=f"{center_url}/delete",
        center_url=center_url,
    )

    @login_required(
        login_url=f"{prefix}/login",
        user_keyword="user_id",
    )
    async def topbar(request: Request, *, user_id: int) -> Response:
        fragment = await render_topbar_fragment(request, user_id=user_id)
        return html_response(fragment)

    @api_login_required(user_keyword="user_id")
    @csrf_protect()
    async def read(request: Request, *, user_id: int) -> Response:
        try:
            operation, notification_ids = _read_operation(request.json)
        except (BadRequest, TypeError, ValueError) as exc:
            return _invalid_request(str(exc))
        changed = await notifications.mark_all_read(user_id) if operation == "all" else await notifications.mark_read(user_id, notification_ids)
        return api_response(DefaultApiResponse(data={"changed": changed}))

    @api_login_required(user_keyword="user_id")
    @csrf_protect()
    async def delete(request: Request, *, user_id: int) -> Response:
        try:
            notification_ids = _delete_ids(request.json)
        except (BadRequest, TypeError, ValueError) as exc:
            return _invalid_request(str(exc))
        changed = await notifications.delete(user_id, notification_ids)
        return api_response(DefaultApiResponse(data={"changed": changed}))

    @login_required(
        login_url=f"{prefix}/login",
        user_keyword="user_id",
    )
    async def open_notification(
        request: Request,
        notification_id: int,
        *,
        user_id: int,
    ) -> Response:
        del request
        notification = await notifications.get_for_user(user_id, notification_id)
        if notification is None:
            raise NotFound("Notification was not found")
        payload = NotificationPayload.from_msgpack(notification.payload)
        if payload.href is not None and not is_same_site_path(payload.href):
            raise NotFound("Notification target was not found")
        await notifications.mark_read(user_id, (notification_id,))
        return redirect_response(payload.href or routes.center_url, status=303)

    app.add_route(
        cast(Any, topbar),
        routes.topbar_url,
        methods=["GET"],
        name=_route_name(prefix, "topbar"),
    )
    app.add_route(
        cast(Any, read),
        routes.read_url,
        methods=["POST"],
        name=_route_name(prefix, "read"),
    )
    app.add_route(
        cast(Any, delete),
        routes.delete_url,
        methods=["POST"],
        name=_route_name(prefix, "delete"),
    )
    app.add_route(
        cast(Any, open_notification),
        f"{routes.center_url}/<notification_id:int>/open",
        methods=["GET"],
        name=_route_name(prefix, "open"),
    )

    if not isinstance(installed, dict):
        installed = {}
        setattr(app.ctx, _ROUTES_CONTEXT_ATTRIBUTE, installed)
    installed[prefix] = routes
    return routes


__all__ = ["NotificationRoutes", "init_app"]
