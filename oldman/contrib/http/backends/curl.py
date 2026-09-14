"""
@author:alex
@date:2025/8/10
@time:13:50
"""

__author__ = "alex"
import asyncio
import ipaddress
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urljoin, urlsplit

from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession, Cookies, Response
from curl_cffi.requests.exceptions import RequestException

from oldman.contrib.http.base import BaseHttpClient
from oldman.contrib.http.contants import CURL_HEADERS
from oldman.contrib.http.response import (
    HttpHeaders,
    HttpResponse,
    HttpStreamResponse,
    _apply_cookie_headers,
    cookie_jar_from_headers,
    copy_cookie_jar,
)
from oldman.contrib.http.schemas import HttpMethod
from oldman.logging import logger

# 只在类型检查时导入，避免循环导入
if TYPE_CHECKING:
    from oldman.contrib.http.multi_client import MultiHttpClient


def _response_header_blocks(raw_headers: bytes) -> list[tuple[int, HttpHeaders]]:
    """Parse every HTTP response block retained by libcurl redirects."""

    blocks: list[tuple[int, HttpHeaders]] = []
    status_code: int | None = None
    items: list[tuple[str, str]] = []
    for raw_line in raw_headers.splitlines():
        if raw_line.startswith(b"HTTP/"):
            if status_code is not None:
                blocks.append((status_code, HttpHeaders(items)))
            parts = raw_line.decode("latin-1").split(" ", 2)
            try:
                status_code = int(parts[1])
            except (IndexError, ValueError):
                status_code = 0
            items = []
            continue
        if not raw_line.strip() or status_code is None:
            continue
        if raw_line[:1] in {b" ", b"\t"} and items:
            name, value = items[-1]
            items[-1] = (name, f"{value} {raw_line.decode('latin-1').strip()}")
            continue
        name, separator, value = raw_line.partition(b":")
        if separator:
            items.append((name.decode("latin-1"), value.decode("latin-1").strip()))
    if status_code is not None:
        blocks.append((status_code, HttpHeaders(items)))
    return blocks


class _OldmanAsyncSession(AsyncSession):
    """Retain redirect headers so the canonical CookieJar sees every Set-Cookie."""

    def _parse_response(
        self,
        curl: Any,
        buffer: Any,
        header_buffer: Any,
        default_encoding: Any,
        discard_cookies: bool,
    ) -> Response:
        """Attach parsed response blocks without changing curl_cffi transport logic."""

        response = super()._parse_response(
            curl,
            buffer,
            header_buffer,
            default_encoding,
            discard_cookies,
        )
        response._oldman_header_blocks = _response_header_blocks(header_buffer.getvalue())
        return response


def _http_version(response: Response) -> str:
    """把 libcurl 的版本常量转换成常见 HTTP/x 文本。"""

    versions = {
        1: "HTTP/1.0",
        2: "HTTP/1.1",
        3: "HTTP/2",
        4: "HTTP/2",
        5: "HTTP/2",
        30: "HTTP/3",
        31: "HTTP/3",
    }
    return versions.get(int(response.http_version), "")


def _metadata(response: Response) -> dict[str, Any]:
    """构造普通响应和流响应共享的元数据。"""

    headers = HttpHeaders(response.headers.multi_items())
    url = str(response.url)
    return {
        "status_code": response.status_code,
        "url": url,
        "headers": headers,
        "cookies": cookie_jar_from_headers(headers, url),
        "encoding": response.encoding,
        "reason": response.reason,
        "http_version": _http_version(response),
        "native_response": response,
    }


def _request_hostname(url: str) -> tuple[str | None, bool]:
    """返回请求 hostname，并标记它是否为无点、非 IP 的单标签主机。"""

    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return None, False
    if hostname is None:
        return None, False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname, "." not in hostname
    return hostname, False


