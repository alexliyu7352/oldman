"""
@author:alex
@date:2025/8/10
@time:13:49
"""

__author__ = "alex"

from contextlib import asynccontextmanager
from email.utils import formatdate
from http.cookiejar import Cookie, CookieJar
from http.cookies import Morsel
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

import aiohttp
from aiohttp import AsyncResolver
from yarl import URL

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

# MozillaCookieJar 使用该历史拼写编码 Netscape 文件中的 HttpOnly 标记。
_HTTP_ONLY_ATTR = "HTTPOnly"


def _header_items(response: aiohttp.ClientResponse) -> list[tuple[str, str]]:
    """复制 aiohttp 的重复响应头。"""

    return list(response.headers.items())


def _http_version(response: aiohttp.ClientResponse) -> str:
    """把 aiohttp version 对象转成常见 HTTP/x.y 文本。"""

    version = response.version
    if version is None:
        return ""
    return f"HTTP/{version.major}.{version.minor}"


def _response_metadata(response: aiohttp.ClientResponse) -> dict[str, Any]:
    """构造普通响应和流响应共享的元数据。"""

    headers = HttpHeaders(_header_items(response))
    url = str(response.url)
    return {
        "status_code": response.status,
        "url": url,
        "headers": headers,
        "cookies": cookie_jar_from_headers(headers, url),
        "encoding": response.charset,
        "reason": response.reason or "",
        "http_version": _http_version(response),
        "native_response": response,
    }


def _to_aiohttp_cookie(cookie: Cookie) -> tuple[Morsel[str], URL]:
    """把一个标准库 Cookie 导入 aiohttp 原生 CookieJar。"""

    value = cookie.value or ""
    morsel: Morsel[str] = Morsel()
    morsel.set(cookie.name, value, value)

    if cookie.domain_specified:
        morsel["domain"] = cookie.domain
    if cookie.path:
        morsel["path"] = cookie.path
    if cookie.secure:
        morsel["secure"] = True
    if cookie.expires is not None:
        morsel["expires"] = formatdate(cookie.expires, usegmt=True)
    if cookie.comment:
        morsel["comment"] = cookie.comment
    if cookie.version:
        morsel["version"] = str(cookie.version)
    if cookie.has_nonstandard_attr(_HTTP_ONLY_ATTR) or cookie.has_nonstandard_attr("HttpOnly"):
        morsel["httponly"] = True
    if same_site := cookie.get_nonstandard_attr("SameSite"):
        morsel["samesite"] = str(same_site)

    host = cookie.domain.lstrip(".")
    if not host:
        return morsel, URL()
    scheme = "https" if cookie.secure else "http"
    return morsel, URL.build(scheme=scheme, host=host, path=cookie.path or "/")


def _import_cookie_jar(native_jar: aiohttp.CookieJar, cookies: CookieJar) -> None:
    """首次创建 aiohttp CookieJar 时导入外部标准库 CookieJar。"""

    for cookie in cookies:
        morsel, response_url = _to_aiohttp_cookie(cookie)
        native_jar.update_cookies({cookie.name: morsel}, response_url=response_url)


def _export_cookie_jar(native_jar: aiohttp.CookieJar, destination: CookieJar) -> None:
    """把 aiohttp 原生 CookieJar 的有效状态导出到标准库 CookieJar。"""

    # aiohttp 没有公开过期时间的导出接口；精确锁定 3.14.3 后把私有访问限制在此边界。
    native_jar._do_expiration()  # pyright: ignore[reportPrivateUsage]
    exported: list[Cookie] = []
    host_only_cookies = native_jar.host_only_cookies
    for (domain, storage_path), cookies in native_jar.cookies.items():
        for name, morsel in cookies.items():
            host_only = (domain, name) in host_only_cookies
            domain_cookie = bool(domain) and not host_only
            cookie_domain = f".{domain.lstrip('.')}" if domain_cookie else domain
            expiration = native_jar._expirations.get(  # pyright: ignore[reportPrivateUsage]
                (domain, storage_path, name)
            )
            rest: dict[str, str] = {}
            if morsel["httponly"]:
                rest[_HTTP_ONLY_ATTR] = ""
            if morsel["samesite"]:
                rest["SameSite"] = morsel["samesite"]
            try:
                version = int(morsel["version"] or 0)
            except ValueError:
                version = 0
            exported.append(
                Cookie(
                    version=version,
                    name=name,
                    value=morsel.value,
                    port=None,
                    port_specified=False,
                    domain=cookie_domain,
                    domain_specified=domain_cookie,
                    domain_initial_dot=domain_cookie,
                    # aiohttp 会把未指定的 Path 规范化成实际路径；导出保留其有效
                    # 运行态，不承诺还原最初 Cookie.path_specified 的元数据。
                    path=morsel["path"] or "/",
                    path_specified=bool(morsel["path"]),
                    secure=bool(morsel["secure"]),
                    expires=int(expiration) if expiration is not None else None,
                    discard=expiration is None,
                    comment=morsel["comment"] or None,
                    comment_url=None,
                    rest=rest,
                    rfc2109=False,
                )
            )

    # 外部 jar 的所有权仍归调用方。多个客户端共享同一个可变 jar 时遵循最后写回者
    # 覆盖，框架不做无法可靠实现的独占检测或跨客户端状态合并。
    destination.clear()
    for cookie in exported:
        destination.set_cookie(cookie)


def _to_aiohttp_cookie_jar(cookies: CookieJar | None) -> aiohttp.CookieJar:
    """使用外部标准库 Cookie 状态初始化 aiohttp 原生传输 jar。"""

    native_jar = aiohttp.CookieJar(unsafe=cookies is not None)
    if cookies is not None:
        _import_cookie_jar(native_jar, cookies)
    return native_jar


