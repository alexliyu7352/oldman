"""
@author:alex
@date:2025/8/10
@time:13:49
"""

__author__ = "alex"
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from oldman.contrib.http.base import BaseHttpClient
from oldman.contrib.http.response import (
    HttpHeaders,
    HttpResponse,
    HttpStreamResponse,
    cookie_jar_from_headers,
)
from oldman.contrib.http.schemas import HttpMethod
from oldman.logging import logger

# 只在类型检查时导入，避免循环导入
if TYPE_CHECKING:
    from oldman.contrib.http.multi_client import MultiHttpClient


def _metadata(response: httpx.Response) -> dict[str, Any]:
    """构造普通响应和流响应共享的元数据。"""

    headers = HttpHeaders(response.headers.multi_items())
    url = str(response.url)
    return {
        "status_code": response.status_code,
        "url": url,
        "headers": headers,
        "cookies": cookie_jar_from_headers(headers, url),
        "encoding": response.encoding,
        "reason": response.reason_phrase,
        "http_version": response.http_version,
        "native_response": response,
    }


class HttpxClient(BaseHttpClient):
    """HTTPX实现的HTTP客户端"""

    def __init__(self, parent: "MultiHttpClient"):
        """
        初始化HTTPX客户端

        Args:
            parent: 父MultiHttpClient实例，包含配置信息
        """
        self.parent = parent
        self.http_client: httpx.AsyncClient | None = None
        # 连接池可以周期重建，但客户端级 Cookie 状态必须跨 reset 保留。
        self.cookie_jar = parent.cookie_jar if parent.cookie_jar is not None else CookieJar()

    session_attribute: ClassVar[str] = "http_client"
    backend_label: ClassVar[str] = "HTTPX"

    async def init_client(self) -> None:
        """初始化HTTPX客户端"""
        logger.info(f"初始化HTTPX客户端, 最大连接数: {self.parent.max_connections}")

    async def close_session(self, session: Any) -> None:
        """关闭 HTTPX 客户端。"""
        await session.aclose()

    async def get_client(self) -> httpx.AsyncClient:
        """获取或创建HTTPX客户端实例"""
        async with self.parent.lock:
            if self.http_client is None or self.http_client.is_closed:
                # 配置连接池
                limits = httpx.Limits(
                    max_keepalive_connections=self.parent.max_connections // 2,
                    max_connections=self.parent.max_connections,
                    keepalive_expiry=self.parent.keepalive_expiry,
                )

                # 配置传输层
                transport = httpx.AsyncHTTPTransport(
                    verify=self.parent.verify,
                    retries=0,  # 禁用内置重试，使用我们自己的重试逻辑
                    limits=limits,
                )

                # 配置超时
                timeout = httpx.Timeout(
                    timeout=self.parent.read_timeout * 2,
                    read=self.parent.read_timeout,
                    connect=self.parent.connect_timeout,
                )

                # 创建客户端
                self.http_client = httpx.AsyncClient(
                    verify=self.parent.verify,
                    proxy=self.parent.proxy_url,
                    timeout=timeout,
                    follow_redirects=True,
                    cookies=self.cookie_jar,
                    limits=limits,
                    transport=transport,
                )  # type: ignore
            return self.http_client

    def prepare_request_params(self, **kwargs: Any) -> dict[str, Any]:
        """转换 HTTPX 参数并补充统一 User-Agent。"""

        # 处理超时参数
        timeout = kwargs.pop("timeout", None)
        if timeout is not None:
            if isinstance(timeout, (int, float)):
                from httpx import Timeout

                timeout = Timeout(timeout)
            kwargs["timeout"] = timeout
        # 添加用户代理
        headers = dict(kwargs.get("headers", {}))
        if not any(name.lower() == "user-agent" for name in headers):
            headers["User-Agent"] = self.parent.user_agent
        if not any(name.lower() == "accept-encoding" for name in headers):
            headers["Accept-Encoding"] = "gzip, deflate" if self.parent.content_decoding else "identity"
        kwargs["headers"] = headers
        return kwargs

    def _stream_response(self, response: httpx.Response) -> HttpStreamResponse:
        """把 HTTPX 流响应适配为统一流接口。"""

        async def iter_raw():
            """逐块读取 HTTPX 的 wire-level 内容。"""

            async for chunk in response.aiter_raw():
                yield chunk

        async def close() -> None:
            """关闭 HTTPX 流响应。"""

            await response.aclose()

        return HttpStreamResponse(
            **_metadata(response),
            iter_raw=iter_raw,
            close=close,
            decode_content=self.parent.content_decoding,
        )

    async def request(self, method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse:
        """执行HTTPX请求"""
        client = await self.get_client()
        kwargs = self.prepare_request_params(**kwargs)
        # 通过 raw stream 完整读取一次，确保原始正文不会被 HTTPX 自动解码后丢失。
        async with client.stream(method, url, **kwargs) as response:
            raw_content = b"".join([chunk async for chunk in response.aiter_raw()])
            return HttpResponse(
                **_metadata(response),
                raw_content=raw_content,
                decode_content=self.parent.content_decoding,
            )

    @asynccontextmanager
    async def stream(self, method: HttpMethod, url: str, **kwargs: Any):
        """流式请求上下文管理器"""
        client = await self.get_client()
        kwargs = self.prepare_request_params(**kwargs)
        # 执行流式请求
        async with client.stream(method, url, **kwargs) as response:
            stream_response = self._stream_response(response)
            try:
                yield stream_response
            finally:
                await stream_response.aclose()

    @asynccontextmanager
    async def reconnect_stream(
        self,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs: Any,
    ):
        """复用统一流适配器，生命周期由断点续传对象显式持有。"""

        del live_stream
        async with self.stream(method, url, **kwargs) as response:
            yield response
