"""A raw TCP HTTP origin for tests that need byte-exact responses.

aiohttp's test server always frames its responses correctly; cut-off bodies, missing chunk
terminators, close-delimited bodies and slow trickles need the bytes written by hand.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

# What an answer may be: the whole response, or pieces written (and flushed) one after another.
Answer = bytes | AsyncIterator[bytes]


class RawOrigin:
    """Answer request number `attempt` (from 1) with `answer(attempt, headers)`, then close the connection.

    Header names are lowercased. Every request's headers are kept in `requests`, in arrival order.
    """

    def __init__(self, answer: Callable[[int, dict[str, str]], Answer | Awaitable[Answer]]) -> None:
        self.answer = answer
        self.requests: list[dict[str, str]] = []
        # time.monotonic() when each connection ended (answer finished, or the peer went away).
        self.ended_at: list[float] = []

    async def _serve_one(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one request head, write the answer, close."""

        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(":") for line in lines[1:] if ":" in line)}
            self.requests.append(headers)
            answer = self.answer(len(self.requests), headers)
            if isinstance(answer, Awaitable):
                answer = await answer
            if isinstance(answer, bytes):
                writer.write(answer)
                await writer.drain()
            else:
                async for piece in answer:
                    writer.write(piece)
                    await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.ended_at.append(time.monotonic())
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    @asynccontextmanager
    async def serve(self) -> AsyncIterator[str]:
        """Listen on 127.0.0.1 and yield the origin's base URL."""

        server = await asyncio.start_server(self._serve_one, "127.0.0.1", 0)
        try:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        finally:
            server.close()
            await server.wait_closed()


def response_head(status: str, headers: dict[str, str | int]) -> bytes:
    """Format a status line and header block."""

    return f"HTTP/1.1 {status}\r\n".encode() + b"".join(f"{name}: {value}\r\n".encode() for name, value in headers.items()) + b"\r\n"


def chunk_frame(data: bytes) -> bytes:
    """Frame one chunk of a chunked body."""

    return f"{len(data):x}\r\n".encode() + data + b"\r\n"


def requested_range(headers: dict[str, str], total: int) -> tuple[int, int] | None:
    """The single byte range a request asks for, resolved against `total`; None without a Range."""

    value = headers.get("range")
    if not value:
        return None
    first, _, last = value.removeprefix("bytes=").partition("-")
    start = int(first)
    end = int(last) if last else total - 1
    return start, min(end, total - 1)
