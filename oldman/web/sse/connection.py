"""One-writer connection and backpressure rules for browser SSE streams."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, cast

from oldman.web.sse.events import ServerSentEvent, encode_sse_event

_CLOSE = object()
type SSESessionGuard = Callable[[], Awaitable[str | None]]


class SSEQueueMode(StrEnum):
    """Supported bounded-queue behavior for one browser connection."""

    FIFO = "fifo"
    LATEST = "latest"


class SSEConnectionClosedError(ConnectionError):
    """Raised when business code writes after connection shutdown started."""


class SSEBackpressureError(SSEConnectionClosedError):
    """Raised after a full FIFO queue closes a slow browser connection."""


class SSEWriter(Protocol):
    """Minimal native Sanic response methods owned by the connection writer."""

    async def send(self, data: str, end_stream: bool | None = None) -> None:
        """Write one SSE frame."""

    async def eof(self) -> None:
        """Finish the HTTP response."""


class SSEConnection:
    """Serialize queue events, heartbeat, retry, and EOF through one task."""

    def __init__(
        self,
        response: SSEWriter,
        *,
        queue_mode: SSEQueueMode,
        queue_size: int,
        heartbeat_interval: float,
        retry: int | None,
        session_guard: SSESessionGuard | None = None,
        session_check_interval: float | None = None,
    ) -> None:
        if not isinstance(queue_mode, SSEQueueMode):
            raise TypeError("queue_mode must be an SSEQueueMode")
        if type(queue_size) is not int or queue_size <= 0:
            raise ValueError("queue_size must be a positive integer")
        if queue_mode is SSEQueueMode.LATEST and queue_size != 1:
            raise ValueError("LATEST queues must have queue_size=1")
        if not isinstance(heartbeat_interval, (int, float)) or heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if retry is not None:
            encode_sse_event(ServerSentEvent(retry=retry))
        if session_guard is not None and (not isinstance(session_check_interval, (int, float)) or session_check_interval <= 0):
            raise ValueError("session_check_interval must be positive when a guard is configured")

        self._response = response
        self.queue_mode = queue_mode
        self.queue_size = queue_size
        self.heartbeat_interval = float(heartbeat_interval)
        self.retry = retry
        self._session_guard = session_guard
        self._session_check_interval = float(session_check_interval) if session_check_interval is not None else None
        # One reserved slot guarantees normal/abort sentinels never wait behind a full business queue.
        self._queue: asyncio.Queue[str | object] = asyncio.Queue(maxsize=queue_size + 1)
        self._finishing = False
        self._aborted = False
        self._closed = asyncio.Event()
        self._eof_sent = False

    @property
    def is_closed(self) -> bool:
        """Return whether the writer has completed its cleanup."""
        return self._closed.is_set()

    async def enqueue(self, frame: str) -> None:
        """Add one encoded frame without allowing producers to write the response."""
        self.enqueue_nowait(frame)

    def enqueue_nowait(self, frame: str) -> None:
        """Add one frame without yielding the worker-wide Redis subscriber."""
        if not isinstance(frame, str):
            raise TypeError("frame must be a string")
        if self._finishing or self._aborted or self.is_closed:
            raise SSEConnectionClosedError("SSE connection is closing")

        pending = self._queue.qsize()
        if self.queue_mode is SSEQueueMode.FIFO:
            if pending >= self.queue_size:
                self.abort()
                raise SSEBackpressureError("SSE FIFO queue is full")
        elif pending:
            # The writer has already removed any frame currently being sent, so this only
            # replaces a stale snapshot still waiting in the queue.
            self._queue.get_nowait()

        self._queue.put_nowait(frame)

    def finish(self) -> None:
        """Drain already queued events and then close the connection."""
        if self._finishing or self._aborted or self.is_closed:
            return
        self._finishing = True
        self._queue.put_nowait(_CLOSE)

    def abort(self) -> None:
        """Discard pending events and ask the writer to close promptly."""
        if self._aborted or self.is_closed:
            return
        self._aborted = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(_CLOSE)

    async def wait_closed(self) -> None:
        """Wait until the writer has sent EOF or failed."""
        await self._closed.wait()

    async def run_writer(self) -> None:
        """Write every protocol frame and EOF from this single coroutine."""
        failure: BaseException | None = None
        try:
            loop = asyncio.get_running_loop()
            next_heartbeat = loop.time() + self.heartbeat_interval
            next_session_check = loop.time() if self._session_guard is not None else None

            invalidated = await self._check_session(next_session_check)
            if invalidated is not None:
                await self._response.send(invalidated)
                return
            if next_session_check is not None:
                assert self._session_check_interval is not None
                next_session_check = loop.time() + self._session_check_interval

            if self.retry is not None:
                await self._response.send(encode_sse_event(ServerSentEvent(retry=self.retry)))

            heartbeat = encode_sse_event(ServerSentEvent(comment="heartbeat"))
            while True:
                now = loop.time()
                if next_session_check is not None and now >= next_session_check:
                    invalidated = await self._check_session(next_session_check)
                    if invalidated is not None:
                        await self._response.send(invalidated)
                        break
                    assert self._session_check_interval is not None
                    next_session_check = loop.time() + self._session_check_interval
                    now = loop.time()

                deadline = next_heartbeat
                if next_session_check is not None:
                    deadline = min(deadline, next_session_check)
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=max(0.0, deadline - now),
                    )
                except TimeoutError:
                    if loop.time() >= next_heartbeat:
                        await self._response.send(heartbeat)
                        next_heartbeat = loop.time() + self.heartbeat_interval
                    continue
                if item is _CLOSE:
                    break
                await self._response.send(cast(str, item))
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                await self._send_eof()
            except Exception:
                if failure is None:
                    raise
            finally:
                self._closed.set()

    async def _check_session(self, due_at: float | None) -> str | None:
        """Run the optional guard only when its writer-owned deadline is due."""
        if due_at is None or self._session_guard is None:
            return None
        return await self._session_guard()

    async def _send_eof(self) -> None:
        """Send EOF at most once even when cleanup paths converge."""
        if self._eof_sent:
            return
        self._eof_sent = True
        await self._response.eof()


__all__ = [
    "SSEBackpressureError",
    "SSEConnection",
    "SSEConnectionClosedError",
    "SSEQueueMode",
]
