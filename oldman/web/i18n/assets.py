"""Resolve optional language flags through the collected static-file root."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final
from urllib.parse import urlparse

from oldman.web.staticfiles import oldman_asset_path, static_asset_url

BUILTIN_FLAG_ASSETS: Final = MappingProxyType(
    {
        "cn": oldman_asset_path("images/flags/cn.svg"),
        "tw": oldman_asset_path("images/flags/tw.svg"),
        "us": oldman_asset_path("images/flags/us.svg"),
    }
)


def direct_flag_url(value: str, *, static_url: str) -> str:
    """Resolve one language flag against the configured public static prefix."""
    normalized = value.strip()
    if not normalized:
        return ""

    built_in = BUILTIN_FLAG_ASSETS.get(normalized.casefold())
    if built_in is not None:
        return static_asset_url(static_url, built_in)
    if normalized.startswith("/") or urlparse(normalized).scheme:
        return normalized
    return static_asset_url(static_url, normalized)


__all__ = ["BUILTIN_FLAG_ASSETS", "direct_flag_url"]
