"""
多后端HTTP客户端工厂
@author:alex
@date:2025/8/10
@time:13:48
"""

__author__ = "alex"

import asyncio
import gc
import time
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, MozillaCookieJar
from typing import TYPE_CHECKING, Any, ClassVar

from oldman.conf.schemas import HttpClientConfig
from oldman.contrib.http.response import HttpResponse, HttpStreamResponse
from oldman.contrib.http.schemas import ClientType, HttpMethod
from oldman.logging import logger

from ._logging import redact_proxy, redact_url
from .base import BaseHttpClient
from .exceptions import RequestFailedError
from .reconnect_stream import ReconnectStreamResponse

# 使用 TYPE_CHECKING 避免运行时循环导入
if TYPE_CHECKING:
    from .backends import AioHttpClient, CurlCffiClient, HttpxClient


def _configured_http_client() -> HttpClientConfig:
    """读取已配置 Settings，未配置时返回 schema 的安全默认值。"""

    try:
        from oldman.conf import settings
    except (AttributeError, ImportError, RuntimeError):
        return HttpClientConfig()
    return settings.http_client


def _is_cookie_header_name(name: object) -> bool:
    """大小写不敏感地识别 str/bytes Cookie header 名，不转换 header 内容。"""

    if isinstance(name, bytes):
        return name.lower() == b"cookie"
    return str(name).lower() == "cookie"


def _validate_request_cookie_inputs(kwargs: dict[str, Any]) -> None:
    """Reject ambiguous or stateful per-request cookie inputs."""

    cookies = kwargs.get("cookies")
    if cookies is None:
        return
    if isinstance(cookies, CookieJar):
        raise TypeError("单次请求 cookies 不支持 CookieJar；请通过 MultiHttpClient(cookie_jar=...) 配置")

    headers = dict(kwargs.get("headers") or {})
    if any(_is_cookie_header_name(name) for name in headers):
        raise ValueError("Cookie header 与 cookies 参数不能同时使用")


def _validate_request_tls_inputs(kwargs: dict[str, Any]) -> None:
    """拒绝无法由三个 backend 一致兑现的单次请求 TLS 配置。"""

    if "verify" in kwargs:
        raise TypeError("verify 只能在构造 MultiHttpClient 时设置")


