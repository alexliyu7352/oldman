"""
@author:alex
@date:2025/8/10
@time:13:44
"""

from __future__ import annotations

__author__ = "alex"

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar
from typing import TYPE_CHECKING, Any

from oldman.contrib.http.exceptions import HTTPClientError, HttpStatusError, RequestFailedError
from oldman.contrib.http.schemas import HttpMethod

if TYPE_CHECKING:
    from oldman.contrib.http.response import HttpResponse, HttpStreamResponse


class BaseHttpClient:
    """所有HTTP客户端实现必须遵循的基础接口"""

    async def init_client(self) -> None:
        """初始化 backend，但不要求立即建立网络连接。"""

        raise NotImplementedError

    async def reset_client(self) -> bool:
        """重置 backend 持有的会话。"""

        raise NotImplementedError

    async def close_client(self) -> None:
        """关闭 backend 持有的资源。"""

        raise NotImplementedError

    def export_cookie_jar(self, destination: CookieJar) -> None:
        """把 backend 运行态 Cookie 导出到标准库 jar；直接使用该 jar 的实现无需处理。"""

    async def request(self, method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse:
        """执行普通请求并返回统一的缓冲响应。"""

        raise NotImplementedError

    @asynccontextmanager
    async def stream(self, method: HttpMethod, url: str, **kwargs: Any) -> AsyncIterator[HttpStreamResponse]:
        """打开统一的流式响应上下文。"""

        raise NotImplementedError
        yield  # pragma: no cover

    @asynccontextmanager
    async def reconnect_stream(
        self,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """打开供断点续传包装器管理的 backend 流上下文。"""

        raise NotImplementedError
        yield  # pragma: no cover

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """GET请求"""
        return await self.request(HttpMethod.GET, url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> HttpResponse:
        """POST请求"""
        return await self.request(HttpMethod.POST, url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> HttpResponse:
        """PUT请求"""
        return await self.request(HttpMethod.PUT, url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> HttpResponse:
        """DELETE请求"""
        return await self.request(HttpMethod.DELETE, url, **kwargs)


__all__ = [
    "BaseHttpClient",
    "HTTPClientError",
    "HttpStatusError",
    "RequestFailedError",
]
