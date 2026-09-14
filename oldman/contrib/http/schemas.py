"""
@author:alex
@date:2025/7/6
@time:11:05
"""

__author__ = "alex"

import enum


class ClientType(enum.StrEnum):
    """HTTP 客户端类型的字符串枚举"""

    HTTPX = "httpx"
    AIOHTTP = "aiohttp"
    CURL_CFFI = "curl_cffi"


class HttpMethod(enum.StrEnum):
    """HTTP 方法的字符串枚举"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
