"""Server-Sent Events support."""

from __future__ import annotations

from oldman.web.sse.connection import SSEQueueMode
from oldman.web.sse.events import ServerSentEvent, encode_sse_event
from oldman.web.sse.extension import SSEExtension, sse
from oldman.web.sse.messages import (
    SSEPublishedMessage,
    SSESessionInvalidatedPayload,
    SSETargetType,
)
from oldman.web.sse.publisher import SSEPublisher
from oldman.web.sse.stream import SSEStream

__all__ = [
    "SSEExtension",
    "SSEPublishedMessage",
    "SSEPublisher",
    "SSEQueueMode",
    "SSESessionInvalidatedPayload",
    "SSEStream",
    "SSETargetType",
    "ServerSentEvent",
    "encode_sse_event",
    "sse",
]
