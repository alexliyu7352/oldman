"""Backend-neutral HTTP response objects."""

from __future__ import annotations

import codecs
import copy
import json as jsonlib
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Mapping
from email.message import Message
from http.cookiejar import CookieJar
from typing import Any, Protocol, cast
from urllib.request import Request

from .exceptions import HttpContentDecodingError, HttpStatusError, HttpStreamConsumedError

HeaderItems = Iterable[tuple[str | bytes, str | bytes | None]]
AsyncBytesFactory = Callable[[], AsyncIterator[bytes]]
AsyncClose = Callable[[], Awaitable[None]]


def _to_text(value: str | bytes | None) -> str:
    """Normalize a backend header value without losing byte values."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def _resolve_encoding(explicit: str | None, headers: HttpHeaders) -> str:
    """Resolve response encoding from explicit metadata or Content-Type."""

    if explicit:
        return explicit

    content_type = headers.get("content-type")
    if content_type:
        message = Message()
        message["content-type"] = content_type
        charset = message.get_content_charset()
        if charset:
            return charset
    return "utf-8"


def _decode(content: bytes, encoding: str) -> str:
    """Decode content and fall back to UTF-8 for an unknown codec name."""

    try:
        return content.decode(encoding, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def _validate_chunk_size(chunk_size: int | None) -> None:
    """Reject chunk sizes that cannot make progress."""

    if chunk_size is not None and chunk_size <= 0:
        raise ValueError("chunk_size 必须为正整数或 None")


async def _rechunk(source: AsyncIterator[bytes], chunk_size: int | None) -> AsyncIterator[bytes]:
    """Apply a stable chunk-size contract over backend-specific iterators."""

    _validate_chunk_size(chunk_size)
    if chunk_size is None:
        async for chunk in source:
            if chunk:
                yield bytes(chunk)
        return

    pending = bytearray()
    try:
        async for chunk in source:
            if not chunk:
                continue
            pending.extend(chunk)
            offset = 0
            while len(pending) - offset >= chunk_size:
                yield bytes(memoryview(pending)[offset : offset + chunk_size])
                offset += chunk_size
            if offset:
                # 每个 backend chunk 最多移动一次余数，避免小 chunk_size 时反复删除头部。
                pending = pending[offset:]
    except Exception:
        # backend 已读取的正文必须先交付，续传偏移才能与实际输出保持一致。
        if pending:
            yield bytes(pending)
        raise
    if pending:
        yield bytes(pending)


class HttpHeaders(Mapping[str, str]):
    """Immutable, case-insensitive HTTP headers that retain duplicates."""

    def __init__(self, headers: HeaderItems | Mapping[str, str] | None = None) -> None:
        """Copy headers into a lowercase, backend-independent representation."""

        items: HeaderItems
        if isinstance(headers, HttpHeaders):
            items = headers.multi_items()
        elif isinstance(headers, Mapping):
            mapping = cast(Mapping[str | bytes, str | bytes | None], headers)
            items = mapping.items()
        else:
            items = headers or ()
        self._items = tuple((_to_text(key).lower(), _to_text(value)) for key, value in items)

        keys: list[str] = []
        values: dict[str, list[str]] = {}
        for key, value in self._items:
            if key not in values:
                keys.append(key)
                values[key] = []
            values[key].append(value)
        self._keys = tuple(keys)
        self._values = {key: tuple(items) for key, items in values.items()}

    def __getitem__(self, key: str) -> str:
        """Return all values for one header joined with a comma."""

        values = self._values[key.lower()]
        return ", ".join(values)

    def __iter__(self) -> Iterator[str]:
        """Iterate unique lowercase header names in wire order."""

        return iter(self._keys)

    def __len__(self) -> int:
        """Return the number of unique header names."""

        return len(self._keys)

    def __repr__(self) -> str:
        """Return a compact representation useful in request logs."""

        return f"HttpHeaders({self._items!r})"

    def get_list(self, name: str) -> list[str]:
        """Return every value associated with a header name."""

        return list(self._values.get(name.lower(), ()))

    def multi_items(self) -> list[tuple[str, str]]:
        """Return header pairs without joining duplicate values."""

        return list(self._items)

    def copy(self) -> HttpHeaders:
        """Return an independent immutable headers object."""

        return type(self)(self._items)


class _ContentDecoder(Protocol):
    """Minimal incremental decoder used by buffered and streaming bodies."""

    def decode(self, data: bytes) -> bytes:
        """Decode one encoded body fragment."""

        ...

    def flush(self) -> bytes:
        """Finish decoding and return buffered output."""

        ...


class _IdentityDecoder:
    """Pass through response bytes when decoding is disabled or unnecessary."""

    def decode(self, data: bytes) -> bytes:
        """Return the input unchanged."""

        return data

    def flush(self) -> bytes:
        """Identity decoding has no buffered tail."""

        return b""


class _ZLibMemberDecoder:
    """Strictly decode every member that uses one fixed zlib wrapper mode."""

    def __init__(self, mode: int, encoding: str) -> None:
        """Create the first member decoder and remember its error label."""

        self._mode = mode
        self._encoding = encoding
        self._decompressor = zlib.decompressobj(mode)

    def decode(self, data: bytes) -> bytes:
        """Decode input and continue through concatenated members."""

        if not data:
            return b""

        output = bytearray()
        pending = data
        while pending:
            # aiohttp 3.14 introduced the same reset rule for a member ending
            # exactly at a network chunk boundary.
            if self._decompressor.eof:
                self._decompressor = zlib.decompressobj(self._mode)
            output.extend(self._decompressor.decompress(pending))
            unused = self._decompressor.unused_data
            if self._decompressor.eof and unused:
                pending = unused
                continue
            break
        return bytes(output)

    def flush(self) -> bytes:
        """Finish the last member and reject a truncated or garbage suffix."""

        tail = self._decompressor.flush()
        if not self._decompressor.eof:
            raise zlib.error(f"incomplete or truncated {self._encoding} stream")
        return tail


class _GZipDecoder:
    """Incrementally decode the standard gzip content encoding."""

    def __init__(self) -> None:
        """Create a zlib decoder configured for a gzip wrapper."""

        self._members = _ZLibMemberDecoder(zlib.MAX_WBITS | 16, "gzip")

    def decode(self, data: bytes) -> bytes:
        """Decode one gzip fragment."""

        return self._members.decode(data)

    def flush(self) -> bytes:
        """Finish the gzip stream and reject a missing trailer."""

        return self._members.flush()


class _DeflateDecoder:
    """Decode both zlib-wrapped and legacy raw deflate responses."""

    def __init__(self) -> None:
        """Delay wrapper selection until the two-byte zlib header is available."""

        self._probe = bytearray()
        self._members: _ZLibMemberDecoder | None = None

    def decode(self, data: bytes) -> bytes:
        """Decode one fragment after selecting zlib-wrapped or raw deflate."""

        if self._members is None:
            self._probe.extend(data)
            if len(self._probe) < 2:
                return b""
            data = bytes(self._probe)
            self._probe.clear()
            self._members = _ZLibMemberDecoder(
                self._wrapper_mode(data[:2]),
                "deflate",
            )
        return self._members.decode(data)

    def flush(self) -> bytes:
        """Finish the selected deflate stream and reject incomplete input."""

        pending = b""
        if self._members is None:
            probe = bytes(self._probe)
            self._probe.clear()
            self._members = _ZLibMemberDecoder(
                self._wrapper_mode(probe[:2]),
                "deflate",
            )
            pending = self._members.decode(probe)
        return pending + self._members.flush()

    @staticmethod
    def _wrapper_mode(header: bytes) -> int:
        """Return zlib mode only when the complete header satisfies RFC 1950."""

        if len(header) == 2:
            cmf, flags = header
            if (cmf & 0x0F) == 8 and (cmf >> 4) <= 7 and ((cmf << 8) | flags) % 31 == 0:
                return zlib.MAX_WBITS
        return -zlib.MAX_WBITS


class _MultiDecoder:
    """Reverse a sequence of Content-Encoding transformations."""

    def __init__(self, decoders: Iterable[_ContentDecoder]) -> None:
        """Store decoders in reverse application order as required by HTTP."""

        self._decoders = tuple(reversed(tuple(decoders)))

    def decode(self, data: bytes) -> bytes:
        """Pass one fragment through every decoder."""

        for decoder in self._decoders:
            data = decoder.decode(data)
        return data

    def flush(self) -> bytes:
        """Flush each decoder and pass its output through the remaining chain."""

        data = b""
        for decoder in self._decoders:
            data = decoder.decode(data) + decoder.flush()
        return data


def _content_encodings(headers: HttpHeaders) -> tuple[str, ...]:
    """Parse all Content-Encoding header values in application order."""

    encodings: list[str] = []
    for value in headers.get_list("content-encoding"):
        encodings.extend(item.strip().lower() for item in value.split(",") if item.strip())
    return tuple(encodings)


def _content_decoder(headers: HttpHeaders, decode_content: bool) -> _ContentDecoder:
    """Create a decoder without relying on backend-private response APIs."""

    if not decode_content:
        return _IdentityDecoder()

    decoders: list[_ContentDecoder] = []
    for encoding in _content_encodings(headers):
        if encoding == "identity":
            decoders.append(_IdentityDecoder())
        elif encoding in {"gzip", "x-gzip"}:
            decoders.append(_GZipDecoder())
        elif encoding == "deflate":
            decoders.append(_DeflateDecoder())
        else:
            raise HttpContentDecodingError(f"不支持的 Content-Encoding: {encoding}")
    if not decoders:
        return _IdentityDecoder()
    if len(decoders) == 1:
        return decoders[0]
    return _MultiDecoder(decoders)


def _decode_content(content: bytes, headers: HttpHeaders, decode_content: bool) -> bytes:
    """Decode one complete body and normalize decoder failures."""

    decoder = _content_decoder(headers, decode_content)
    try:
        return decoder.decode(content) + decoder.flush()
    except zlib.error as exc:
        raise HttpContentDecodingError(f"响应正文解码失败: {exc}") from exc


async def _iter_decoded(
    source: AsyncIterator[bytes],
    headers: HttpHeaders,
    decode_content: bool,
) -> AsyncIterator[bytes]:
    """Incrementally decode raw body fragments."""

    decoder = _content_decoder(headers, decode_content)
    try:
        async for chunk in source:
            decoded = decoder.decode(chunk)
            if decoded:
                yield decoded
        tail = decoder.flush()
        if tail:
            yield tail
    except zlib.error as exc:
        raise HttpContentDecodingError(f"响应正文解码失败: {exc}") from exc


class _CookieResponse:
    """Minimal urllib-compatible response exposing repeated Set-Cookie fields."""

    def __init__(self, headers: HttpHeaders) -> None:
        """Copy cookie fields into the email-style interface CookieJar expects."""

        self._headers = Message()
        for value in headers.get_list("set-cookie"):
            self._headers.add_header("Set-Cookie", value)

    def info(self) -> Message:
        """Return response fields for ``CookieJar.extract_cookies``."""

        return self._headers


def cookie_jar_from_headers(headers: HttpHeaders, url: str) -> CookieJar:
    """Let the standard CookieJar parse and validate every Set-Cookie field."""

    jar = CookieJar()
    _apply_cookie_headers(jar, headers, url)
    return jar


def _apply_cookie_headers(jar: CookieJar, headers: HttpHeaders, url: str) -> None:
    """Apply Set-Cookie fields directly so expiry records can remove old values."""

    # typeshed narrows this duck-typed interface to HTTPResponse, while CookieJar only calls info().
    jar.extract_cookies(cast(Any, _CookieResponse(headers)), Request(url))


def copy_cookie_jar(cookies: CookieJar | None) -> CookieJar:
    """Detach response cookies from mutable backend session jars."""

    copied = CookieJar()
    if cookies is None:
        return copied
    for cookie in cookies:
        copied.set_cookie(copy.deepcopy(cookie))
    return copied


class HttpResponse:
    """Fully buffered response returned by every HTTP backend."""

    def __init__(
        self,
        *,
        status_code: int,
        url: str,
        headers: HeaderItems | Mapping[str, str] | HttpHeaders | None = None,
        cookies: CookieJar | None = None,
        raw_content: bytes = b"",
        decode_content: bool = False,
        encoding: str | None = None,
        reason: str = "",
        http_version: str = "",
        native_response: Any = None,
    ) -> None:
        """Store detached metadata plus raw and optionally decoded body bytes."""

        self.status_code = int(status_code)
        self.url = str(url)
        self.headers = headers.copy() if isinstance(headers, HttpHeaders) else HttpHeaders(headers)
        self.cookies = copy_cookie_jar(cookies)
        self._raw_content = bytes(raw_content)
        self._decode_content = decode_content
        self._content: bytes | None = None
        self.encoding = encoding
        self.reason = reason or ""
        self.http_version = http_version or ""
        self.native_response = native_response

    @property
    def text(self) -> str:
        """Decode the buffered response body."""

        return _decode(self.content, _resolve_encoding(self.encoding, self.headers))

    @property
    def content(self) -> bytes:
        """Return the body after the configured Content-Encoding decoding."""

        if self._content is None:
            self._content = _decode_content(self._raw_content, self.headers, self._decode_content)
        return self._content

    @property
    def ok(self) -> bool:
        """Report whether the response is below the HTTP error range."""

        return self.status_code < 400

    @property
    def is_success(self) -> bool:
        """Report whether the response has a successful 2xx status."""

        return 200 <= self.status_code < 300

    @property
    def is_redirect(self) -> bool:
        """Report whether the response has a 3xx status."""

        return 300 <= self.status_code < 400

    def read(self) -> bytes:
        """Return the already-buffered response body."""

        return self.content

    def raw_content(self) -> bytes:
        """Return the complete body before Content-Encoding decoding."""

        return self._raw_content

    def json(self, **kwargs: Any) -> Any:
        """Deserialize the buffered response body as JSON."""

        return jsonlib.loads(self.content, **kwargs)

    def raise_for_status(self) -> HttpResponse:
        """Raise the framework status exception for 4xx and 5xx responses."""

        if 400 <= self.status_code < 600:
            raise HttpStatusError(self)
        return self


class HttpStreamResponse:
    """Streaming response with one asynchronous API for every backend."""

    def __init__(
        self,
        *,
        status_code: int,
        url: str,
        headers: HeaderItems | Mapping[str, str] | HttpHeaders | None = None,
        cookies: CookieJar | None = None,
        decode_content: bool = False,
        encoding: str | None = None,
        reason: str = "",
        http_version: str = "",
        iter_raw: AsyncBytesFactory,
        close: AsyncClose,
        native_response: Any = None,
    ) -> None:
        """Bind normalized metadata to one raw backend body stream."""

        self.status_code = int(status_code)
        self.url = str(url)
        self.headers = headers.copy() if isinstance(headers, HttpHeaders) else HttpHeaders(headers)
        self.cookies = copy_cookie_jar(cookies)
        self.encoding = encoding
        self.reason = reason or ""
        self.http_version = http_version or ""
        self.native_response = native_response

        self._should_decode_content = decode_content
        self._iter_raw = iter_raw
        self._close = close
        self._raw_content: bytes | None = None
        self._content: bytes | None = None
        self._stream_started = False
        self._closed = False

    @property
    def closed(self) -> bool:
        """Report whether the unified response has been closed."""

        return self._closed

    @property
    def ok(self) -> bool:
        """Report whether the response is below the HTTP error range."""

        return self.status_code < 400

    @property
    def is_success(self) -> bool:
        """Report whether the response has a successful 2xx status."""

        return 200 <= self.status_code < 300

    @property
    def is_redirect(self) -> bool:
        """Report whether the response has a 3xx status."""

        return 300 <= self.status_code < 400

    async def aread(self) -> bytes:
        """Read, decode, and cache the complete response body."""

        if self._content is None:
            raw_content = await self.raw_content()
            self._content = _decode_content(raw_content, self.headers, self._should_decode_content)
        return self._content

    async def raw_content(self) -> bytes:
        """Read and cache the complete body before Content-Encoding decoding."""

        if self._raw_content is None:
            chunks = [chunk async for chunk in self._raw_source()]
            self._raw_content = b"".join(chunks)
        return self._raw_content

    async def json(self, **kwargs: Any) -> Any:
        """Read and deserialize the response body as JSON."""

        return jsonlib.loads(await self.aread(), **kwargs)

    async def _claim_raw_source(self) -> AsyncIterator[bytes]:
        """Yield the backend stream exactly once."""

        if self._stream_started:
            raise HttpStreamConsumedError("响应流已经被消费，无法再次读取完整正文")
        if self._closed:
            raise HttpStreamConsumedError("响应流已经关闭，无法读取正文")
        self._stream_started = True
        async for chunk in self._iter_raw():
            if chunk:
                yield bytes(chunk)

    async def _raw_source(self) -> AsyncIterator[bytes]:
        """Replay cached raw bytes or claim the backend stream."""

        if self._raw_content is not None:
            if self._raw_content:
                yield self._raw_content
            return
        async for chunk in self._claim_raw_source():
            yield chunk

    async def _decoded_source(self) -> AsyncIterator[bytes]:
        """Replay cached decoded bytes or decode the raw source incrementally."""

        if self._content is not None:
            if self._content:
                yield self._content
            return
        if self._raw_content is not None:
            self._content = _decode_content(self._raw_content, self.headers, self._should_decode_content)
            if self._content:
                yield self._content
            return
        async for chunk in _iter_decoded(self._claim_raw_source(), self.headers, self._should_decode_content):
            yield chunk

    def aiter_raw(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        """Iterate wire-level bytes with stable optional rechunking."""

        return _rechunk(self._raw_source(), chunk_size)

    def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        """Iterate decoded-content bytes with stable optional rechunking."""

        return _rechunk(self._decoded_source(), chunk_size)

    async def aiter_text(self, chunk_size: int | None = None) -> AsyncIterator[str]:
        """Incrementally decode text without splitting multibyte characters."""

        encoding = _resolve_encoding(self.encoding, self.headers)
        try:
            decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        except LookupError:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        async for chunk in self.aiter_bytes(chunk_size):
            text = decoder.decode(chunk)
            if text:
                yield text
        tail = decoder.decode(b"", final=True)
        if tail:
            yield tail

    async def aiter_lines(self, chunk_size: int | None = None) -> AsyncIterator[str]:
        """Iterate decoded lines across arbitrary backend chunk boundaries."""

        pending = ""
        async for text in self.aiter_text(chunk_size):
            pending += text
            while pending:
                cr = pending.find("\r")
                lf = pending.find("\n")
                positions = [position for position in (cr, lf) if position >= 0]
                if not positions:
                    break

                boundary = min(positions)
                if pending[boundary] == "\r" and boundary == len(pending) - 1:
                    break
                separator_length = 2 if pending[boundary : boundary + 2] == "\r\n" else 1
                yield pending[:boundary]
                pending = pending[boundary + separator_length :]

        if pending.endswith("\r"):
            yield pending[:-1]
        elif pending:
            yield pending

    async def aclose(self) -> None:
        """Close the backend stream exactly once."""

        if self._closed:
            return
        self._closed = True
        await self._close()

    def raise_for_status(self) -> HttpStreamResponse:
        """Raise the framework status exception for 4xx and 5xx responses."""

        if 400 <= self.status_code < 600:
            raise HttpStatusError(self)
        return self


__all__ = [
    "HttpHeaders",
    "HttpResponse",
    "HttpStreamResponse",
    "cookie_jar_from_headers",
    "copy_cookie_jar",
]
