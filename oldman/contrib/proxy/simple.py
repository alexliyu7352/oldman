"""
@author:alex
@date:2025/12/16
@time:10:41
"""

__author__ = "alex"

import asyncio
import base64
import re
from functools import lru_cache
from typing import Any, cast
from urllib import parse

from msgspec import msgpack
from redis.exceptions import LockError
from sanic import HTTPResponse, Request, redirect, text

from oldman.contrib.http import ReconnectStreamResponse
from oldman.contrib.http.schemas import HttpMethod
from oldman.contrib.proxy.base import BaseStreamProxy, _sanic_response_headers
from oldman.contrib.proxy.sealing import UrlSealingMixin
from oldman.logging import logger
from oldman.utils import strings_utils
from oldman.utils.strings_utils import escape_url_for_xml

PROXY_PARAM_KEY = "proxy_params"

# 由于是反代, 所以一些请求头不需要被传递到上游服务器, 可以在此处排除
excluded_headers = ["content-length", "transfer-encoding", "connection", "host"]


class SimpleStreamProxy(BaseStreamProxy):
    """
    简单的流代理, 不进行任何的加密和缓存, 直接转发请求到本地的代理上
    """

    def __init__(self, proxy_name: str = "base", local_proxy=""):
        super().__init__(proxy_name)
        self.local_proxy = local_proxy

    @classmethod
    async def _get_final_url(cls, stream: ReconnectStreamResponse):
        try:
            # 获取最终的URL
            if not stream.current_response:
                return None
            final_url = stream.current_response.url
            if final_url:
                return str(final_url)
        except Exception:
            logger.error("获取最终URL失败")
            return None

    @classmethod
    def _get_new_proxy_path(cls, base_url: str | None, url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        if url in ["false", "true"]:
            return url
        # 处理相对路径，转换为完整URL
        if not url.startswith(("http://", "https://")):
            url = parse.urljoin(base_url or "", url)
        # 转换为代理格式路径
        if url.startswith("https://"):
            ts_url = url.replace("https://", "/https/")
        elif url.startswith("http://"):
            ts_url = url.replace("http://", "/http/")
        else:
            ts_url = url  # 防御性编程，处理意外情况
        if proxy_params_str:
            query_string = f"{PROXY_PARAM_KEY}={proxy_params_str}"
            if "?" in ts_url:
                ts_url += f"&{query_string}"
            else:
                ts_url += f"?{query_string}"
        if local_proxy:
            # 如果local_proxy是/结尾, 则去掉/
            if local_proxy.endswith("/"):
                local_proxy = local_proxy[:-1]
            ts_url = f"{local_proxy}{ts_url}"
        return ts_url

    @classmethod
    def _replace_uri_in_line(cls, line: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        def replace_uri(match):
            ts_path = match.group(1)
            ts_url = cls._get_new_proxy_path(base_url, ts_path, proxy_params_str, local_proxy)
            return f'URI="{ts_url}"'

        return re.sub(r'URI="([^"]+)"', replace_uri, line)

    @classmethod
    def _process_m3u8_ts_path(cls, m3u8_content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径
        :param local_proxy:
        :param base_url:
        :param m3u8_content: m3u8内容
        :param proxy_params_str: 代理使用的参数字符串
        :return: 处理后的m3u8内容
        """
        lines = m3u8_content.splitlines()
        result: list[str] = []
        for line in lines:
            if not line:
                result.append(line)
                continue
            if not line.startswith("#"):
                ts_url = cls._get_new_proxy_path(base_url, line.strip(), proxy_params_str, local_proxy)
                result.append(ts_url)
                continue
            elif line.startswith("#") and not line.strip().startswith("#EXT"):
                # 跳过非标准的EXT行
                continue
            elif line.startswith("#EXT-X-MEDIA:") or line.startswith("#EXT-X-KEY:"):
                line = cls._replace_uri_in_line(line, base_url, proxy_params_str, local_proxy)

            result.append(line)

        return "\n".join(result) + "\n"

    @classmethod
    def _process_mpd_path(cls, mpd_content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        """
        处理mpd内容,替换资源路径为代理路径
        :param local_proxy: 代理路径
        :param mpd_content: mpd内容
        :param base_url: 完整URL
        :param proxy_params_str: 代理使用的参数字符串
        :return: 处理后的MPD内容
        """
        resolved_base_url: str | None = base_url
        if mpd_content.find("</BaseURL>") != -1:
            # 处理BaseURL标签
            mpd_content = re.sub(
                r"<BaseURL\s*>(.*?)</BaseURL>",
                lambda m: f"<BaseURL>{escape_url_for_xml(cls._get_new_proxy_path(resolved_base_url, m.group(1), None, None))}</BaseURL>",
                mpd_content,
            )
            resolved_base_url = None  # 已经处理过BaseURL, 后续不需要再处理相对路径
        # 处理媒体段URL属性: media, initialization, index等
        # 常见于SegmentTemplate中的属性
        url_attributes = ["media", "initialization", "index", "bitstreamSwitching"]
        for attr in url_attributes:
            pattern = rf'({attr})="([^"]+)"'
            mpd_content = re.sub(
                pattern,
                lambda m: (
                    f'{m.group(1)}="{escape_url_for_xml(cls._get_new_proxy_path(resolved_base_url, m.group(2), proxy_params_str, local_proxy))}"'
                ),
                mpd_content,
            )

        # 处理SegmentURL的media属性
        mpd_content = re.sub(
            r'<SegmentURL\s+media="([^"]+)"',
            lambda m: (
                f'<SegmentURL media="{escape_url_for_xml(cls._get_new_proxy_path(resolved_base_url, m.group(1), proxy_params_str, local_proxy))}"'
            ),
            mpd_content,
        )

        # 处理xlink:href属性 (用于外部引用)
        mpd_content = re.sub(
            r'xlink:href="([^"]+)"',
            lambda m: f'xlink:href="{escape_url_for_xml(cls._get_new_proxy_path(resolved_base_url, m.group(1), proxy_params_str, local_proxy))}"',
            mpd_content,
        )

        return mpd_content

    @classmethod
    async def process_manifest(cls, content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        if "#EXTM3U" in content:
            return cls._process_m3u8_ts_path(content, base_url, proxy_params_str, local_proxy)
        elif "<MPD" in content:
            return cls._process_mpd_path(content, base_url, proxy_params_str, local_proxy)
        return content

    def proxy_m3u8_process(
        self,
        m3u8_content: str,
        base_url: str,
        local_proxy: str,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径, 如果本身不包含子m3u8, 那么就生成一个包含实际代理路径的m3u8内容
         :param local_proxy:
         :param direct:
         :param user_agent:
         :param proxy_url:
         :param m3u8_content: m3u8内容
         :param base_url: 基础URL
         :return: 处理后的m3u8内容
        """
        params_str = self.make_params(direct, proxy_url, user_agent, **extra_context)

        if not direct and "#EXT-X-STREAM-INF:" not in m3u8_content and "#EXT-X-MEDIA:" not in m3u8_content:
            # 说明这是一个没有子m3u8的单一流, 直接生成一个包含子m3u8的m3u8, 其中子m3u8为代理的m3u8地址
            proxy_m3u8_url = self._get_new_proxy_path("", base_url, params_str, local_proxy)
            return f"#EXTM3U\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2084544\n{proxy_m3u8_url}\n"

        return self._process_m3u8_ts_path(m3u8_content, base_url, params_str, local_proxy)

    @staticmethod
    def make_params(
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str:
        """
        序列化请求参数到base64字符串
        :param direct:
        :param proxy_url:
        :param user_agent:
        :param extra_context:
        :return:
        """
        context = {
            "proxy_url": proxy_url or "",
            "user_agent": user_agent or "",
            # 保存bool为数字
            "direct": 1 if direct else 0,
            **extra_context,  # 合并额外上下文
        }
        data = msgpack.encode(context)
        return base64.urlsafe_b64encode(data).decode("utf-8")

    @staticmethod
    def load_params(params_str: str) -> dict[str, Any] | None:
        """
        反序列化请求参数从base64字符串
        :param params_str:
        :return:
        """
        try:
            data = base64.urlsafe_b64decode(params_str.encode("utf-8"))
            if not data:
                return None
            params = msgpack.decode(data)
            params["direct"] = params.get("direct") in (1, "1")
            return params
        except Exception as e:
            logger.error(f"解析参数失败: {repr(e)}")
            return None

    async def proxy_remote_manifest(
        self,
        request: Request,
        channel_id: str,
        play_url: str,
        local_proxy: str | None = None,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str | None:
        """
        直接代理远程m3u8内容, 不进行任何缓存
        :param local_proxy: 本地代理路径或者代理地址
        :param channel_id: 频道ID
        :param request: Sanic请求对象
        :param play_url: 播放URL
        :param direct: 是否直接请求
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param extra_context: 额外上下文信息，子类可以扩展
        :return: 处理后的m3u8内容
        """
        cached_id = channel_id
        local_proxy = local_proxy or self.local_proxy
        try:
            conn = await self._redis_connection()
            lock_name = f"redis_m3u8_lock:{self.CACHE_PREFIX}:{self.proxy_name}_{cached_id}"
            # 使用分布式锁防止缓存雪崩
            async with conn.lock(lock_name, timeout=30, blocking_timeout=10):
                logger.debug(f"从远程获取m3u8: url={play_url}")
                # 检查extra_context是否包含headers, 并提取
                if "headers" in extra_context:
                    headers = extra_context.pop("headers")  # type: dict[str, str] | None
                else:
                    headers = None
                m3u8_content, real_url = await self.get_final_m3u8(request, play_url, user_agent, proxy_url, headers, **extra_context)
                if not real_url:
                    real_url = play_url
                if m3u8_content:
                    if "#EXTM3U" in m3u8_content:
                        # 处理m3u8内容,替换TS路径
                        m3u8_content = self.proxy_m3u8_process(
                            m3u8_content,
                            real_url,
                            local_proxy,
                            direct,
                            proxy_url,
                            user_agent,
                            **extra_context,
                        )
                        return m3u8_content
                    elif "<MPD" in m3u8_content:
                        # 说明这是dash流的mpd文件
                        params_str = self.make_params(direct, proxy_url, user_agent, **extra_context)
                        mpd_content = self._process_mpd_path(m3u8_content, real_url, params_str, local_proxy)
                        return mpd_content
                    elif m3u8_content.startswith("http"):
                        # 说明返回的内容是一个重定向URL
                        redirect_url = m3u8_content.strip()
                        logger.info(f"m3u8内容为重定向URL, 返回代理重定向: {play_url} -> {m3u8_content} -> {redirect_url}")
                        return self.proxy_m3u8_process(
                            "",
                            redirect_url,
                            local_proxy,
                            direct,
                            proxy_url,
                            user_agent,
                            **extra_context,
                        )
                return None

        except LockError as e:
            logger.error(f"Failed to acquire the m3u8 lock: {repr(e)}, url is {play_url}")
        except Exception as e:
            logger.error(f"获取m3u8失败: {repr(e)}")
            raise e

        return None

    def get_client_remark(self, stream_url: str) -> str:
        """
        返回url的md5值作为客户端备注
        :param stream_url:
        :return:
        """
        return ""

    async def proxy_sub_manifest_or_stream(
        self,
        request: Request,
        stream_url: str,
        params_str: str | None,
        user_headers: dict[str, str] | None = None,
        live_stream: bool = False,
        local_proxy: str | None = None,
        client_type: str | None = None,
    ) -> HTTPResponse | None:
        """
        代理子请求
        :param local_proxy:
        :param client_type: 客户端类型
        :param live_stream:
        :param user_headers:
        :param params_str:
        :param stream_url:
        :param request: Sanic请求对象
        :return: HTTP响应或None
        """
        local_proxy = local_proxy or self.local_proxy
        if not params_str:
            context = {}
        else:
            context = self.load_params(params_str) or {}
        proxy_url = context.pop("proxy_url", None)
        user_agent = context.pop("user_agent", None)
        logger.debug(f"获取流: {stream_url}, proxy_url={proxy_url}, user_agent={user_agent}")
        client_remark = self.get_client_remark(stream_url)
        # 获取请求头信息
        request_headers = await self.get_request_headers(request, user_headers or self.DEFAULT_HEADERS)
        if user_agent:
            request_headers["User-Agent"] = user_agent
        if request:
            headers = {}
            for key, value in request_headers.items():
                if key.lower() in excluded_headers:
                    continue
                headers[key.title()] = value  # 覆盖或添加请求头，以保持一致性
            request_headers = headers
        request_headers["Accept-Encoding"] = "identity"
        # 获取或创建HTTP客户端
        client = await self.get_client(client_type or user_agent, proxy_url, False, client_remark)
        last_response = HTTPResponse(status=500, headers={})
        # logger.info(f"request headers = {request_headers}")
        try:
            async with client.reconnect_stream(HttpMethod.GET, stream_url, headers=request_headers, live_stream=live_stream) as stream:
                # logger.info(f"response headers = {stream.response_headers}")
                # 判断文件类型, 如果不是视频流, 那么就解析
                content_type = stream.response_headers.get("Content-Type", "")
                if stream.status_code not in [200, 206]:
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None) or content_type or None
                    last_response = HTTPResponse(
                        status=stream.status_code or 500,
                        headers=response_headers,
                        content_type=response_content_type,
                    )
                    return last_response
                final_url = await self._get_final_url(stream)
                # 如果URL发生了跳转,返回302让客户端重定向到新的代理地址
                if final_url and final_url != stream_url:
                    proxy_redirect_url = self._get_new_proxy_path(
                        base_url=stream_url,  # 用于处理相对路径
                        url=final_url,
                        proxy_params_str=params_str,
                        local_proxy=local_proxy,
                    )
                    logger.info(f"检测到上游重定向,返回代理重定向: {stream_url} -> {final_url} -> {proxy_redirect_url}")
                    return redirect(proxy_redirect_url)

                if not any(media_type in content_type for media_type in ["video", "audio", "octet-stream"]):
                    # 调用response.aiter_bytes读取全部的内容
                    blocks: list[Any] = []
                    async for chunk in stream.aiter_bytes(2 * 1024 * 1024):
                        if chunk:
                            blocks.append(chunk)
                    content = b"".join(blocks).decode("utf-8", errors="ignore")
                    if not final_url:
                        final_url = stream_url
                    base_url = final_url[: final_url.rfind("/") + 1]
                    content = await self.process_manifest(content, base_url, params_str, local_proxy)
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None) or content_type or "text/plain; charset=utf-8"
                    return text(
                        content,
                        200,
                        headers=cast(dict[str, str], response_headers),
                        content_type=response_content_type,
                    )
                else:
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None)
                    last_response = HTTPResponse(
                        status=stream.status_code or 500,
                        headers=response_headers,
                        content_type=response_content_type,
                    )
                    # 流式返回内容
                    await self.stream_response(request, stream)
                    return None
        except asyncio.CancelledError:
            logger.warning(f"协程取消: ts_url={stream_url}")
            return None
        except Exception as e:
            logger.error(f"获取TS失败: {repr(e)}")
            return last_response


class SimpleEncryptedStreamProxy(UrlSealingMixin, SimpleStreamProxy):
    """
    简单加密的流代理, 加密真实URL, 但是不进行任何缓存, 直接转发请求到本地的代理上
    """

    # Proxy 实例随服务进程长期存在，有界缓存避免重复进行相同 URL 变换。
    # 密封是确定性的，所以两个方向都能缓存，下游 HTTP 缓存也仍然有效。
    @lru_cache(maxsize=4096)  # noqa: B019
    def encrypt_url(self, url: str) -> str:
        """把真实 URL 封成不可伪造的路径段。"""
        return self.seal_url(url)

    @lru_cache(maxsize=2048)  # noqa: B019
    def decrypt_url(self, encrypted_url: str) -> str | None:
        """还原真实 URL；被改写或伪造的路径段返回 None。"""
        return self.unseal_url(encrypted_url)

    def get_encrypt_path(self, base_url: str, url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        # 处理相对路径，转换为完整URL
        if not url.startswith(("http://", "https://")):
            url = parse.urljoin(base_url, url)
        ext_name = strings_utils.get_ext_from_filename(url) or ".ts"
        encrypted_url = self.encrypt_url(url)
        ts_url = f"{encrypted_url}{ext_name}"
        if proxy_params_str:
            query_string = f"{PROXY_PARAM_KEY}={proxy_params_str}"
            if "?" in ts_url:
                ts_url += f"&{query_string}"
            else:
                ts_url += f"?{query_string}"
        if local_proxy:
            # 如果local_proxy是/结尾, 则去掉/
            if local_proxy.endswith("/"):
                local_proxy = local_proxy[:-1]
            ts_url = f"{local_proxy}/{ts_url}"
        return ts_url

    def proxy_m3u8_process(
        self,
        m3u8_content: str,
        base_url: str,
        local_proxy: str,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径, 如果本身不包含子m3u8, 那么就生成一个包含实际代理路径的m3u8内容
         :param local_proxy:
         :param direct:
         :param user_agent:
         :param proxy_url:
         :param m3u8_content: m3u8内容
         :param base_url: 基础URL
         :return: 处理后的m3u8内容
        """
        params_str = self.make_params(direct, proxy_url, user_agent, **extra_context)

        if not direct and "#EXT-X-STREAM-INF:" not in m3u8_content and "#EXT-X-MEDIA:" not in m3u8_content:
            # 说明这是一个没有子m3u8的单一流, 直接生成一个包含子m3u8的m3u8, 其中子m3u8为代理的m3u8地址
            proxy_m3u8_url = self.get_encrypt_path("", base_url, params_str, local_proxy)
            return f"#EXTM3U\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2084544\n{proxy_m3u8_url}\n"

        return self.process_m3u8_ts_path(m3u8_content, base_url, params_str, local_proxy)

    def process_m3u8_ts_path(self, m3u8_content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径
        :param local_proxy:
        :param base_url:
        :param m3u8_content: m3u8内容
        :param proxy_params_str: 代理使用的参数字符串
        :return: 处理后的m3u8内容
        """
        lines = m3u8_content.splitlines()
        result: list[str] = []
        for line in lines:
            if not line:
                result.append(line)
                continue
            if not line.startswith("#"):
                ts_url = self.get_encrypt_path(base_url, line.strip(), proxy_params_str, local_proxy)
                result.append(ts_url)
                continue
            elif line.startswith("#") and not line.strip().startswith("#EXT"):
                # 跳过非标准的EXT行
                continue
            elif line.startswith("#EXT-X-MEDIA:") or line.startswith("#EXT-X-KEY:"):
                line = self._replace_uri_in_line(line, base_url, proxy_params_str, local_proxy)

            result.append(line)

        return "\n".join(result) + "\n"

    async def proxy_sub_manifest_or_stream(
        self,
        request: Request,
        stream_url: str,
        params_str: str | None,
        user_headers: dict[str, str] | None = None,
        live_stream: bool = False,
        local_proxy: str | None = None,
        client_type: str | None = None,
    ) -> HTTPResponse | None:
        """
        代理子请求
        :param local_proxy:
        :param client_type: 客户端类型
        :param live_stream:
        :param user_headers:
        :param params_str:
        :param stream_url:
        :param request: Sanic请求对象
        :return: HTTP响应或None
        """
        local_proxy = local_proxy or self.local_proxy
        if not params_str:
            context = {}
        else:
            context = self.load_params(params_str) or {}
        decrypted_url = self.decrypt_url(stream_url)
        if not decrypted_url:
            logger.error(f"解密URL失败: {decrypted_url}")
            return text(status=400, body="Invalid URL")
        stream_url = decrypted_url
        proxy_url = context.pop("proxy_url", None)
        user_agent = context.pop("user_agent", None)
        logger.debug(f"获取流: {stream_url}, proxy_url={proxy_url}, user_agent={user_agent}")
        client_remark = self.get_client_remark(stream_url)
        # 获取请求头信息
        request_headers = await self.get_request_headers(request, user_headers or self.DEFAULT_HEADERS)
        if user_agent:
            request_headers["User-Agent"] = user_agent
        if request:
            headers = {}
            for key, value in request_headers.items():
                if key.lower() in excluded_headers:
                    continue
                headers[key.title()] = value  # 覆盖或添加请求头，以保持一致性
            request_headers = headers
        request_headers["Accept-Encoding"] = "identity"
        # 获取或创建HTTP客户端
        client = await self.get_client(client_type or user_agent, proxy_url, False, client_remark)
        last_response = HTTPResponse(status=500, headers={})
        # logger.info(f"request headers = {request_headers}")
        try:
            async with client.reconnect_stream(HttpMethod.GET, stream_url, headers=request_headers, live_stream=live_stream) as stream:
                # logger.info(f"response headers = {stream.response_headers}")
                # 判断文件类型, 如果不是视频流, 那么就解析
                content_type = stream.response_headers.get("Content-Type", "")
                if stream.status_code not in [200, 206]:
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None) or content_type or None
                    last_response = HTTPResponse(
                        status=stream.status_code or 500,
                        headers=response_headers,
                        content_type=response_content_type,
                    )
                    return last_response
                final_url = await self._get_final_url(stream)
                # 如果URL发生了跳转,返回302让客户端重定向到新的代理地址
                if final_url and final_url != stream_url:
                    proxy_redirect_url = self._get_new_proxy_path(
                        base_url=stream_url,  # 用于处理相对路径
                        url=final_url,
                        proxy_params_str=params_str,
                        local_proxy=local_proxy,
                    )
                    logger.info(f"检测到上游重定向,返回代理重定向: {stream_url} -> {final_url} -> {proxy_redirect_url}")
                    return redirect(proxy_redirect_url)

                if not any(media_type in content_type for media_type in ["video", "audio", "octet-stream"]):
                    # 调用response.aiter_bytes读取全部的内容
                    blocks: list[Any] = []
                    async for chunk in stream.aiter_bytes(2 * 1024 * 1024):
                        if chunk:
                            blocks.append(chunk)
                    content = b"".join(blocks).decode("utf-8", errors="ignore")
                    if not final_url:
                        final_url = stream_url
                    base_url = final_url[: final_url.rfind("/") + 1]
                    if "#EXTM3U" in content:
                        content = self.process_m3u8_ts_path(content, base_url, params_str, local_proxy)
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None) or content_type or "text/plain; charset=utf-8"
                    return text(
                        content,
                        200,
                        headers=cast(dict[str, str], response_headers),
                        content_type=response_content_type,
                    )
                else:
                    response_headers = _sanic_response_headers(stream.response_headers, body_changed=True)
                    response_content_type = response_headers.pop("content-type", None)
                    last_response = HTTPResponse(
                        status=stream.status_code or 500,
                        headers=response_headers,
                        content_type=response_content_type,
                    )
                    # 流式返回内容
                    await self.stream_response(request, stream)
                    return None
        except asyncio.CancelledError:
            logger.warning(f"协程取消: ts_url={stream_url}")
            return None
        except Exception as e:
            logger.error(f"获取TS失败: {repr(e)}")
            return last_response


async def get_final_url(stream: ReconnectStreamResponse):
    return await SimpleStreamProxy._get_final_url(stream)


def get_new_proxy_path(base_url: str, url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
    return SimpleStreamProxy._get_new_proxy_path(base_url, url, proxy_params_str, local_proxy)


def replace_uri_in_line(line: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
    return SimpleStreamProxy._replace_uri_in_line(line, base_url, proxy_params_str, local_proxy)


def process_m3u8_ts_path(m3u8_content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
    return SimpleStreamProxy._process_m3u8_ts_path(m3u8_content, base_url, proxy_params_str, local_proxy)


def process_mpd_path(mpd_content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
    return SimpleStreamProxy._process_mpd_path(mpd_content, base_url, proxy_params_str, local_proxy)


async def process_manifest(content: str, base_url: str, proxy_params_str: str | None = None, local_proxy: str | None = None) -> str:
    return await SimpleStreamProxy.process_manifest(content, base_url, proxy_params_str, local_proxy)
