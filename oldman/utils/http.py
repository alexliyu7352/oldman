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


# 只拒绝"点一下就执行代码"的伪协议。允许 http/https/mailto 和相对路径,因为跳转到
# 外部系统(支付页、工单、对象存储)是正常业务需求,框架不该替使用者禁掉它。
DANGEROUS_SCHEMES = frozenset({"javascript", "data", "vbscript", "file", "blob"})


def is_safe_link(value: object) -> bool:
    """Return whether a link is safe to render into an anchor or hand to a browser navigation.

    Escaping protects the attribute — it stops the value breaking out of the quotes — but says
    nothing about the scheme: `javascript:` in an href is a script, not a link.

    So this refuses schemes that execute, and nothing else. An external `https://` link is a
    normal thing to point at, and a framework that required every link to be local would just
    push its users into working around it.

    Also refuses control characters and backslashes, which are how a scheme gets smuggled past a
    naive parser (`java\tscript:`), and values that are not valid UTF-8.

    This lives in `oldman.utils.http` rather than beside its first caller because it is the one
    rule for every link the framework emits: message hrefs, table cells, response actions. A
    module under `oldman.web.messages` could not be imported by `oldman.web.api` without a cycle.
    """
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if any(character == "\\" or ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return False
    try:
        scheme = urllib.parse.urlparse(value).scheme
    except ValueError:
        return False
    return scheme.lower() not in DANGEROUS_SCHEMES


def is_same_site_path(value: object) -> bool:
    """Return whether a value is safe to use as a server-side redirect target.

    Stricter than `is_safe_link`, and deliberately so: these are two different uses with two
    different threat models.

    A link that is *rendered* may point anywhere a business needs, because the user sees where
    they are going and clicks it themselves. A destination the server *redirects* to is an open
    redirect: a link on your own domain that silently lands the visitor on someone else's, which
    is what makes it useful for phishing. Stored notifications are opened through a route that
    issues a 303, so their href has to stay local.

    Requires a plain local absolute path: no scheme, no authority, no protocol-relative
    `//host`, no backslash or control character, and valid UTF-8.
    """
    if not is_safe_link(value):
        return False
    text = str(value)
    if not text.startswith("/") or text.startswith("//"):
        return False
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc
