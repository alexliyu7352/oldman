"""Oldman names for Sanic response types and factories."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any, cast

from markupsafe import Markup
from sanic.response import BaseHTTPResponse as Response
from sanic.response import HTTPResponse
from sanic.response import ResponseStream as StreamingResponse
from sanic.response import empty as sanic_empty
from sanic.response import html as sanic_html
from sanic.response import json as sanic_json
from sanic.response import raw as sanic_raw
from sanic.response import redirect as sanic_redirect
from sanic.response import text as sanic_text

from oldman.web.api import DefaultApiResponse, HtmlSwap, ReplaceHtmlAction

StreamWriter = StreamingResponse


def api_response(payload: DefaultApiResponse, *, status: int = 200) -> Response:
    """Return a native JSON response for an Oldman API payload."""
    return json_response(payload.to_dict(), status=status)


def replace_html_response(
    html: str | Markup,
    *,
    target: str | None = None,
    swap: HtmlSwap | None = None,
    status: int = 200,
) -> Response:
    """Return one JSON replace-html action for a successful request."""
    if not 200 <= status < 300:
        raise ValueError("replace_html_response status must be between 200 and 299")
    return api_response(
        DefaultApiResponse(
            actions=[ReplaceHtmlAction(html=str(html), target=target, swap=swap)]
        ),
        status=status,
    )


def json_response(
    body: Any,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    content_type: str = "application/json",
    dumps: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> Response:
    """Create a Sanic JSON response under the stable Oldman name."""
    return sanic_json(
        body,
        status=status,
        headers=_headers_dict(headers),
        content_type=content_type,
        dumps=dumps,
        **kwargs,
    )


def text_response(
    body: str,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    content_type: str | None = "text/plain; charset=utf-8",
) -> Response:
    """Create a text response while allowing an omitted upstream content type."""
    if content_type is None:
        return HTTPResponse(
            body,
            status=status,
            headers=_headers_dict(headers),
            content_type=None,
        )
    return sanic_text(
        body,
        status=status,
        headers=_headers_dict(headers),
        content_type=content_type,
    )


def html_response(body: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> Response:
    """Create a Sanic HTML response under the stable Oldman name."""
    return sanic_html(body, status=status, headers=_headers_dict(headers))


def redirect_response(
    to: str,
    headers: Mapping[str, str] | None = None,
    status: int = 302,
    content_type: str = "text/html; charset=utf-8",
) -> Response:
    """Create a Sanic redirect response under the stable Oldman name."""
    return sanic_redirect(
        to,
        headers=_headers_dict(headers),
        status=status,
        content_type=content_type,
    )


def empty_response(status: int = 204, headers: Mapping[str, str] | None = None) -> Response:
    """Create a Sanic empty response under the stable Oldman name."""
    return sanic_empty(status=status, headers=_headers_dict(headers))


def raw_response(
    body: str | bytes | None,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    content_type: str = "application/octet-stream",
) -> Response:
    """Create a Sanic raw response under the stable Oldman name."""
    return sanic_raw(
        cast(Any, body),
        status=status,
        headers=_headers_dict(headers),
        content_type=content_type,
    )


def stream_response(
    streaming_fn: Callable[[StreamWriter], Awaitable[None]],
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    content_type: str | None = None,
) -> StreamingResponse:
    """Create a Sanic streaming response under the stable Oldman name."""
    return StreamingResponse(
        cast(Callable[[Any], Coroutine[Any, Any, None]], streaming_fn),
        status=status,
        headers=_headers_dict(headers),
        content_type=content_type,
    )


def _headers_dict(headers: Mapping[str, str] | None) -> dict[str, str] | None:
    """Normalize general mappings for Sanic's concrete header contract."""
    return dict(headers) if headers is not None else None


__all__ = [
    "Response",
    "StreamWriter",
    "StreamingResponse",
    "api_response",
    "empty_response",
    "html_response",
    "json_response",
    "raw_response",
    "redirect_response",
    "replace_html_response",
    "stream_response",
    "text_response",
]
