"""Oldman 后端组件 HTTP 视图基类。"""

from __future__ import annotations

import inspect
from typing import Any, Literal
from urllib.parse import quote

from sanic.exceptions import Forbidden
from sanic.views import HTTPMethodView as SanicHTTPMethodView

import oldman.conf as conf
from oldman.i18n import gettext
from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.authentication import request_user
from oldman.web.errors import render_html_error_response
from oldman.web.request import bearer_credential, get_arg
from oldman.web.response import json_response, redirect_response

ResponseMode = Literal["auto", "html", "json"]


def resolve_response_mode(request: Any, default: ResponseMode = "auto") -> Literal["html", "json"]:
    """按 response_mode 参数优先、Accept 兜底解析响应模式。

    出示了 Bearer 令牌的请求来自 API 客户端:令牌过期时它要的是 JSON 401,不是跳转到登录页的 302。
    只认 Bearer,不认任意 Authorization——代理在测试站前面加的 HTTP Basic 不该把整站变成 JSON。
    """
    args = getattr(request, "args", {}) or {}
    value = str(get_arg(args, "response_mode", "") or "").lower()
    if value in {"html", "json"}:
        return value  # type: ignore[return-value]
    if default in {"html", "json"}:
        return default  # type: ignore[return-value]
    if bearer_credential(request) is not None:
        return "json"
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "json" if "application/json" in accept else "html"


def build_login_url(request: Any, login_url: str | None = None) -> str:
    """构造包含原始 path/query 的登录跳转地址;`login_url` 省略时用站点的 `web.account.login_url`。"""
    if login_url is None:
        login_url = conf.settings.web.account.login_url
    path = str(getattr(request, "path", "") or "/")
    query_string = str(getattr(request, "query_string", "") or "")
    next_url = f"{path}?{query_string}" if query_string else path
    separator = "&" if "?" in login_url else "?"
    return f"{login_url}{separator}next={quote(next_url, safe='')}"


def authentication_required_response(
    request: Any,
    response_mode: Literal["html", "json"],
    *,
    login_url: str | None = None,
):
    """返回未登录响应;`login_url` 省略时用站点的 `web.account.login_url`。"""
    if login_url is None:
        login_url = conf.settings.web.account.login_url
    headers = getattr(request, "headers", {}) or {}
    is_oldman_request = str(headers.get("x-requested-with", "")).lower() == "xmlhttprequest"
    if response_mode == "json" or is_oldman_request:
        payload = DefaultApiResponse(
            error_code=ApiErrorCode.AUTHENTICATION_REQUIRED,
            message=gettext("Authentication required", request=request),
            data={"login_url": login_url},
        )
        return json_response(payload.to_dict(), status=401)
    return redirect_response(build_login_url(request, login_url), status=302)


async def permission_denied_response(request: Any, response_mode: Literal["html", "json"], *, message: str | None = None):
    """返回 JSON 403 或项目可覆盖的 HTML 403 页面;没给 message 时用翻译后的"没有权限"。"""
    message = message or gettext("Permission denied", request=request)
    if response_mode == "json":
        payload = DefaultApiResponse(error_code=ApiErrorCode.PERMISSION_DENIED, message=message)
        return json_response(payload.to_dict(), status=403)
    return await render_html_error_response(request, Forbidden(message))


async def access_denied_response(request: Any, *, login_url: str | None = None, response_mode: ResponseMode = "auto"):
    """Turn away a request a page's own check refused: 403 when signed in, the login protocol otherwise.

    For checks the decorators do not express, such as the built-in Admin's "may use the Admin at
    all" or an account page's `allow`. `login_url` omitted, the site's `web.account.login_url`.
    """
    resolved_mode = resolve_response_mode(request, response_mode)
    if request_user(request).is_authenticated:
        return await permission_denied_response(request, resolved_mode)
    return authentication_required_response(request, resolved_mode, login_url=login_url)


class HTTPMethodView(SanicHTTPMethodView):
    """Sanic 的 HTTPMethodView 加上 Oldman 的登录与 staff 权限协议。

    ``require_authenticated`` 与 ``require_staff`` 默认关闭,此时行为与 Sanic 的原类相同。
    """

    require_authenticated = False
    require_staff = False
    response_mode: ResponseMode = "auto"

    async def dispatch_request(self, request: Any, *args: object, **kwargs: object):
        """执行认证/权限检查后按 Sanic HTTPMethodView 规则分派 method。"""
        self.request = request
        method_name = str(getattr(request, "method", "")).lower()
        response_mode = resolve_response_mode(request, self.response_mode)
        route_kwargs = dict(kwargs)

        if self.require_authenticated and not self.is_authenticated(request):
            return await self.resolve_hook_response(self.on_authentication_required(request, response_mode, method_name=method_name))

        if self.require_staff and not self.is_staff(request):
            denied = gettext("Permission denied", request=request)
            return await self.resolve_hook_response(self.on_permission_denied(request, response_mode, message=denied, method_name=method_name))

        allowed, message = await self.check_permission(request, method_name=method_name, route_kwargs=route_kwargs)
        if not allowed:
            return await self.resolve_hook_response(
                self.on_permission_denied(
                    request, response_mode, message=message or gettext("Permission denied", request=request), method_name=method_name
                )
            )

        handler = getattr(self, method_name, None)
        if not handler and method_name == "head":
            handler = getattr(self, "get", None)
        if not handler:
            raise NotImplementedError(f"{request.method} is not supported for this endpoint.")

        result = handler(request, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def is_authenticated(self, request: Any) -> bool:
        """判断请求是否来自已登录用户,不论它凭什么认证。"""
        return request_user(request).is_authenticated

    def is_staff(self, request: Any) -> bool:
        """判断请求用户是否具备后台 staff 权限;匿名用户一律没有。"""
        return request_user(request).is_staff

    async def check_permission(self, request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]:
        """endpoint 级权限 hook，默认允许。"""
        del request, method_name, route_kwargs
        return True, None

    async def resolve_hook_response(self, response: Any) -> Any:
        """兼容同步和异步权限响应 hook。"""
        if inspect.isawaitable(response):
            return await response
        return response

    def on_authentication_required(self, request: Any, response_mode: Literal["html", "json"], *, method_name: str):
        """未登录响应 hook。"""
        del method_name
        return authentication_required_response(request, response_mode)

    async def on_permission_denied(self, request: Any, response_mode: Literal["html", "json"], *, message: str, method_name: str):
        """无权限响应 hook。"""
        del method_name
        return await permission_denied_response(request, response_mode, message=message)


__all__ = [
    "HTTPMethodView",
    "access_denied_response",
    "authentication_required_response",
    "build_login_url",
    "permission_denied_response",
    "resolve_response_mode",
]
