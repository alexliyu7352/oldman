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

# User-Agent 以这些开头（不分大小写）时，BaseStreamProxy 选 curl 后端。用不用浏览器指纹由 curl 后端决定：
# 以这些开头（分大小写）、又不含 "/" 和空白的值才当成指纹名（见 backends/curl.py 的 update_impersonate）。
CURL_HEADERS = ["edge", "chrome", "firefox", "safari", "curl"]
