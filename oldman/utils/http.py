import ipaddress
import urllib.parse
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any, cast

FORWARDED_CLIENT_IP_HEADERS = (
    "x-forwarded-for",  # client, proxy1, proxy2
    "x-real-ip",
    "x-client-ip",
    "x-cluster-client-ip",
    "forwarded-for",
)


def update_url_query(url: str, params: Mapping[str, Any] | None = None, /, **kwargs: Any) -> str:
    """修改 url 的查询参数：params 与 kwargs 里给出的键设成新值，其余参数原样保留。

    - 已有的键在原位置替换（同名出现多次时只留第一个位置）；原来没有的追加在末尾。
    - 值是 list、tuple 或 set 时展开成多个同名参数，空列表表示删掉这个键；其他值用 str() 转换。
    - 没改动的参数不解码也不重新编码、顺序不变——签名参数（如 ``hdnts=exp=…~acl=/*~hmac=…``）不会失效；
      没有值的参数（``a=``、``flag``）也保留。``#片段`` 保持在最后。
    - 键名带横线、或与本函数的参数同名时，用 params 传：``update_url_query(url, {"x-token": "t", "url": "u"})``。

    这里是覆盖；只想把参数接在后面、不管同名，用 append_query。
    """
    updates = {**(params or {}), **kwargs}
    if not updates:
        return url
    replacements = {key: urllib.parse.urlencode({key: _query_values(value)}, doseq=True) for key, value in updates.items()}

    base, hash_mark, fragment = url.partition("#")
    path, _, query = base.partition("?")
    pairs: list[str] = []
    replaced: set[str] = set()
    for pair in query.split("&"):
        if not pair:
            continue
        key = urllib.parse.unquote_plus(pair.split("=", 1)[0])
        if key not in replacements:
            pairs.append(pair)
        elif key not in replaced:
            pairs.append(replacements[key])
            replaced.add(key)
    pairs.extend(encoded for key, encoded in replacements.items() if key not in replaced)

    new_query = "&".join(pair for pair in pairs if pair)
    return f"{path}{'?' if new_query else ''}{new_query}{hash_mark}{fragment}"


def _query_values(value: Any) -> list[str]:
    """一个或多个查询参数值，统一成字符串列表。"""
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def append_query(url: str, query: str | Mapping[str, Any], exclude: Collection[str] = (), doseq: bool = True) -> str:
    """把查询参数接到 url 后面，先去掉 exclude 里列出的键；url 已有查询参数时用 & 接上。

    代理转发请求时常用：把收到的参数去掉代理自己要用的几个，其余交给上游::

        append_query(upstream_url, request.query_string, [PROXY_PARAM_KEY])
        append_query(upstream_url, request.args, ["channel_id"])

    - query 是 str（原始查询串）：只按键过滤，其余参数**原样保留**，不解码也不重新编码，顺序不变。上游按原始写法
      校验签名时（如 CDN 的 ``hdnts=exp=…~acl=/*~hmac=…``）不会失效；没有值的参数（``flag``、``a=``）也原样保留。
    - query 是映射（如 ``request.args``）：用 urlencode 编码，doseq 为 True 时列表值展开成多个同名参数。
    - 键按解码后的名字与 exclude 比较。过滤后没有参数时原样返回 url；url 里的 ``#片段`` 保持在最后。
    - exclude 是键的集合，只排除一个键也写成 ``[key]``；传字符串报 TypeError（否则 ``in`` 做的是子串判断，
      ``"channel_id"`` 会连 ``c``、``id`` 这些键一起排除）。

    这里是追加；要覆盖 url 里已有的同名参数用 update_url_query。
    """
    if isinstance(exclude, str):
        raise TypeError("append_query() exclude is a collection of keys; pass one key as [key], not as a string")
    if isinstance(query, str):
        kept = [pair for pair in query.split("&") if pair and urllib.parse.unquote_plus(pair.split("=", 1)[0]) not in exclude]
        encoded = "&".join(kept)
    else:
        encoded = urllib.parse.urlencode({key: value for key, value in query.items() if key not in exclude}, doseq=doseq)
    if not encoded:
        return url

    base, hash_mark, fragment = url.partition("#")
    if "?" not in base:
        separator = "?"
    elif base.endswith(("?", "&")):
        separator = ""
    else:
        separator = "&"
    return f"{base}{separator}{encoded}{hash_mark}{fragment}"


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
    """把路径变成可以放进键名的一段：去掉首尾的 /，其余 / 换成 _。

    只做这一件事，**不是安全过滤**：不处理 ``..``、冒号、空白或其他字符。不同路径可能得到同一个结果——
    ``a/b`` 与 ``a_b`` 都是 ``a_b``——所以不要拿不受控的输入（如请求路径）当唯一键；框架的限流器传的都是
    固定的名字。
    """
    return path.strip("/").replace("/", "_")


def get_server_timestamp_from_header(response_headers: Any, *, use_last_modified: bool = False) -> float | None:
    """从 HTTP 响应头读出服务器当前时间（Unix 时间戳），用来计算本机与服务器的时钟差。

    读 ``Date`` 头，HTTP 允许的三种日期格式（RFC 1123、RFC 850、asctime）都能解析。没有这个头或解析失败时
    返回 None，由调用方决定怎么办——不拿本机时间冒充服务器时间，否则算出的时钟差恒为 0 且无从察觉。

    use_last_modified=True 时，``Date`` 缺失或解析失败再读 ``Last-Modified``。它是资源的修改时间，不是服务器
    当前时间：只对每几秒刷新一次的资源（如直播 m3u8）才接近当前时间，普通文件可能差出几年，所以默认不用。
    """
    get = getattr(response_headers, "get", None)
    if get is None:
        return None
    names = ("Date", "Last-Modified") if use_last_modified else ("Date",)
    for name in names:
        value = get(name)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            continue
        # HTTP 日期一律是 GMT；asctime 格式与 “-0000” 解析出来不带时区，按 UTC 处理
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()
    return None


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


def is_plain_site_path(value: object) -> bool:
    """Return whether a value is a same-site path with no query or fragment.

    For paths a route is registered at as well as redirected to, such as the login page in the
    settings: `is_same_site_path` plus nothing after the path.
    """
    return is_same_site_path(value) and "?" not in str(value) and "#" not in str(value)
