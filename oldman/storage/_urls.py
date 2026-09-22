"""The browser URL of a stored media name, derived from the published media route."""

from __future__ import annotations

from urllib.parse import quote

import oldman.conf as conf


def media_url(name: str, *, quote_name: bool = True) -> str:
    """The URL the browser can request for one name stored in the media storage.

    It joins `web.media.url` with the stored name, so a project that moves the media prefix does
    not have to hunt for hard-written "/media/" strings. An empty name, or a configuration with no
    media route (`web.media.url` empty), gives "". It does not check that the file exists, and it
    is not an authenticated download URL: private attachments belong in their own storage alias
    behind their own view.

    Names already carrying a scheme (`https://...`, `data:...`) are returned unchanged, so a model
    column holding a remote address keeps working.
    """
    if not name:
        return ""
    if "://" in name or name.startswith("data:"):
        return name
    base = str(getattr(getattr(getattr(conf.settings, "web", None), "media", None), "url", "") or "")
    if not base:
        return ""
    relative = name.lstrip("/")
    return f"{base.rstrip('/')}/{quote(relative, safe='/') if quote_name else relative}"


__all__ = ["media_url"]
