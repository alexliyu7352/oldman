"""Private Sanic integration for publishing the configured media storage."""

from __future__ import annotations

import mimetypes
from email.utils import format_datetime
from typing import Any, cast

from sanic import Request
from sanic.exceptions import SanicException
from sanic.response import ResponseStream

from oldman.storage.backends.filesystem import FileSystemStorage
from oldman.storage.base import Storage
from oldman.storage.exceptions import InvalidStorageName, StorageFileNotFound
from oldman.storage.streams import FileInfo

_BINARY_CONTENT_TYPE = "application/octet-stream"


def _response_headers(info: FileInfo) -> dict[str, str]:
    return {
        "Content-Length": str(info.size),
        "Last-Modified": format_datetime(info.modified_at, usegmt=True),
    }


def _content_type(name: str) -> str:
    guessed, _encoding = mimetypes.guess_type(name)
    return guessed or _BINARY_CONTENT_TYPE


async def _empty_stream(response: Any) -> None:
    del response


def install_media(app: object, *, storage: Storage, url: str) -> None:
    """Install one read-only media publication route on a Sanic application."""
    if not url:
        return

    sanic_app = cast(Any, app)
    if sanic_app.router.find_route_by_view_name("media") is not None:
        raise SanicException("media route name is already registered")
    if isinstance(storage, FileSystemStorage):
        sanic_app.static(
            url,
            storage.location,
            name="media",
            use_content_range=True,
            stream_large_files=True,
        )
        return

    async def publish(request: Request, name: str) -> ResponseStream:
        try:
            if request.method == "HEAD":
                info = await storage.stat(name)
                return ResponseStream(
                    _empty_stream,
                    headers=_response_headers(info),
                    content_type=_content_type(name),
                )

            stored = await storage.open(name)
        except (InvalidStorageName, StorageFileNotFound):
            return ResponseStream(_empty_stream, status=404)

        async def stream(response: Any) -> None:
            async with stored:
                async for chunk in stored:
                    await response.write(chunk)

        return ResponseStream(
            stream,
            headers=_response_headers(stored.info),
            content_type=_content_type(name),
        )

    route = f"{url.rstrip('/')}/<name:path>"
    sanic_app.add_route(
        publish,
        route,
        methods={"GET", "HEAD"},
        name="media",
    )


__all__ = ("install_media",)
