"""Business-facing API for one browser Server-Sent Events connection."""

from __future__ import annotations

from typing import cast

from oldman.i18n.serialization import _encode_json_with_translations
from oldman.i18n.translations import TranslationCatalog
from oldman.serializers import MsgspecModel
from oldman.web.sse.connection import SSEConnection
from oldman.web.sse.events import ServerSentEvent, encode_sse_event
from oldman.web.sse.pool import SSEConnectionPool
from oldman.web.sse.publisher import validate_event_name, validate_stream_name, validate_user_id


class SSEStream:
    """Send strongly typed JSON through one connection-owned queue."""

    def __init__(
        self,
        connection: SSEConnection,
        *,
        pool: SSEConnectionPool | None = None,
        distributed_enabled: bool = False,
        guarded_user_id: int | None = None,
        translations: TranslationCatalog | None = None,
    ) -> None:
        self._connection = connection
        self._pool = pool
        self._distributed_enabled = distributed_enabled
        self._guarded_user_id = guarded_user_id
        self._translations = translations

    @property
    def translations(self) -> TranslationCatalog | None:
        """Return the translation catalog captured when the connection opened."""
        return self._translations

    @property
    def is_closed(self) -> bool:
        """Return whether the underlying writer has completed."""
        return self._connection.is_closed

    async def send(
        self,
        payload: MsgspecModel,
        *,
        event: str,
        id: str | None = None,
    ) -> None:
        """Encode one strongly typed JSON event and place it in the connection queue."""
        if not isinstance(payload, MsgspecModel):
            raise TypeError("payload must be a MsgspecModel")
        frame = encode_sse_event(
            ServerSentEvent(
                data=payload.to_json_str(),
                event=validate_event_name(event),
                id=id,
            )
        )
        await self._connection.enqueue(frame)

    async def subscribe(self, stream: str) -> None:
        """Register this browser under one distributed business stream until close."""
        name = validate_stream_name(stream)
        pool = self._require_distributed_pool()
        pool.subscribe_stream(name, self)
        try:
            await self._connection.wait_closed()
        finally:
            pool.unsubscribe_stream(name, self)

    async def subscribe_user(self, user_id: int) -> None:
        """Register this guarded browser under its authenticated user until close."""
        validated = validate_user_id(user_id)
        pool = self._require_distributed_pool()
        if self._guarded_user_id is None:
            raise RuntimeError("subscribe_user() requires session_guard=True")
        if validated != self._guarded_user_id:
            raise ValueError("user_id does not match the guarded Session user")
        pool.subscribe_user(validated, self)
        try:
            await self._connection.wait_closed()
        finally:
            pool.unsubscribe_user(validated, self)

    def _enqueue_published(self, *, payload: object, event: str) -> None:
        """Translate and enqueue one already routed Redis payload."""
        data = _encode_json_with_translations(
            payload,
            cast(TranslationCatalog, self._translations),
        ).decode("utf-8")
        frame = encode_sse_event(ServerSentEvent(data=data, event=event))
        self._connection.enqueue_nowait(frame)

    def _abort(self) -> None:
        """Close this stream when its worker begins shutting down."""
        self._connection.abort()

    async def _wait_closed(self) -> None:
        """Wait for shutdown without exposing the connection implementation publicly."""
        await self._connection.wait_closed()

    def _require_distributed_pool(self) -> SSEConnectionPool:
        """Require the Redis-backed routing capability for subscribe operations."""
        if not self._distributed_enabled or self._pool is None:
            raise RuntimeError("distributed SSE is disabled")
        return self._pool


__all__ = ["SSEStream"]
