"""Request and streaming-response translation lifecycle tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sanic import Sanic
from sanic.response import BaseHTTPResponse, ResponseStream, text

from oldman.i18n import (
    bind_translations,
    gettext,
    reset_translations,
)
from oldman.web.middlewares.i18n import cleanup_i18n, install_i18n


class _Catalog:
    """Small catalog used to expose the currently bound translation."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def gettext(self, message: str) -> str:
        """Translate one singular message."""
        return f"{self.prefix}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        """Translate one plural message."""
        return f"{self.prefix}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        """Translate one contextual message."""
        return f"{self.prefix}:{context}:{message}"


def _request_with_catalog(catalog: _Catalog) -> SimpleNamespace:
    """Create one request context with the same binding as request middleware."""
    request = SimpleNamespace(ctx=SimpleNamespace(translations=catalog))
    request.ctx._oldman_i18n_catalog_token = bind_translations(catalog)
    return request


class OldmanI18nStreamingTest(unittest.IsolatedAsyncioTestCase):
    """Keep ContextVar state correct across every response lifetime."""

    async def test_normal_response_restores_the_previous_catalog(self) -> None:
        """A non-stream response must release its request binding immediately."""
        outer = bind_translations(_Catalog("outer"))
        try:
            request = _request_with_catalog(_Catalog("request"))
            self.assertEqual(gettext("Save"), "request:Save")

            response = text("ok")
            result = await cleanup_i18n(
                cast(Any, request),
                cast(Any, response),
            )

            self.assertIsNone(result)
            self.assertEqual(gettext("Save"), "outer:Save")
            self.assertFalse(
                hasattr(request.ctx, "_oldman_i18n_catalog_token")
            )
        finally:
            reset_translations(outer)

    async def test_stream_binds_catalog_during_execution_and_restores_afterward(
        self,
    ) -> None:
        """A successful stream must see request translations after middleware cleanup."""
        observed: list[str] = []

        async def stream(
            _response: BaseHTTPResponse | ResponseStream,
        ) -> None:
            observed.append(gettext("Save"))
            await asyncio.sleep(0)
            observed.append(gettext("Save"))

        outer = bind_translations(_Catalog("outer"))
        try:
            request = _request_with_catalog(_Catalog("stream"))
            response = ResponseStream(stream)

            await cleanup_i18n(cast(Any, request), cast(Any, response))
            self.assertEqual(gettext("Save"), "outer:Save")
            await response.streaming_fn(response)

            self.assertEqual(observed, ["stream:Save", "stream:Save"])
            self.assertEqual(gettext("Save"), "outer:Save")
        finally:
            reset_translations(outer)

    async def test_stream_exception_releases_catalog(self) -> None:
        """An exception from the original stream cannot leak its request binding."""

        async def stream(
            _response: BaseHTTPResponse | ResponseStream,
        ) -> None:
            self.assertEqual(gettext("Save"), "stream:Save")
            raise RuntimeError("stream failed")

        outer = bind_translations(_Catalog("outer"))
        try:
            request = _request_with_catalog(_Catalog("stream"))
            response = ResponseStream(stream)
            await cleanup_i18n(cast(Any, request), cast(Any, response))

            with self.assertRaisesRegex(RuntimeError, "stream failed"):
                await response.streaming_fn(response)

            self.assertEqual(gettext("Save"), "outer:Save")
        finally:
            reset_translations(outer)

    async def test_stream_cancellation_releases_catalog(self) -> None:
        """Task cancellation must execute the stream wrapper's cleanup."""
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def stream(
            _response: BaseHTTPResponse | ResponseStream,
        ) -> None:
            try:
                self.assertEqual(gettext("Save"), "stream:Save")
                started.set()
                await asyncio.Future()
            finally:
                cancelled.set()

        request = _request_with_catalog(_Catalog("stream"))
        response = ResponseStream(stream)
        await cleanup_i18n(cast(Any, request), cast(Any, response))
        task = asyncio.create_task(response.streaming_fn(response))
        await started.wait()
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertTrue(cancelled.is_set())
        self.assertEqual(gettext("Save"), "Save")

    async def test_real_sanic_stream_keeps_catalog_until_body_is_written(self) -> None:
        """The registered Sanic middleware path must preserve stream translations."""
        app = Sanic(f"oldman-i18n-stream-{id(self)}")
        catalog = _Catalog("stream")
        service = SimpleNamespace(
            use_i18n_path=False,
            get_locale=lambda request, auto_detect=True: "en",
            get_translations=lambda language: catalog,
        )

        @app.get("/stream")
        async def stream_view(_request: Any) -> ResponseStream:
            async def write(
                response: BaseHTTPResponse | ResponseStream,
            ) -> None:
                await cast(ResponseStream, response).write(gettext("Save"))

            return ResponseStream(write, content_type="text/plain")

        app.register_middleware(install_i18n, "request")
        app.register_middleware(cast(Any, cleanup_i18n), "response")

        with patch("oldman.web.middlewares.i18n.translation", service):
            _request, response = await app.asgi_client.get("/stream")

        self.assertEqual(response.body, b"stream:Save")
        self.assertEqual(gettext("Save"), "Save")

    async def test_real_sanic_response_continues_to_later_middleware(self) -> None:
        """i18n cleanup must not stop Session, Message, or other response middleware."""
        app = Sanic(f"oldman-i18n-response-chain-{id(self)}")
        catalog = _Catalog("request")
        calls: list[str] = []
        service = SimpleNamespace(
            use_i18n_path=False,
            get_locale=lambda request, auto_detect=True: "en",
            get_translations=lambda language: catalog,
        )

        @app.get("/")
        async def view(_request: Any):
            return text("ok")

        async def later_middleware(_request: Any, _response: Any) -> None:
            calls.append("later")

        app.register_middleware(later_middleware, "response")
        app.register_middleware(install_i18n, "request")
        app.register_middleware(cast(Any, cleanup_i18n), "response")

        with patch("oldman.web.middlewares.i18n.translation", service):
            await app.asgi_client.get("/")

        self.assertEqual(calls, ["later"])


if __name__ == "__main__":
    unittest.main()
