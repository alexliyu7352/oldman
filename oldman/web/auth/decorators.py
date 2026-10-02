"""Authentication and permission decorators for Oldman Web handlers."""

from __future__ import annotations

from collections.abc import Callable, Collection
from functools import wraps
from inspect import isawaitable
from typing import Any

from oldman.i18n import gettext
from oldman.utils.decorators import method_adaptor
from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.authentication import HTTP_BASIC_METHOD, Authentication, http_basic_challenge, request_user
from oldman.web.http import (
    ResponseMode,
    authentication_required_response,
    permission_denied_response,
    resolve_response_mode,
)
from oldman.web.request import Request
from oldman.web.response import json_response


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
    login_url: str | None = None,
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require a signed-in user for one Web handler, however the request authenticated."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            user = request_user(request)
            if not user.is_authenticated:
                resolved_mode = resolve_response_mode(request, response_mode)
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )

            if user_keyword is not None:
                kwargs[user_keyword] = user.id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _api_login_required(*, user_keyword: str | None = None):
    """Require authentication and use the JSON authentication response."""
    return _login_required(response_mode="json", user_keyword=user_keyword)


def _staff_required(
    login_url: str | None = None,
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require a signed-in staff user."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            user = request_user(request)
            resolved_mode = resolve_response_mode(request, response_mode)
            if not user.is_authenticated:
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )
            if not user.is_staff:
                return await permission_denied_response(
                    request,
                    resolved_mode,
                    message=gettext("Staff permission required", request=request),
                )

            if user_keyword is not None:
                kwargs[user_keyword] = user.id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _superuser_required(
    login_url: str | None = None,
    *,
    response_mode: ResponseMode = "auto",
    user_keyword: str | None = None,
):
    """Require a signed-in staff user with superuser permission."""

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            user = request_user(request)
            resolved_mode = resolve_response_mode(request, response_mode)
            if not user.is_authenticated:
                return authentication_required_response(
                    request,
                    resolved_mode,
                    login_url=login_url,
                )
            if not user.is_staff or not user.is_superuser:
                return await permission_denied_response(
                    request,
                    resolved_mode,
                    message=gettext("Superuser permission required", request=request),
                )

            if user_keyword is not None:
                kwargs[user_keyword] = user.id
            return await _call_handler(handler, view, request, args, kwargs)

        return decorated_function

    return decorator


def _authenticated_by(
    *methods: str,
    callers: Collection[str] | None = None,
    login_url: str | None = None,
    response_mode: ResponseMode | None = None,
):
    """Admit a request only when it authenticated by one of ``methods``.

    For endpoints other services, scripts or internal networks call, where "is someone signed
    in" is the wrong question: ``authenticated_by("api_key")`` admits any configured key,
    ``authenticated_by("api_key", callers={"monitor"})`` only that one. ``callers`` restricts
    callers — the key, account or network a method recognized — and not users, so listing
    ``session`` or ``jwt`` beside them admits signed-in users as before.

    A request that authenticated no way at all gets 401; one that authenticated some other
    way, or as a caller not listed, gets 403. Where ``session`` is listed the answers follow
    the page's response mode like ``login_required``, a browser page going to the login page;
    otherwise they are JSON, since the callers are programs, and the 401 carries a
    ``WWW-Authenticate: Basic`` challenge when ``http_basic`` is listed.
    """
    if not methods:
        raise ValueError("authenticated_by needs at least one method")
    allowed_callers = None if callers is None else frozenset(callers)
    serves_browsers = "session" in methods
    challenges_basic = HTTP_BASIC_METHOD in methods and not serves_browsers
    mode: ResponseMode = response_mode or ("auto" if serves_browsers else "json")

    def decorator(handler: Callable[..., Any]):
        @wraps(handler)
        async def decorated_function(
            view: Any,
            request: Request,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            auth = getattr(getattr(request, "ctx", None), "auth", None)
            if (
                isinstance(auth, Authentication)
                and auth.method in methods
                and (allowed_callers is None or auth.caller is None or auth.caller in allowed_callers)
            ):
                return await _call_handler(handler, view, request, args, kwargs)
            resolved_mode = resolve_response_mode(request, mode)
            if not isinstance(auth, Authentication):
                if serves_browsers:
                    return authentication_required_response(request, resolved_mode, login_url=login_url)
                payload = DefaultApiResponse(
                    error_code=ApiErrorCode.AUTHENTICATION_REQUIRED,
                    message=gettext("Authentication required", request=request),
                )
                # Asking for Basic credentials is what makes a browser show its sign-in prompt.
                headers = {"WWW-Authenticate": http_basic_challenge()} if challenges_basic else None
                return json_response(payload.to_dict(), status=401, headers=headers)
            return await permission_denied_response(request, resolved_mode)

        return decorated_function

    return decorator


login_required = method_adaptor(_login_required)
api_login_required = method_adaptor(_api_login_required)
staff_required = method_adaptor(_staff_required)
superuser_required = method_adaptor(_superuser_required)
authenticated_by = method_adaptor(_authenticated_by)

__all__ = [
    "api_login_required",
    "authenticated_by",
    "login_required",
    "staff_required",
    "superuser_required",
]
