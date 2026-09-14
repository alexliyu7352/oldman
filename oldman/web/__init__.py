"""Lightweight public Web primitives for Oldman applications."""

from oldman.web.exceptions import Forbidden, NotFound
from oldman.web.http import HTTPMethodView, OldmanHTTPMethodView
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
from oldman.web.routing import WebApp, autodiscover, get_app, import_app_modules
from oldman.web.template import render_template

__all__ = [
    "Forbidden",
    "HTTPMethodView",
    "NotFound",
    "OldmanHTTPMethodView",
    "Request",
    "Response",
    "StreamingResponse",
    "StreamWriter",
    "WebApp",
    "api_response",
    "autodiscover",
    "empty_response",
    "get_app",
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
]
