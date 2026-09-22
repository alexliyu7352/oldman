"""Unified HTTP response and real backend matrix tests."""

from __future__ import annotations

import asyncio
import datetime
import gzip
import ipaddress
import ssl
import tempfile
import time
import unittest
import zlib
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from http.cookies import SimpleCookie
from pathlib import Path
from typing import cast

import aiohttp
import httpx
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from curl_cffi import CurlError
from multidict import CIMultiDict

from oldman.contrib.http import (
    ClientType,
    HttpContentDecodingError,
    HttpHeaders,
    HttpMethod,
    HttpRangeError,
    HttpResponse,
    HttpStatusError,
    HttpStreamConsumedError,
    HttpStreamResponse,
    MultiHttpClient,
)

STREAM_BODY = "第一行\nsecond\r\n末行".encode()
RANGE_BODY = b"abcdefghijklmnopqrstuvwxyz"
HTTP_ONLY_ATTR = "HTTPOnly"
TLS_VERIFY_ERRORS = (aiohttp.ClientConnectionError, httpx.TransportError, CurlError)


def self_signed_server_context(directory: Path) -> ssl.SSLContext:
    """Create one localhost certificate and return a server-side TLS context."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    key_path = directory / "key.pem"
    certificate_path = directory / "certificate.pem"
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, key_path)
    return context


def scoped_cookie(
    value: str | None,
    path: str,
    name: str = "session",
    *,
    domain: str = "127.0.0.1",
    domain_specified: bool = False,
    secure: bool = False,
) -> Cookie:
    """Build one host-only test cookie for the local HTTP server."""

    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=domain_specified,
        domain_initial_dot=domain.startswith("."),
        path=path,
        path_specified=True,
        secure=secure,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class IterationCountingCookieJar(CookieJar):
    """Count full external-jar scans while retaining real CookieJar behavior."""

    def __init__(self) -> None:
        """Initialize an empty real jar and its scan counter."""

        super().__init__()
        self.iteration_count = 0

    def __iter__(self) -> Iterator[Cookie]:
        """Record each complete-jar iteration requested by the client."""

        self.iteration_count += 1
        return super().__iter__()


class HttpResponseContractTest(unittest.IsolatedAsyncioTestCase):
    """Verify backend-neutral response behavior without network I/O."""

    def test_headers_preserve_duplicates_and_ignore_name_case(self) -> None:
        """Headers expose joined and repeated views without mutation."""

        headers = HttpHeaders([("X-Test", "one"), ("x-test", "two"), ("Content-Type", "text/plain")])

        self.assertEqual("one, two", headers["X-TEST"])
        self.assertEqual(["one", "two"], headers.get_list("x-test"))
        self.assertEqual(
            [("x-test", "one"), ("x-test", "two"), ("content-type", "text/plain")],
            headers.multi_items(),
        )
        with self.assertRaises(TypeError):
            headers["x-test"] = "changed"  # type: ignore[index]

    def test_buffered_response_has_sync_body_and_status_api(self) -> None:
        """Buffered responses decode synchronously and raise one status error."""

        response = HttpResponse(
            status_code=404,
            url="https://example.test/missing",
            headers={"Content-Type": "text/plain; charset=iso-8859-1"},
            raw_content=b"caf\xe9",
            reason="Not Found",
        )

        self.assertEqual(b"caf\xe9", response.read())
        self.assertEqual(b"caf\xe9", response.raw_content())
        self.assertEqual("café", response.text)
        self.assertFalse(response.ok)
        self.assertFalse(response.is_success)
        with self.assertRaises(HttpStatusError) as raised:
            response.raise_for_status()
        self.assertIs(response, raised.exception.response)

    async def test_stream_response_rechunks_decodes_lines_and_closes_once(self) -> None:
        """The common stream layer handles backend chunks and idempotent close."""

        close_calls = 0

        async def iter_bytes() -> AsyncIterator[bytes]:
            """Split UTF-8 code points and newlines across source chunks."""

            for chunk in (STREAM_BODY[:2], STREAM_BODY[2:7], STREAM_BODY[7:13], STREAM_BODY[13:]):
                yield chunk

        async def close() -> None:
            """Count close calls from the unified response."""

            nonlocal close_calls
            close_calls += 1

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/stream",
            headers={"Content-Type": "text/plain; charset=utf-8"},
            iter_raw=iter_bytes,
            close=close,
        )

        chunks = [chunk async for chunk in response.aiter_raw(3)]
        self.assertEqual(STREAM_BODY, b"".join(chunks))
        self.assertTrue(all(0 < len(chunk) <= 3 for chunk in chunks))

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/stream",
            headers={"Content-Type": "text/plain; charset=utf-8"},
            iter_raw=iter_bytes,
            close=close,
        )
        self.assertEqual(["第一行", "second", "末行"], [line async for line in response.aiter_lines(2)])
        await response.aclose()
        await response.aclose()
        self.assertTrue(response.closed)
        self.assertEqual(1, close_calls)

    async def test_raw_content_reads_the_complete_raw_stream_without_manual_joining(self) -> None:
        """The full raw body API is cached and cannot follow partial iteration."""

        compressed = gzip.compress(STREAM_BODY)

        async def iter_raw() -> AsyncIterator[bytes]:
            """Yield one compressed body in deliberately small pieces."""

            for offset in range(0, len(compressed), 5):
                yield compressed[offset : offset + 5]

        async def close() -> None:
            """Provide the no-op close required by the stream contract."""

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/compressed",
            headers={"Content-Encoding": "gzip"},
            iter_raw=iter_raw,
            close=close,
            decode_content=True,
        )

        self.assertEqual(compressed, await response.raw_content())
        self.assertEqual(STREAM_BODY, await response.aread())
        self.assertEqual(compressed, await response.raw_content())

        partially_consumed = HttpStreamResponse(
            status_code=200,
            url="https://example.test/compressed",
            headers={"Content-Encoding": "gzip"},
            iter_raw=iter_raw,
            close=close,
            decode_content=True,
        )
        iterator = cast(AsyncGenerator[bytes, None], partially_consumed.aiter_raw())
        await anext(iterator)
        await iterator.aclose()
        with self.assertRaises(HttpStreamConsumedError):
            await partially_consumed.raw_content()

    async def test_unknown_content_encoding_keeps_raw_body_available(self) -> None:
        """Unsupported decoding fails explicitly without hiding the raw bytes."""

        async def iter_raw() -> AsyncIterator[bytes]:
            """Yield bytes marked with an unavailable content encoding."""

            yield b"encoded"

        async def close() -> None:
            """Provide the no-op close required by the stream contract."""

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/encoded",
            headers={"Content-Encoding": "unsupported"},
            iter_raw=iter_raw,
            close=close,
            decode_content=True,
        )

        self.assertEqual(b"encoded", await response.raw_content())
        with self.assertRaises(HttpContentDecodingError):
            await response.aread()

        buffered = HttpResponse(
            status_code=200,
            url="https://example.test/encoded",
            headers={"Content-Encoding": "unsupported"},
            raw_content=b"encoded",
            decode_content=True,
        )
        self.assertEqual(b"encoded", buffered.raw_content())
        with self.assertRaises(HttpContentDecodingError):
            _ = buffered.content

    def test_truncated_gzip_is_rejected_even_when_plaintext_was_recovered(self) -> None:
        """A missing gzip trailer must not be treated as a complete response."""

        compressed = gzip.compress(STREAM_BODY)
        response = HttpResponse(
            status_code=200,
            url="https://example.test/truncated",
            headers={"Content-Encoding": "gzip"},
            raw_content=compressed[:-8],
            decode_content=True,
        )

        with self.assertRaises(HttpContentDecodingError):
            _ = response.content

    def test_concatenated_gzip_and_deflate_members_are_all_decoded(self) -> None:
        """Every compressed member belongs to the response representation."""

        first = b"first-member"
        second = b"second-member"
        gzip_response = HttpResponse(
            status_code=200,
            url="https://example.test/concatenated-gzip",
            headers={"Content-Encoding": "gzip"},
            raw_content=gzip.compress(first) + gzip.compress(second),
            decode_content=True,
        )
        deflate_response = HttpResponse(
            status_code=200,
            url="https://example.test/concatenated-deflate",
            headers={"Content-Encoding": "deflate"},
            raw_content=zlib.compress(first) + zlib.compress(second),
            decode_content=True,
        )

        self.assertEqual(first + second, gzip_response.content)
        self.assertEqual(first + second, deflate_response.content)

    async def test_streaming_gzip_handles_a_member_boundary_between_chunks(self) -> None:
        """A network chunk boundary may coincide with a gzip member boundary."""

        first = gzip.compress(b"first")
        second = gzip.compress(b"second")

        async def iter_raw() -> AsyncIterator[bytes]:
            """Split the encoded body exactly between its two members."""

            yield first
            yield second

        async def close() -> None:
            """Provide the no-op close required by the stream contract."""

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/concatenated-gzip",
            headers={"Content-Encoding": "gzip"},
            iter_raw=iter_raw,
            close=close,
            decode_content=True,
        )

        self.assertEqual(b"firstsecond", await response.aread())

    def test_truncated_or_garbage_final_compressed_member_is_rejected(self) -> None:
        """A valid first member cannot hide a corrupt trailing member."""

        valid = gzip.compress(b"first")
        truncated = gzip.compress(b"second")[:-4]
        for raw_content in (valid + truncated, valid + b"not-a-gzip-member"):
            with self.subTest(raw_content=raw_content[-12:]):
                response = HttpResponse(
                    status_code=200,
                    url="https://example.test/corrupt-gzip",
                    headers={"Content-Encoding": "gzip"},
                    raw_content=raw_content,
                    decode_content=True,
                )
                with self.assertRaises(HttpContentDecodingError):
                    _ = response.content

    async def test_raw_deflate_detection_tolerates_one_byte_source_chunks(self) -> None:
        """Legacy raw deflate remains decodable regardless of network chunking."""

        content = b"oldman-response-" * 200
        compressed = zlib.compress(content, wbits=-zlib.MAX_WBITS)

        async def iter_raw() -> AsyncIterator[bytes]:
            """Expose the compressed representation one byte at a time."""

            for value in compressed:
                yield bytes((value,))

        async def close() -> None:
            """Provide the no-op close required by the stream contract."""

        response = HttpStreamResponse(
            status_code=200,
            url="https://example.test/raw-deflate",
            headers={"Content-Encoding": "deflate"},
            iter_raw=iter_raw,
            close=close,
            decode_content=True,
        )

        self.assertEqual(content, await response.aread())

    async def test_cancelled_client_close_keeps_backend_available_for_retry(self) -> None:
        """Cancellation must not discard a backend whose resources may still be open."""

        class BlockingBackend:
            """Simulate a backend whose first close attempt is cancelled."""

            def __init__(self) -> None:
                """Initialize close-attempt state."""

                self.close_started = asyncio.Event()
                self.close_attempts = 0

            async def close_client(self) -> None:
                """Block the first close and let a later retry complete."""

                self.close_attempts += 1
                if self.close_attempts == 1:
                    self.close_started.set()
                    await asyncio.Event().wait()

        client = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        backend = BlockingBackend()
        client._impl = backend  # type: ignore[assignment]

        close_task = asyncio.create_task(client.close_client())
        await backend.close_started.wait()
        close_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await close_task

        self.assertIs(backend, client._impl)
        await client.close_client()
        self.assertIsNone(client._impl)
        self.assertEqual(2, backend.close_attempts)

    async def test_reset_reports_backend_failure_and_propagates_cancellation(self) -> None:
        """A failed or cancelled backend reset cannot be reported as successful."""

        class ResetBackend:
            """Provide deterministic failure and cancellation reset modes."""

            def __init__(self, exception: BaseException) -> None:
                """Store the exception raised by the next reset."""

                self.exception = exception

            async def reset_client(self) -> bool:
                """Raise the configured reset outcome."""

                raise self.exception

        class DeclinedResetBackend:
            """Report a reset that did not complete without raising."""

            async def reset_client(self) -> bool:
                """Return the backend interface's explicit failure result."""

                return False

        failed_client = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        failed_client._impl = ResetBackend(RuntimeError("reset failed"))  # type: ignore[assignment]
        failed_client.last_client_reset = 0
        before_failure = time.time()
        self.assertFalse(await failed_client.reset_client())
        self.assertGreaterEqual(failed_client.last_client_reset, before_failure)
        failed_client._impl = None

        declined_client = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        declined_client._impl = DeclinedResetBackend()  # type: ignore[assignment]
        declined_client.last_client_reset = 0
        before_decline = time.time()
        self.assertFalse(await declined_client.reset_client())
        self.assertGreaterEqual(declined_client.last_client_reset, before_decline)
        declined_client._impl = None

        cancelled_client = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        cancelled_client._impl = ResetBackend(asyncio.CancelledError())  # type: ignore[assignment]
        cancelled_client.last_client_reset = 0
        with self.assertRaises(asyncio.CancelledError):
            await cancelled_client.reset_client()
        cancelled_client._impl = None

    async def test_request_logs_redact_secrets_without_hiding_status_context(self) -> None:
        """Retry logs retain status and location while omitting request secrets."""

        class ErrorBackend:
            """Return one deterministic response containing sensitive metadata."""

            async def request(self, method: HttpMethod, url: str, **kwargs: object) -> HttpResponse:
                """Return an error without inspecting caller headers."""

                del method, kwargs
                return HttpResponse(
                    status_code=500,
                    url=url,
                    headers={"X-Secret": "response-header-secret"},
                    raw_content=b"response-body-secret",
                )

        client = MultiHttpClient(
            ClientType.HTTPX,
            retry_count=0,
            proxy_url="http://proxy-user:proxy-password@proxy.test:8080/private?proxy-token=secret",
        )
        client._impl = ErrorBackend()  # type: ignore[assignment]
        with self.assertLogs("default", level="WARNING") as captured:
            response = await client.get(
                "https://url-user:url-password@example.test/path?query-token=secret#fragment-secret",
                headers={
                    "Authorization": "Bearer authorization-secret",
                    "Cookie": "session=cookie-secret",
                },
            )
        client._impl = None

        output = "\n".join(captured.output)
        self.assertEqual(500, response.status_code)
        self.assertIn("https://example.test/path", output)
        self.assertIn("http://proxy.test:8080", output)
        self.assertIn("状态码: 500", output)
        for secret in (
            "url-user",
            "url-password",
            "query-token",
            "fragment-secret",
            "proxy-user",
            "proxy-password",
            "proxy-token",
            "authorization-secret",
            "cookie-secret",
            "response-header-secret",
            "response-body-secret",
        ):
            self.assertNotIn(secret, output)

    async def test_aiohttp_native_jar_preserves_stdlib_cookie_scope(self) -> None:
        """The aiohttp seed adapter retains host, domain, path, and secure rules."""

        from aiohttp import CookieJar as AiohttpCookieJar
        from yarl import URL

        from oldman.contrib.http.backends.aiohttp import _to_aiohttp_cookie_jar

        cookies = CookieJar()
        cookies.set_cookie(
            scoped_cookie(
                "host",
                "/",
                name="host-only",
                domain="example.test",
            )
        )
        cookies.set_cookie(
            scoped_cookie(
                "domain",
                "/",
                name="domain-wide",
                domain=".example.test",
                domain_specified=True,
            )
        )
        cookies.set_cookie(
            scoped_cookie(
                "secure",
                "/",
                name="secure-only",
                domain=".example.test",
                domain_specified=True,
                secure=True,
            )
        )
        cookies.set_cookie(
            scoped_cookie(
                "inside",
                "/inside",
                name="path-only",
                domain="example.test",
            )
        )
        native = _to_aiohttp_cookie_jar(cookies)
        self.assertIs(AiohttpCookieJar, type(native))

        exact = native.filter_cookies(URL("http://example.test/inside/page"))
        outside = native.filter_cookies(URL("http://example.test/outside"))
        subdomain = native.filter_cookies(URL("http://sub.example.test/"))
        secure_subdomain = native.filter_cookies(URL("https://sub.example.test/"))

        self.assertEqual(
            {"domain-wide": "domain", "host-only": "host", "path-only": "inside"},
            {name: morsel.value for name, morsel in exact.items()},
        )
        self.assertEqual(
            {"domain-wide": "domain", "host-only": "host"},
            {name: morsel.value for name, morsel in outside.items()},
        )
        self.assertEqual(
            {"domain-wide": "domain"},
            {name: morsel.value for name, morsel in subdomain.items()},
        )
        self.assertEqual(
            {"domain-wide": "domain", "secure-only": "secure"},
            {name: morsel.value for name, morsel in secure_subdomain.items()},
        )

    async def test_aiohttp_export_keeps_a_domainless_cookie_unspecified(self) -> None:
        """Export cannot invent a Domain attribute for a shared stdlib cookie."""

        from oldman.contrib.http.backends.aiohttp import _export_cookie_jar, _to_aiohttp_cookie_jar

        cookies = CookieJar()
        cookies.set_cookie(scoped_cookie("shared", "/", domain=""))
        native = _to_aiohttp_cookie_jar(cookies)
        exported = CookieJar()
        _export_cookie_jar(native, exported)

        [cookie] = list(exported)
        self.assertEqual("", cookie.domain)
        self.assertFalse(cookie.domain_specified)
        self.assertFalse(cookie.domain_initial_dot)


