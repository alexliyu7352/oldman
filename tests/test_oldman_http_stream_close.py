"""Early consumer exits must close the whole streaming iterator chain, not leave it to the GC."""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator
from contextlib import aclosing

from oldman.contrib.http.response import HttpStreamResponse


class SourceProbe:
    """Backend iterator that records whether it was closed and how many chunks it produced."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False
        self.produced = 0

    async def __call__(self) -> AsyncIterator[bytes]:
        try:
            for chunk in self.chunks:
                self.produced += 1
                yield chunk
        finally:
            self.closed = True


def stream_response(probe: SourceProbe, **headers: str) -> HttpStreamResponse:
    async def close() -> None:
        return None

    return HttpStreamResponse(status_code=200, url="http://example.invalid/stream", headers=headers, iter_raw=probe, close=close)


class HttpStreamCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_closing_a_rechunked_iterator_closes_the_backend_source(self) -> None:
        probe = SourceProbe([b"abcdef", b"ghijkl", b"mnopqr"])
        body = stream_response(probe).aiter_bytes(4)

        first = await body.__anext__()
        await body.aclose()

        self.assertEqual(b"abcd", first)
        self.assertTrue(probe.closed)
        self.assertEqual(1, probe.produced)

    async def test_breaking_out_of_aiter_lines_closes_every_layer(self) -> None:
        probe = SourceProbe([b"one\ntwo\n", b"three\n"])
        response = stream_response(probe, **{"Content-Type": "text/plain; charset=utf-8"})

        async with aclosing(response.aiter_lines(4)) as lines:
            async for line in lines:
                self.assertEqual("one", line)
                break

        self.assertTrue(probe.closed)

    async def test_raw_iteration_still_delivers_every_chunk_and_closes_at_the_end(self) -> None:
        probe = SourceProbe([b"ab", b"cd", b"e"])

        delivered = [chunk async for chunk in stream_response(probe).aiter_raw()]

        self.assertEqual([b"ab", b"cd", b"e"], delivered)
        self.assertTrue(probe.closed)
        self.assertEqual(3, probe.produced)


if __name__ == "__main__":
    unittest.main()