class MultiHttpClient(BaseHttpClient):
    """支持多种后端的统一HTTP客户端工厂"""

    # 类级别的全局清理器，避免每个实例都有后台任务
    _instances: ClassVar["weakref.WeakSet[MultiHttpClient]"] = weakref.WeakSet()
    _cleanup_registered = False

    def __init__(
        self,
        client_type: ClientType = ClientType.HTTPX,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        proxy_url: str | None = None,
        retry_count: int = 3,
        retry_backoff_factor: float = 0.5,
        no_retry_statuses: list[int] | None = None,
        keepalive_expiry: int = 300,
        max_connections: int = 0,
        user_agent: str | None = None,
        content_decoding: bool = False,
        nameservers: list[str] | None = None,
        cookie_jar: CookieJar | None = None,
        verify: bool = True,
    ):
        """
        初始化多后端HTTP客户端

        Args:
            client_type: HTTP客户端类型，支持 'httpx', 'aiohttp', 'curl_cffi'
            max_connections: 最大连接数
            connect_timeout: 连接超时时间（秒）
            read_timeout: 读取超时时间（秒）
            proxy_url: 代理URL
            retry_count: 请求失败时的重试次数
            retry_backoff_factor: 重试延迟的增长因子
            no_retry_statuses: 不需要重试的HTTP状态码列表
            keepalive_expiry: 连接保持活跃的过期时间（秒）
            user_agent: 默认 User-Agent；未指定时读取 Settings 或 schema 默认值
            cookie_jar: 客户端级标准库 CookieJar；aiohttp 首次导入并在显式导出、保存或关闭时写回。
                可变 jar 的共享和并发写回由调用方协调，框架不检测它是否被其他客户端共同使用
            verify: 是否验证 HTTPS 服务端证书；仅支持构造级布尔配置
        """
        if not isinstance(verify, bool):
            raise TypeError("verify 必须是 bool")
        self.cookie_jar = cookie_jar
        self.client_type = client_type
        # 连接池和超时配置
        configured = _configured_http_client()
        self.max_connections = configured.max_connections if max_connections == 0 else max_connections
        if self.max_connections <= 0:
            raise ValueError("max_connections 必须为正整数")
        self.user_agent = configured.user_agent if user_agent is None else user_agent
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.proxy_url = proxy_url
        self.keepalive_expiry = keepalive_expiry
        self.content_decoding = content_decoding
        self.verify = verify
        # 重试配置
        self.retry_count = retry_count
        self.retry_backoff_factor = retry_backoff_factor
        self.no_retry_statuses = no_retry_statuses or [404]

        # 统一资源管理
        self.lock = asyncio.Lock()
        self.client_semaphore = asyncio.Semaphore(self.max_connections)
        self.last_client_reset = time.time()
        self.timeout_count = 0
        self.max_timeout_count = 100
        self.nameservers = nameservers

        # 具体实现客户端
        # 具体实现客户端
        self._impl: HttpxClient | AioHttpClient | CurlCffiClient | None = None

        # 重置时间配置
        self.soft_reset_interval = 3600  # 1小时后可以重置
        self.hard_reset_interval = 86400  # 24小时强制重置
        self.active_requests = 0

        # 定期强制垃圾回收，防止内存泄漏
        self.gc_lock = asyncio.Lock()
        self.last_gc_time = time.time()
        self.gc_interval = 3600  # 每小时进行一次垃圾回收

        self._no_active_requests = asyncio.Event()
        self._no_active_requests.set()  # 初始状态为无活跃请求

        MultiHttpClient._instances.add(self)
        self._register_global_cleanup()

    @classmethod
    def _register_global_cleanup(cls):
        """注册全局清理函数"""
        if not cls._cleanup_registered:
            import atexit

            atexit.register(cls._cleanup_all_instances)
            cls._cleanup_registered = True

    @classmethod
    def _cleanup_all_instances(cls):
        """清理所有实例"""
        instances = list(cls._instances)
        if instances:
            logger.info(f"程序退出时清理 {len(instances)} 个HTTP客户端实例")

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def cleanup_all():
                    """并发关闭仍持有 backend 资源的客户端实例。"""

                    tasks = []
                    for instance in instances:
                        if instance._impl is not None:
                            tasks.append(instance.close_client())
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)

                loop.run_until_complete(cleanup_all())
                loop.close()
            except Exception as e:
                logger.warning(f"批量清理HTTP客户端失败: {type(e).__name__}")

    @property
    def client(self):
        """获取当前实现的客户端实例"""
        if self._impl is None:
            raise RuntimeError("HTTP客户端尚未初始化，请先调用 init_client()")
        return self._impl

    def is_initialized(self) -> bool:
        """检查客户端是否已初始化"""
        return self._impl is not None

    async def init_client(self) -> None:
        """初始化HTTP客户端；已初始化时保持现有 backend 不变。"""

        if self._impl is not None:
            return

        from .backends import AioHttpClient, CurlCffiClient, HttpxClient

        self.client_semaphore = asyncio.Semaphore(self.max_connections)
        logger.info(f"初始化 {self.client_type} 客户端, 最大连接数: {self.max_connections}")
        # 根据类型创建具体的客户端实现
        if self.client_type == ClientType.HTTPX:
            self._impl = HttpxClient(self)  # type: ignore
        elif self.client_type == ClientType.AIOHTTP:
            self._impl = AioHttpClient(self)  # type: ignore
        elif self.client_type == ClientType.CURL_CFFI:
            self._impl = CurlCffiClient(self)  # type: ignore
        else:
            raise ValueError(f"不支持的客户端类型: {self.client_type}")

        # 初始化具体实现
        await self._impl.init_client()

    async def check_health(self) -> bool:
        """检查客户端健康状态，根据需要重置"""
        if self.timeout_count > self.max_timeout_count:
            # 如果连续超时次数过多，重置客户端
            logger.error(f"连续超时次数: {self.timeout_count}, 重置HTTP客户端")
            self.timeout_count = 0
            reset_success = await self.reset_client()
        elif time.time() - self.last_client_reset > self.soft_reset_interval:
            # 如果客户端运行时间超过1小时，定期重置以防止内存泄漏
            logger.debug(f"客户端运行时间: {time.time() - self.last_client_reset}秒, 定期重置")
            reset_success = await self.reset_client()
        else:
            reset_success = False
        if time.time() - self.last_gc_time > self.gc_interval:
            async with self.gc_lock:
                if time.time() - self.last_gc_time > self.gc_interval:
                    logger.info("执行垃圾回收以释放内存")
                    try:
                        gc.collect()
                    except Exception as e:
                        logger.error(f"显式垃圾回收失败: {type(e).__name__}")
                    self.last_gc_time = time.time()
        return reset_success

    async def reset_client(self) -> bool:
        """重置HTTP客户端 - 增强调试版本"""
        current_time = time.time()
        # caller_info = f"调用者线程: {asyncio.current_task()}"
        #
        # logger.info(f"reset_client 被调用 - {caller_info}")

        # 粗略检查是否可能需要重置（避免不必要的锁竞争）
        rough_check_force_reset = current_time - self.last_client_reset > self.hard_reset_interval

        # 正常情况下，如果有活跃请求且不是强制重置就跳过
        if not rough_check_force_reset and self.active_requests > 0:
            logger.debug(f"有 {self.active_requests} 个请求正在进行，跳过客户端重置")
            return False

        # 尝试获取锁
        # logger.info(f"尝试获取重置锁 - {caller_info}")
        try:
            async with self.lock:
                # logger.info(f"成功获取重置锁 - {caller_info}")
                # 重新检查状态
                current_time = time.time()
                force_reset = current_time - self.last_client_reset > self.hard_reset_interval
                # logger.info(f"锁内重新检查: force_reset={force_reset}, active_requests={self.active_requests}")
                if not force_reset and self.active_requests > 0:
                    logger.debug("在获取重置锁后发现有新请求，跳过重置")
                    return False
                if not force_reset and current_time - self.last_client_reset < self.soft_reset_interval:
                    logger.debug("在获取重置锁后发现不需要重置，跳过重置")
                    return False
                # 强制重置模式：等待活跃请求完成
                if force_reset and self.active_requests > 0:
                    logger.warning(f"客户端运行时间过长，强制重置模式：等待 {self.active_requests} 个请求完成...")
                    try:
                        await asyncio.wait_for(self._no_active_requests.wait(), timeout=5.0)
                    except TimeoutError:
                        pass
                    if self.active_requests > 0:
                        logger.error(f"强制重置超时，仍有 {self.active_requests} 个活跃请求，继续执行重置")
                if self._impl:
                    try:
                        reset_start = time.time()
                        reset_succeeded = await self._impl.reset_client()
                        if not reset_succeeded:
                            # backend 用 False 明确报告未完成时，与抛出普通异常采用相同
                            # 冷却语义，避免后续每个请求立即重复 reset。
                            self.last_client_reset = time.time()
                            logger.error("底层重置未成功")
                            return False
                        reset_duration = time.time() - reset_start
                        logger.info(f"底层重置完成，耗时: {reset_duration:.2f}秒")
                    except Exception as e:
                        # 记录本次失败尝试，避免每个后续请求立即重复 reset。
                        self.last_client_reset = time.time()
                        logger.error(f"底层重置失败: {type(e).__name__}")
                        return False
                self.last_client_reset = time.time()
                logger.info(f"{self.client_type} 客户端已{'强制' if force_reset else ''}重置")
                return True
        except asyncio.CancelledError:
            logger.warning("重置客户端任务被取消")
            raise
        except Exception as e:
            logger.error(f"重置客户端过程中发生异常: {type(e).__name__}")
            return False
        finally:
            logger.info("reset_client 执行完成")
        return False

    async def close_client(self) -> bool:
        """关闭HTTP客户端并清理资源。

        永不抛普通异常：调用方多半是业务的收尾路径，不应该被迫 catch。失败只记日志并
        返回 False，同时保留 backend 引用——backend 那边也保留了会话，退出清理或下一次
        关闭还能再试。取消仍然向上传递。
        """
        logger.info(f"正在关闭 {self.client_type} 客户端...")
        if self._impl is None:
            return True
        impl = self._impl
        try:
            # aiohttp 在运行期持有原生 jar；其他 backend 的导出 hook 保持无操作。
            if self.cookie_jar is not None:
                impl.export_cookie_jar(self.cookie_jar)
        except Exception as exc:
            # 导出失败也不能跳过网络资源清理，更不该把异常丢给调用方。
            logger.error(f"导出 {self.client_type} Cookie 失败: {type(exc).__name__}")
        released = await impl.close_client()
        # backend 用 False 明确报告"会话还在"，这时丢掉引用就再也没人能关掉它。
        if released is False:
            logger.error(f"{self.client_type} 客户端未能释放，保留引用以便重试")
            return False
        self._impl = None
        logger.info("资源清理完成")
        return True

    async def request(self, method: HttpMethod, url: str, **kwargs: Any) -> HttpResponse:
        """
        发送HTTP请求，支持自动重试和错误处理

        Args:
            method: HTTP方法 ('GET', 'POST', 等)
            url: 请求URL
            **kwargs: 传递给底层客户端的额外参数
                - headers: 请求头字典
                - params: URL查询参数
                - data: 请求体数据
                - json: JSON请求体
                - timeout: 自定义超时（覆盖默认值）
                - follow_redirects: 是否跟随重定向

        Returns:
            与 backend 无关的统一缓冲响应
        """
        _validate_request_cookie_inputs(kwargs)
        _validate_request_tls_inputs(kwargs)
        await self.check_health()
        log_url = redact_url(url)
        log_proxy = redact_proxy(self.proxy_url)

        # 增加活跃请求计数
        self.active_requests += 1
        self._no_active_requests.clear()
        try:
            retries_left = kwargs.pop("retries", self.retry_count)
            no_retry_statuses = kwargs.pop("no_retry_statuses", self.no_retry_statuses)
            retry_backoff = kwargs.pop("retry_backoff", self.retry_backoff_factor)

            # 使用信号量限制并发连接数
            # async with self.client_semaphore:
            last_exception: BaseException | None = None
            response_text: str = ""
            response_status_code: int = 0
            for attempt in range(retries_left + 1):
                try:
                    if attempt > 0:
                        # 计算退避时间: {backoff} * (2 ^ {attempt - 1})
                        wait_time = retry_backoff * (2 ** (attempt - 1))
                        logger.info(f"重试请求 {attempt}/{retries_left}, 等待 {wait_time:.2f}秒: {log_url}")
                        await asyncio.sleep(wait_time)

                    response = await self.client.request(method, url, **kwargs)

                    if response.is_success:
                        # 所有合法 2xx 状态都属于成功响应。
                        # 请求成功，重置超时计数
                        self.timeout_count = 0
                        return response
                    # 检查是否需要根据状态码重试
                    if response.status_code not in no_retry_statuses and attempt < retries_left:
                        logger.warning(
                            f"收到状态码 {response.status_code}，将重试请求: {log_url}, "
                            f"代理: {log_proxy}, 尝试: {attempt + 1}/{retries_left + 1}"
                        )
                        response_text = response.text
                        response_status_code = response.status_code
                        continue
                    else:
                        # 如果状态码不需要重试, 比如404，直接返回响应
                        self.timeout_count = 0
                        logger.warning(
                            f"请求未成功, 状态码: {response.status_code}, 不需要重试: {log_url}, "
                            f"代理: {log_proxy}"
                        )
                        return response
                except TimeoutError as e:
                    self.timeout_count += 1
                    last_exception = e
                    logger.warning(
                        f"请求超时 ({attempt + 1}/{retries_left + 1}): {log_url}, "
                        f"代理: {log_proxy}, 累计超时次数: {self.timeout_count}"
                    )
                    # 继续重试循环
                except Exception as e:
                    request_info = getattr(e, "request_info", None)
                    real_url = getattr(request_info, "real_url", None)
                    if real_url is not None and str(real_url) != url:
                        url = str(real_url)
                        log_url = redact_url(url)
                    logger.error(
                        f"请求错误 ({attempt + 1}/{retries_left + 1}): {type(e).__name__}, url: {log_url}"
                    )
                    last_exception = e
                    # 继续重试循环

            # 所有重试都失败
            if last_exception:
                raise last_exception
            raise RequestFailedError(f"请求失败，已重试 {retries_left} 次: {url}", response_status_code, response_text)
        finally:
            self.active_requests = max(0, self.active_requests - 1)
            if self.active_requests == 0:
                self._no_active_requests.set()

    @asynccontextmanager
    async def stream(
        self,
        method: HttpMethod,
        url: str,
        **kwargs: Any,
    ) -> AsyncIterator[HttpStreamResponse]:
        """改进的流式请求上下文管理器，支持重试和续传"""
        _validate_request_cookie_inputs(kwargs)
        _validate_request_tls_inputs(kwargs)
        await self.check_health()
        log_url = redact_url(url)
        log_proxy = redact_proxy(self.proxy_url)
        self.active_requests += 1
        self._no_active_requests.clear()
        try:
            retries_left = kwargs.pop("retries", self.retry_count)
            no_retry_statuses = kwargs.pop("no_retry_statuses", self.no_retry_statuses)
            retry_backoff = kwargs.pop("retry_backoff", self.retry_backoff_factor)
            # async with self.client_semaphore:
            last_exception: BaseException | None = None
            for attempt in range(retries_left + 1):
                connected = False
                try:
                    if attempt > 0:
                        wait_time = retry_backoff * (2 ** (attempt - 1))
                        await asyncio.sleep(wait_time)

                    async with self.client.stream(method, url, **kwargs) as stream:
                        # 检查状态码是否需要重试
                        if not stream.is_success and stream.status_code not in no_retry_statuses:
                            if attempt < retries_left:
                                logger.warning(f"流式请求收到状态码 {stream.status_code}，将重试, [{log_url}]")
                                continue
                        connected = True

                        yield stream

                        self.timeout_count = 0
                        return  # 成功完成

                except TimeoutError as e:
                    self.timeout_count += 1
                    last_exception = e
                    logger.warning(
                        f"流式请求超时 ({attempt + 1}/{retries_left + 1}), [{log_url}], 代理: {log_proxy}"
                    )
                    # 继续重试

                except Exception as e:
                    logger.error(
                        f"流式请求错误 ({attempt + 1}/{retries_left + 1}): "
                        f"{type(e).__name__}, url is {log_url}"
                    )
                    last_exception = e
                    # 继续重试
                    if connected:
                        # 如果连接上, 读取报错, 那么没必要重试了, 因为stream对象已经传递上层了
                        break

            # 所有重试都失败
            if last_exception:
                raise last_exception
            raise Exception(f"流式请求失败，已重试 {retries_left} 次, [{url}]")
        finally:
            self.active_requests = max(0, self.active_requests - 1)
            if self.active_requests == 0:
                self._no_active_requests.set()

    @asynccontextmanager
    async def reconnect_stream(self, method: HttpMethod, url: str, live_stream: bool = False, **kwargs) -> AsyncIterator["ReconnectStreamResponse"]:
        """建立支持读取中断后按 Range 续传的统一流响应。"""

        _validate_request_cookie_inputs(kwargs)
        _validate_request_tls_inputs(kwargs)
        await self.check_health()
        log_url = redact_url(url)
        self.active_requests += 1
        self._no_active_requests.clear()
        stream_response = None
        try:
            stream_response = ReconnectStreamResponse(self.client, method, url, live_stream, **kwargs)
            await stream_response.connect()
            yield stream_response
        except Exception as e:
            logger.error(f"流式请求失败: {type(e).__name__}, [{log_url}]")
            raise
        finally:
            # 确保资源被清理
            if stream_response:
                await stream_response.release()
            self.active_requests = max(0, self.active_requests - 1)
            if self.active_requests == 0:
                self._no_active_requests.set()

    def export_cookies(self) -> CookieJar | None:
        """显式导出 backend 运行态 Cookie 到构造时传入的标准库 jar。"""

        if self.cookie_jar is not None and self._impl is not None:
            self._impl.export_cookie_jar(self.cookie_jar)
        return self.cookie_jar

    def save_cookies(self, filename: str | None = None) -> None:
        """导出并保存 cookies 到文件（仅对 MozillaCookieJar 有效）。"""

        self.export_cookies()
        if isinstance(self.cookie_jar, MozillaCookieJar):
            self.cookie_jar.save(filename, ignore_discard=True, ignore_expires=True)
            logger.info(f"Cookies 已保存到: {filename or self.cookie_jar.filename}")
        else:
            logger.warning("当前 cookie_jar 不支持保存到文件，请使用 MozillaCookieJar")

    def response_has_cookies(self, response: HttpResponse | HttpStreamResponse) -> bool:
        """检查响应是否包含新的 cookies"""
        return bool(response.cookies)
