"""Request lifecycle integration for Web translations."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, cast

from sanic.response import BaseHTTPResponse, ResponseStream

from oldman.i18n.translations import (
    TranslationCatalog,
    bind_translations,
    reset_translations,
)
from oldman.web.i18n.translation import translation
from oldman.web.request import Request
from oldman.web.response import Response

_CATALOG_TOKEN = "_oldman_i18n_catalog_token"

type StreamingFunction = Callable[
    [BaseHTTPResponse | ResponseStream],
    Coroutine[Any, Any, None],
]


def install_i18n(request: Request) -> None:
    """Resolve and bind one request catalog without mutating the Jinja environment."""
    locale = translation.get_locale(
        request,
        auto_detect=not translation.use_i18n_path,
    )
    catalog = translation.get_translations(locale)
    request.ctx.locale = locale
    request.ctx.translations = catalog
    setattr(
        request.ctx,
        _CATALOG_TOKEN,
        bind_translations(cast(TranslationCatalog, catalog)),
    )


async def cleanup_i18n(request: Request, response: Response) -> None:
    """Restore the handler context and preserve it only while a stream executes."""
    token = getattr(request.ctx, _CATALOG_TOKEN, None)
    if token is None:
        return

    try:
        if isinstance(response, ResponseStream):
            catalog = getattr(request.ctx, "translations", None)
            if catalog is not None:
                response.streaming_fn = _stream_with_translations(
                    response.streaming_fn,
                    cast(TranslationCatalog, catalog),
                )
    finally:
        reset_translations(token)
        delattr(request.ctx, _CATALOG_TOKEN)


def _stream_with_translations(
    streaming_fn: StreamingFunction,
    catalog: TranslationCatalog,
) -> StreamingFunction:
    """Bind one request catalog only for the lifetime of its streaming callback."""

    async def run_stream(
        response: BaseHTTPResponse | ResponseStream,
    ) -> None:
        token = bind_translations(catalog)
        try:
            await streaming_fn(response)
        finally:
            reset_translations(token)

    return run_stream


__all__ = ["cleanup_i18n", "install_i18n"]
