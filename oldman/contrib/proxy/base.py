import asyncio
import hashlib
import socket
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from urllib import parse
from urllib.parse import urlparse

from redis.exceptions import LockError
from sanic import HTTPResponse, Request, text
from sanic.compat import Header

from oldman.cache import MemoryCache, TwoLevelCache, redis_cache
from oldman.conf.schemas import DefaultSettings
from oldman.contrib.http import HttpHeaders, MultiHttpClient, ReconnectStreamResponse
from oldman.contrib.http.schemas import ClientType, HttpMethod
from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.utils import strings_utils

"""
@author:alex
@date:2025/4/3
@time:03:38
"""

__author__ = "alex"


_HOP_BY_HOP_RESPONSE_HEADERS = (
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
)


def _configured_settings() -> DefaultSettings:
    """Resolve process Settings only when a Proxy instance is constructed."""

    from oldman.conf import settings

    return settings


def _sanic_response_headers(
    headers: HttpHeaders | Mapping[str, str] | None,
    *,
    body_changed: bool = False,
) -> Header:
    """Convert unified headers once while preserving duplicates for Sanic."""

    if isinstance(headers, HttpHeaders):
        response_headers = Header(headers.multi_items())
    else:
        response_headers = Header(headers or {})
    connection_options = {
        option.strip().lower() for value in response_headers.getall("connection", []) for option in value.split(",") if option.strip()
    }
    for name in connection_options:
        response_headers.pop(name, None)
    for name in _HOP_BY_HOP_RESPONSE_HEADERS:
        response_headers.pop(name, None)
    if body_changed:
        response_headers.pop("content-length", None)
    return response_headers