class HttpBackendMatrixTest(unittest.IsolatedAsyncioTestCase):
    """Run the same public contract against all three real backend libraries."""

    async def asyncSetUp(self) -> None:
        """Start a real local HTTP server for backend-independent assertions."""

        app = web.Application()
        app.router.add_get("/json", self._json_response)
        app.router.add_get("/redirect", self._redirect_response)
        app.router.add_get("/cookies", self._cookie_response)
        app.router.add_get("/echo-cookie", self._echo_cookie_response)
        app.router.add_get("/nested/echo-cookie", self._echo_cookie_response)
        app.router.add_get("/nested/redirect-root", self._redirect_root_response)
        app.router.add_get("/redirect-nested", self._redirect_nested_response)
        app.router.add_get("/redirect-set-cookie", self._redirect_set_cookie_response)
        app.router.add_get("/delete-cookie", self._delete_cookie_response)
        app.router.add_get("/redirect-delete-cookie", self._redirect_delete_cookie_response)
        app.router.add_get("/retry-cookie", self._retry_cookie_response)
        app.router.add_get("/encoded", self._encoded_response)
        app.router.add_get("/deflate", self._deflate_response)
        app.router.add_get("/stream", self._stream_response)
        app.router.add_get("/success-stream", self._success_stream_response)
        app.router.add_post("/post-retry", self._post_retry_response)
        app.router.add_get("/disconnect-once", self._disconnect_once_response)
        app.router.add_get("/cookie-disconnect-once", self._cookie_disconnect_once_response)
        app.router.add_get("/etag-disconnect", self._etag_disconnect_response)
        app.router.add_get("/stale-etag-disconnect", self._stale_etag_disconnect_response)
        app.router.add_get("/short-range", self._short_range_response)
        app.router.add_get("/unsolicited-partial", self._unsolicited_partial_response)
        app.router.add_get("/unsolicited-partial-no-range", self._unsolicited_partial_without_range_response)
        app.router.add_get("/overlong-range", self._overlong_range_response)
        app.router.add_get("/live-disconnect", self._live_disconnect_response)
        app.router.add_get("/live-error-after-disconnect", self._live_error_after_disconnect_response)
        app.router.add_get("/bounded-disconnect-once", self._bounded_disconnect_once_response)
        app.router.add_get("/suffix-disconnect-once", self._suffix_disconnect_once_response)
        app.router.add_get("/wrong-suffix", self._wrong_suffix_response)
        app.router.add_get("/ignore-resume", self._ignore_resume_response)
        app.router.add_get("/mismatch-resume", self._mismatch_resume_response)
        app.router.add_get("/changed-total-resume", self._changed_total_resume_response)
        app.router.add_get("/slow-stream", self._slow_stream_response)
        app.router.add_get("/missing", self._missing_response)
        self.disconnect_attempts = 0
        self.reconnect_cookie_headers: list[str] = []
        self.etag_requests: list[tuple[str | None, str | None]] = []
        self.stale_etag_requests: list[tuple[str | None, str | None]] = []
        self.retry_cookie_headers: list[str] = []
        self.success_stream_attempts = 0
        self.post_retry_attempts = 0
        self.short_ranges: list[str | None] = []
        self.unsolicited_ranges: list[str | None] = []
        self.live_headers: list[tuple[str | None, str | None]] = []
        self.live_error_attempts = 0
        self.bounded_ranges: list[str | None] = []
        self.suffix_ranges: list[str | None] = []
        self.ignore_resume_attempts = 0
        self.slow_stream_release = asyncio.Event()
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        assert self.site._server is not None
        server = cast(asyncio.Server, self.site._server)
        port = server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"

    async def asyncTearDown(self) -> None:
        """Stop the local HTTP server and release its listening socket."""

        await self.runner.cleanup()

    @staticmethod
    async def _json_response(request: web.Request) -> web.Response:
        """Return duplicate headers, a cookie, JSON, and a non-200 2xx status."""

        headers = CIMultiDict([("X-Repeated", "one"), ("X-Repeated", "two")])
        response = web.json_response(
            {"ok": True, "user_agent": request.headers.get("User-Agent")},
            status=201,
            headers=headers,
        )
        response.set_cookie("session", "abc")
        return response

    @staticmethod
    async def _cookie_response(request: web.Request) -> web.Response:
        """Return same-name cookies with different paths and attributes."""

        del request
        headers = CIMultiDict()
        headers.add("Set-Cookie", "session=root; Path=/; HttpOnly; Partitioned")
        headers.add("Set-Cookie", "session=nested; Path=/nested; SameSite=Lax; Priority=High")
        return web.Response(status=200, text="cookies", headers=headers)

    @staticmethod
    async def _redirect_response(request: web.Request) -> web.StreamResponse:
        """Redirect to the common JSON endpoint."""

        del request
        raise web.HTTPFound(location="/json")

    @staticmethod
    async def _redirect_root_response(request: web.Request) -> web.StreamResponse:
        """Redirect from a nested path to the cookie echo at the root."""

        del request
        raise web.HTTPFound(location="/echo-cookie")

    @staticmethod
    async def _redirect_nested_response(request: web.Request) -> web.StreamResponse:
        """Redirect from the root to the nested cookie echo endpoint."""

        del request
        raise web.HTTPFound(location="/nested/echo-cookie")

    @staticmethod
    async def _redirect_set_cookie_response(request: web.Request) -> web.StreamResponse:
        """Set a cookie on an intermediate response before redirecting."""

        del request
        response = web.HTTPFound(location="/echo-cookie")
        response.set_cookie("redirected", "yes", path="/")
        raise response

    @staticmethod
    async def _delete_cookie_response(request: web.Request) -> web.Response:
        """Expire an existing persistent cookie on the final response."""

        del request
        response = web.Response(status=200, text="deleted")
        response.del_cookie("session", path="/")
        return response

    @staticmethod
    async def _redirect_delete_cookie_response(request: web.Request) -> web.StreamResponse:
        """Expire a cookie before redirecting to an endpoint that echoes cookies."""

        del request
        response = web.HTTPFound(location="/echo-cookie")
        response.del_cookie("session", path="/")
        raise response

    async def _retry_cookie_response(self, request: web.Request) -> web.Response:
        """Set a session cookie on an error response and echo the retry request."""

        cookie_header = request.headers.get("Cookie", "")
        self.retry_cookie_headers.append(cookie_header)
        if len(self.retry_cookie_headers) == 1:
            response = web.Response(status=500, text="retry")
            response.set_cookie("retry", "server", path="/")
            return response
        return web.Response(status=200, text=cookie_header)

    @staticmethod
    async def _encoded_response(request: web.Request) -> web.Response:
        """Return a gzip entity regardless of the request's advertised encodings."""

        del request
        return web.Response(
            status=200,
            body=gzip.compress(STREAM_BODY, mtime=0),
            headers={
                "Content-Encoding": "gzip",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )

    @staticmethod
    async def _deflate_response(request: web.Request) -> web.Response:
        """Return an RFC-compliant zlib-wrapped deflate entity."""

        del request
        return web.Response(
            status=200,
            body=zlib.compress(STREAM_BODY),
            headers={
                "Content-Encoding": "deflate",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )

    @staticmethod
    async def _echo_cookie_response(request: web.Request) -> web.Response:
        """Return the exact Cookie header selected for this request path."""

        return web.Response(status=200, text=request.headers.get("Cookie", ""))

    @staticmethod
    async def _stream_response(request: web.Request) -> web.StreamResponse:
        """Write a UTF-8 body using deliberately awkward native chunks."""

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        await response.prepare(request)
        for chunk in (STREAM_BODY[:2], STREAM_BODY[2:7], STREAM_BODY[7:13], STREAM_BODY[13:]):
            await response.write(chunk)
        await response.write_eof()
        return response

    async def _success_stream_response(self, request: web.Request) -> web.Response:
        """Return a legal non-200 success status and count transport attempts."""

        del request
        self.success_stream_attempts += 1
        return web.Response(status=201, body=b"created")

    async def _post_retry_response(self, request: web.Request) -> web.Response:
        """Fail one POST before succeeding to preserve the established retry contract."""

        del request
        self.post_retry_attempts += 1
        if self.post_retry_attempts == 1:
            return web.Response(status=500, text="retry")
        return web.Response(status=201, text="created")

    @staticmethod
    async def _missing_response(request: web.Request) -> web.Response:
        """Return a stable HTTP error response."""

        del request
        return web.Response(status=404, text="missing")

    async def _disconnect_once_response(self, request: web.Request) -> web.StreamResponse:
        """Abort the first body so reconnect logic must issue a Range request."""

        range_header = request.headers.get("Range")
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            return web.Response(
                status=206,
                body=RANGE_BODY[start:],
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
                },
            )

        self.disconnect_attempts += 1
        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:7])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _cookie_disconnect_once_response(self, request: web.Request) -> web.StreamResponse:
        """Set a persistent cookie before forcing one real reconnect."""

        self.reconnect_cookie_headers.append(request.headers.get("Cookie", ""))
        range_header = request.headers.get("Range")
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            return web.Response(
                status=206,
                body=RANGE_BODY[start:],
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
                },
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
                "Set-Cookie": "session=server; Path=/",
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:7])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _etag_disconnect_response(self, request: web.Request) -> web.StreamResponse:
        """Change a strong ETag while keeping the resumed byte interval valid."""

        range_header = request.headers.get("Range")
        self.etag_requests.append((range_header, request.headers.get("If-Range")))
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            changed = RANGE_BODY.upper()
            return web.Response(
                status=206,
                body=changed[start:],
                headers={
                    "Content-Range": f"bytes {start}-{len(changed) - 1}/{len(changed)}",
                    "ETag": '"version-2"',
                },
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
                "ETag": '"version-1"',
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:6])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _stale_etag_disconnect_response(self, request: web.Request) -> web.StreamResponse:
        """Retry an error response before interrupting a successful untagged body."""

        range_header = request.headers.get("Range")
        self.stale_etag_requests.append((range_header, request.headers.get("If-Range")))
        if len(self.stale_etag_requests) == 1:
            return web.Response(status=500, text="retry", headers={"ETag": '"error-page"'})
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            return web.Response(
                status=206,
                body=RANGE_BODY[start:],
                headers={"Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}"},
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:5])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _short_range_response(self, request: web.Request) -> web.Response:
        """End one 206 body cleanly before its declared Content-Range is complete."""

        range_header = request.headers.get("Range")
        self.short_ranges.append(range_header)
        if len(self.short_ranges) == 1:
            return web.Response(
                status=206,
                body=RANGE_BODY[:10],
                headers={"Content-Range": f"bytes 0-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}"},
            )

        assert range_header is not None
        start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
        return web.Response(
            status=206,
            body=RANGE_BODY[start:],
            headers={"Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}"},
        )

    async def _unsolicited_partial_response(self, request: web.Request) -> web.StreamResponse:
        """Return and interrupt a valid 206 even though the caller sent no Range."""

        range_header = request.headers.get("Range")
        self.unsolicited_ranges.append(range_header)
        if range_header:
            start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text)
            return web.Response(
                status=206,
                body=RANGE_BODY[start : end + 1],
                headers={"Content-Range": f"bytes {start}-{end}/{len(RANGE_BODY)}"},
            )

        response = web.StreamResponse(
            status=206,
            headers={
                "Content-Length": "6",
                "Content-Range": f"bytes 10-15/{len(RANGE_BODY)}",
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[10:13])
        assert request.transport is not None
        request.transport.close()
        return response

    @staticmethod
    async def _unsolicited_partial_without_range_response(request: web.Request) -> web.Response:
        """Allow a complete unsolicited 206 whose origin omitted Content-Range."""

        del request
        return web.Response(status=206, body=b"partial")

    @staticmethod
    async def _overlong_range_response(request: web.Request) -> web.Response:
        """Send more bytes than the bounded Content-Range declares."""

        del request
        return web.Response(
            status=206,
            body=RANGE_BODY[:11],
            headers={"Content-Range": f"bytes 0-9/{len(RANGE_BODY)}"},
        )

    async def _live_disconnect_response(self, request: web.Request) -> web.StreamResponse:
        """Drop one live connection and provide a fresh stream on reconnect."""

        self.live_headers.append((request.headers.get("Range"), request.headers.get("If-Range")))
        if len(self.live_headers) > 1:
            return web.Response(status=200, body=b"second", headers={"ETag": '"live-2"'})

        response = web.StreamResponse(
            status=200,
            headers={"Content-Length": "10", "ETag": '"live-1"'},
        )
        await response.prepare(request)
        await response.write(b"first")
        assert request.transport is not None
        request.transport.close()
        return response

    async def _live_error_after_disconnect_response(self, request: web.Request) -> web.StreamResponse:
        """Drop one live body, then return only error pages on reconnect."""

        self.live_error_attempts += 1
        if self.live_error_attempts > 1:
            return web.Response(status=500, body=b"error-page")

        response = web.StreamResponse(status=200, headers={"Content-Length": "10"})
        await response.prepare(request)
        await response.write(b"part")
        assert request.transport is not None
        request.transport.close()
        return response

    async def _bounded_disconnect_once_response(self, request: web.Request) -> web.StreamResponse:
        """Disconnect a bounded range once and record the resumed range."""

        range_header = request.headers.get("Range")
        self.bounded_ranges.append(range_header)
        if len(self.bounded_ranges) > 1:
            assert range_header is not None
            start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text)
            return web.Response(
                status=206,
                body=RANGE_BODY[start : end + 1],
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{len(RANGE_BODY)}",
                },
            )

        response = web.StreamResponse(
            status=206,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": "8",
                "Content-Range": f"bytes 5-12/{len(RANGE_BODY)}",
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[5:8])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _ignore_resume_response(self, request: web.Request) -> web.StreamResponse:
        """Ignore a resumed Range so the client must reject unsafe concatenation."""

        range_header = request.headers.get("Range")
        if range_header:
            return web.Response(status=200, body=RANGE_BODY)

        self.ignore_resume_attempts += 1
        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:7])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _suffix_disconnect_once_response(self, request: web.Request) -> web.StreamResponse:
        """Resolve a suffix range once, then resume it by absolute offset."""

        range_header = request.headers.get("Range")
        self.suffix_ranges.append(range_header)
        if len(self.suffix_ranges) > 1:
            assert range_header is not None
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            return web.Response(
                status=206,
                body=RANGE_BODY[start:],
                headers={
                    "Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
                },
            )

        start = len(RANGE_BODY) - 8
        response = web.StreamResponse(
            status=206,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": "8",
                "Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[start : start + 3])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _mismatch_resume_response(self, request: web.Request) -> web.StreamResponse:
        """Return a 206 whose Content-Range starts at the wrong byte."""

        range_header = request.headers.get("Range")
        if range_header:
            requested_start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            wrong_start = requested_start + 1
            return web.Response(
                status=206,
                body=RANGE_BODY[wrong_start:],
                headers={
                    "Content-Range": f"bytes {wrong_start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
                },
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:7])
        assert request.transport is not None
        request.transport.close()
        return response

    async def _changed_total_resume_response(self, request: web.Request) -> web.StreamResponse:
        """Change the advertised resource length between the initial response and resume."""

        range_header = request.headers.get("Range")
        if range_header:
            requested_start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            changed_body = RANGE_BODY + b"!"
            return web.Response(
                status=206,
                body=changed_body[requested_start:],
                headers={
                    "Content-Range": f"bytes {requested_start}-{len(changed_body) - 1}/{len(changed_body)}",
                },
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(RANGE_BODY)),
            },
        )
        await response.prepare(request)
        await response.write(RANGE_BODY[:7])
        assert request.transport is not None
        request.transport.close()
        return response

    @staticmethod
    async def _wrong_suffix_response(request: web.Request) -> web.Response:
        """Return more bytes than the requested suffix so the client must reject it."""

        del request
        start = len(RANGE_BODY) - 9
        return web.Response(
            status=206,
            body=RANGE_BODY[start:],
            headers={
                "Content-Range": f"bytes {start}-{len(RANGE_BODY) - 1}/{len(RANGE_BODY)}",
            },
        )

    async def _slow_stream_response(self, request: web.Request) -> web.StreamResponse:
        """Keep a curl stream open after its first chunk until the test releases it."""

        response = web.StreamResponse(status=200, headers={"Content-Type": "application/octet-stream"})
        await response.prepare(request)
        await response.write(b"first")
        await self.slow_stream_release.wait()
        try:
            await response.write(b"last")
            await response.write_eof()
        except (ConnectionError, RuntimeError):
            pass
        return response

    async def test_all_backends_return_the_same_response_contract(self) -> None:
        """Normal, stream, reconnect, and status APIs stay backend-neutral."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=5,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/json")
                    self.assertIs(type(response), HttpResponse)
                    self.assertEqual(201, response.status_code)
                    self.assertTrue(response.is_success)
                    self.assertEqual(
                        {"ok": True, "user_agent": "Oldman-Test/1"},
                        response.json(),
                    )
                    self.assertEqual(["one", "two"], response.headers.get_list("x-repeated"))
                    self.assertEqual(
                        {("session", "/", "abc")},
                        {(cookie.name, cookie.path, cookie.value) for cookie in response.cookies},
                    )
                    self.assertTrue(response.http_version.startswith("HTTP/"))
                    self.assertFalse(hasattr(response, "history"))

                    redirected = await client.get(f"{self.base_url}/redirect")
                    self.assertEqual(f"{self.base_url}/json", redirected.url)

                    missing = await client.get(f"{self.base_url}/missing")
                    with self.assertRaises(HttpStatusError):
                        missing.raise_for_status()

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/stream") as stream:
                        self.assertIs(type(stream), HttpStreamResponse)
                        chunks = [chunk async for chunk in stream.aiter_raw(3)]
                        self.assertEqual(STREAM_BODY, b"".join(chunks))
                        self.assertTrue(all(0 < len(chunk) <= 3 for chunk in chunks))
                    self.assertTrue(stream.closed)

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/stream") as stream:
                        lines = [line async for line in stream.aiter_lines(2)]
                        self.assertEqual(["第一行", "second", "末行"], lines)

                    async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/stream") as stream:
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(4)])
                        self.assertEqual(STREAM_BODY, body)
                finally:
                    await client.close_client()

    async def test_all_backends_accept_every_legal_stream_success_status_once(self) -> None:
        """A non-200 2xx stream must not consume the retry budget."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.success_stream_attempts = 0
                client = MultiHttpClient(
                    client_type,
                    retry_count=2,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    async with client.stream(
                        HttpMethod.GET,
                        f"{self.base_url}/success-stream",
                    ) as stream:
                        body = await stream.raw_content()
                        self.assertEqual(201, stream.status_code)
                    self.assertEqual(1, self.success_stream_attempts)

                    self.success_stream_attempts = 0
                    async with client.reconnect_stream(
                        HttpMethod.GET,
                        f"{self.base_url}/success-stream",
                    ) as reconnecting:
                        reconnect_body = b"".join([chunk async for chunk in reconnecting.aiter_bytes(4)])
                        self.assertEqual(201, reconnecting.status_code)
                finally:
                    await client.close_client()

                self.assertEqual(b"created", body)
                self.assertEqual(b"created", reconnect_body)
                self.assertEqual(1, self.success_stream_attempts)

    async def test_all_backends_preserve_post_status_retries(self) -> None:
        """The established retry policy continues to retry a failed POST."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.post_retry_attempts = 0
                client = MultiHttpClient(
                    client_type,
                    retry_count=1,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    response = await client.post(f"{self.base_url}/post-retry", json={"value": 1})
                finally:
                    await client.close_client()

                self.assertEqual(201, response.status_code)
                self.assertEqual("created", response.text)
                self.assertEqual(2, self.post_retry_attempts)

    async def test_repeated_init_keeps_the_existing_backend(self) -> None:
        """Calling init twice cannot replace a live backend and leak its session."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(client_type, retry_count=0)
                await client.init_client()
                backend = client.client
                try:
                    await client.get(f"{self.base_url}/json")
                    await client.init_client()
                    self.assertIs(backend, client.client)
                finally:
                    await client.close_client()

    async def test_all_backends_export_current_cookie_state(self) -> None:
        """Explicit export exposes every backend's current cookies through the caller jar."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    await client.get(f"{self.base_url}/json")
                    client.export_cookies()
                finally:
                    await client.close_client()

                self.assertEqual({"session": "abc"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_httpx_and_curl_observe_external_cookie_jar_mutations(self) -> None:
        """Backends that use the external jar directly keep observing its mutations."""

        for client_type in (ClientType.HTTPX, ClientType.CURL_CFFI):
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("secret", "/", name="auth"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    initial = await client.get(f"{self.base_url}/echo-cookie")
                    cookie_jar.clear()
                    cleared = await client.get(f"{self.base_url}/echo-cookie")
                    cookie_jar.set_cookie(scoped_cookie("fresh", "/", name="runtime"))
                    added = await client.get(f"{self.base_url}/echo-cookie")
                    cookie_jar.clear()
                    cookie_jar.set_cookie(scoped_cookie("stream", "/", name="streaming"))
                    async with client.stream(HttpMethod.GET, f"{self.base_url}/echo-cookie") as stream:
                        streamed = await stream.raw_content()
                finally:
                    await client.close_client()

                self.assertEqual("secret", SimpleCookie(initial.text)["auth"].value)
                self.assertEqual("", cleared.text)
                self.assertEqual("fresh", SimpleCookie(added.text)["runtime"].value)
                self.assertEqual("stream", SimpleCookie(streamed.decode())["streaming"].value)

    async def test_aiohttp_external_cookie_jar_is_initial_state_not_live_state(self) -> None:
        """Mutating the import jar after session creation cannot replace native state."""

        cookie_jar = CookieJar()
        cookie_jar.set_cookie(scoped_cookie("secret", "/", name="auth"))
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0, cookie_jar=cookie_jar)
        await client.init_client()
        try:
            initial = await client.get(f"{self.base_url}/echo-cookie")
            cookie_jar.clear()
            cookie_jar.set_cookie(scoped_cookie("fresh", "/", name="runtime"))
            unchanged = await client.get(f"{self.base_url}/echo-cookie")
        finally:
            await client.close_client()

        self.assertEqual("secret", SimpleCookie(initial.text)["auth"].value)
        unchanged_cookies = SimpleCookie(unchanged.text)
        self.assertEqual("secret", unchanged_cookies["auth"].value)
        self.assertNotIn("runtime", unchanged_cookies)

    async def test_aiohttp_scans_the_external_jar_only_when_initializing_native_state(self) -> None:
        """Ordinary requests never rescan the external initialization jar."""

        cookie_jar = IterationCountingCookieJar()
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0, cookie_jar=cookie_jar)
        await client.init_client()
        try:
            await client.get(f"{self.base_url}/echo-cookie")
            scans_after_first_request = cookie_jar.iteration_count
            response = await client.get(f"{self.base_url}/echo-cookie")
        finally:
            await client.close_client()

        self.assertEqual("", response.text)
        self.assertEqual(0, cookie_jar.iteration_count - scans_after_first_request)

    async def test_aiohttp_native_cookie_state_survives_session_reset(self) -> None:
        """Resetting the connection-pool session cannot discard native Cookie state."""

        cookie_jar = CookieJar()
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0, cookie_jar=cookie_jar)
        await client.init_client()
        try:
            await client.get(f"{self.base_url}/json")
            await client.client.reset_client()
            persisted = await client.get(f"{self.base_url}/echo-cookie")
            client.export_cookies()
        finally:
            await client.close_client()

        self.assertEqual("session=abc", persisted.text)
        self.assertEqual({"session": "abc"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_all_backends_keep_internal_cookie_state_across_session_reset(self) -> None:
        """A transport reset must not discard a client session established at runtime."""

        base_url = self.base_url.replace("127.0.0.1", "localhost")
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(client_type, retry_count=0)
                await client.init_client()
                try:
                    await client.get(f"{base_url}/json")
                    await client.client.reset_client()
                    persisted = await client.get(f"{base_url}/echo-cookie")
                finally:
                    await client.close_client()

                self.assertEqual("session=abc", persisted.text)

    async def test_aiohttp_sends_a_stdlib_cookie_without_a_value(self) -> None:
        """A no-value stdlib cookie is transported as an empty aiohttp value."""

        cookie_jar = CookieJar()
        cookie_jar.set_cookie(scoped_cookie(None, "/", name="flag"))
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0, cookie_jar=cookie_jar)
        await client.init_client()
        try:
            response = await client.get(f"{self.base_url}/echo-cookie")
        finally:
            await client.close_client()

        self.assertEqual("", SimpleCookie(response.text)["flag"].value)

    async def test_all_backends_reselect_scoped_cookies_after_redirects(self) -> None:
        """Redirect targets must receive cookies selected for their own path."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("root", "/"))
                cookie_jar.set_cookie(scoped_cookie("nested", "/nested"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    root = await client.get(f"{self.base_url}/nested/redirect-root")
                    nested = await client.get(f"{self.base_url}/redirect-nested")
                finally:
                    await client.close_client()

                self.assertEqual("session=root", root.text)
                if client_type == ClientType.AIOHTTP:
                    self.assertEqual("session=nested", nested.text)
                else:
                    self.assertEqual("session=nested; session=root", nested.text)

    async def test_all_backends_store_cookies_from_redirect_responses(self) -> None:
        """The canonical jar includes cookies received before the final response."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/redirect-set-cookie")
                    client.export_cookies()
                finally:
                    await client.close_client()

                self.assertEqual("redirected=yes", response.text)
                self.assertEqual({"redirected": "yes"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_all_backends_apply_cookie_deletion_on_final_and_redirect_responses(self) -> None:
        """Expired Set-Cookie fields must remove canonical cookies on every hop."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type, response="final"):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("old", "/"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    await client.get(f"{self.base_url}/delete-cookie")
                    client.export_cookies()
                finally:
                    await client.close_client()
                self.assertEqual([], list(cookie_jar))

            with self.subTest(client_type=client_type, response="redirect"):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("old", "/"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/redirect-delete-cookie")
                    client.export_cookies()
                finally:
                    await client.close_client()
                self.assertEqual("", response.text)
                self.assertEqual([], list(cookie_jar))

    async def test_all_backends_keep_request_cookies_local_to_one_request(self) -> None:
        """Per-request mapping cookies are sent once without entering the session jar."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("jar", "/"))
                cookie_jar.set_cookie(scoped_cookie("kept", "/", name="persistent"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    response = await client.get(
                        f"{self.base_url}/echo-cookie",
                        cookies={"explicit": "yes"},
                    )
                    next_response = await client.get(f"{self.base_url}/echo-cookie")
                finally:
                    await client.close_client()

                cookies = SimpleCookie(response.text)
                self.assertEqual("jar", cookies["session"].value)
                self.assertEqual("kept", cookies["persistent"].value)
                self.assertEqual("yes", cookies["explicit"].value)
                next_cookies = SimpleCookie(next_response.text)
                self.assertEqual("jar", next_cookies["session"].value)
                self.assertEqual("kept", next_cookies["persistent"].value)
                self.assertNotIn("explicit", next_cookies)

    async def test_aiohttp_passes_request_cookie_mapping_through_unchanged(self) -> None:
        """The wrapper leaves request-level Cookie mapping semantics to aiohttp."""

        cookies = {"explicit": "a;b"}
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0)
        await client.init_client()
        try:
            prepared = client.client.prepare_request_params(cookies=cookies)
            response = await client.get(f"{self.base_url}/echo-cookie", cookies=cookies)
        finally:
            await client.close_client()

        self.assertIs(cookies, prepared["cookies"])
        self.assertEqual("a;b", SimpleCookie(response.text)["explicit"].value)

    async def test_cookie_header_and_cookies_argument_are_mutually_exclusive(self) -> None:
        """Two explicit request-cookie sources must fail instead of silently dropping one."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    for cookie_headers in (
                        {"Cookie": "manual=yes"},
                        {b"Cookie": b"manual=yes"},
                    ):
                        header_type = type(next(iter(cookie_headers)))
                        with self.subTest(header_type=header_type, entrypoint="request"):
                            with self.assertRaisesRegex(ValueError, "Cookie header"):
                                await client.get(
                                    f"{self.base_url}/echo-cookie",
                                    headers=cookie_headers,
                                    cookies={"explicit": "yes"},
                                )

                        with self.subTest(header_type=header_type, entrypoint="stream"):
                            with self.assertRaisesRegex(ValueError, "Cookie header"):
                                async with client.stream(
                                    HttpMethod.GET,
                                    f"{self.base_url}/echo-cookie",
                                    headers=cookie_headers,
                                    cookies={"explicit": "yes"},
                                ):
                                    pass

                        with self.subTest(header_type=header_type, entrypoint="reconnect_stream"):
                            with self.assertRaisesRegex(ValueError, "Cookie header"):
                                async with client.reconnect_stream(
                                    HttpMethod.GET,
                                    f"{self.base_url}/echo-cookie",
                                    headers=cookie_headers,
                                    cookies={"explicit": "yes"},
                                ):
                                    pass
                finally:
                    await client.close_client()

    async def test_manual_cookie_header_remains_user_controlled(self) -> None:
        """The wrapper must not reject a manual header or take redirect control away."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("jar", "/", name="persistent"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    direct = await client.get(
                        f"{self.base_url}/echo-cookie",
                        headers={"Cookie": 'manual="a;b"'},
                    )
                    followed = await client.get(
                        f"{self.base_url}/redirect-nested",
                        headers={"Cookie": "manual=yes"},
                        follow_redirects=True,
                    )
                    authenticated_redirect = await client.get(
                        f"{self.base_url}/redirect-set-cookie",
                        headers={"Cookie": "manual=yes"},
                        follow_redirects=True,
                    )
                    not_followed = await client.get(
                        f"{self.base_url}/redirect-nested",
                        headers={"Cookie": "manual=yes"},
                        follow_redirects=False,
                    )
                finally:
                    await client.close_client()

                self.assertEqual("a;b", SimpleCookie(direct.text)["manual"].value)
                self.assertEqual(f"{self.base_url}/nested/echo-cookie", followed.url)
                self.assertEqual("yes", SimpleCookie(authenticated_redirect.text)["redirected"].value)
                self.assertEqual(302, not_followed.status_code)
                self.assertEqual(f"{self.base_url}/redirect-nested", not_followed.url)

    async def test_browser_cookie_file_remains_persistent_across_redirects(self) -> None:
        """A loaded MozillaCookieJar stays usable and saveable as the client session jar."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type), tempfile.TemporaryDirectory() as directory:
                cookie_file = Path(directory, "cookies.txt")
                cookie_file.write_text(
                    "# Netscape HTTP Cookie File\n"
                    "127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tbrowser\tsaved\n"
                    '127.0.0.1\tFALSE\t/\tFALSE\t2147483647\ttoken\t"a;b"\n',
                    encoding="utf-8",
                )
                cookie_jar = MozillaCookieJar(cookie_file)
                cookie_jar.load(ignore_discard=True, ignore_expires=True)
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    quoted = await client.get(
                        f"{self.base_url}/echo-cookie",
                        cookies={"explicit": "yes"},
                    )
                    redirected = await client.get(f"{self.base_url}/redirect-nested")
                    await client.get(f"{self.base_url}/json")
                    client.save_cookies()
                finally:
                    await client.close_client()

                quoted_cookies = SimpleCookie(quoted.text)
                self.assertEqual("a;b", quoted_cookies["token"].value)
                self.assertEqual("yes", quoted_cookies["explicit"].value)
                self.assertEqual("saved", SimpleCookie(redirected.text)["browser"].value)
                reloaded = MozillaCookieJar(cookie_file)
                reloaded.load(ignore_discard=True, ignore_expires=True)
                self.assertEqual(
                    {"browser": "saved", "session": "abc", "token": '"a;b"'},
                    {cookie.name: cookie.value for cookie in reloaded},
                )

    async def test_aiohttp_exports_native_cookie_state_when_saving(self) -> None:
        """Saving exports native aiohttp state before writing the external jar."""

        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory, "cookies.txt")
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n"
                "127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tbrowser\tsaved\n"
                "#HttpOnly_127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tsecret\tprivate\n"
                ".example.test\tTRUE\t/nested\tTRUE\t2147483647\tdomain-cookie\twide\n",
                encoding="utf-8",
            )
            cookie_jar = MozillaCookieJar(cookie_file)
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            client = MultiHttpClient(
                ClientType.AIOHTTP,
                max_connections=2,
                user_agent="Oldman-Test/1",
                retry_count=0,
                cookie_jar=cookie_jar,
            )
            await client.init_client()
            try:
                await client.get(f"{self.base_url}/json")
                self.assertEqual(
                    {"browser", "domain-cookie", "secret"},
                    {cookie.name for cookie in cookie_jar},
                )
                client.save_cookies()
            finally:
                await client.close_client()

            reloaded = MozillaCookieJar(cookie_file)
            reloaded.load(ignore_discard=True, ignore_expires=True)
            self.assertEqual(
                {
                    "browser": "saved",
                    "domain-cookie": "wide",
                    "secret": "private",
                    "session": "abc",
                },
                {cookie.name: cookie.value for cookie in reloaded},
            )
            secret = next(cookie for cookie in reloaded if cookie.name == "secret")
            self.assertTrue(secret.has_nonstandard_attr(HTTP_ONLY_ATTR))
            domain_cookie = next(cookie for cookie in reloaded if cookie.name == "domain-cookie")
            self.assertEqual(".example.test", domain_cookie.domain)
            self.assertTrue(domain_cookie.domain_specified)
            self.assertTrue(domain_cookie.domain_initial_dot)
            self.assertEqual("/nested", domain_cookie.path)
            self.assertTrue(domain_cookie.secure)
            self.assertEqual(2147483647, domain_cookie.expires)

    async def test_aiohttp_can_explicitly_export_native_state_to_a_plain_cookie_jar(self) -> None:
        """A plain external CookieJar can receive native state before close."""

        cookie_jar = CookieJar()
        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
            cookie_jar=cookie_jar,
        )
        await client.init_client()
        try:
            await client.get(f"{self.base_url}/json")
            self.assertEqual([], list(cookie_jar))
            exported = client.export_cookies()
        finally:
            await client.close_client()

        self.assertIs(cookie_jar, exported)
        self.assertEqual({"session": "abc"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_aiohttp_exports_native_cookie_state_when_closing(self) -> None:
        """Closing the wrapper writes native state back to its external CookieJar."""

        cookie_jar = CookieJar()
        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
            cookie_jar=cookie_jar,
        )
        await client.init_client()
        try:
            await client.get(f"{self.base_url}/json")
            self.assertEqual([], list(cookie_jar))
        finally:
            await client.close_client()

        self.assertEqual({"session": "abc"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_request_cookiejar_must_be_configured_on_the_client(self) -> None:
        """A scoped stdlib jar is client state, not a request-level cookie mapping."""

        request_cookies = CookieJar()
        request_cookies.set_cookie(scoped_cookie("request", "/"))
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    with self.assertRaisesRegex(TypeError, "cookie_jar"):
                        await client.get(f"{self.base_url}/echo-cookie", cookies=request_cookies)

                    with self.assertRaisesRegex(TypeError, "cookie_jar"):
                        async with client.stream(
                            HttpMethod.GET,
                            f"{self.base_url}/echo-cookie",
                            cookies=request_cookies,
                        ):
                            pass

                    with self.assertRaisesRegex(TypeError, "cookie_jar"):
                        async with client.reconnect_stream(
                            HttpMethod.GET,
                            f"{self.base_url}/echo-cookie",
                            cookies=request_cookies,
                        ):
                            pass
                finally:
                    await client.close_client()

    async def test_client_cookiejar_does_not_leak_path_cookie_after_redirect(self) -> None:
        """Every backend must preserve a client-level CookieJar's path selection."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cookie_jar = CookieJar()
                cookie_jar.set_cookie(scoped_cookie("nested", "/nested"))
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/nested/redirect-root")
                finally:
                    await client.close_client()

                self.assertEqual("", response.text)

    async def test_request_cookies_do_not_become_session_cookies(self) -> None:
        """A per-request cookie is not retained by the selected backend session."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    explicit = await client.get(
                        f"{self.base_url}/echo-cookie",
                        cookies={"request-only": "yes"},
                    )
                    empty = await client.get(f"{self.base_url}/echo-cookie")
                    await client.get(f"{self.base_url}/json")
                    persisted = await client.get(f"{self.base_url}/echo-cookie")
                finally:
                    await client.close_client()

                self.assertEqual("request-only=yes", explicit.text)
                self.assertEqual("", empty.text)
                if client_type == ClientType.AIOHTTP:
                    # aiohttp intentionally rejects cookies set by an IP host
                    # unless its native CookieJar is configured as unsafe.
                    self.assertEqual("", persisted.text)
                else:
                    self.assertEqual("session=abc", persisted.text)

    async def test_aiohttp_without_external_state_still_uses_its_native_cookie_jar(self) -> None:
        """Omitting cookie_jar disables persistence, not aiohttp session cookies."""

        base_url = self.base_url.replace("127.0.0.1", "localhost")
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0)
        await client.init_client()
        try:
            await client.get(f"{base_url}/json")
            persisted = await client.get(f"{base_url}/echo-cookie")
        finally:
            await client.close_client()

        self.assertEqual("session=abc", persisted.text)

    async def test_curl_localhost_cookies_work_without_mutating_canonical_scope(self) -> None:
        """The curl adapter restores native localhost behavior in request-only state."""

        base_url = self.base_url.replace("127.0.0.1", "localhost")
        cookie_jar = CookieJar()
        client = MultiHttpClient(
            ClientType.CURL_CFFI,
            retry_count=0,
            cookie_jar=cookie_jar,
        )
        await client.init_client()
        try:
            await client.get(f"{base_url}/json")
            persisted = await client.get(f"{base_url}/echo-cookie")
            explicit = await client.get(
                f"{base_url}/echo-cookie",
                cookies={"request-only": "yes"},
            )
            after_explicit = await client.get(f"{base_url}/echo-cookie")
            manual = await client.get(
                f"{base_url}/echo-cookie",
                headers={"Cookie": "manual=yes"},
            )
        finally:
            await client.close_client()

        self.assertEqual("abc", SimpleCookie(persisted.text)["session"].value)
        explicit_cookies = SimpleCookie(explicit.text)
        self.assertEqual("abc", explicit_cookies["session"].value)
        self.assertEqual("yes", explicit_cookies["request-only"].value)
        self.assertNotIn("request-only", SimpleCookie(after_explicit.text))
        self.assertEqual("yes", SimpleCookie(manual.text)["manual"].value)
        [canonical] = list(cookie_jar)
        self.assertEqual("localhost.local", canonical.domain)
        self.assertFalse(canonical.domain_specified)

    async def test_aiohttp_custom_middleware_keeps_native_cookie_state(self) -> None:
        """A request middleware cannot bypass native Cookie updates or force live export."""

        cookie_jar = CookieJar()
        sync_states: list[bool] = []

        async def passthrough(request, handler):
            """Forward one aiohttp request without changing it."""

            response = await handler(request)
            sync_states.append(bool(cookie_jar))
            return response

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
            cookie_jar=cookie_jar,
        )
        await client.init_client()
        try:
            await client.get(
                f"{self.base_url}/json",
                middlewares=(passthrough,),
            )
            persisted = await client.get(f"{self.base_url}/echo-cookie")
            self.assertEqual([], list(cookie_jar))
            client.export_cookies()
        finally:
            await client.close_client()

        self.assertEqual([False], sync_states)
        self.assertEqual("session=abc", persisted.text)
        self.assertEqual({"session": "abc"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_all_backends_reuse_user_cookies_and_session_cookies_for_retry(self) -> None:
        """A framework retry reuses user input and the backend's updated session jar."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.retry_cookie_headers = []
                cookie_jar = CookieJar()
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=1,
                    retry_backoff_factor=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    response = await client.get(
                        f"{self.base_url}/retry-cookie",
                        cookies={"request-only": "yes"},
                    )
                    client.export_cookies()
                finally:
                    await client.close_client()

                first = SimpleCookie(self.retry_cookie_headers[0])
                second = SimpleCookie(response.text)
                self.assertNotIn("retry", first)
                self.assertEqual("yes", first["request-only"].value)
                self.assertEqual("server", second["retry"].value)
                self.assertEqual("yes", second["request-only"].value)
                self.assertEqual({"retry": "server"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_reconnect_stream_resumes_after_a_partial_body(self) -> None:
        """A read failure must resume from the last byte yielded to the caller."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.disconnect_attempts = 0
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=2,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/disconnect-once") as stream:
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(4)])
                finally:
                    await client.close_client()

                self.assertEqual(RANGE_BODY, body)
                self.assertEqual(1, self.disconnect_attempts)

    async def test_reconnect_reuses_user_cookie_and_exports_the_server_cookie(self) -> None:
        """A real reconnect keeps explicit input and can export the server cookie separately."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.reconnect_cookie_headers = []
                cookie_jar = CookieJar()
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=2,
                    retry_backoff_factor=0,
                    cookie_jar=cookie_jar,
                )
                await client.init_client()
                try:
                    async with client.reconnect_stream(
                        HttpMethod.GET,
                        f"{self.base_url}/cookie-disconnect-once",
                        cookies={"session": "request"},
                    ) as stream:
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(4)])
                    client.export_cookies()
                finally:
                    await client.close_client()

                self.assertEqual(RANGE_BODY, body)
                self.assertEqual(2, len(self.reconnect_cookie_headers))
                self.assertEqual(
                    ["request", "request"],
                    [SimpleCookie(value)["session"].value for value in self.reconnect_cookie_headers],
                )
                self.assertEqual({"session": "server"}, {cookie.name: cookie.value for cookie in cookie_jar})

    async def test_resume_uses_if_range_and_rejects_a_changed_strong_etag(self) -> None:
        """A resumed body must belong to the same strongly validated representation."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/etag-disconnect") as stream:
                    _ = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

        self.assertEqual((None, None), self.etag_requests[0])
        self.assertEqual(("bytes=6-", '"version-1"'), self.etag_requests[1])

    async def test_retryable_error_etag_is_not_reused_for_a_successful_body(self) -> None:
        """An error-page validator must never become If-Range for later content."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=3,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            async with client.reconnect_stream(
                HttpMethod.GET,
                f"{self.base_url}/stale-etag-disconnect",
            ) as stream:
                body = b"".join([chunk async for chunk in stream.aiter_bytes(16)])
        finally:
            await client.close_client()

        self.assertEqual(RANGE_BODY, body)
        self.assertEqual(
            [(None, None), (None, None), ("bytes=5-", None)],
            self.stale_etag_requests,
        )

    async def test_clean_short_206_resumes_from_the_delivered_offset(self) -> None:
        """A clean EOF cannot complete a body shorter than its Content-Range."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            async with client.reconnect_stream(
                HttpMethod.GET,
                f"{self.base_url}/short-range",
                headers={"Range": "bytes=0-"},
            ) as stream:
                body = b"".join([chunk async for chunk in stream.aiter_bytes(4)])
        finally:
            await client.close_client()

        self.assertEqual(RANGE_BODY, body)
        self.assertEqual(["bytes=0-", "bytes=10-"], self.short_ranges)

    async def test_unsolicited_206_adopts_its_actual_interval_before_resuming(self) -> None:
        """A valid initial 206 without a request Range resumes only that interval."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.unsolicited_ranges = []
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=2,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    async with client.reconnect_stream(
                        HttpMethod.GET,
                        f"{self.base_url}/unsolicited-partial",
                    ) as stream:
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(16)])
                finally:
                    await client.close_client()

                self.assertEqual(RANGE_BODY[10:16], body)
                self.assertEqual([None, "bytes=13-15"], self.unsolicited_ranges)

    async def test_complete_unsolicited_206_without_content_range_is_accepted(self) -> None:
        """A nonconforming but complete initial 206 remains usable without resume."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    async with client.reconnect_stream(
                        HttpMethod.GET,
                        f"{self.base_url}/unsolicited-partial-no-range",
                    ) as stream:
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(16)])
                        self.assertFalse(stream.supports_range)
                finally:
                    await client.close_client()
                self.assertEqual(b"partial", body)

    async def test_206_body_cannot_exceed_its_declared_content_range(self) -> None:
        """A reconnecting stream must not yield bytes outside the validated range."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(
                    HttpMethod.GET,
                    f"{self.base_url}/overlong-range",
                    headers={"Range": "bytes=0-9"},
                ) as stream:
                    _ = b"".join([chunk async for chunk in stream.aiter_bytes(4)])
        finally:
            await client.close_client()

    async def test_live_stream_reconnects_without_range_after_a_read_failure(self) -> None:
        """Every backend preserves pending live bytes and reconnects as a fresh GET."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.live_headers = []
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=2,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    async with client.reconnect_stream(
                        HttpMethod.GET,
                        f"{self.base_url}/live-disconnect",
                        live_stream=True,
                        headers={"Range": "bytes=100-", "If-Range": '"caller-value"'},
                    ) as stream:
                        # 大于断线前正文，覆盖代理使用大块读取时的 pending-byte 边界。
                        body = b"".join([chunk async for chunk in stream.aiter_bytes(2 * 1024 * 1024)])
                finally:
                    await client.close_client()

                self.assertEqual(b"firstsecond", body)
                self.assertEqual([(None, None), (None, None)], self.live_headers)

    async def test_live_reconnect_never_appends_error_pages_and_uses_one_budget(self) -> None:
        """Read failure and error responses share retries without yielding error bodies."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                self.live_error_attempts = 0
                body = bytearray()
                client = MultiHttpClient(
                    client_type,
                    retry_count=2,
                    retry_backoff_factor=0,
                )
                await client.init_client()
                try:
                    with self.assertRaises(HttpStatusError) as raised:
                        async with client.reconnect_stream(
                            HttpMethod.GET,
                            f"{self.base_url}/live-error-after-disconnect",
                            live_stream=True,
                        ) as stream:
                            async for chunk in stream.aiter_bytes(1024):
                                body.extend(chunk)
                finally:
                    await client.close_client()

                self.assertEqual(500, raised.exception.status_code)
                self.assertEqual(b"part", body)
                self.assertNotIn(b"error-page", body)
                self.assertEqual(3, self.live_error_attempts)

    async def test_all_backends_preserve_raw_and_decoded_content(self) -> None:
        """Buffered and streaming APIs expose raw and decoded gzip/deflate bytes."""

        compressed = gzip.compress(STREAM_BODY, mtime=0)
        deflated = zlib.compress(STREAM_BODY)
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                    content_decoding=True,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/encoded")
                    self.assertEqual(STREAM_BODY, response.content)
                    self.assertEqual(compressed, response.raw_content())

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/encoded") as stream:
                        self.assertEqual(compressed, await stream.raw_content())
                        self.assertEqual(STREAM_BODY, await stream.aread())

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/encoded") as stream:
                        decoded = b"".join([chunk async for chunk in stream.aiter_bytes(3)])
                        self.assertEqual(STREAM_BODY, decoded)

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/encoded") as stream:
                        raw = b"".join([chunk async for chunk in stream.aiter_raw(3)])
                        self.assertEqual(compressed, raw)

                    deflate_response = await client.get(f"{self.base_url}/deflate")
                    self.assertEqual(deflated, deflate_response.raw_content())
                    self.assertEqual(STREAM_BODY, deflate_response.content)

                    async with client.stream(HttpMethod.GET, f"{self.base_url}/deflate") as stream:
                        self.assertEqual(deflated, await stream.raw_content())
                        self.assertEqual(STREAM_BODY, await stream.aread())
                finally:
                    await client.close_client()

    async def test_all_backends_preserve_same_name_cookie_scope(self) -> None:
        """The canonical CookieJar must not collapse cookies by name."""

        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(
                    client_type,
                    max_connections=2,
                    user_agent="Oldman-Test/1",
                    retry_count=0,
                )
                await client.init_client()
                try:
                    response = await client.get(f"{self.base_url}/cookies")
                finally:
                    await client.close_client()

                self.assertEqual(
                    {
                        ("session", "/", "root", True, None, None, True),
                        ("session", "/nested", "nested", False, "Lax", "High", False),
                    },
                    {
                        (
                            cookie.name,
                            cookie.path,
                            cookie.value,
                            cookie.has_nonstandard_attr("HttpOnly"),
                            cookie.get_nonstandard_attr("SameSite"),
                            cookie.get_nonstandard_attr("Priority"),
                            cookie.has_nonstandard_attr("Partitioned"),
                        )
                        for cookie in response.cookies
                    },
                )

    async def test_aiohttp_native_jar_selects_the_most_specific_same_name_cookie(self) -> None:
        """The aiohttp transport keeps its native single-name selection behavior."""

        cookie_jar = CookieJar()
        cookie_jar.set_cookie(scoped_cookie("root", "/"))
        cookie_jar.set_cookie(scoped_cookie("nested", "/nested"))
        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
            cookie_jar=cookie_jar,
        )
        await client.init_client()
        try:
            root = await client.get(f"{self.base_url}/echo-cookie")
            nested = await client.get(f"{self.base_url}/nested/echo-cookie")
        finally:
            await client.close_client()

        self.assertEqual("session=root", root.text)
        self.assertEqual("session=nested", nested.text)

    async def test_bounded_range_keeps_its_end_when_resuming(self) -> None:
        """A reconnect must not turn an explicit bounded range into an open range."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            async with client.reconnect_stream(
                HttpMethod.GET,
                f"{self.base_url}/bounded-disconnect-once",
                headers={"Range": "bytes=5-12"},
            ) as stream:
                body = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

        self.assertEqual(RANGE_BODY[5:13], body)
        # 断线时已经从 backend 读取的第三个字节必须先交付，再按下一个位置续传。
        self.assertEqual(["bytes=5-12", "bytes=8-12"], self.bounded_ranges)

    async def test_resume_rejects_an_origin_that_ignores_range(self) -> None:
        """A full 200 response must never be appended after a partial body."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/ignore-resume") as stream:
                    _ = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

        self.assertEqual(1, self.ignore_resume_attempts)

    async def test_suffix_range_uses_the_first_content_range_for_resume(self) -> None:
        """A suffix range must become an absolute range only after the first 206."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            async with client.reconnect_stream(
                HttpMethod.GET,
                f"{self.base_url}/suffix-disconnect-once",
                headers={"Range": "bytes=-8"},
            ) as stream:
                body = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

        self.assertEqual(RANGE_BODY[-8:], body)
        self.assertEqual(["bytes=-8", "bytes=21-"], self.suffix_ranges)

    async def test_suffix_range_rejects_a_different_interval(self) -> None:
        """A suffix response must contain exactly the last requested N bytes."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(
                    HttpMethod.GET,
                    f"{self.base_url}/wrong-suffix",
                    headers={"Range": "bytes=-8"},
                ):
                    pass
        finally:
            await client.close_client()

    async def test_resume_rejects_a_mismatched_content_range(self) -> None:
        """A wrong 206 start offset must not be appended to delivered bytes."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/mismatch-resume") as stream:
                    _ = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

    async def test_resume_rejects_a_changed_resource_length(self) -> None:
        """A changed total length must not be appended to an earlier partial body."""

        client = MultiHttpClient(
            ClientType.AIOHTTP,
            max_connections=2,
            user_agent="Oldman-Test/1",
            retry_count=2,
            retry_backoff_factor=0,
        )
        await client.init_client()
        try:
            with self.assertRaises(HttpRangeError):
                async with client.reconnect_stream(HttpMethod.GET, f"{self.base_url}/changed-total-resume") as stream:
                    _ = b"".join([chunk async for chunk in stream.aiter_bytes(2)])
        finally:
            await client.close_client()

    async def test_tls_verification_is_secure_by_default_and_constructor_scoped(self) -> None:
        """All backends reject a self-signed server unless explicitly opted out."""

        tls_requests = 0

        async def tls_response(request: web.Request) -> web.Response:
            """Count application requests that completed the TLS handshake."""

            nonlocal tls_requests
            del request
            tls_requests += 1
            return web.Response(status=200, text="secure")

        with tempfile.TemporaryDirectory() as directory:
            app = web.Application()
            app.router.add_get("/secure", tls_response)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(
                runner,
                "127.0.0.1",
                0,
                ssl_context=self_signed_server_context(Path(directory)),
            )
            await site.start()
            assert site._server is not None
            server = cast(asyncio.Server, site._server)
            port = server.sockets[0].getsockname()[1]
            url = f"https://127.0.0.1:{port}/secure"
            loop = asyncio.get_running_loop()
            previous_exception_handler = loop.get_exception_handler()
            loop.set_exception_handler(lambda _loop, _context: None)
            try:
                for client_type in ClientType:
                    with self.subTest(client_type=client_type, verify=True):
                        client = MultiHttpClient(client_type, retry_count=0)
                        await client.init_client()
                        try:
                            with self.assertRaises(TLS_VERIFY_ERRORS):
                                await client.get(url)
                            if client_type == ClientType.CURL_CFFI:
                                # curl_cffi 的极短 TLS 失败曾在复用 session 时
                                # 产生空 URL 响应；连续两次必须仍抛原始传输错误。
                                for _attempt in range(2):
                                    with self.assertRaises(TLS_VERIFY_ERRORS):
                                        async with client.stream(HttpMethod.GET, url):
                                            pass
                        finally:
                            await client.close_client()

                    with self.subTest(client_type=client_type, verify=False):
                        client = MultiHttpClient(client_type, retry_count=0, verify=False)
                        await client.init_client()
                        try:
                            response = await client.get(url)
                            self.assertEqual("secure", response.text)
                            with self.assertRaisesRegex(TypeError, "构造 MultiHttpClient"):
                                await client.get(url, verify=False)
                            with self.assertRaisesRegex(TypeError, "构造 MultiHttpClient"):
                                async with client.stream(HttpMethod.GET, url, verify=False):
                                    pass
                            with self.assertRaisesRegex(TypeError, "构造 MultiHttpClient"):
                                async with client.reconnect_stream(HttpMethod.GET, url, verify=False):
                                    pass
                        finally:
                            await client.close_client()

                # Stream 和 reconnect 共用 MultiHttpClient 的 TLS/重试路径，
                # 另用全新 backend 验证它们不会执行历史上的 HTTPS 降级。
                for entrypoint in ("stream", "reconnect_stream"):
                    with self.subTest(entrypoint=entrypoint):
                        client = MultiHttpClient(ClientType.HTTPX, retry_count=0)
                        await client.init_client()
                        try:
                            with self.assertRaises(TLS_VERIFY_ERRORS):
                                if entrypoint == "stream":
                                    async with client.stream(HttpMethod.GET, url):
                                        pass
                                else:
                                    async with client.reconnect_stream(HttpMethod.GET, url):
                                        pass
                        finally:
                            await client.close_client()
            finally:
                await runner.cleanup()
                # TLS handshake failures may schedule their server-side callback
                # one event-loop turn after the client has already received its error.
                await asyncio.sleep(0)
                loop.set_exception_handler(previous_exception_handler)

        self.assertEqual(len(ClientType), tls_requests)

    async def test_curl_stream_close_interrupts_download_and_keeps_session_usable(self) -> None:
        """Closing curl after one chunk must be prompt and leave its pool reusable."""

        client = MultiHttpClient(
            ClientType.CURL_CFFI,
            max_connections=1,
            user_agent="Oldman-Test/1",
            retry_count=0,
        )
        await client.init_client()
        try:
            started = time.perf_counter()
            async with client.stream(HttpMethod.GET, f"{self.base_url}/slow-stream") as stream:
                iterator = stream.aiter_raw()
                self.assertEqual(b"first", await anext(iterator))
                await asyncio.wait_for(stream.aclose(), timeout=0.5)
            elapsed = time.perf_counter() - started
            self.slow_stream_release.set()

            response = await asyncio.wait_for(client.get(f"{self.base_url}/json"), timeout=1.0)
            self.assertEqual(201, response.status_code)
            self.assertLess(elapsed, 0.5)
        finally:
            self.slow_stream_release.set()
            await client.close_client()


if __name__ == "__main__":
    unittest.main()