class AioHttpClient(BaseHttpClient):
    """aiohttp实现的HTTP客户端"""

    def __init__(self, parent: "MultiHttpClient"):
        """
        初始化aiohttp客户端

        Args:
            parent: 父MultiHttpClient实例，包含配置信息
        """
        self.parent = parent
        self.session: aiohttp.ClientSession | None = None
        self._native_cookie_jar: aiohttp.CookieJar | None = None

    session_attribute: ClassVar[str] = "session"
    backend_label: ClassVar[str] = "aiohttp"

    async def init_client(self) -> None:
        """初始化aiohttp客户端"""
        logger.info(f"初始化aiohttp客户端, 最大连接数: {self.parent.max_connections}")

    async def close_session(self, session: Any) -> None:
        """关闭 aiohttp 会话。"""
        await session.close()

    async def get_client(self) -> aiohttp.ClientSession:
        """获取或创建aiohttp会话"""

        async with self.parent.lock:
            if self.session is None or self.session.closed:
                # 配置TCP连接器
                if self.parent.nameservers:
                    resolver = AsyncResolver(nameservers=self.parent.nameservers)
                else:
                    resolver = None

                # ===== 解析代理认证 =====
                proxy_url = self.parent.proxy_url
                proxy_auth = None

                if proxy_url and "@" in proxy_url:
                    parsed = urlparse(proxy_url)

                    if parsed.username and parsed.password:
                        proxy_auth = aiohttp.BasicAuth(parsed.username, parsed.password)
                        # 重构不带认证的URL
                        proxy_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"

                connector = aiohttp.TCPConnector(
                    ssl=self.parent.verify,
                    limit=self.parent.max_connections,
                    ttl_dns_cache=300,  # DNS缓存时间
                    keepalive_timeout=self.parent.keepalive_expiry,
                    force_close=False,
                    resolver=resolver,
                )

                # 配置超时
                timeout = aiohttp.ClientTimeout(connect=self.parent.connect_timeout, sock_read=self.parent.read_timeout)

                # 标准库 jar 只在首次创建时导入；运行期由 aiohttp 原生 jar 增量维护。
                if self._native_cookie_jar is None:
                    self._native_cookie_jar = _to_aiohttp_cookie_jar(self.parent.cookie_jar)
                self.session = aiohttp.ClientSession(
                    connector=connector,
                    proxy=proxy_url,  # 不带认证的URL
                    proxy_auth=proxy_auth,  # 单独传入认证
                    timeout=timeout,
                    cookie_jar=self._native_cookie_jar,
                    trust_env=True,
                    read_bufsize=1024 * 1024 * 4,
                )  # type: ignore
            return self.session

    def export_cookie_jar(self, destination: CookieJar) -> None:
        """把 aiohttp 运行态 Cookie 导出到标准库 jar。"""

        if self._native_cookie_jar is not None:
            _export_cookie_jar(self._native_cookie_jar, destination)

    def prepare_request_params(self, **kwargs: Any) -> dict[str, Any]:
        """转换 aiohttp 参数并补充统一 User-Agent。"""

        # 处理超时参数
        timeout = kwargs.pop("timeout", None)
        if timeout is not None:
            if isinstance(timeout, (int, float)):
                from aiohttp import ClientTimeout

                timeout = ClientTimeout(total=timeout)
            kwargs["timeout"] = timeout
        # 添加用户代理
        headers = dict(kwargs.get("headers", {}))
        if not any(name.lower() == "user-agent" for name in headers):
            headers["User-Agent"] = self.parent.user_agent
        if not any(name.lower() == "accept-encoding" for name in headers):
            headers["Accept-Encoding"] = "gzip, deflate" if self.parent.content_decoding else "identity"
        kwargs["headers"] = headers
        # 处理重定向
        allow_redirects = kwargs.pop("follow_redirects", True)
        max_redirects = 10 if allow_redirects else 0
        kwargs["allow_redirects"] = allow_redirects  # 是否跟随重定向
        kwargs["max_redirects"] = max_redirects  # 最大重定向次数
        # 统一 Response 必须先保留原始正文，再由公共层按配置解码。
        kwargs["auto_decompress"] = False
        return kwargs

    def _stream_response(self, response: aiohttp.ClientResponse) -> HttpStreamResponse:
        """把 aiohttp 流响应适配为统一流接口。"""

        async def iter_raw():
            """逐块读取 aiohttp 未自动解压的响应内容。"""

            async for chunk in response.content.iter_any():
                yield chunk

        async def close() -> None:
            """同步释放响应并等待底层连接回收到连接池。"""

            response.release()
            await response.wait_for_close()

        return HttpStreamResponse(
            **_response_metadata(response),
            iter_raw=iter_raw,
            close=close,
            decode_content=self.parent.content_decoding,
        )

    async def request(self, method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse:
        """执行aiohttp请求"""
        session = await self.get_client()
        kwargs = self.prepare_request_params(**kwargs)  # 准备请求参数
        assert session is not None
        # 执行请求
        async with session.request(method, url, raise_for_status=False, **kwargs) as response:
            raw_content = await response.read()
            result = HttpResponse(
                **_response_metadata(response),
                raw_content=raw_content,
                decode_content=self.parent.content_decoding,
            )
            return result

    @asynccontextmanager
    async def stream(self, method: HttpMethod, url: str, **kwargs: Any):
        """流式请求上下文管理器"""
        session = await self.get_client()

        kwargs = self.prepare_request_params(**kwargs)  # 准备请求参数

        # 执行流式请求
        response = await session.request(method, url, **kwargs)
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
