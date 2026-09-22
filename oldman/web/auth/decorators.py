"""Authentication and shared-secret decorators for Oldman Web handlers."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from inspect import isawaitable
from typing import Any

from oldman.utils.crypto import constant_time_equals
from oldman.utils.decorators import method_adaptor
from oldman.web.api import DefaultApiResponse
from oldman.web.http import (
    ResponseMode,
    authentication_required_response,
    permission_denied_response,
    resolve_response_mode,
)
from oldman.web.request import Request, get_arg
from oldman.web.response import json_response
from oldman.web.session import SessionData


def _request_session(request: Request) -> SessionData | None:
    """Return the request's typed SessionData when Session is installed."""
    session = getattr(getattr(request, "ctx", None), "session", None)
    return session if isinstance(session, SessionData) else None


async def _call_handler(
    handler: Callable[..., Any],
    view: Any,
    request: Request,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Call one function or bound-view handler and await it when necessary."""
    if view is None:
        response = handler(request, *args, **kwargs)
    else:
        response = handler(view, request, *args, **kwargs)
    return await response if isawaitable(response) else response


def _login_required(
    login_url: str = "/login",
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require an authenticated SessionData for one Web handler."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            session = _request_session(request)
            if session is None or not session.is_authenticated():
                resolved_mode = resolve_response_mode(request, response_mode)
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )

            if user_keyword is not None:
                kwargs[user_keyword] = session.user_id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _api_login_required(*, user_keyword: str | None = None):
    """Require authentication and use the JSON authentication response."""
    return _login_required(response_mode="json", user_keyword=user_keyword)


def _staff_required(
    login_url: str = "/login",
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require an authenticated active staff SessionData."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            session = _request_session(request)
            resolved_mode = resolve_response_mode(request, response_mode)
            if session is None or not session.is_authenticated():
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )
            if not session.is_staff:
                return await permission_denied_response(
                    request,
                    resolved_mode,
                    message="Staff permission required",
                )

            if user_keyword is not None:
                kwargs[user_keyword] = session.user_id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _superuser_required(
    login_url: str = "/login",
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require an authenticated staff SessionData with superuser permission."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            session = _request_session(request)
            resolved_mode = resolve_response_mode(request, response_mode)
            if session is None or not session.is_authenticated():
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )
            if not session.is_staff or not session.is_superuser:
                return await permission_denied_response(
                    request,
                    resolved_mode,
                    message="Superuser permission required",
                )

            if user_keyword is not None:
                kwargs[user_keyword] = session.user_id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _api_authorized(secret_key: str):
    """Require one explicit query-string shared secret outside loopback.

    A request whose socket peer and resolved client address are both 127.0.0.1 skips the
    check entirely, so a local operator reaches the endpoint without the secret. Behind a
    reverse proxy that rests on `web.real_ip_header` and `web.proxies_count` being set:
    they are what makes `request.client_ip` the caller rather than the proxy in front of it.

    The secret travels in the query string, where access logs, browser history and the
    Referer header all see it. `api_key_authorized` reads the same kind of secret from the
    request token instead.
    """
    if not secret_key:
        raise ValueError("secret_key must not be empty")

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            is_loopback = request.ip == "127.0.0.1" and request.client_ip == "127.0.0.1"
            supplied_secret = str(get_arg(request.args, "admin_secrets", ""))
            if not is_loopback and not constant_time_equals(supplied_secret, secret_key):
                return _shared_secret_denied_response()
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _api_key_authorized(secret_key: str):
    """Require one explicit request-token shared secret.

    The token is Sanic's `request.token`: the Bearer or Token value of an Authorization
    header, or the header verbatim when it carries no scheme. Unlike `api_authorized`
    there is no loopback exemption — every caller presents the secret.
    """
    if not secret_key:
        raise ValueError("secret_key must not be empty")

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            if not constant_time_equals(request.token or "", secret_key):
                return _shared_secret_denied_response()
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _shared_secret_denied_response():
    """Return the source-compatible shared-secret denial payload."""
    payload = DefaultApiResponse(error_code=-1, message="not authorized", data={})
    return json_response(payload.to_dict(), status=403)


login_required = method_adaptor(_login_required)
api_login_required = method_adaptor(_api_login_required)
staff_required = method_adaptor(_staff_required)
superuser_required = method_adaptor(_superuser_required)
api_authorized = method_adaptor(_api_authorized)
api_key_authorized = method_adaptor(_api_key_authorized)

__all__ = [
    "api_authorized",
    "api_key_authorized",
    "api_login_required",
    "login_required",
    "staff_required",
    "superuser_required",
]
