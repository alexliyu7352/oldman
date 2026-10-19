"""Focused behavior tests for the migrated stream Proxy package."""

from __future__ import annotations

import asyncio
import os
import socket
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

from sanic import HTTPResponse, Request, Sanic, text
from sanic.compat import Header

import oldman.conf as conf
from oldman.cache import MemoryCache, redis_cache
from oldman.contrib.http import ClientType, HttpHeaders, HttpMethod, MultiHttpClient
from oldman.contrib.proxy.base import BaseStreamProxy, _sanic_response_headers
from oldman.contrib.proxy.encrypt import EncryptMixStreamProxy, EncryptStreamProxy
from oldman.contrib.proxy.simple import SimpleStreamProxy
from oldman.tasks.simple import BackgroundTaskManager
from tests.raw_http_origin import RawOrigin, chunk_frame, requested_range, response_head

_PROXY_FREE_ENVIRONMENT = {
    "HTTP_PROXY": "",
    "HTTPS_PROXY": "",
    "ALL_PROXY": "",
    "http_proxy": "",
    "https_proxy": "",
    "all_proxy": "",
    "NO_PROXY": "",
    "no_proxy": "",
}


def _settings(*, connect_timeout: int = 5, read_timeout: int = 10, debug: bool = False) -> SimpleNamespace:
    """Build the configured Settings fields consumed by Proxy construction."""

    return SimpleNamespace(
        core=SimpleNamespace(app_name="oldman", namespace="svc", debug=debug),
        proxy=SimpleNamespace(connect_timeout=connect_timeout, read_timeout=read_timeout),
        web=SimpleNamespace(
            security=SimpleNamespace(secret_key="proxy-test-root-secret-0123456789abcdef"),
        ),
        http_client=SimpleNamespace(max_connections=10, user_agent="oldman-proxy-test"),
    )


class _AsyncLock:
    """Minimal Redis lock context used by real-URL tests."""

    async def __aenter__(self) -> _AsyncLock:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _RedisConnection:
    """Record the Redis operations used by one uncached real-URL lookup."""

    def __init__(self) -> None:
        self.get = AsyncMock(side_effect=[None, None])
        self.set = AsyncMock()
        self.lock = Mock(return_value=_AsyncLock())


