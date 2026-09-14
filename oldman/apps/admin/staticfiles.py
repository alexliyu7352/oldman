"""Built-in Admin static bundle registration."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from oldman.web.staticfiles import StaticBundle, StaticBundleRegistry
from oldman.web.staticfiles.urls import oldman_asset_path, static_asset_url

ADMIN_BUNDLE_NAME = "oldman:admin"
ADMIN_ENTRY_PATH = "src/main.ts"
ADMIN_STATIC_PATH = oldman_asset_path("admin")


def register_admin_static_bundle(
    registry: StaticBundleRegistry,
    *,
    static_root: str | Path | None = None,
    static_url: str = "",
    dev_mode: bool = False,
    dev_server_url: str = "",
) -> StaticBundle:
    """Register Admin against collected output or its explicit dev server."""
    collected_root = None if static_root is None or (isinstance(static_root, str) and not static_root.strip()) else Path(static_root)
    normalized_static_url = static_url.strip()
    normalized_dev_server_url = dev_server_url.strip().rstrip("/")
    if dev_mode:
        _validate_dev_server_url(normalized_dev_server_url)
    elif collected_root is None or not normalized_static_url:
        raise RuntimeError(
            "Oldman Admin production assets require settings.web.static.root and settings.web.static.url; run `oldman <service> static collect` before startup"
        )

    manifest_root = collected_root if collected_root is not None else Path()
    bundle = StaticBundle(
        name=ADMIN_BUNDLE_NAME,
        entry_path=ADMIN_ENTRY_PATH,
        manifest_path=manifest_root / ADMIN_STATIC_PATH / ".vite" / "manifest.json",
        static_url=(static_asset_url(normalized_static_url, ADMIN_STATIC_PATH) if normalized_static_url else ""),
        dev_server_url=normalized_dev_server_url,
        dev_mode=dev_mode,
    )
    registry.register(bundle)
    return bundle


def _validate_dev_server_url(dev_server_url: str) -> None:
    """Require an absolute HTTP(S) URL when Admin uses the Vite dev server."""
    try:
        parsed_url = urlsplit(dev_server_url)
        hostname = parsed_url.hostname
        port = parsed_url.port
    except ValueError:
        parsed_url = None
        hostname = None
        port = None
    if (
        parsed_url is None
        or parsed_url.scheme not in {"http", "https"}
        or not hostname
        or port == 0
        or any(character.isspace() for character in parsed_url.netloc)
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise RuntimeError("Oldman Admin development assets require an absolute HTTP(S) dev_server_url without a query or fragment")


__all__ = [
    "ADMIN_BUNDLE_NAME",
    "ADMIN_ENTRY_PATH",
    "ADMIN_STATIC_PATH",
    "register_admin_static_bundle",
]
