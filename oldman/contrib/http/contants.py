"""
@author:alex
@date:2025/8/10
@time:13:46
"""

__author__ = "alex"

import asyncio

import httpx
from aiohttp import ClientError
from curl_cffi import CurlError

StreamConnectionError = (
    httpx.RequestError,
    ClientError,
    CurlError,
    ConnectionError,
    asyncio.TimeoutError,
)
StreamReadError = (
    httpx.ReadError,
    httpx.RemoteProtocolError,  # Httpx read issues
    ClientError,  # Aiohttp read issues (can overlap with connection)
    CurlError,  # Curl read issues (e.g., timeout, partial file)
)

DEFAULT_HEADERS = {
    # "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/json",
}

M3U8_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
}

CURL_HEADERS = ["edge", "chrome", "firefox", "safari", "curl", "chrome_android"]


def is_use_curl(play_ua: str | None = None) -> bool:
    """判断是否使用curl_cffi, 根据play_ua起始字符串判断"""
    if play_ua:
        for prefix in CURL_HEADERS:
            if play_ua.startswith(prefix):
                return True
    return False
