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
from typing import TYPE_CHECKING, Any, ClassVar

from oldman.contrib.http.exceptions import HTTPClientError, HttpStatusError, RequestFailedError
from oldman.contrib.http.schemas import HttpMethod
from oldman.logging import logger

if TYPE_CHECKING:
    from oldman.contrib.http.response import HttpResponse, HttpStreamResponse


class BaseHttpClient:
    """所有HTTP客户端实现必须遵循的基础接口"""

    async def init_client(self) -> None:
        """初始化 backend，但不要求立即建立网络连接。"""

        raise NotImplementedError

    #: 持有活动会话的属性名；下面两个模板方法据此管理它。
    session_attribute: ClassVar[str] = ""
    #: 日志里用来指代这个 backend 的名字。
    backend_label: ClassVar[str] = "HTTP"

    async def close_session(self, session: Any) -> None:
        """关闭一个活动会话。子类用自己的关闭调用覆盖它。"""

        raise NotImplementedError

    async def reset_client(self) -> bool:
        """丢弃当前会话，下次请求会重新建立。失败向上抛，由调用方决定冷却。

        **先摘引用，再关闭。** `close_session` 抛错或被取消时，属性已经是 None，下一次请求
        会新建会话；反过来先关后清，那个关不掉的会话会被继续复用，而上层挡不住——
        `MultiHttpClient.reset_client` 捕获这次异常后只记日志、设冷却、返回 False，**不会
        替你换掉会话**，冷却过后还是去关同一个坏会话。

        接受的代价：关闭失败的那个会话没人再持有它，aiohttp 会在 GC 时打
        "Unclosed client session"。这是有意的——reset 的语义就是丢弃。
        下面的 `close_client` 走的是**相反**的契约：它失败时保留会话，好让退出清理再试一次。
        两者的差异是刻意的，不要"统一"掉。
        """

        session = getattr(self, self.session_attribute, None)
        if session is not None:
            setattr(self, self.session_attribute, None)
            await self.close_session(session)
        logger.info(f"{self.backend_label}客户端已重置")
        return True

    async def close_client(self) -> bool:
        """释放会话资源。

        永远不抛普通异常：调用方大多是业务里的收尾代码，不应该被迫去 catch。失败时
        记日志、返回 False，并且**保留会话**——上层据此保留 backend 引用，退出清理或
        下一次关闭还能再试一次。全部吞掉再置空，会让会话活着却再也没人能关。
        取消（CancelledError 属于 BaseException）照常向上传递。
        """

        session = getattr(self, self.session_attribute, None)
        if session is None:
            return True
        try:
            await self.close_session(session)
        except Exception as exc:
            logger.error(f"关闭{self.backend_label}客户端时出错: {type(exc).__name__}")
            return False
        setattr(self, self.session_attribute, None)
        logger.info(f"{self.backend_label}资源清理完成")
        return True

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