class BaseStreamProxy:
    """流媒体代理基类。

    部署约束：只在内网/localhost 使用，不要绑定到公网 IP。
    ==========================================================================
    这个代理会去取调用方给的任意上游 URL，而它**没有地址级的 SSRF 防护**。
    2026-09-20 的 review 实测确认了两个问题，经评估按"内部使用"接受，不修：

    1. **允许清单可被绕过。** `validate_real_url` 的 `included` 用字符串通配匹配，
       `*` 会匹配 `/`、`#`、`?`。运营方写"只允许 `*.mycdn.com`"，
       一个 `http://attacker.com/#.mycdn.com/` 就能通过校验——而 `#` 之后的片段
       根本不会发给服务器，代理实际连的是 attacker.com。实测：清单只写了 `/safe/`，
       请求真的打到了攻击者端口。

    2. **默认完全不校验。** `included` 和 `blacklisted` 都默认 `None`，
       即默认放行任意地址：`http://127.0.0.1:6379`（Redis）、
       `http://169.254.169.254/`（云厂商凭据接口）都取得到，协议也不限于 http/https。

    因此：**谁能控制传进来的上游 URL，谁就能让这个进程向任意地址发请求。**
    只要代理不暴露在公网、且上游 URL 只来自可信的内部来源，这个风险是被围住的。
    一旦要对公网开放，先补上按 URL 结构（scheme/host/path）匹配的允许清单、
    限定 http/https、并拦截私有与回环地址。
    """

    # 默认头信息
    DEFAULT_HEADERS = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
    }

    # 缓存键前缀
    CACHE_PREFIX = "proxy"

    # 媒体代理需要兼容证书不完整的上游；专用子类仍可显式开启验证。
    VERIFY_TLS = False

    def __init__(self, proxy_name: str = "base"):
        """
        初始化代理
        :param proxy_name: 代理名称，用于区分不同代理的缓存键
        """
        configured = _configured_settings()
        self.proxy_name = proxy_name
        # 缓存键定义
        self.CACHED_URL_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_url:{{channel_id}}"
        self.M3U8_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_m3u8_content:{{channel_id}}"
        self.M3U_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_m3u_cache:{{play_list_key}}"
        self.REAL_URL_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_real_url:{{channel_id}}"
        self.TS_URL_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_ts_url:{{channel_id}}:{{hash_url}}"
        self.SUB_M3U8_URL_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_sub_m3u8_url:{{channel_id}}:{{hash_url}}"
        self.REDIRECT_URL_CACHE_KEY = f"{self.CACHE_PREFIX}_{proxy_name}_cache_redirect_url:{{hash_url}}"
        self.connect_timeout = configured.proxy.connect_timeout  # 连接超时设置
        self.read_timeout = configured.proxy.read_timeout
        self._debug = configured.web.debug
        self._cache = TwoLevelCache(MemoryCache(), redis_cache)
        self._http_clients: dict[str, MultiHttpClient] = {}
        self._client_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _redis_connection(self) -> Any:
        """Return the decoded DEFAULT Redis connection used by source Proxy records."""

        return await redis_client.async_get_conn()

    async def _redis_binary_connection(self) -> Any:
        """Return the binary DEFAULT Redis connection used by MsgPack records."""

        return await redis_client.async_get_bin_conn()

    @classmethod
    @lru_cache(maxsize=100)
    def generate_channel_id(cls, url: str) -> str:
        """生成频道ID (使用LRU缓存减少重复计算)"""
        return hashlib.blake2b(url.encode("utf8"), digest_size=32).hexdigest()

    @classmethod
    def is_use_curl(cls, user_agent: str | None = None) -> bool:
        """判断是否使用curl_cffi, 根据user_agent起始字符串判断"""
        if user_agent:
            # 可配置的浏览器标识列表
            browser_prefixes = ["edge", "chrome", "firefox", "safari", "curl"]
            for prefix in browser_prefixes:
                if user_agent.lower().startswith(prefix):
                    return True
        return False

    def get_client_type(self, user_agent: str | None = None) -> ClientType:
        """
        获取客户端类型
        :param user_agent: 用户代理字符串
        :return: 客户端类型
        """
        if self.is_use_curl(user_agent):
            return ClientType.CURL_CFFI
        else:
            return ClientType.AIOHTTP

    def get_client_key(self, client_type: ClientType, client_remark: str = "", proxy_url: str | None = None, content_decoding: bool = False) -> str:
        if not proxy_url:
            client_key = f"{self.proxy_name}_no_proxy"
        else:
            client_key = f"{self.proxy_name}_{proxy_url}"
        if client_type == ClientType.CURL_CFFI:
            client_key = f"{client_key}_curl"
        if content_decoding:
            client_key = f"{client_key}_decoded"
        if client_remark:
            client_key = f"{client_key}_{client_remark}"
        return client_key

    async def get_client(
        self, user_agent: str | None = None, proxy_url: str | None = None, content_decoding: bool = False, client_remark: str | None = None
    ) -> MultiHttpClient:
        """获取或创建HTTP客户端"""
        if not client_remark:
            client_remark = ""
        client_type = self.get_client_type(user_agent)  # 获取客户端类型
        client_key = self.get_client_key(client_type, client_remark, proxy_url, content_decoding)

        # 快速路径:客户端已存在
        if client_key in self._http_clients:
            return self._http_clients[client_key]
        # 慢速路径:需要创建客户端
        async with self._client_locks[client_key]:  # ✅ defaultdict 保证原子性
            # 使用锁确保同一时间只有一个协程创建客户端
            if client_key not in self._http_clients:
                client = MultiHttpClient(
                    client_type=client_type,
                    connect_timeout=self.connect_timeout,
                    read_timeout=self.read_timeout,
                    proxy_url=proxy_url or None,
                    retry_backoff_factor=0.1,
                    content_decoding=content_decoding,
                    verify=self.VERIFY_TLS,
                )
                await client.init_client()
                self._http_clients[client_key] = client
            return self._http_clients[client_key]

    async def get_request_headers(self, request: Request | None = None, base_headers: dict | None = None) -> dict:
        """获取请求头,合并基础头和客户端重要头信息"""
        headers = base_headers.copy() if base_headers else self.DEFAULT_HEADERS.copy()
        return headers

    async def delete_cached_channel_url(self, channel_id: str):
        """删除缓存的频道URL"""
        conn = await self._redis_connection()
        await conn.delete(self.CACHED_URL_KEY.format(channel_id=channel_id))

    async def save_cached_channel_url(self, channel_id: str, url: str, ttl: int = 60 * 60 * 24 * 7):
        """保存频道URL到缓存"""
        conn = await self._redis_connection()
        await conn.set(
            self.CACHED_URL_KEY.format(channel_id=channel_id),
            url,
            ex=ttl,
        )

    async def get_cached_channel_url(self, channel_id: str) -> str | None:
        """从缓存获取频道URL"""
        conn = await self._redis_connection()
        url: str | None = await conn.get(self.CACHED_URL_KEY.format(channel_id=channel_id))
        return url

    @staticmethod
    def generate_hash_url(current_id: str, ts_url: str) -> str:
        """生成TS URL的哈希值"""
        return hashlib.blake2b(f"{current_id}:{ts_url}".encode(), digest_size=32).hexdigest()

    async def save_sub_url(
        self,
        channel_id: str,
        cached_id: str,
        ts_url: str,
        sub_ttl: int = 60,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        ext_name: str | None = None,
        **extra_context,
    ) -> str:
        """
        保存TS URL到Redis并生成新URL
        :param ext_name: 扩展名
        :param cached_id: 当前m3u8的唯一ID, 用于生成子资源的哈希值
        :param channel_id: 频道ID
        :param ts_url: 原始TS URL
        :param sub_ttl: 子资源缓存时间(秒)
        :param direct: 是否直接请求
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param extra_context: 额外上下文信息，子类可以扩展
        :return: 新的代理URL路径
        """
        hash_url = self.generate_hash_url(cached_id, ts_url)

        if not ext_name:
            # 确定文件扩展名
            ext_name = strings_utils.get_ext_from_filename(ts_url) or ".ts"
            # 如果m3u8中本身不包含子m3u8, 但是ts_url中包含, 则强制使用ts
            if ext_name in [".m3u8", ".php"]:
                ext_name = ".ts"
        # 生成URL路径，格式为 /[代理名称]/[频道ID]/[哈希].[扩展名]
        new_url = f"/{self.proxy_name}/{channel_id}/{hash_url}{ext_name}"
        cache_key = self.TS_URL_CACHE_KEY.format(channel_id=channel_id, hash_url=hash_url)

        # 基础上下文
        context = {
            "ts_url": ts_url,
            "proxy_url": proxy_url or "",
            "user_agent": user_agent or "",
            "channel_id": channel_id,
            "ext_name": ext_name,
            # 保存bool为数字
            "direct": 1 if direct else 0,
            **extra_context,  # 合并额外上下文
        }

        # 使用管道优化Redis操作
        conn = await self._redis_connection()
        pipe = await conn.pipeline()
        pipe.delete(cache_key)
        pipe.hset(cache_key, mapping=context)
        pipe.expire(cache_key, sub_ttl)
        await pipe.execute()

        return new_url

    async def get_sub_url(self, channel_id: str, hash_url: str) -> dict[str, Any] | Any:
        """获取TS URL信息"""
        # 如果包含扩展名, 则去除扩展名
        ext_name = strings_utils.get_ext_from_filename(hash_url)
        if ext_name:
            hash_url = hash_url.replace(ext_name, "")

        cache_key = self.TS_URL_CACHE_KEY.format(channel_id=channel_id, hash_url=hash_url)
        conn = await self._redis_connection()
        result = await conn.hgetall(cache_key)  # type: ignore
        if not result:  # 修复：如果result为空，直接返回None
            return None
        if "direct" in result and result["direct"] == "1":
            result["direct"] = True
        else:
            result["direct"] = False
        return result

    async def proxy_m3u8_ts_path(
        self,
        channel_id: str,
        m3u8_content: str,
        base_url: str,
        cached_id: str = "",
        sub_ttl: tuple[int, int] = (3600, 300),
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径
        :param sub_ttl: 子资源URL缓存时间(秒),格式为(子m3u8, ts)
        :param cached_id: 当前m3u8的唯一ID, 用于生成子资源的哈希值
        :param channel_id: 频道ID
        :param m3u8_content: m3u8内容
        :param base_url: 基础URL
        :param direct: 是否直接请求
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param extra_context: 额外上下文信息，子类可以扩展
        :return: 处理后的m3u8内容
        """
        lines = m3u8_content.splitlines()
        result: list[str] = []

        # 根据m3u8类型设置缓存TTL
        is_master_playlist = "#EXT-X-STREAM-INF" in m3u8_content
        if is_master_playlist:
            sub_url_ext_name = ".m3u8"
            sub_url_ttl = sub_ttl[0] if len(sub_ttl) > 0 else 0
        else:
            sub_url_ext_name = None
            sub_url_ttl = sub_ttl[1] if len(sub_ttl) > 1 else 0

        for line in lines:
            if not line:
                result.append(line)
                continue

            if not line.startswith("#"):
                # 处理TS URL
                if not line.startswith("http"):
                    ts_url = parse.urljoin(base_url, line.strip())
                else:
                    ts_url = line.strip()

                line = await self.save_sub_url(
                    channel_id, cached_id, ts_url, sub_url_ttl, direct, proxy_url, user_agent, sub_url_ext_name, **extra_context
                )
            elif line.startswith("#") and not line.strip().startswith("#EXT"):
                # 跳过非标准的EXT行
                continue
            elif line.startswith("#EXT-X-MEDIA:"):
                # EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio1",NAME="AAA",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="AAA",URI="05.m3u8"
                # 这样的也要替换地址为基于base_url的路径
                parts = line.split(",")
                if len(parts) > 1:
                    # 只处理URI部分
                    for i in range(len(parts)):
                        if parts[i].strip().startswith("URI="):
                            uri_part = parts[i].split("=")
                            if len(uri_part) == 2:
                                ts_path = uri_part[1].strip('"')
                                ts_url = parse.urljoin(base_url, ts_path)
                                ts_url = await self.save_sub_url(
                                    channel_id,
                                    cached_id,
                                    ts_url,
                                    sub_url_ttl,
                                    direct,
                                    proxy_url,
                                    user_agent,
                                    sub_url_ext_name,
                                    **extra_context,
                                )
                                parts[i] = f'URI="{ts_url}"'
                    # 重新组合行
                    line = ",".join(parts)
            result.append(line)

        return "\n".join(result) + "\n"

    def proxy_mpd_path(
        self,
        mpd_content: str,
        play_url: str,
    ) -> str:
        """
        处理mpd内容,替换TS路径为代理路径
        :param mpd_content: mpd内容
        :param play_url: 完整URL
        :return: 处理后的MPD内容
        """
        base_url = play_url[: play_url.rfind("/")]
        mpd_content = mpd_content.replace('"$RepresentationID', f'"{base_url}/$RepresentationID')
        return mpd_content

    async def get_final_m3u8(
        self,
        request: Request,
        m3u8_url: str,
        user_agent: str | None = None,
        proxy_url: str | None = None,
        headers: dict[str, str] | None = None,
        **extra_context,
    ) -> tuple[str | None, str]:
        """
        获取m3u8内容,支持嵌套m3u8处理
        :param request: Sanic请求对象
        :param m3u8_url: m3u8 URL
        :param user_agent: 用户代理
        :param proxy_url: 代理URL
        :param headers: 自定义请求头

        :return: 元组(m3u8内容, 真实URL)
        """
        # 获取请求头信息
        request_headers = await self.get_request_headers(request, headers or self.DEFAULT_HEADERS)
        if user_agent:
            request_headers["User-Agent"] = user_agent

        # 获取或创建HTTP客户端
        client = await self.get_client(user_agent, proxy_url, content_decoding=True)

        try:
            # 直接获取最终m3u8内容
            response = await client.request(HttpMethod.GET, m3u8_url, headers=request_headers, **extra_context)
            content = response.text
            real_url = str(response.url)
            return content, real_url
        except Exception as e:
            if self._debug:
                logger.exception(f"获取m3u8失败: url={m3u8_url}", exc_info=True)
            else:
                logger.error(f"获取m3u8失败: url={m3u8_url}, error={repr(e)}")
            return None, m3u8_url

    def update_ttl_from_content(self, m3u8_content: str, current_ttl: int) -> int:
        """
        从m3u8内容中提取缓存时间并更新TTL
        :param m3u8_content: m3u8内容
        :param current_ttl: 当前TTL
        :return: 更新后的TTL
        """
        return current_ttl

    async def fetch_remote_manifest(
        self,
        request: Request,
        channel_id: str,
        play_url: str,
        ttl: int = 2,
        sub_ttl: tuple[int, int] = (3600, 300),
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        is_sub_manifest: bool = False,
        **extra_context,
    ) -> str | None:
        """
        获取远程m3u8内容,支持缓存
        :param sub_ttl: 子资源缓存时间(秒),格式为(子m3u8, ts)
        :param is_sub_manifest:
        :param channel_id: 频道ID
        :param request: Sanic请求对象
        :param play_url: 播放URL
        :param ttl: 缓存时间(秒)
        :param direct: 是否直接请求
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param extra_context: 额外上下文信息，子类可以扩展
        :return: 处理后的m3u8内容
        """
        # 为当前m3u8生成一个唯一ID，用作子资源的父ID
        if is_sub_manifest:
            cached_id = hashlib.blake2b(f"{channel_id}:{play_url}".encode(), digest_size=8).hexdigest()
        else:
            cached_id = channel_id
        cache_key = self.M3U8_CACHE_KEY.format(channel_id=cached_id)

        # 如果启用缓存，首先尝试从缓存获取
        if ttl > 0:
            m3u8_content: str | None = await self._cache.get(cache_key, ttl=ttl)
            if m3u8_content:
                return m3u8_content

        try:
            conn = await self._redis_connection()
            lock_name = f"redis_m3u8_lock:{self.CACHE_PREFIX}:{self.proxy_name}_{cached_id}"

            # 使用分布式锁防止缓存雪崩
            async with conn.lock(lock_name, timeout=30, blocking_timeout=10):
                # 双重检查(DCLP模式)
                if ttl > 0:
                    m3u8_content = await self._cache.get(cache_key, ttl=ttl)
                    if m3u8_content:
                        return m3u8_content

                logger.debug(f"从远程获取m3u8: url={play_url}")
                # 检查extra_context是否包含headers, 并提取
                if "headers" in extra_context:
                    headers = extra_context.pop("headers")  # type: dict[str, str] | None
                else:
                    headers = None
                m3u8_content, real_url = await self.get_final_m3u8(request, play_url, user_agent, proxy_url, headers)

                if not real_url:
                    real_url = play_url

                ttl = self.update_ttl_from_content(m3u8_content or "", ttl)
                if m3u8_content:
                    if "#EXTM3U" in m3u8_content:
                        # 处理m3u8内容,替换TS路径
                        m3u8_content = await self.proxy_m3u8_ts_path(
                            channel_id,
                            m3u8_content,
                            real_url,
                            cached_id,
                            sub_ttl,
                            direct,
                            proxy_url,
                            user_agent,
                            **extra_context,
                        )

                        # 缓存处理后的内容和URL映射
                        if ttl > 0:
                            await self.save_cached_channel_url(cached_id, play_url, ttl=ttl)
                            await self._cache.set(cache_key, m3u8_content, ttl=ttl)

                        return m3u8_content
                    elif "<MPD" in m3u8_content:
                        # 说明这是dash流的mpd文件
                        mpd_content = self.proxy_mpd_path(m3u8_content, real_url)
                        # 缓存处理后的内容和URL映射
                        if ttl > 0:
                            await self.save_cached_channel_url(cached_id, play_url, ttl=ttl)
                            await self._cache.set(cache_key, mpd_content, ttl=ttl)
                        return mpd_content
                return None

        except LockError as e:
            logger.error(f"Failed to acquire the m3u8 lock: {repr(e)}, url is {play_url}")
            # 如果获取锁失败但有缓存内容，仍然返回缓存内容
            if ttl > 0:
                m3u8_content = await self._cache.get(cache_key)
                if m3u8_content:
                    return m3u8_content
        except Exception as e:
            logger.error(f"获取m3u8失败: {repr(e)}")
            raise e

        return None

    async def stream_response(self, request: Request, response: ReconnectStreamResponse, content_type: str = "video/mp2t") -> None:
        """
        流式返回响应内容
        :param request: Sanic请求对象
        :param response: 代理响应对象
        :param content_type: 内容类型
        """
        # 创建流式响应
        response_headers = _sanic_response_headers(response.response_headers)

        # 处理content-type
        raw_content_type = response_headers.pop("content-type", "").strip()
        if raw_content_type:
            content_type = raw_content_type

        # # 处理内容编码与长度一致性问题
        # has_encoding = "content-encoding" in response_headers
        # has_range = "content-range" in response_headers
        #
        # # 如果同时存在Content-Encoding和Content-Range/Content-Length，需要做特殊处理
        # if has_encoding and (has_range or "content-length" in response_headers):
        #     # 方案1: 移除Content-Encoding，因为我们不处理解压缩
        #     # response_headers.pop("content-encoding", None)
        #
        #     # 方案2: 确保Content-Length和Content-Range一致
        #     if has_range and "content-length" in response_headers:
        #         range_str = response_headers["content-range"]
        #         if range_str.startswith("bytes "):
        #             try:
        #                 # 从Content-Range中提取实际大小
        #                 total_size = int(range_str.split("/")[-1])
        #                 # 更新Content-Length为真实大小
        #                 response_headers["content-length"] = str(total_size)
        #             except (ValueError, IndexError):
        #                 pass

        # 创建响应流
        response_stream = await request.respond(content_type=content_type, headers=response_headers)
        if response_stream is None:
            raise RuntimeError("Sanic did not create a streaming response")

        try:
            # 使用较大的块大小提高性能
            async for chunk in response.aiter_bytes(2 * 1024 * 1024):
                if chunk:
                    await response_stream.send(chunk)
        except asyncio.CancelledError:
            logger.debug("流式响应被取消")
        except Exception as e:
            logger.error(f"流式响应异常: {repr(e)}")
        finally:
            # 确保关闭流
            try:
                await response_stream.eof()  # type: ignore
            except Exception:
                pass

    async def get_ts_stream(
        self,
        request: Request,
        ts_url: str,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        headers: dict[str, str] | None = None,
        live_stream: bool = False,
    ) -> HTTPResponse | None:
        """
        获取TS流内容
        :param live_stream: 是否是直播流
        :param request: Sanic请求对象
        :param ts_url: TS URL
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param headers: 自定义请求头
        :return: HTTP响应或None
        """
        # 获取请求头信息
        request_headers = await self.get_request_headers(request, headers or self.DEFAULT_HEADERS)
        if user_agent:
            request_headers["User-Agent"] = user_agent

        # 获取或创建HTTP客户端
        client = await self.get_client(user_agent, proxy_url)
        last_response = HTTPResponse(status=500, headers={})

        try:
            async with client.reconnect_stream(HttpMethod.GET, ts_url, headers=request_headers, live_stream=live_stream) as stream:
                response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                response_content_type = response_headers.pop("content-type", None)
                last_response = HTTPResponse(
                    status=stream.status_code or 500,
                    headers=response_headers,
                    content_type=response_content_type,
                )
                logger.debug(f"获取TS流成功: ts_url={ts_url}, status={stream.status_code}")
                # 流式返回内容
                await self.stream_response(request, stream)
                return None
        except asyncio.CancelledError:
            logger.warning(f"协程取消: ts_url={ts_url}")
            raise
        except Exception as e:
            logger.error(f"获取TS失败: {repr(e)}")
            return last_response

    async def get_ts_stream_direct(
        self,
        request: Request,
        ts_url: str,
        proxy_url: str | None = None,
        user_agent: str | None = None,
    ) -> HTTPResponse | None:
        """
        使用直接TCP连接获取TS流内容，优化CPU使用率并处理chunked编码
        :param request: Sanic请求对象
        :param ts_url: TS URL
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :return: HTTP响应或None
        """
        # 解析URL
        parsed = urlparse(ts_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_ssl = parsed.scheme == "https"
        exclude_headers = ["host", "connection"]

        # 构建请求路径和请求头
        path = parsed.path
        if parsed.query:
            path += f"?{parsed.query}"

        # 构建HTTP请求头
        request_lines = [f"GET {path} HTTP/1.1", f"Host: {host}"]

        # 添加User-Agent
        if user_agent:
            request_lines.append(f"User-Agent: {user_agent}")
            exclude_headers.append("user-agent")

        # 转发重要请求头
        for header, value in request.headers.items():
            if header.lower() not in exclude_headers:
                request_lines.append(f"{header.title()}: {value}")

        # 添加连接关闭头，避免保持连接导致的问题
        request_lines.append("Connection: close")

        # 添加空行表示头部结束
        request_lines.append("")
        request_lines.append("")
        request_data = "\r\n".join(request_lines).encode()

        reader = None
        writer = None
        response_stream = None

        try:
            # 使用更短的连接超时，提高响应速度
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=use_ssl),
                timeout=5,  # 连接超时5秒
            )

            # 设置TCP_NODELAY以减少延迟
            sock = writer.get_extra_info("socket")
            if sock:
                # print(sock)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)

            # 发送请求
            writer.write(request_data)
            await writer.drain()

            # 读取并解析HTTP响应头
            header_data = b""
            headers_complete = False
            status_code = 200
            headers: dict[str, Any] = {}

            # 使用较短的读取超时，避免在头部处理时卡住
            while not headers_complete:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                if not line or line == b"\r\n":
                    headers_complete = True
                    continue

                header_data += line
                line_text = line.decode("utf-8", "replace").strip()

                if line_text.startswith("HTTP/"):
                    # 解析状态行
                    parts = line_text.split(" ", 2)
                    if len(parts) >= 2:
                        try:
                            status_code = int(parts[1])
                        except ValueError:
                            pass
                elif ":" in line_text:
                    # 解析头部
                    key, value = line_text.split(":", 1)
                    headers[key.lower().strip()] = value.strip()

            # 检查状态码，确保成功响应
            if status_code not in [200, 206]:
                logger.error(f"TS请求返回非成功状态码: {status_code} - {ts_url}")
                return HTTPResponse(f"上游服务器返回错误: {status_code}".encode(), status=status_code)

            # 检查是否为分块传输编码
            is_chunked = headers.get("transfer-encoding", "").lower() == "chunked"
            logger.debug(f"TS流传输编码: {'chunked' if is_chunked else '标准'}")

            # 只有在成功解析头部后，才创建响应流
            response_stream = await request.respond(content_type=headers.get("content-type", ""))
            if response_stream is None:
                raise RuntimeError("Sanic did not create a streaming response")

            # 直连路径已经移除 HTTP chunk frame，不能再向下游传递连接级响应头。
            response_stream.headers = _sanic_response_headers(headers)

            # TS流最佳读取参数
            buffer_size = 1024 * 1024  # 1MB缓冲区
            bytes_received = 0
            content_length = int(headers.get("content-length", 0) or 0)

            # 处理数据流
            if is_chunked:
                # 处理分块传输编码
                while True:
                    # 读取分块大小
                    chunk_size_line = await reader.readline()
                    if not chunk_size_line:
                        break

                    # 解析分块大小
                    try:
                        chunk_size = int(chunk_size_line.strip(), 16)
                    except ValueError:
                        break

                    if chunk_size == 0:
                        # 读取最后的CRLF
                        await asyncio.wait_for(reader.readline(), timeout=5)
                        break

                    # 读取完整数据块
                    chunk_data = b""
                    remaining = chunk_size
                    while remaining > 0:
                        read_size = min(remaining, buffer_size)
                        data = await reader.read(read_size)
                        if not data:
                            break
                        chunk_data += data
                        remaining -= len(data)

                    # 发送实际数据（不含分块头）
                    if chunk_data:
                        await response_stream.send(chunk_data)
                        bytes_received += len(chunk_data)

                    # 读取块结束的CRLF
                    await asyncio.wait_for(reader.readline(), timeout=5)
            else:
                # 标准传输处理
                while True:
                    chunk = await reader.read(buffer_size)
                    if not chunk:
                        break

                    # 发送数据块
                    await response_stream.send(chunk)
                    bytes_received += len(chunk)

                    # 如果已知内容长度，检查是否接收完毕
                    if 0 < content_length <= bytes_received:
                        break

            logger.debug(f"TS流完成: {bytes_received} 字节，来自 {ts_url}")
            return None

        except TimeoutError:
            logger.error(f"连接超时: {host}:{port} - {ts_url}")
            if not response_stream:
                return HTTPResponse("连接上游服务器超时".encode(), status=504)
            return None
        except Exception as e:
            logger.error(f"代理TS流错误: {repr(e)} - {ts_url}")
            if not response_stream:
                return HTTPResponse(f"代理错误: {repr(e)}".encode(), status=502)
            return None
        finally:
            # 关闭连接
            if writer:
                try:
                    writer.close()
                    await asyncio.shield(writer.wait_closed())
                except Exception as e:
                    logger.debug(f"关闭写入器错误: {repr(e)}")

            # 确保响应流正确关闭
            if response_stream:
                try:
                    await response_stream.eof()  # type: ignore
                except Exception as e:
                    logger.debug(f"Error closing response stream: {repr(e)}")

    async def process_sub_manifest(
        self, request: Request, channel_id: str, ts_context: dict[str, Any], ttl: int = 2, sub_ttl: int = 0, **kwargs
    ) -> HTTPResponse | None:
        """
        处理子m3u8的逻辑，子类可重载此方法以实现特定逻辑
        :param request: Sanic请求对象
        :param channel_id: 频道ID
        :param ts_context: TS上下文信息
        :param ttl: 缓存时间(秒)
        :param sub_ttl: 子资源缓存时间(秒)
        :param kwargs: 额外参数
        :return: HTTP响应或None
        """
        m3u8_content = await self.fetch_remote_manifest(
            request,
            channel_id,
            ts_context["ts_url"],
            ttl=ttl,
            sub_ttl=(0, sub_ttl),
            direct=ts_context.get("direct", False),
            proxy_url=ts_context.get("proxy_url"),
            user_agent=ts_context.get("user_agent"),
            is_sub_manifest=True,  # 标记为子m3u8处理
            **kwargs,
        )
        if m3u8_content:
            return text(m3u8_content, content_type="application/vnd.apple.mpegurl")
        else:
            # 清除缓存的频道URL
            await self.delete_cached_channel_url(channel_id)
            parent_cache_key = self.M3U8_CACHE_KEY.format(channel_id=channel_id)
            await self._cache.delete(parent_cache_key)
            return text("Content expired or not available", status=404)

    async def process_sub_stream(self, request: Request, channel_id: str, ts_context: dict[str, Any], **kwargs) -> HTTPResponse | None:
        """
        处理子流的逻辑，子类可重载此方法以实现特定逻辑
        :param request:
        :param channel_id:
        :param ts_context:
        :param kwargs:
        :return:
        """
        # 处理TS文件
        if ts_context.get("direct") == "1" or ts_context.get("direct") is True:
            # 直接获取TS流
            return await self.get_ts_stream_direct(request, ts_context["ts_url"], ts_context["proxy_url"], ts_context["user_agent"])
        else:
            headers = kwargs.get("headers", None)
            return await self.get_ts_stream(request, ts_context["ts_url"], ts_context["proxy_url"], ts_context["user_agent"], headers)

    async def fetch_sub_manifest_or_stream(
        self, request: Request, channel_id: str, hash_url: str, ttl: int = 2, sub_url_ttl: int = 0
    ) -> HTTPResponse | None:
        """
        获取子m3u8或ts文件 中转
        :param ttl: 缓存时间(秒)
        :param sub_url_ttl: 子资源缓存时间(秒)
        :param request: Sanic请求对象
        :param channel_id: 频道ID
        :param hash_url: 哈希URL
        :return: HTTP响应或None
        """
        ts_url = None
        lock_key = None
        try:
            # 获取TS或M3U8信息
            ts_context = await self.get_sub_url(channel_id, hash_url)
            if not ts_context:
                return text("", status=404)

            ts_url = ts_context["ts_url"]
            # 准备自定义参数
            custom_params = {}
            for key, value in ts_context.items():
                if key not in ["ts_url", "proxy_url", "user_agent", "channel_id", "ext_name", "direct"]:
                    custom_params[key] = value

            # 根据文件类型处理不同内容
            if ts_context["ext_name"] == ".m3u8":
                # 处理子M3U8 - 这里需要实现子类特定逻辑
                return await self.process_sub_manifest(request, channel_id, ts_context, ttl, sub_url_ttl, **custom_params)
            else:
                return await self.process_sub_stream(request, channel_id, ts_context, **custom_params)

        except asyncio.CancelledError:
            logger.warning(f"协程取消: url is {ts_url}, lock_key is {lock_key}")
            return None
        except Exception as e:
            logger.error(f"获取内容失败: {repr(e)}")
            return text("获取内容失败", status=500)

    async def proxy_stream(
        self,
        request: Request,
        play_url: str,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> HTTPResponse | None:
        """代理直播流媒体"""
        try:
            # 处理TS文件
            if direct:
                return await self.get_ts_stream_direct(request, play_url, proxy_url, user_agent)
            else:
                return await self.get_ts_stream(request, play_url, proxy_url, user_agent, headers, True)
        except asyncio.CancelledError:
            logger.warning(f"协程取消: play_url={play_url}")
            # 客户端断开时返回None，避免Sanic尝试发送响应
            return None
        except Exception as e:
            logger.error(f"获取流失败: {repr(e)}")
            return text("获取流失败", status=500)

    async def get_real_url(
        self,
        request: Request,
        play_url: str,
        ttl: int,
        included: list[str] | None = None,
        blacklisted: list[str] | None = None,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        headers: dict | None = None,
        http_method: HttpMethod = HttpMethod.GET,
    ) -> tuple[str | None, str | None]:
        """获取真实URL"""
        channel_id = self.generate_channel_id(play_url)
        cache_key = self.REAL_URL_CACHE_KEY.format(channel_id=channel_id)
        try:
            conn = await self._redis_connection()

            # 首次检查缓存
            real_url: str | None = await conn.get(cache_key)
            if real_url:
                return real_url, None

            lock_name = f"redis_redirect_lock:{self.CACHE_PREFIX}:{channel_id}"
            lock_timeout = 15  # 锁持有时间缩短到15秒
            blocking_timeout = 5  # 等待锁时间缩短到5秒
            try:
                # 使用分布式锁防止缓存雪崩
                async with conn.lock(lock_name, timeout=lock_timeout, blocking_timeout=blocking_timeout):
                    # 双重检查(DCLP模式)
                    real_url = await conn.get(cache_key)
                    if real_url:
                        return real_url, None
                    request_headers = await self.get_request_headers(request, headers or self.DEFAULT_HEADERS)
                    if user_agent:
                        request_headers["User-Agent"] = user_agent
                    # 获取或创建HTTP客户端
                    client = await self.get_client(user_agent, proxy_url)
                    real_url = ""
                    status_code = 0
                    if http_method == HttpMethod.HEAD:
                        # 发起HEAD请求获取重定向URL（避免下载body）
                        http_method = HttpMethod.GET
                        try:
                            response = await client.request(
                                HttpMethod.HEAD, play_url, headers=request_headers, follow_redirects=True, no_retry_statuses=[403, 404, 401]
                            )
                            real_url = str(response.url)
                            status_code = response.status_code
                        except Exception as e:
                            logger.warning(f"HEAD请求失败: {repr(e)}, url is {play_url}")
                            # HEAD请求失败时降级为GET请求但立即关闭
                            real_url = ""
                    if not real_url or real_url == play_url:
                        # 如果HEAD请求没有得到重定向，或者HEAD请求失败，则使用GET请求
                        # 只进入stream获取响应头，退出上下文时立即终止直播正文及代理上游请求。
                        async with client.stream(http_method, play_url, headers=request_headers, no_retry_statuses=[403, 404, 401]) as stream:
                            real_url = str(stream.url)
                            status_code = stream.status_code
                    if status_code not in (200, 206, 301, 302, 303, 307, 308):
                        logger.error(f"获取真实URL时上游返回错误状态码: {status_code}, url is {play_url}")
                        return None, f"Upstream returned error status code: {status_code}"
                    check_result, error_msg = self.validate_real_url(real_url, included, blacklisted)
                    if not check_result:
                        return None, error_msg
                    # 缓存真实URL
                    await conn.set(cache_key, real_url, ex=ttl)
                    return real_url, None
            except LockError as e:
                logger.error(f"Failed to acquire the get_real_url lock: {repr(e)}, url is {play_url}")
                # 如果获取锁失败但有缓存内容，仍然返回缓存内容
                cached_url = await conn.get(cache_key)
                if cached_url:
                    logger.debug(f"使用缓存的URL（可能过期）: {cached_url}")
                    return cached_url, None
                return None, "Failed to acquire the lock"
        except asyncio.CancelledError:
            logger.warning(f"协程取消: play_url={play_url}")
            return None, "Request cancelled"
        except Exception as e:
            logger.error(f"获取真实URL失败: {repr(e)}")
            return None, f"Failed to get the real URL: {repr(e)}"

    @staticmethod
    def validate_real_url(real_url: str, included: list[str] | None = None, blacklisted: list[str] | None = None) -> tuple[bool, str | None]:
        """验证真实URL是否符合要求。

        不是一道能挡住攻击者的边界，只是一层配置过滤。见类 docstring 的部署约束：

        - `match_url` 是整串 URL 上的字符串通配，`*` 会匹配 `/`、`#`、`?`。所以
          `included=["*.mycdn.com/*"]` 会被 `http://attacker.com/#.mycdn.com/` 通过，
          而请求实际发往 attacker.com（片段不会上线）。
        - 两个参数默认 `None` = 不做任何校验；协议也不限 http/https。

        要当真正的安全边界用，得改成按 urlsplit 的结果分别比对 scheme/host/path，
        并另外拦截私有与回环地址。
        """
        # 检查 real_url 是否匹配调用方传入的黑名单规则。
        if blacklisted and any(strings_utils.match_url(real_url, pattern) for pattern in blacklisted):
            logger.error(f"真实URL匹配黑名单: {real_url}")
            return False, f"Real URL matching blacklist: {real_url}"
        # 检查是否包含指定的字符串
        if included and not any(strings_utils.match_url(real_url, pattern) for pattern in included):
            logger.error(f"真实URL不包含指定字符串: {real_url}")
            return False, f"Real URL does not contain specified strings: {real_url}"
        return True, None

    async def delete_real_url_cache(self, play_url: str) -> None:
        """删除真实URL缓存"""
        channel_id = self.generate_channel_id(play_url)
        cache_key = self.REAL_URL_CACHE_KEY.format(channel_id=channel_id)
        try:
            conn = await self._redis_connection()
            await conn.delete(cache_key)
            logger.debug(f"Deleted real URL cache for {play_url}")
        except Exception as e:
            logger.error(f"Failed to delete real URL cache for {play_url}: {repr(e)}")

    async def get_real_url_with_sub(
        self,
        request: Request,
        play_url: str,
        ttl: int,
        included: list[str] | None = None,
        blacklisted: list[str] | None = None,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        headers: dict | None = None,
    ) -> tuple[str | None, str | None]:
        """获取真实URL, 如果有子m3u8,获取子m3u8的第一个URL"""
        channel_id = self.generate_channel_id(play_url)
        cache_key = self.REAL_URL_CACHE_KEY.format(channel_id=channel_id)
        try:
            conn = await self._redis_connection()

            # 首次检查缓存
            real_url: str | None = await conn.get(cache_key)
            if real_url:
                return real_url, None

            lock_name = f"redis_sub_redirect_lock:{self.CACHE_PREFIX}:{channel_id}"
            lock_timeout = 15  # 锁持有时间缩短到15秒
            blocking_timeout = 5  # 等待锁时间缩短到5秒
            try:
                # 使用分布式锁防止缓存雪崩
                async with conn.lock(lock_name, timeout=lock_timeout, blocking_timeout=blocking_timeout):
                    # 双重检查(DCLP模式)
                    real_url = await conn.get(cache_key)
                    if real_url:
                        return real_url, None
                    request_headers = await self.get_request_headers(request, headers or self.DEFAULT_HEADERS)
                    if user_agent:
                        request_headers["User-Agent"] = user_agent
                    # 获取或创建HTTP客户端
                    client = await self.get_client(user_agent, proxy_url)
                    response = await client.request(
                        HttpMethod.GET, play_url, headers=request_headers, follow_redirects=True, no_retry_statuses=[403, 404, 401]
                    )
                    real_url = str(response.url)
                    content = response.text
                    check_result, error_msg = self.validate_real_url(real_url, included, blacklisted)
                    if not check_result:
                        return None, error_msg
                    # 检查内容是否为m3u8
                    if "#EXTM3U" in content and "#EXT-X-STREAM-INF" in content:
                        # 说明这是一个主m3u8, 需要获取第一个子m3u8的URL
                        lines = content.splitlines()
                        sub_m3u8_url = None
                        for line in lines:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                if not line.startswith("http"):
                                    sub_m3u8_url = parse.urljoin(real_url, line)
                                else:
                                    sub_m3u8_url = line
                                break
                        if sub_m3u8_url:
                            logger.debug(f"发现子m3u8, 获取第一个子m3u8的URL: {sub_m3u8_url}")
                            try:
                                sub_response = await client.request(
                                    HttpMethod.GET, sub_m3u8_url, headers=request_headers, follow_redirects=True, no_retry_statuses=[403, 404, 401]
                                )
                                real_url = str(sub_response.url)
                            except Exception as e:
                                logger.warning(f"获取子m3u8失败: {repr(e)}, url is {sub_m3u8_url}")
                                # 获取子m3u8失败时继续使用主m3u8的URL
                    check_result, error_msg = self.validate_real_url(real_url, included, blacklisted)
                    if not check_result:
                        return None, error_msg
                    # 缓存真实URL
                    await conn.set(cache_key, real_url, ex=ttl)
                    return real_url, None
            except LockError as e:
                logger.error(f"Failed to acquire the get_real_url lock: {repr(e)}, url is {play_url}")
                # 如果获取锁失败但有缓存内容，仍然返回缓存内容
                cached_url = await conn.get(cache_key)
                if cached_url:
                    logger.debug(f"使用缓存的URL（可能过期）: {cached_url}")
                    return cached_url, None
                return None, "Failed to acquire the lock"
        except asyncio.CancelledError:
            logger.warning(f"协程取消: play_url={play_url}")
            return None, "Request cancelled"
        except Exception as e:
            logger.error(f"获取真实URL失败: {repr(e)}")
            return None, f"Failed to get the real URL: {repr(e)}"