def _bind_request_cookie_domains(cookies: CookieJar, url: str) -> None:
    """在 request-only jar 中绑定 domainless 和单标签 host-only Cookie。"""

    hostname, single_label = _request_hostname(url)
    if hostname is None:
        return

    local_hostname = f"{hostname}.local".lower()
    for cookie in cookies:
        if not cookie.domain:
            # curl_cffi 对 domainless Cookie 也会做同样绑定；这里显式绑定，
            # 使合并了临时 Cookie 的 request-only jar 语义清楚且可测试。
            cookie.domain = hostname
        elif single_label and not cookie.domain_specified and cookie.domain.lower() == local_hostname:
            cookie.domain = hostname


def _adapt_request_cookie_jar(cookies: CookieJar, url: str) -> CookieJar:
    """复制 canonical jar，并只在副本中完成请求 hostname 适配。"""

    request_jar = copy_cookie_jar(cookies)
    _bind_request_cookie_domains(request_jar, url)
    return request_jar


async def _ensure_stream_response_started(response: Response) -> None:
    """Surface a pending curl stream error before adapting an invalid response."""

    if response.status_code > 0 and response.url:
        return
    # curl_cffi 极短失败存在 header 事件和错误队列之间的竞态。消费这个
    # 仅错误路径的 iterator 会抛出原始 RequestException。
    try:
        async for _chunk in response.aiter_content():
            pass
    except asyncio.CancelledError as exc:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
        # curl_cffi 0.15.0 复用发生过快速传输失败的 session 时，内部下载
        # task 可能只留下 STREAM_END 后进入 cancelled 状态。它不是调用方
        # 取消，仍应作为“尚未取得 HTTP 响应”的传输错误对外暴露。
        response.astream_task = None
        raise RequestException("curl_cffi 流请求在响应头前终止", response=response) from exc
    raise RuntimeError("curl_cffi 流响应缺少有效状态或 URL")


