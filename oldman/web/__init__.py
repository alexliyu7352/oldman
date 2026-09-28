"""Lightweight public Web primitives for Oldman applications."""

from oldman.web.exceptions import BadRequest, Forbidden, NotFound, TooManyRequests, Unauthorized
from oldman.web.http import HTTPMethodView
from oldman.web.request import (
    Request,
    get_arg,
    get_current_request,
    request_accepts_json,
)
from oldman.web.response import (
    Response,
    StreamingResponse,
    StreamWriter,
    api_response,
    empty_response,
    html_response,
    json_response,
    raw_response,
    redirect_response,
    replace_html_response,
    stream_response,
    text_response,
)
from oldman.web.routing import Router, WebApp, autodiscover, import_app_modules, router
from oldman.web.template import render_template

__all__ = [
    "BadRequest",
    "Forbidden",
    "HTTPMethodView",
    "NotFound",
    "Request",
    "Response",
    "StreamingResponse",
    "StreamWriter",
    "WebApp",
    "api_response",
    "autodiscover",
    "empty_response",
    "Router",
    "router",
    "get_arg",
    "get_current_request",
    "html_response",
    "import_app_modules",
    "json_response",
    "raw_response",
    "redirect_response",
    "replace_html_response",
    "render_template",
    "request_accepts_json",
    "stream_response",
    "text_response",
    "TooManyRequests",
    "Unauthorized",
]