class _InfiniteOrigin:
    """Serve an endless chunked body and expose when the peer disconnects."""

    def __init__(self) -> None:
        self.closed = asyncio.Event()
        self.chunks_sent = 0

    async def _write_chunks(self, writer: asyncio.StreamWriter) -> None:
        """Continuously write framed payloads while the peer keeps the socket open."""

        payload = b"x" * (64 * 1024)
        framed = f"{len(payload):x}\r\n".encode() + payload + b"\r\n"
        while True:
            writer.write(framed)
            await writer.drain()
            self.chunks_sent += 1
            await asyncio.sleep(0.002)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Write until the HTTP client, or a forward proxy, closes the socket."""

        tasks: list[asyncio.Task[Any]] = []
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: video/mp2t\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
            await writer.drain()
            tasks = [
                asyncio.create_task(reader.read()),
                asyncio.create_task(self._write_chunks(writer)),
            ]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.closed.set()
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


class _ForwardProxy:
    """Minimal real HTTP forward proxy used to observe downstream cancellation."""

    def __init__(self) -> None:
        self.requests = 0

    @staticmethod
    async def _copy_response(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Copy the upstream response until either side closes."""

        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Forward one absolute-form GET and close upstream when its client leaves."""

        upstream_writer: asyncio.StreamWriter | None = None
        tasks: list[asyncio.Task[Any]] = []
        try:
            request_head = await reader.readuntil(b"\r\n\r\n")
            lines = request_head.split(b"\r\n")
            method, raw_target, version = lines[0].decode("ascii").split(" ", 2)
            target = urlsplit(raw_target)
            if target.hostname is None:
                raise ValueError("forward proxy requires an absolute request target")

            upstream_reader, upstream_writer = await asyncio.open_connection(
                target.hostname,
                target.port or (443 if target.scheme == "https" else 80),
            )
            path = target.path or "/"
            if target.query:
                path = f"{path}?{target.query}"
            forwarded_headers = [line for line in lines[1:] if line and not line.lower().startswith((b"connection:", b"proxy-connection:"))]
            upstream_writer.write(b"\r\n".join([f"{method} {path} {version}".encode("ascii"), *forwarded_headers, b"Connection: close", b"", b""]))
            await upstream_writer.drain()
            self.requests += 1

            tasks = [
                asyncio.create_task(reader.read()),
                asyncio.create_task(self._copy_response(upstream_reader, writer)),
            ]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if upstream_writer is not None:
                upstream_writer.close()
                with suppress(Exception):
                    await upstream_writer.wait_closed()
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


class ProxyConfigurationTest(unittest.IsolatedAsyncioTestCase):
    """Verify Settings, Redis and HTTP-client construction boundaries."""

    def test_package_import_does_not_require_configured_settings(self) -> None:
        """Importing Proxy is safe, while constructing one still requires Settings."""

        with patch.dict(conf.__dict__, {}, clear=False):
            conf.__dict__.pop("settings", None)
            with self.assertRaisesRegex(RuntimeError, "settings are not configured"):
                BaseStreamProxy()

    def test_constructor_reads_typed_proxy_and_web_settings(self) -> None:
        """The removed flat and legacy Settings fields are not consulted."""

        with patch.dict(conf.__dict__, {"settings": _settings(connect_timeout=7, read_timeout=13, debug=True)}):
            proxy = BaseStreamProxy("configured")

        self.assertEqual(7, proxy.connect_timeout)
        self.assertEqual(13, proxy.read_timeout)
        self.assertTrue(proxy._debug)
        self.assertIsInstance(proxy._cache.memory, MemoryCache)
        self.assertIs(proxy._cache.redis, redis_cache)

    async def test_decoded_and_binary_redis_connections_use_default_registry(self) -> None:
        """Native Proxy records retain the source DEFAULT Redis database semantics."""

        decoded = object()
        binary = object()
        registry = Mock()
        registry.async_get_conn = AsyncMock(return_value=decoded)
        registry.async_get_bin_conn = AsyncMock(return_value=binary)
        proxy = object.__new__(BaseStreamProxy)

        with patch("oldman.contrib.proxy.base.redis_client", registry):
            self.assertIs(decoded, await proxy._redis_connection())
            self.assertIs(binary, await proxy._redis_binary_connection())

        registry.async_get_conn.assert_awaited_once_with()
        registry.async_get_bin_conn.assert_awaited_once_with()
        registry.using.assert_not_called()

    async def test_http_client_initialization_is_single_and_disables_tls_verification(self) -> None:
        """Concurrent callers share one client and Proxy applies its TLS policy explicitly."""

        clients: list[Any] = []

        class FakeHttpClient:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs
                self.init_calls = 0
                clients.append(self)

            async def init_client(self) -> None:
                self.init_calls += 1
                await asyncio.sleep(0)

        with (
            patch.dict(conf.__dict__, {"settings": _settings()}),
            patch("oldman.contrib.proxy.base.MultiHttpClient", FakeHttpClient),
        ):
            proxy = BaseStreamProxy("clients")
            first, second = await asyncio.gather(proxy.get_client(), proxy.get_client())

        self.assertIs(first, second)
        self.assertEqual(1, len(clients))
        self.assertEqual(1, clients[0].init_calls)
        self.assertIs(False, clients[0].kwargs["verify"])

    async def test_proxy_subclass_can_enable_tls_verification(self) -> None:
        """A specialized Proxy can opt back into certificate verification."""

        class VerifiedProxy(BaseStreamProxy):
            VERIFY_TLS = True

        client = AsyncMock()
        client.init_client = AsyncMock()
        factory = Mock(return_value=client)
        with (
            patch.dict(conf.__dict__, {"settings": _settings()}),
            patch("oldman.contrib.proxy.base.MultiHttpClient", factory),
        ):
            proxy = VerifiedProxy("verified")
            await proxy.get_client()

        self.assertIs(True, factory.call_args.kwargs["verify"])


class ProxyResponseBoundaryTest(unittest.IsolatedAsyncioTestCase):
    """Verify conversion between unified HTTP responses and Sanic responses."""

    def test_sanic_headers_preserve_duplicates_and_remove_transport_headers(self) -> None:
        """Header conversion keeps repeated fields without forwarding connection metadata."""

        source = HttpHeaders(
            [
                ("Set-Cookie", "first=1"),
                ("Set-Cookie", "second=2"),
                ("Content-Type", "video/mp2t"),
                ("Content-Length", "100"),
                ("Transfer-Encoding", "chunked"),
                ("Connection", "keep-alive, X-Upstream-Hop"),
                ("X-Upstream-Hop", "private"),
            ]
        )

        streaming = _sanic_response_headers(source)
        rewritten = _sanic_response_headers(source, body_changed=True)

        self.assertIsInstance(streaming, Header)
        self.assertEqual(["first=1", "second=2"], streaming.getall("set-cookie"))
        self.assertEqual("100", streaming["content-length"])
        self.assertNotIn("transfer-encoding", streaming)
        self.assertNotIn("connection", streaming)
        self.assertNotIn("x-upstream-hop", streaming)
        self.assertNotIn("content-length", rewritten)

    async def test_stream_response_uses_sanic_headers_without_reading_metadata_as_mutable(self) -> None:
        """The stream bridge forwards duplicate headers and writes the body once."""

        class Upstream:
            status_code = 200
            url = "https://origin.test/live.ts"
            response_headers = HttpHeaders(
                [
                    ("Content-Type", "video/mp2t"),
                    ("Set-Cookie", "first=1"),
                    ("Set-Cookie", "second=2"),
                    ("Transfer-Encoding", "chunked"),
                ]
            )

            async def aiter_bytes(self, chunk_size: int):
                self.chunk_size = chunk_size
                yield b"stream-body"

        writer = SimpleNamespace(send=AsyncMock(), eof=AsyncMock())
        request = SimpleNamespace(respond=AsyncMock(return_value=writer))
        proxy = object.__new__(BaseStreamProxy)

        await proxy.stream_response(request, Upstream())  # type: ignore[arg-type]

        kwargs = request.respond.await_args.kwargs
        self.assertEqual("video/mp2t", kwargs["content_type"])
        self.assertEqual(["first=1", "second=2"], kwargs["headers"].getall("set-cookie"))
        self.assertNotIn("transfer-encoding", kwargs["headers"])
        writer.send.assert_awaited_once_with(b"stream-body")
        writer.eof.assert_awaited_once_with()


class ProxyRealUrlTest(unittest.IsolatedAsyncioTestCase):
    """Verify the header-only real-URL lookup paths."""

    def setUp(self) -> None:
        settings_patch = patch.dict(conf.__dict__, {"settings": _settings()})
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.proxy = BaseStreamProxy("redirect")
        self.redis = _RedisConnection()
        self.proxy._redis_connection = AsyncMock(return_value=self.redis)  # type: ignore[method-assign]

    async def test_head_redirect_uses_head_status_without_opening_get_stream(self) -> None:
        """A successful redirected HEAD no longer reads an unassigned status variable."""

        client = SimpleNamespace(
            request=AsyncMock(return_value=SimpleNamespace(url="https://cdn.test/live.ts", status_code=200)),
            stream=Mock(),
        )
        self.proxy.get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

        result = await self.proxy.get_real_url(
            Mock(),
            "https://origin.test/live.ts",
            60,
            http_method=HttpMethod.HEAD,
        )

        self.assertEqual(("https://cdn.test/live.ts", None), result)
        client.stream.assert_not_called()
        self.redis.set.assert_awaited_once()

    async def test_every_lookup_lock_lives_under_the_service_namespace(self) -> None:
        """G4-6: three lock names skipped core.namespace, so two services sharing a Redis waited on each other's locks."""

        class Taken(Exception):
            """Stops each lookup at its lock; only the lock's name is of interest here."""

        self.redis.get = AsyncMock(return_value=None)
        self.redis.lock = Mock(side_effect=Taken)
        lookups = (
            lambda: self.proxy.fetch_remote_manifest(Mock(), "channel-1", "https://origin.test/live.m3u8", ttl=0),
            lambda: self.proxy.get_real_url(Mock(), "https://origin.test/live.ts", 60, http_method=HttpMethod.HEAD),
            lambda: self.proxy.get_real_url_with_sub(Mock(), "https://origin.test/live.m3u8", 60),
        )
        for lookup in lookups:
            with suppress(Taken):
                await lookup()

        names = [call.args[0] for call in self.redis.lock.call_args_list]
        self.assertEqual(3, len(set(names)), names)
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(name.startswith("svc:lock:"), name)

    async def test_failed_head_falls_back_to_get_headers_and_closes_without_body_read(self) -> None:
        """The GET fallback captures metadata then immediately exits its stream context."""

        state = SimpleNamespace(entered=False, exited=False, body_read=False)
        stream_response = SimpleNamespace(url="https://cdn.test/live.ts", status_code=200)

        @asynccontextmanager
        async def stream(*args: Any, **kwargs: Any):
            state.entered = True
            try:
                yield stream_response
            finally:
                state.exited = True

        client = SimpleNamespace(
            request=AsyncMock(side_effect=TimeoutError("HEAD unavailable")),
            stream=Mock(side_effect=stream),
        )
        self.proxy.get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

        result = await self.proxy.get_real_url(
            Mock(),
            "https://origin.test/live.ts",
            60,
            proxy_url="http://proxy.test:8080",
            http_method=HttpMethod.HEAD,
        )

        self.assertEqual(("https://cdn.test/live.ts", None), result)
        self.assertTrue(state.entered)
        self.assertTrue(state.exited)
        self.assertFalse(state.body_read)
        self.proxy.get_client.assert_awaited_once_with(None, "http://proxy.test:8080")
        self.assertEqual(HttpMethod.GET, client.stream.call_args.args[0])

    async def test_head_error_status_is_returned_without_caching(self) -> None:
        """A redirected HEAD with an upstream error keeps the existing error contract."""

        client = SimpleNamespace(
            request=AsyncMock(return_value=SimpleNamespace(url="https://cdn.test/live.ts", status_code=403)),
            stream=Mock(),
        )
        self.proxy.get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]

        result = await self.proxy.get_real_url(
            Mock(),
            "https://origin.test/live.ts",
            60,
            http_method=HttpMethod.HEAD,
        )

        self.assertEqual((None, "Upstream returned error status code: 403"), result)
        client.stream.assert_not_called()
        self.redis.set.assert_not_awaited()


class ProxyHeaderOnlyIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Prove header-only stream exit closes direct and forward-proxied upstreams."""

    async def test_real_proxy_head_fallback_closes_infinite_get_without_body_read(self) -> None:
        """The actual get_real_url path returns metadata and terminates its GET origin."""

        origin = _InfiniteOrigin()
        origin_server = await asyncio.start_server(origin.handle, "127.0.0.1", 0)
        origin_socket = (origin_server.sockets or [])[0]
        origin_port = int(origin_socket.getsockname()[1])
        play_url = f"http://127.0.0.1:{origin_port}/live.ts"
        client: MultiHttpClient | None = None
        try:
            with (
                patch.dict(conf.__dict__, {"settings": _settings()}),
                patch.dict(os.environ, _PROXY_FREE_ENVIRONMENT),
            ):
                proxy = BaseStreamProxy("real-fallback")
                redis = _RedisConnection()
                proxy._redis_connection = AsyncMock(return_value=redis)  # type: ignore[method-assign]
                client = await proxy.get_client()
                with patch.object(client, "request", AsyncMock(side_effect=TimeoutError("HEAD unavailable"))):
                    result = await proxy.get_real_url(Mock(), play_url, 60, http_method=HttpMethod.HEAD)

                self.assertEqual((play_url, None), result)
                await asyncio.wait_for(origin.closed.wait(), timeout=2)
                self.assertGreater(origin.chunks_sent, 0)
                redis.set.assert_awaited_once()
        finally:
            if client is not None:
                await client.close_client()
            origin_server.close()
            await origin_server.wait_closed()

    async def _exercise_backend(self, client_type: ClientType, *, use_forward_proxy: bool) -> None:
        """Open an infinite response, read no body, and observe the origin disconnect."""

        origin = _InfiniteOrigin()
        origin_server = await asyncio.start_server(origin.handle, "127.0.0.1", 0)
        origin_socket = (origin_server.sockets or [])[0]
        origin_port = int(origin_socket.getsockname()[1])

        forward = _ForwardProxy()
        forward_server: asyncio.Server | None = None
        proxy_url: str | None = None
        if use_forward_proxy:
            forward_server = await asyncio.start_server(forward.handle, "127.0.0.1", 0)
            forward_socket = (forward_server.sockets or [])[0]
            forward_port = int(forward_socket.getsockname()[1])
            proxy_url = f"http://127.0.0.1:{forward_port}"

        client: MultiHttpClient | None = None
        try:
            with (
                patch.dict(conf.__dict__, {"settings": _settings()}),
                patch.dict(os.environ, _PROXY_FREE_ENVIRONMENT),
            ):
                client = MultiHttpClient(
                    client_type=client_type,
                    proxy_url=proxy_url,
                    retry_count=0,
                    connect_timeout=2,
                    read_timeout=2,
                    max_connections=4,
                    user_agent="oldman-proxy-test",
                )
                await client.init_client()
                async with client.stream(
                    HttpMethod.GET,
                    f"http://127.0.0.1:{origin_port}/live.ts",
                    retries=0,
                ) as response:
                    self.assertEqual(200, response.status_code)
                    self.assertEqual("video/mp2t", response.headers["content-type"])

                await asyncio.wait_for(origin.closed.wait(), timeout=2)
                self.assertGreater(origin.chunks_sent, 0)
                if use_forward_proxy:
                    self.assertEqual(1, forward.requests)
        finally:
            if client is not None:
                await client.close_client()
            origin_server.close()
            await origin_server.wait_closed()
            if forward_server is not None:
                forward_server.close()
                await forward_server.wait_closed()

    async def test_all_http_backends_close_direct_infinite_stream_after_headers(self) -> None:
        """Every backend terminates a direct infinite origin without reading its body."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                await self._exercise_backend(client_type, use_forward_proxy=False)

    async def test_all_http_backends_close_forward_proxy_upstream_after_headers(self) -> None:
        """Every backend propagates header-only cancellation through a forward proxy."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                await self._exercise_backend(client_type, use_forward_proxy=True)


class ProxyDirectTcpIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the retained direct TCP streaming implementation against a local server."""

    async def test_chunked_origin_is_forwarded_to_sanic_writer(self) -> None:
        """The direct path removes HTTP chunk frames and completes the Sanic stream."""

        origin_finished = asyncio.Event()

        async def serve_chunked(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Return two finite HTTP chunks for the direct TCP Proxy path."""

            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: video/mp2t\r\n"
                    b"Transfer-Encoding: chunked\r\n"
                    b"Connection: close\r\n\r\n"
                    b"5\r\nhello\r\n"
                    b"5\r\nworld\r\n"
                    b"0\r\n\r\n"
                )
                await writer.drain()
            finally:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()
                origin_finished.set()

        server = await asyncio.start_server(serve_chunked, "127.0.0.1", 0)
        server_socket = (server.sockets or [])[0]
        port = int(server_socket.getsockname()[1])
        sanic_writer = SimpleNamespace(send=AsyncMock(), eof=AsyncMock(), headers=None)
        request = SimpleNamespace(headers={}, respond=AsyncMock(return_value=sanic_writer))

        try:
            with patch.dict(conf.__dict__, {"settings": _settings()}):
                proxy = BaseStreamProxy("direct")
            result = await proxy.get_ts_stream_direct(
                request,  # type: ignore[arg-type]
                f"http://127.0.0.1:{port}/live.ts",
            )
        finally:
            server.close()
            await server.wait_closed()

        self.assertIsNone(result)
        self.assertEqual([b"hello", b"world"], [item.args[0] for item in sanic_writer.send.await_args_list])
        sanic_writer.eof.assert_awaited_once_with()
        self.assertEqual("video/mp2t", request.respond.await_args.kwargs["content_type"])
        self.assertNotIn("transfer-encoding", sanic_writer.headers)
        self.assertNotIn("connection", sanic_writer.headers)
        await asyncio.wait_for(origin_finished.wait(), timeout=1)


_RELAY_PAYLOAD = bytes(range(256)) * 400


def _relay_origin(mode: str) -> RawOrigin:
    """Origin for relay tests.

    complete / missing / range answer every request the same way; zero sends headers and no body every
    time; cut and chunked_cut send part of the body on the first request and 503 afterwards.
    """

    def answer(attempt: int, headers: dict[str, str]) -> bytes:
        body = _RELAY_PAYLOAD
        media = {"Content-Type": "video/mp2t"}
        if mode == "complete":
            return response_head("200 OK", {**media, "Content-Length": len(body)}) + body
        if mode == "missing":
            return response_head("404 Not Found", {**media, "Content-Length": 4}) + b"gone"
        if mode == "range":
            interval = requested_range(headers, len(body))
            assert interval is not None
            start, end = interval
            return (
                response_head(
                    "206 Partial Content", {**media, "Content-Range": f"bytes {start}-{end}/{len(body)}", "Content-Length": end - start + 1}
                )
                + body[start : end + 1]
            )
        if mode == "zero":
            return response_head("200 OK", {**media, "Content-Length": len(body)})
        if attempt > 1:
            return response_head("503 Service Unavailable", {"Content-Length": 0})
        if mode == "cut":
            return response_head("200 OK", {**media, "Content-Length": len(body)}) + body[:30000]
        if mode == "chunked_cut":
            return response_head("200 OK", {**media, "Transfer-Encoding": "chunked"}) + chunk_frame(body[:30000])
        raise AssertionError(mode)

    return RawOrigin(answer)


@asynccontextmanager
async def _relay(
    origin: RawOrigin,
    *,
    handling: str = "raise",
    proxy_class: type[BaseStreamProxy] = BaseStreamProxy,
    user_agent: str | None = None,
    stream_options: dict[str, Any] | None = None,
    response_timeout: float | None = None,
    caught: list[tuple[str, str | None]] | None = None,
) -> AsyncIterator[tuple[str, int]]:
    """Serve a real Sanic app whose route relays the origin through the proxy; yield its address.

    `stream_options` go to get_ts_stream as keyword arguments (BaseStreamProxy only). `response_timeout` is Sanic's
    RESPONSE_TIMEOUT. `caught` collects (exception type, cause type) of every cancellation the route receives.

    `handling` is what the route does with a cancellation from the proxy, written the ways
    downstream projects write it: raise it, return None, or answer 404.
    """

    async with origin.serve() as origin_url:
        async with _relay_app(
            f"{origin_url}/segment.ts", handling, proxy_class, user_agent, stream_options or {}, response_timeout, caught
        ) as address:
            yield address


@asynccontextmanager
async def _relay_app(
    upstream: str,
    handling: str,
    proxy_class: type[BaseStreamProxy],
    user_agent: str | None,
    stream_options: dict[str, Any],
    response_timeout: float | None,
    caught: list[tuple[str, str | None]] | None,
) -> AsyncIterator[tuple[str, int]]:
    """The Sanic side of _relay."""

    with patch.dict(conf.__dict__, {"settings": _settings()}):
        proxy = proxy_class("relay")
    client = MultiHttpClient(proxy.get_client_type(user_agent), retry_count=1, retry_backoff_factor=0, connect_timeout=3, read_timeout=3)
    await client.init_client()

    async def get_client(*args: Any, **kwargs: Any) -> MultiHttpClient:
        """Hand every lookup the one client of this relay."""

        return client

    proxy.get_client = get_client  # type: ignore[method-assign]
    app = Sanic(f"oldman-relay-{time.time_ns()}")
    app.config.ACCESS_LOG = False
    # TOUCHUP rewrites class methods; several apps started in one process would interfere.
    app.config.TOUCHUP = False
    # A bare server: sanic-ext's CORS middleware expects route setup this test does not run.
    app.config.AUTO_EXTEND = False
    if response_timeout is not None:
        app.config.update({"RESPONSE_TIMEOUT": response_timeout})

    @app.get("/segment")
    async def segment(request: Request) -> HTTPResponse | None:
        """Relay the origin the way a downstream route does."""

        headers = {"Range": request.headers["range"]} if "range" in request.headers else None
        try:
            if isinstance(proxy, SimpleStreamProxy):
                return await proxy.proxy_sub_manifest_or_stream(request, upstream, None, client_type=user_agent)
            return await proxy.get_ts_stream(request, upstream, user_agent=user_agent, headers=headers, **stream_options)
        except asyncio.CancelledError as error:
            if caught is not None:
                caught.append((type(error).__name__, type(error.__cause__).__name__ if error.__cause__ is not None else None))
            if handling == "return_none":
                return None
            if handling == "return_404":
                return text("cancelled", status=404)
            raise

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = await app.create_server(sock=sock, access_log=False, return_asyncio_server=True)
    try:
        assert server is not None
        await server.startup()
        serving = server.start_serving()  # Sanic types these as maybe None: it returns None before the server exists.
        assert serving is not None
        await serving
        yield sock.getsockname()
    finally:
        if server is not None:
            server.close()
            closed = server.wait_closed()
            if closed is not None:
                await closed
        sock.close()
        Sanic.unregister_app(app)
        await client.close_client()


async def _fetch(address: tuple[str, int], extra_headers: str = "") -> tuple[int, dict[str, str], bytes]:
    """Read the relay's response over a raw socket: status, headers, and every body byte before the close."""

    reader, writer = await asyncio.open_connection(*address)
    try:
        writer.write(f"GET /segment HTTP/1.1\r\nHost: relay\r\nConnection: close\r\n{extra_headers}\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), 10)
    finally:
        writer.close()
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = {name.lower(): value for name, value in (line.split(": ", 1) for line in lines[1:])}
    return int(lines[0].split(" ")[1]), headers, body


def _dechunk(body: bytes) -> tuple[bytes, bool]:
    """Undo chunked framing; the flag says whether the terminating chunk arrived."""

    data, position = bytearray(), 0
    while position < len(body):
        line_end = body.index(b"\r\n", position)
        size = int(body[position:line_end], 16)
        if size == 0:
            return bytes(data), True
        data += body[line_end + 2 : line_end + 2 + size]
        position = line_end + 2 + size + 2
    return bytes(data), False


class ProxyRelayFailureTest(unittest.IsolatedAsyncioTestCase):
    """A real Sanic relay: what the requester gets when the upstream answers, or fails for good."""

    async def test_the_upstream_status_reaches_the_requester(self) -> None:
        """200, 404 and a 206 for the requester's own Range keep their status and body."""

        for mode, extra, expected_status, expected_body in (
            ("complete", "", 200, _RELAY_PAYLOAD),
            ("missing", "", 404, b"gone"),
            ("range", "Range: bytes=10-19\r\n", 206, _RELAY_PAYLOAD[10:20]),
        ):
            with self.subTest(mode=mode):
                async with _relay(_relay_origin(mode)) as address:
                    status, headers, body = await _fetch(address, extra)
                self.assertEqual(expected_status, status)
                self.assertEqual(expected_body, body)
                if mode == "range":
                    self.assertEqual(f"bytes 10-19/{len(_RELAY_PAYLOAD)}", headers["content-range"])

    async def test_a_failure_before_any_byte_is_answered_with_500(self) -> None:
        """The upstream sent headers but no body and cannot be resumed: not an empty 200."""

        for proxy_class in (BaseStreamProxy, SimpleStreamProxy):
            with self.subTest(proxy=proxy_class.__name__):
                async with _relay(_relay_origin("zero"), proxy_class=proxy_class) as address:
                    status, _, body = await _fetch(address)
                self.assertEqual(500, status)
                self.assertNotEqual(_RELAY_PAYLOAD[:1], body[:1])

    async def test_a_failure_after_part_of_the_body_drops_the_connection(self) -> None:
        """Half a body is never ended like a complete one, however the route handles the cancellation.

        The proxy closes the requester's connection itself, so a route that swallows the
        cancellation (common downstream) cannot turn the half body into a complete response.
        """

        for proxy_class in (BaseStreamProxy, SimpleStreamProxy):
            for user_agent in (None, "chrome"):
                for handling in ("raise", "return_none", "return_404"):
                    with self.subTest(proxy=proxy_class.__name__, user_agent=user_agent, handling=handling):
                        origin = _relay_origin("chunked_cut")
                        with self.assertLogs("default", level="WARNING") as logs:
                            async with _relay(origin, handling=handling, proxy_class=proxy_class, user_agent=user_agent) as address:
                                status, headers, body = await _fetch(address)
                        self.assertEqual(200, status)
                        self.assertEqual("chunked", headers.get("transfer-encoding"))
                        data, terminated = _dechunk(body)
                        self.assertFalse(terminated, "a half body must not carry the terminating chunk")
                        self.assertTrue(0 < len(data) < len(_RELAY_PAYLOAD))
                        self.assertEqual(_RELAY_PAYLOAD[: len(data)], data)
                        self.assertEqual(2, len(origin.requests))
                        self.assertTrue(any("流式响应异常" in line and "/segment.ts" in line for line in logs.output), logs.output)
                        self.assertFalse(any("协程取消" in line for line in logs.output), "an upstream failure is not a cancelled request")

    async def test_get_ts_stream_passes_stream_options_to_the_reconnect_stream(self) -> None:
        """retries / no_retry_statuses reach the wrapper: listing 416 hands the refusal back instead of re-asking."""

        def refuses_range(attempt: int, headers: dict[str, str]) -> bytes:
            if "range" in headers:
                return response_head("416 Range Not Satisfiable", {"Content-Range": f"bytes */{len(_RELAY_PAYLOAD)}", "Content-Length": 0})
            return response_head("200 OK", {"Content-Type": "video/mp2t", "Content-Length": len(_RELAY_PAYLOAD)}) + _RELAY_PAYLOAD

        async with _relay(RawOrigin(refuses_range)) as address:
            status, _, body = await _fetch(address, "Range: bytes=0-\r\n")
        self.assertEqual((200, _RELAY_PAYLOAD), (status, body))
        async with _relay(RawOrigin(refuses_range), stream_options={"no_retry_statuses": [404, 416]}) as address:
            status, _, body = await _fetch(address, "Range: bytes=0-\r\n")
        self.assertEqual((416, b""), (status, body))

    async def test_a_detached_upstream_is_released_even_while_the_task_manager_stops(self) -> None:
        """The web runtime stops BackgroundTaskManager before Sanic's graceful shutdown ends: releases must not depend on it."""

        released = asyncio.Event()

        class Context:
            async def __aexit__(self, *exc_info: object) -> None:
                released.set()

        class Upstream:
            url = "https://origin.test/live.ts"

            def detach_response(self) -> Context:
                return Context()

        manager = BackgroundTaskManager()
        stopping = manager._stopping
        manager._stopping = True
        try:
            object.__new__(BaseStreamProxy)._release_upstream_in_background(cast(Any, Upstream()))
            await asyncio.wait_for(released.wait(), timeout=1)
        finally:
            manager._stopping = stopping

    async def test_a_failure_while_the_upstream_still_sends_hangs_it_up_and_is_not_logged_as_a_cancellation(self) -> None:
        """A 206 that overruns its Content-Range fails while the upstream is still sending: the upstream is let go in
        the background, the requester's connection is dropped at once, and the failure is not logged as a cancellation."""

        async def overrunning(attempt: int, headers: dict[str, str]) -> AsyncIterator[bytes]:
            yield response_head("206 Partial Content", {"Content-Type": "video/mp2t", "Content-Range": "bytes 0-9/100", "Content-Length": 10_000_000})
            yield b"01234"
            await asyncio.sleep(0.2)
            for _ in range(2000):
                yield b"x" * 16384
                await asyncio.sleep(0.01)

        for user_agent in (None, "chrome"):
            with self.subTest(user_agent=user_agent):
                origin = RawOrigin(overrunning)
                with self.assertLogs("default", level="WARNING") as logs:
                    async with _relay(origin, user_agent=user_agent) as address:
                        started = time.monotonic()
                        status, _, body = await _fetch(address)
                        await asyncio.sleep(0.5)
                self.assertEqual((206, b"01234"), (status, body))
                self.assertEqual(1, len(origin.ended_at), "the upstream connection must be closed")
                self.assertLess(origin.ended_at[0] - started, 1.5)
                self.assertTrue(any("流式响应异常" in line and "/segment.ts" in line for line in logs.output), logs.output)
                self.assertFalse(any("协程取消" in line for line in logs.output), logs.output)

    async def test_a_requester_that_goes_away_is_logged_as_a_cancellation_and_the_upstream_stops(self) -> None:
        """A real cancellation is still logged as one (only upstream failures are not), and the upstream is hung up."""

        async def trickle(attempt: int, headers: dict[str, str]) -> AsyncIterator[bytes]:
            yield response_head("200 OK", {"Content-Type": "video/mp2t", "Transfer-Encoding": "chunked"})
            for _ in range(400):
                yield chunk_frame(_RELAY_PAYLOAD[:65536])
                await asyncio.sleep(0.01)
            yield b"0\r\n\r\n"

        origin = RawOrigin(trickle)
        with self.assertLogs("default", level="WARNING") as logs:
            async with _relay(origin) as address:
                reader, writer = await asyncio.open_connection(*address)
                writer.write(b"GET /segment HTTP/1.1\r\nHost: relay\r\nConnection: close\r\n\r\n")
                await writer.drain()
                received = 0
                while received < 200_000:
                    received += len(await asyncio.wait_for(reader.read(65536), 5))
                started = time.monotonic()
                writer.close()
                await asyncio.sleep(1)
        self.assertTrue(any("协程取消" in line for line in logs.output), logs.output)
        self.assertEqual(1, len(origin.ended_at))
        self.assertLess(origin.ended_at[0] - started, 1)

    async def test_a_requester_that_stops_reading_past_the_response_timeout_gets_no_end_marker(self) -> None:
        """Sanic cancels the handler at RESPONSE_TIMEOUT; whatever the route does with that, half a body is not ended."""

        async def flood(attempt: int, headers: dict[str, str]) -> AsyncIterator[bytes]:
            yield response_head("200 OK", {"Content-Type": "video/mp2t", "Transfer-Encoding": "chunked"})
            for _ in range(400):
                yield chunk_frame(_RELAY_PAYLOAD[:65536])
            yield b"0\r\n\r\n"

        for handling in ("raise", "return_none", "return_404"):
            with self.subTest(handling=handling):
                async with _relay(RawOrigin(flood), handling=handling, response_timeout=1) as address:
                    sock = socket.socket()
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
                    sock.setblocking(False)
                    await asyncio.get_running_loop().sock_connect(sock, address)
                    reader, writer = await asyncio.open_connection(sock=sock)
                    writer.write(b"GET /segment HTTP/1.1\r\nHost: relay\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    data = bytearray(await asyncio.wait_for(reader.read(100_000), 5))
                    await asyncio.sleep(3)
                    while piece := await asyncio.wait_for(reader.read(1 << 20), 5):
                        data += piece
                    writer.close()
                head, _, body = bytes(data).partition(b"\r\n\r\n")
                self.assertIn(b"transfer-encoding: chunked", head.lower())
                self.assertFalse(body.endswith(b"0\r\n\r\n"), "a half body must not carry the terminating chunk")
                self.assertLess(len(body), 400 * 65536)

    async def test_simple_proxy_passes_an_upstream_failure_on_instead_of_ending_normally(self) -> None:
        """SimpleStreamProxy raises the RequestCancelled that carries the upstream failure, so the route can tell it."""

        caught: list[tuple[str, str | None]] = []
        async with _relay(_relay_origin("chunked_cut"), proxy_class=SimpleStreamProxy, caught=caught) as address:
            await _fetch(address)
        self.assertEqual([("RequestCancelled", "HttpStatusError")], caught)

    async def test_a_known_length_body_cut_short_ends_short(self) -> None:
        """With a Content-Length the requester sees fewer bytes than declared, never a padded body."""

        async with _relay(_relay_origin("cut")) as address:
            status, headers, body = await _fetch(address)
        self.assertEqual(200, status)
        self.assertEqual(str(len(_RELAY_PAYLOAD)), headers["content-length"])
        self.assertTrue(0 < len(body) < len(_RELAY_PAYLOAD))
        self.assertEqual(_RELAY_PAYLOAD[: len(body)], body)


class ProxyParameterTest(unittest.IsolatedAsyncioTestCase):
    """Verify the existing MsgPack parameter formats without changing their wire shape."""

    def test_simple_params_restore_integer_direct_flag(self) -> None:
        """Simple URL parameters round-trip the integer flag written by make_params()."""

        encoded = SimpleStreamProxy.make_params(direct=True, proxy_url="http://proxy.test:8080")

        self.assertEqual(
            {"proxy_url": "http://proxy.test:8080", "user_agent": "", "direct": True},
            SimpleStreamProxy.load_params(encoded),
        )

    async def test_encrypted_params_restore_integer_direct_flag(self) -> None:
        """Redis-backed MsgPack parameters use the binary DEFAULT connection and retain direct."""

        storage: dict[str, bytes] = {}

        class BinaryConnection:
            async def setex(self, key: str, ttl: int, value: bytes) -> None:
                self.ttl = ttl
                storage[key] = value

            async def get(self, key: str) -> bytes | None:
                return storage.get(key)

        with patch.dict(conf.__dict__, {"settings": _settings()}):
            proxy = EncryptMixStreamProxy("encrypted")
        proxy._redis_binary_connection = AsyncMock(return_value=BinaryConnection())  # type: ignore[method-assign]

        await proxy.save_params("channel", 30, direct=True, user_agent="agent")
        params = await proxy.load_params("channel")

        self.assertEqual({"proxy_url": "", "user_agent": "agent", "direct": True}, params)

    async def test_manifest_paths_keep_source_rewrite_shapes(self) -> None:
        """M3U8 and MPD relative resources retain their established proxy URL format."""

        m3u8 = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:5,\nsegment.ts\n'
        rewritten_m3u8 = await SimpleStreamProxy.process_manifest(
            m3u8,
            "https://origin.test/live/master.m3u8",
            "packed",
        )
        self.assertIn('URI="/https/origin.test/live/key.bin?proxy_params=packed"', rewritten_m3u8)
        self.assertIn("/https/origin.test/live/segment.ts?proxy_params=packed", rewritten_m3u8)

        mpd = '<MPD><SegmentTemplate media="chunk-$Number$.m4s" initialization="init.mp4"/></MPD>'
        rewritten_mpd = await SimpleStreamProxy.process_manifest(
            mpd,
            "https://origin.test/live/manifest.mpd",
            "packed",
        )
        self.assertIn('media="/https/origin.test/live/chunk-$Number$.m4s?proxy_params=packed"', rewritten_mpd)
        self.assertIn('initialization="/https/origin.test/live/init.mp4?proxy_params=packed"', rewritten_mpd)

    async def test_sealed_url_formats_round_trip_and_reject_forgeries(self) -> None:
        """Both proxies share one sealed format: reversible, and closed to edited paths."""

        url = "https://origin.test/live/segment.ts?token=secret"
        with patch.dict(conf.__dict__, {"settings": _settings()}):
            encrypted_proxy = EncryptStreamProxy("aes")
            mixed_proxy = EncryptMixStreamProxy("mixed")

        encrypted = await encrypted_proxy.encrypt_url(url)
        mixed = await mixed_proxy.encrypt_url(url)

        self.assertEqual(url, await encrypted_proxy.decrypt_url(f"{encrypted}.ts"))
        self.assertEqual(url, await mixed_proxy.decrypt_url(f"{mixed}.ts"))

        # 上游地址会被直接拿去发请求，所以被改写的路径段必须拒绝，而不是解出别的地址。
        tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")
        self.assertIsNone(await encrypted_proxy.decrypt_url(f"{tampered}.ts"))

    async def test_sealed_urls_do_not_share_a_keystream(self) -> None:
        """A fixed keystream let anyone read every proxied address off one playlist."""

        with patch.dict(conf.__dict__, {"settings": _settings()}):
            proxy = EncryptMixStreamProxy("mixed")

        first = await proxy.encrypt_url("https://origin.test/live/ch01/seg00001.ts")
        second = await proxy.encrypt_url("https://origin.test/live/ch01/seg00002.ts")
        self.assertNotEqual(first[:16], second[:16])


if __name__ == "__main__":
    unittest.main()
