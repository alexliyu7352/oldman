"""
@author:alex
@date:2025/8/10
@time:19:59
"""

__author__ = "alex"

import asyncio
import base64
import re
import time
from hashlib import md5, sha256
from typing import Any, cast
from urllib import parse

from async_lru import alru_cache
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from isodate import parse_duration
from msgspec import msgpack
from sanic import HTTPResponse, Request, text

from oldman.contrib.proxy.base import BaseStreamProxy
from oldman.logging import logger
from oldman.utils import strings_utils
from oldman.utils.hash import pad_pkcs7, unpad_pkcs7


class EncryptStreamProxy(BaseStreamProxy):
    """
    支持加密的代理类
    主要用于使用加密url来替代缓存Url
    """

    DEFAULT_AES_KEY = b"132d73f7-2b6b-3189-a715-c2ab5d19"  # 默认AES密钥
    DEFAULT_AES_IV = b"3f4165@f1e%13!71"  # 默认AES IV

    def __init__(self, proxy_name: str = "base"):
        super().__init__(proxy_name)
        # 默认加密URL的AES密钥和IV
        self.aes_key: bytes = self.DEFAULT_AES_KEY
        self.aes_iv: bytes = self.DEFAULT_AES_IV

    @alru_cache(maxsize=4096)
    async def encrypt_url(self, url: str) -> str:
        """
        加密URL，使用AES-CBC模式
        :param url:
        :return:
        """
        # 使用PKCS7填充
        data = url.encode("utf8")
        padded_data = pad_pkcs7(data)

        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypt_content = encryptor.update(padded_data) + encryptor.finalize()
        return encrypt_content.hex()

    @alru_cache(maxsize=4096)
    async def decrypt_url(self, encrypted_url: str) -> str | None:
        """
        解密url，使用AES-CBC模式
        :param encrypted_url:
        :return:
        """
        # 如果存在扩展名则去除
        ext_name = strings_utils.get_ext_from_filename(encrypted_url)
        if ext_name:
            encrypted_url = encrypted_url.replace(ext_name, "")
        try:
            cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_iv), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypt_content = decryptor.update(bytes.fromhex(encrypted_url)) + decryptor.finalize()

            # 移除PKCS7填充
            decrypt_content = unpad_pkcs7(decrypt_content)
            return decrypt_content.decode("utf8")
        except Exception:
            return None

    async def save_sub_url(  # type: ignore[override]
        self,
        channel_id: str,
        ts_url: str,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        ext_name: str | None = None,
        **extra_context,
    ) -> str:
        """
        保存TS URL到Redis并生成新URL
        :param ext_name: 扩展名
        :param channel_id: 频道ID
        :param ts_url: 原始TS URL
        :param direct: 是否直接请求
        :param proxy_url: 代理URL
        :param user_agent: 用户代理
        :param extra_context: 额外上下文信息，子类可以扩展
        :return: 新的代理URL路径
        """
        if not ext_name:
            ext_name = strings_utils.get_ext_from_filename(ts_url) or ".ts"

        # 基础上下文
        context = {
            "ts_url": ts_url,
            "proxy_url": proxy_url or "",
            "user_agent": user_agent or "",
            "ext_name": ext_name,
            # 保存bool为数字
            "direct": 1 if direct else 0,
            **extra_context,  # 合并额外上下文
        }
        # 把字典的基础上下文转换为使用|||分割的字符串
        context_str = "|||".join(f"{k}={v}" for k, v in context.items() if v is not None)
        encrypted_url = await self.encrypt_url(context_str)
        line = f"/{self.proxy_name}/{channel_id}/{encrypted_url}{ext_name}"
        return line

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
        return await self.proxy_m3u8_ts_path_inter(
            channel_id,
            m3u8_content,
            base_url,
            direct,
            proxy_url,
            user_agent,
            **extra_context,
        )

    async def proxy_m3u8_ts_path_inter(
        self,
        channel_id: str,
        m3u8_content: str,
        base_url: str,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> str:
        """
        处理m3u8内容,替换TS路径为代理路径, 并支持加密TS路径
        :param direct:
        :param user_agent:
        :param proxy_url:
        :param channel_id: 频道ID
        :param m3u8_content: m3u8内容
        :param base_url: 基础URL
        :return: 处理后的m3u8内容
        """
        lines = m3u8_content.splitlines()
        result: list[str] = []

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
                line = await self.save_sub_url(channel_id, ts_url, direct, proxy_url, user_agent, **extra_context)
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
                                    ts_url,
                                    direct,
                                    proxy_url,
                                    user_agent,
                                    **extra_context,
                                )
                                parts[i] = f'URI="{ts_url}"'
                    # 重新组合行
                    line = ",".join(parts)
            result.append(line)

        return "\n".join(result) + "\n"

    async def get_sub_url(self, channel_id: str, hash_url: str) -> dict[str, Any] | Any:
        url_context = await self.decrypt_url(hash_url)
        if not url_context:
            return None
        # 解析上下文字符串
        context_parts = url_context.split("|||")
        result: dict[str, Any] = {}
        for part in context_parts:
            if "=" in part:
                key, value = part.split("=", 1)
                result[key.strip()] = value.strip()
            else:
                result[part.strip()] = None
        if "direct" in result and result["direct"] == "1":
            result["direct"] = True
        else:
            result["direct"] = False
        return result


