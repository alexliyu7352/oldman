"""Build public static URLs from configured prefixes and logical asset paths."""

from __future__ import annotations

from pathlib import PurePosixPath

OLDMAN_STATIC_NAMESPACE = "oldman"


def static_asset_url(static_url: str, asset_path: str) -> str:
    """Join one validated logical asset path to the configured public prefix."""
    normalized_path = PurePosixPath(asset_path.strip().lstrip("/"))
    if (
        not normalized_path.parts
        or ".." in normalized_path.parts
        or "\\" in asset_path
    ):
        raise ValueError(f"invalid static asset path: {asset_path!r}")
    normalized_url = static_url.strip().rstrip("/")
    if not normalized_url:
        raise ValueError("settings.web.static.url must not be blank")
    return f"{normalized_url}/{normalized_path.as_posix()}"


def oldman_asset_path(asset_path: str) -> str:
    """Return a logical path inside Oldman's collected static namespace."""
    normalized_path = PurePosixPath(asset_path.strip().lstrip("/"))
    if (
        not normalized_path.parts
        or ".." in normalized_path.parts
        or "\\" in asset_path
    ):
        raise ValueError(f"invalid Oldman static asset path: {asset_path!r}")
    return f"{OLDMAN_STATIC_NAMESPACE}/{normalized_path.as_posix()}"


def oldman_asset_url(static_url: str, asset_path: str) -> str:
    """Build the public URL for one collected Oldman framework asset."""
    return static_asset_url(static_url, oldman_asset_path(asset_path))


__all__ = [
    "OLDMAN_STATIC_NAMESPACE",
    "oldman_asset_path",
    "oldman_asset_url",
    "static_asset_url",
]