class CurlCffiClient(BaseHttpClient):
    """curl_cffi实现的HTTP客户端"""

    def __init__(self, parent: "MultiHttpClient"):
        """
        初始化curl_cffi客户端

        Args:
            parent: 父MultiHttpClient实例，包含配置信息
        """
        self.parent = parent
        self.client: AsyncSession | None = None
        self.cookie_jar = parent.cookie_jar if parent.cookie_jar is not None else CookieJar()
        self.curl_options = {
            CurlOpt.TCP_NODELAY: 1,  # 禁用Nagle算法
            CurlOpt.BUFFERSIZE: 4 * 1024 * 1024,  # 增加接收缓冲区(256KB)
            # CurlOpt.HTTP_VERSION: CurlHttpVersion.V2TLS,  # 使用HTTP/2
            CurlOpt.MAXCONNECTS: 100,  # 连接池大小
            CurlOpt.FORBID_REUSE: 0,  # 允许连接重用
            CurlOpt.FRESH_CONNECT: 0,  # 不强制新连接
            CurlOpt.TCP_KEEPALIVE: 1,  # 启用TCP保活
            CurlOpt.TCP_KEEPIDLE: 120,  # 保活闲置时间
            # 公共 Response 必须先取得原始正文，再按统一配置执行内容解码。
            CurlOpt.HTTP_CONTENT_DECODING: 0,
            # CurlOpt.HTTP_TRANSFER_DECODING: 0,  # 禁用传输解码
            # # 内存管理
            # CurlOpt.ACCEPT_ENCODING: "",  # 禁用压缩(对流媒体)
            # 多路复用管理
            # CurlMOpt.PIPELINING: 1,  # 启用管道
        }
        if self.parent.nameservers:
            self.curl_options[CurlOpt.DNS_SERVERS] = ",".join(self.parent.nameservers)  # type: ignore

    async def init_client(self) -> None:
        """初始化curl_cffi客户端"""
        logger.info(f"初始化curl_cffi客户端, 最大连接数: {self.parent.max_connections}")

    async def reset_client(self) -> bool:
        """重置curl_cffi客户端"""
        if self.client:
            await self.client.close()
            self.client = None
        logger.info("curl_cffi客户端已重置")
        return True

    async def close_client(self) -> None:
        """关闭curl_cffi客户端"""
        if self.client:
            try:
                await self.client.close()
                self.client = None
            except Exception as e:
                logger.error(f"关闭curl_cffi客户端时出错: {type(e).__name__}")
        logger.info("curl_cffi资源清理完成")

    async def get_client(self) -> AsyncSession:
        """获取或创建curl_cffi客户端"""

        async with self.parent.lock:
            if self.client is None:
                # 创建curl_cffi会话
                self.client = _OldmanAsyncSession(
                    timeout=(self.parent.connect_timeout, self.parent.read_timeout),
                    proxy=self.parent.proxy_url,
                    verify=self.parent.verify,
                    impersonate=None,
                    max_clients=self.parent.max_connections,
                    curl_options=self.curl_options,
                )  # type: ignore
            return self.client

    def update_impersonate(self, **kwargs: Any) -> dict[str, Any]:
        """解析 curl impersonate User-Agent，并保留普通 User-Agent。"""

        # 添加用户代理
        headers = dict(kwargs.get("headers", {}))
        impersonate = None
        user_agent_key = next((name for name in headers if name.lower() == "user-agent"), None)
        if user_agent_key is None:
            headers["User-Agent"] = self.parent.user_agent
        else:
            user_agent = headers[user_agent_key]
            for prefix in CURL_HEADERS:
                if user_agent.startswith(prefix):
                    impersonate = headers.pop(user_agent_key)
                    if impersonate == "curl":
                        impersonate = None
                        headers["User-Agent"] = self.parent.user_agent
                    break
        kwargs["headers"] = headers
        kwargs["impersonate"] = impersonate
        return kwargs

    def prepare_request_params(self, **kwargs: Any) -> dict[str, Any]:
        """转换 curl_cffi 请求参数。"""

        # 处理超时参数
        timeout = kwargs.pop("timeout", None)
        if timeout is not None:
            kwargs["timeout"] = timeout

        # 处理重定向
        allow_redirects = kwargs.pop("follow_redirects", True)
        kwargs["allow_redirects"] = allow_redirects
        kwargs = self.update_impersonate(**kwargs)
        headers = dict(kwargs.get("headers", {}))
        if not any(name.lower() == "accept-encoding" for name in headers):
            headers["Accept-Encoding"] = "gzip, deflate" if self.parent.content_decoding else "identity"
        kwargs["headers"] = headers
        # curl_cffi 只合并 cookie store，无法同步删除，还会持久化单次请求 cookies。
        # 禁用其回写后，公共层只按服务端实际 Set-Cookie 更新 session jar。
        kwargs["discard_cookies"] = True
        return kwargs

    def _prepare_request_cookies(self, kwargs: dict[str, Any], url: str) -> None:
        """Adapt cookies without persisting one request's explicit values."""

        headers = kwargs.get("headers", {})
        if any(name.lower() == "cookie" for name in headers):
            # A manually supplied Cookie header is owned by the caller. Supplying a
            # libcurl cookie store as well would silently replace that header.
            kwargs.pop("cookies", None)
            return

        explicit_cookies = kwargs.pop("cookies", None)
        if explicit_cookies is None:
            _, single_label = _request_hostname(url)
            # 普通域名和 IP 直接复用 canonical jar；只有单标签主机需要隔离副本。
            kwargs["cookies"] = (
                _adapt_request_cookie_jar(self.cookie_jar, url) if single_label else self.cookie_jar
            )
            return

        try:
            explicit_store = Cookies(explicit_cookies)
        except (TypeError, ValueError):
            # Preserve curl_cffi-specific cookie inputs that its public request
            # method may understand better than the common adapter.
            kwargs["cookies"] = explicit_cookies
            return

        request_store = Cookies(copy_cookie_jar(self.cookie_jar))
        for cookie in copy_cookie_jar(explicit_store.jar):
            request_store.jar.set_cookie(cookie)
        _bind_request_cookie_domains(request_store.jar, url)
        kwargs["cookies"] = request_store

    def _apply_session_cookies(self, response: Response, request_url: str) -> None:
        """Apply Set-Cookie from every redirect hop to the curl session jar."""

        current_url = request_url
        blocks = getattr(response, "_oldman_header_blocks", ())
        if not blocks:
            response_url = str(response.url) or request_url
            _apply_cookie_headers(self.cookie_jar, HttpHeaders(response.headers.multi_items()), response_url)
            return

        for status_code, headers in blocks:
            _apply_cookie_headers(self.cookie_jar, headers, current_url)
            location = headers.get("location")
            if status_code in {301, 302, 303, 307, 308} and location:
                current_url = urljoin(current_url, location)

    def _stream_response(self, response: Response) -> HttpStreamResponse:
        """把 curl_cffi 流响应适配为统一流接口。"""

        async def iter_raw():
            """逐块读取 libcurl 提供的响应内容。"""

            async for chunk in response.aiter_content():
                yield chunk
                # 保留来源实现对高吞吐 curl 流的协作式调度。
                await asyncio.sleep(0)

        async def close() -> None:
            """立即终止 curl_cffi 尚未读完的后台下载任务。"""

            task = response.astream_task
            if task is None or getattr(task, "done", lambda: False)():
                await response.aclose()
                return

            quit_now = response.quit_now
            if quit_now is not None:
                quit_now.set()

            cancel = getattr(task, "cancel", None)
            if cancel is None:
                await response.aclose()
                return
            cancel()
            # gather 把内部任务的 CancelledError 作为结果收回，但不会吞掉调用方自身的取消。
            await asyncio.gather(task, return_exceptions=True)
            # curl_cffi 的 stream context 会再次调用 aclose；清空已回收任务使其幂等。
            response.astream_task = None

        return HttpStreamResponse(
            **_metadata(response),
            iter_raw=iter_raw,
            close=close,
            decode_content=self.parent.content_decoding,
        )

    async def request(self, method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse:
        """执行curl_cffi请求"""
        client = await self.get_client()
        kwargs = self.prepare_request_params(**kwargs)  # 准备请求参数
        self._prepare_request_cookies(kwargs, url)
        # 执行请求
        assert client is not None
        try:
            response = await client.request(method, url, **kwargs)  # type: ignore
        except Exception as exc:
            error_response = getattr(exc, "response", None)
            if isinstance(error_response, Response):
                self._apply_session_cookies(error_response, url)
            raise
        self._apply_session_cookies(response, url)
        return HttpResponse(
            **_metadata(response),
            raw_content=response.content,
            decode_content=self.parent.content_decoding,
        )

    @asynccontextmanager
    async def stream(self, method: HttpMethod, url: str, **kwargs: Any):
        """流式请求上下文管理器"""
        client = await self.get_client()

        kwargs = self.prepare_request_params(**kwargs)  # 准备请求参数
        self._prepare_request_cookies(kwargs, url)
        # 执行流式请求
        assert client is not None
        response_seen = False
        try:
            async with client.stream(cast(Any, method), url, **kwargs) as response:
                await _ensure_stream_response_started(response)
                response_seen = True
                self._apply_session_cookies(response, url)
                stream_response = self._stream_response(response)
                try:
                    yield stream_response
                finally:
                    await stream_response.aclose()
        except Exception as exc:
            if not response_seen:
                error_response = getattr(exc, "response", None)
                if isinstance(error_response, Response):
                    self._apply_session_cookies(error_response, url)
            raise

    @asynccontextmanager
    async def reconnect_stream(
        self,
        method: HttpMethod,
        url: str,
        live_stream: bool = False,
        **kwargs: Any,
    ):
        """
        应该与stream方法一致，只是为了兼容接口
        :param method:
        :param url:
        :param kwargs:
        :return:
        """
        del live_stream
        async with self.stream(method, url, **kwargs) as response:
            yield response
