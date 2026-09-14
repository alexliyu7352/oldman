import ipaddress
import urllib.parse
from collections.abc import Iterable
from datetime import UTC, datetime
from os.path import normpath
from typing import Any, cast

FORWARDED_CLIENT_IP_HEADERS = (
    "x-forwarded-for",  # client, proxy1, proxy2
    "x-real-ip",
    "x-client-ip",
    "x-cluster-client-ip",
    "forwarded-for",
)


def my_url_join(base: str, url: str) -> str:
    url1 = urllib.parse.urljoin(base, url)
    arr = urllib.parse.urlparse(url1)
    path = normpath(arr[2])
    result = urllib.parse.urlunparse((arr.scheme, arr.netloc, path, arr.params, arr.query, arr.fragment))
    # 确保返回字符串类型
    if isinstance(result, bytes):
        return result.decode("utf-8")
    return result


def update_url_query(url: str, **kwargs: str | list[str] | set[str]) -> str:
    """
    修改url的query查询参数
    """
    if not kwargs:
        return url
    bits = list(urllib.parse.urlparse(url))
    query = urllib.parse.parse_qs(bits[4])
    for k, v in kwargs.items():
        if isinstance(v, list | set):
            query[k] = [str(item) for item in v]
        else:
            query[k] = [str(v)]
    bits[4] = urllib.parse.urlencode(query, True)
    result = urllib.parse.urlunparse(bits)
    # 确保返回字符串类型
    if isinstance(result, bytes):
        return result.decode("utf-8")
    return result


def first_public_ip(request: Any) -> str | None:
    """Return the first globally routable address found in proxy headers.

    This is a best-effort guess for logging and analytics. Every header it reads
    can be set by the client, so never use the result for authentication or
    access decisions; ``request.client_ip`` with ``web.real_ip_header``,
    ``web.proxies_count`` or ``web.forwarded_secret`` gives the trusted address.
    Falls back to the peer address when that is public, otherwise ``None``.
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        for name in FORWARDED_CLIENT_IP_HEADERS:
            for value in _header_values(headers, name):
                for candidate in value.split(","):
                    address = _public_ip_or_none(candidate)
                    if address is not None:
                        return address
    peer = getattr(request, "ip", None)
    return _public_ip_or_none(peer) if isinstance(peer, str) else None


def _header_values(headers: Any, name: str) -> list[str]:
    """Read every value of a header from Sanic's multi-dict or a plain mapping."""
    getall = getattr(headers, "getall", None)
    if callable(getall):
        return [str(value) for value in cast("Iterable[object]", getall(name, []))]
    value = headers.get(name)
    return [str(value)] if value else []


def _public_ip_or_none(candidate: Any) -> str | None:
    """Parse one header entry or peer address; keep it only when globally routable."""
    if not isinstance(candidate, str):
        return None
    text = candidate.strip().strip('"')
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]  # bracketed IPv6, optionally with a port
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]  # IPv4 with a port
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    return str(address) if address.is_global else None


def sanitize_path(path: str) -> str:
    return path.strip("/").replace("/", "_")


def get_server_timestamp_from_header(response_headers: Any) -> float:
    """从HTTP响应头获取服务器时间戳 (GMT格式)"""
    try:
        # HTTP标准头固定为GMT格式
        time_str = response_headers.get("Date") or response_headers.get("Last-Modified")
        if not time_str:
            return datetime.now(UTC).timestamp()

        # 解析GMT时间 (RFC 2822格式)
        dt = datetime.strptime(time_str, "%a, %d %b %Y %H:%M:%S GMT")
        return dt.replace(tzinfo=UTC).timestamp()

    except (ValueError, AttributeError):
        # 解析失败时返回当前时间
        return datetime.now(UTC).timestamp()
