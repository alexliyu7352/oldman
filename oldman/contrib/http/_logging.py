"""HTTP 日志中使用的最小脱敏工具。"""

from urllib.parse import urlsplit, urlunsplit


def _safe_network_location(value: str) -> tuple[str, str] | None:
    """解析 URL 并返回不含用户凭据的 scheme 和 network location。"""

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if not parsed.scheme or hostname is None:
        return None

    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    network_location = rendered_host if port is None else f"{rendered_host}:{port}"
    return parsed.scheme, network_location


def redact_url(value: str) -> str:
    """保留 URL 的定位信息，同时删除凭据、查询参数和 fragment。"""

    network = _safe_network_location(value)
    if network is None:
        return "<invalid-url>"
    parsed = urlsplit(value)
    scheme, network_location = network
    return urlunsplit((scheme, network_location, parsed.path, "", ""))


def redact_proxy(value: str | None) -> str:
    """只保留代理的 scheme、hostname 和 port。"""

    if value is None:
        return "<none>"
    network = _safe_network_location(value)
    if network is None:
        return "<invalid-proxy>"
    scheme, network_location = network
    return urlunsplit((scheme, network_location, "", "", ""))