class EncryptMixStreamProxy(BaseStreamProxy):
    """
    支持加密和缓存的代理类,
    主要用于使用加密url来替代缓存Url, 但是代理,UA等参数缓存, 避免URL过长
    流程是: 请求m3u8时, 生成加密URL并缓存参数; 请求TS时, 解密URL并从缓存获取参数
    这样可以避免URL过长的问题
    """

    DEFAULT_AES_KEY = b"132d73f7-2b6b-3189-a715-c2ab5d19"  # 默认AES密钥

    def __init__(self, proxy_name: str = "base", key_material: bytes = DEFAULT_AES_KEY):
        super().__init__(proxy_name)
        self.aes_key = key_material
        self.keystream_base: bytearray = bytearray(sha256(key_material).digest())
        self.ttl_cached: dict[str, tuple[int, int]] = {}

    def _generate_keystream(self, length: int) -> bytes:
        """生成指定长度的密钥流"""
        keystream = bytearray(self.keystream_base)
        while len(keystream) < length:
            keystream.extend(sha256(bytes(keystream)).digest())
        return bytes(keystream[:length])

    @alru_cache(maxsize=4096)
    async def encrypt_url(self, url: str) -> str:
        """
        加密URL，使用AES-CBC模式
        :param url:
        :return:
        """
        data = url.encode("utf-8")
        # 生成密钥流(确定性)
        keystream = self._generate_keystream(len(data))
        # XOR 加密
        ciphertext = bytes(a ^ b for a, b in zip(data, keystream, strict=False))
        # 使用 Base64URL 编码 (移除 padding)
        return base64.urlsafe_b64encode(ciphertext).decode("ascii").rstrip("=")

    @alru_cache(maxsize=2048)
    async def decrypt_url(self, encrypted_url: str) -> str | None:
        """
        解密url，使用AES-CBC模式
        :param encrypted_url:
        :return:
        """
        # 如果存在扩展名则去除
        ext_name = strings_utils.get_ext_from_filename(encrypted_url)
        if ext_name:
            encrypted_url = encrypted_url.replace(ext_name, "")
        try:
            # Base64URL 解码需要补充 padding
            padding = 4 - len(encrypted_url) % 4
            if padding != 4:
                encrypted_url += "=" * padding

            ciphertext = base64.urlsafe_b64decode(encrypted_url)
            keystream = self._generate_keystream(len(ciphertext))
            # XOR 解密
            plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False))
            return plaintext.decode("utf-8")
        except Exception:
            return None

    async def get_encrypt_sub_url(
        self,
        channel_id: str,
        ts_url: str,
        ext_name: str | None = None,
    ) -> str:
        """
        保存TS URL到Redis并生成新URL
        :param ext_name: 扩展名
        :param channel_id: 频道ID
        :param ts_url: 原始TS URL
        :return: 新的代理URL路径
        """
        if not ext_name:
            ext_name = strings_utils.get_ext_from_filename(ts_url) or ".ts"
        encrypted_url = await self.encrypt_url(ts_url)
        line = f"/{self.proxy_name}/{channel_id}/{encrypted_url}{ext_name}"
        return line

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
        处理m3u8内容,替换TS路径为代理路径, 并支持加密TS路径
         :param sub_ttl: 这里不需要,采用计算的TTL
         :param cached_id: 用于缓存的ID
         :param direct:
         :param user_agent:
         :param proxy_url:
         :param channel_id: 频道ID
         :param m3u8_content: m3u8内容
         :param base_url: 基础URL
         :return: 处理后的m3u8内容
        """
        lines = m3u8_content.splitlines()
        result: list[str] = []
        if not channel_id:
            # 如果没有传入channel_id, 则使用base_url的md5作为channel_id
            channel_id = md5(base_url.encode("utf8")).hexdigest()
        # 计算缓存时间, 根据m3u8_content中的内容, 如果包含EXT-X-TARGETDURATION, 则使用该值的两倍作为缓存时间, 如果是VOD类型, 则使用全部内容的时间总和
        calculated_ttl = self.calculate_m3u8_ttl(cached_id, m3u8_content)
        # 保存请求参数到Redis
        await self.save_params(
            channel_id,
            calculated_ttl,
            direct,
            proxy_url,
            user_agent,
            **extra_context,
        )
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
                line = await self.get_encrypt_sub_url(channel_id, ts_url)
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
                                ts_url = await self.get_encrypt_sub_url(channel_id, ts_url)
                                parts[i] = f'URI="{ts_url}"'
                    # 重新组合行
                    line = ",".join(parts)
            result.append(line)

        return "\n".join(result) + "\n"

    async def save_params(
        self,
        channel_id: str,
        sub_ttl: int,
        direct: bool = False,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        **extra_context,
    ) -> None:
        """
        保存TS请求参数到Redis
        :param channel_id:
        :param sub_ttl:
        :param direct:
        :param proxy_url:
        :param user_agent:
        :param extra_context:
        :return:
        """
        cache_key = self.CACHED_URL_KEY.format(channel_id=channel_id)
        # print(f"Saving params to cache key: {cache_key} with TTL: {sub_ttl}")
        # 基础上下文
        context = {
            "proxy_url": proxy_url or "",
            "user_agent": user_agent or "",
            # 保存bool为数字
            "direct": 1 if direct else 0,
            **extra_context,  # 合并额外上下文
        }
        data = msgpack.encode(context)
        # 使用管道优化Redis操作
        conn = await self._redis_binary_connection()
        await conn.setex(cache_key, sub_ttl, data)

    async def load_params(self, channel_id: str) -> dict[str, Any] | None:
        """
        从Redis加载TS请求参数
        :param channel_id:
        :return:
        """
        cache_key = self.CACHED_URL_KEY.format(channel_id=channel_id)
        # print(f"Loading params from cache key: {cache_key}")
        conn = await self._redis_binary_connection()
        data = await conn.get(cache_key)
        if not data:
            return None
        params = msgpack.decode(cast(bytes, data))
        if not isinstance(params, dict):
            return None
        params["direct"] = params.get("direct") in (1, "1")
        return params

    def calculate_m3u8_ttl(self, channel_id: str, m3u8_content: str) -> int:
        """
        优化的 TTL 计算：快速判断类型和计算
        :param channel_id:
        :param m3u8_content: m3u8 或 mpd 内容
        :return: TTL 秒数
        """
        current_time = int(time.time())
        if channel_id in self.ttl_cached:
            ttl, expire_time = self.ttl_cached[channel_id]
            if expire_time > current_time:
                return ttl
        # 1. 快速判断文件类型
        is_mpd = m3u8_content.lstrip().startswith("<?xml") or "<MPD" in m3u8_content[:200]

        if is_mpd:
            ttl = max(self._calculate_mpd_ttl(m3u8_content), 10)
        else:
            # 最小缓存时间不低于10秒
            ttl = max(self._calculate_m3u8_ttl(m3u8_content), 10)
        # 缓存TTL计算结果，过期时间为5分钟
        expire_time = int(current_time + 300)
        self.ttl_cached[channel_id] = (ttl, expire_time)
        return ttl

    def _calculate_m3u8_ttl(self, m3u8_content: str) -> int:
        """快速计算 M3U8 的 TTL - 单次遍历优化版本"""
        # 初始化变量
        is_vod = False
        target_duration = 0
        segment_count = 0
        second_segment_duration = 0
        segment_index = 0

        # 单次遍历（O(n)）
        for line in m3u8_content.splitlines():
            line_stripped = line.strip()

            # 检查 VOD 标记
            if line_stripped == "#EXT-X-ENDLIST":
                is_vod = True

            # 提取 TARGET-DURATION
            elif line_stripped.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    target_duration = int(line_stripped.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass

            # 统计切片并提取第二个切片时长
            elif line_stripped.startswith("#EXTINF:"):
                segment_count += 1

                # 提取第二个切片时长作为备用
                if segment_index == 1:
                    try:
                        duration_str = line_stripped.split(":", 1)[1].split(",")[0]
                        second_segment_duration = int(float(duration_str))
                    except (ValueError, IndexError):
                        pass

                segment_index += 1

        # 计算 TTL
        avg_duration = target_duration or second_segment_duration or 10

        if is_vod:
            return segment_count * avg_duration * 4
        else:
            return avg_duration * segment_count * 3

    def _calculate_mpd_ttl(self, mpd_content: str) -> int:
        """使用 isodate 库解析 ISO 8601 Duration"""

        is_vod = 'type="static"' in mpd_content

        if is_vod:
            match = re.search(r'mediaPresentationDuration="([^"]+)"', mpd_content)
            if match:
                duration = parse_duration(match.group(1))
                return int(duration.total_seconds()) + 60
            return 7200
        else:
            match = re.search(r'minimumUpdatePeriod="([^"]+)"', mpd_content)
            if match:
                duration = parse_duration(match.group(1))
                return int(duration.total_seconds()) * 2
            return 300

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
            ts_context = await self.load_params(channel_id)
            if ts_context is None:
                return text("", status=404)
            ts_url = await self.decrypt_url(hash_url)
            if not ts_url:
                return text("", status=404)
            # 准备自定义参数
            custom_params = {}
            for key, value in ts_context.items():
                if key not in ["ts_url", "proxy_url", "user_agent", "channel_id", "ext_name", "direct"]:
                    custom_params[key] = value
            ext_name = strings_utils.get_ext_from_filename(ts_url) or ".ts"
            ts_context["ts_url"] = ts_url
            # 根据文件类型处理不同内容
            if ext_name in [".m3u8", ".m3u", ".mpd"]:
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
