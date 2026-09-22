"""Same-site redirect targets for login and password flows."""

from __future__ import annotations

from urllib.parse import urlparse


def safe_next_url(raw_next_url: object, fallback: str = "/") -> str:
    """Return `raw_next_url` when it is a plain same-site path, otherwise `fallback`.

    Rejected: schemes and hosts, protocol-relative `//host`, backslashes (browsers read `/\\host` as
    `//host`) and control characters. A Sanic query value may arrive as a list; its first item counts.
    """
    if isinstance(raw_next_url, list | tuple):
        raw_next_url = raw_next_url[0] if raw_next_url else None
    try:
        next_url = "" if raw_next_url is None else str(raw_next_url)
        next_url.encode("utf-8")
    except Exception:
        return fallback
    if not next_url.startswith("/") or next_url.startswith("//"):
        return fallback
    if any(character == "\\" or ord(character) < 0x20 or ord(character) == 0x7F for character in next_url):
        return fallback
    try:
        parsed = urlparse(next_url)
    except ValueError:
        return fallback
    if parsed.scheme or parsed.netloc:
        return fallback
    return next_url


__all__ = ["safe_next_url"]
