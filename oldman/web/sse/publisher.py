"""Redis publisher for browser events produced outside Sanic workers."""

from __future__ import annotations

import re
from typing import Final

from oldman.conf.schemas import SSEConfig
from oldman.logging import get_logger
from oldman.providers.redis import RedisAliasClient, RedisClientRegistry, redis_client
from oldman.serializers import MsgspecModel
from oldman.web.sse.messages import SSEPublishedMessage, SSETargetType

_EVENT_SEGMENT: Final = r"[A-Za-z][A-Za-z0-9_-]*"
_EVENT_PATTERN: Final = re.compile(rf"{_EVENT_SEGMENT}(?:\.{_EVENT_SEGMENT})*\Z")
_STREAM_PATTERN: Final = re.compile(rf"{_EVENT_SEGMENT}(?:\.{_EVENT_SEGMENT})+\Z")
_MAX_EVENT_NAME_LENGTH: Final = 128
_MAX_STREAM_NAME_LENGTH: Final = 128


class SSEMessageTooLargeError(ValueError):
    """Raised when one encoded Redis SSE envelope exceeds its limit."""


def validate_event_name(value: object) -> str:
    """Return one safe simple or namespaced browser event name."""
    return _validate_name(value, field_name="event", pattern=_EVENT_PATTERN, max_length=_MAX_EVENT_NAME_LENGTH)


def validate_stream_name(value: object) -> str:
    """Return one namespaced distributed stream route."""
    return _validate_name(value, field_name="stream", pattern=_STREAM_PATTERN, max_length=_MAX_STREAM_NAME_LENGTH)


def validate_user_id(value: object) -> int:
    """Return one integer user identity without implicit conversion."""
    if type(value) is not int:
        raise TypeError("user_id must be an int")
    return value


def _validate_name(value: object, *, field_name: str, pattern: re.Pattern[str], max_length: int) -> str:
    """Apply the shared bounded ASCII identifier contract."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return value


class SSEPublisher:
    """Publish strongly typed events through one configured Redis alias."""

    def __init__(
        self,
        config: SSEConfig,
        *,
        registry: RedisClientRegistry | None = None,
    ) -> None:
        if not isinstance(config, SSEConfig):
            raise TypeError("config must be an SSEConfig")

        self.config = config
        self._logger = get_logger("default.sse.publisher")
        self._failure_active = False
        self._channel = f"{config.channel_prefix}:events:v1" if config.enabled else ""
        self._redis: RedisAliasClient | None = None
        if config.enabled:
            selected_registry = redis_client if registry is None else registry
            # Alias lookup is local configuration validation and does not create a pool.
            self._redis = selected_registry.using(config.redis_alias)

    @classmethod
    def from_settings(cls) -> SSEPublisher:
        """Build a publisher from process settings without opening Redis."""
        from oldman.conf import settings

        return cls(settings.web.sse)

    async def publish_user(
        self,
        *,
        user_id: int,
        event: str,
        payload: MsgspecModel,
    ) -> bool:
        """Publish an event to every connected tab for one user."""
        return await self._publish(
            target_type=SSETargetType.USER,
            target=str(validate_user_id(user_id)),
            event=event,
            payload=payload,
        )

    async def publish_stream(
        self,
        *,
        stream: str,
        event: str,
        payload: MsgspecModel,
    ) -> bool:
        """Publish an event to browsers subscribed to one business stream."""
        return await self._publish(
            target_type=SSETargetType.STREAM,
            target=validate_stream_name(stream),
            event=event,
            payload=payload,
        )

    async def _publish(
        self,
        *,
        target_type: SSETargetType,
        target: str,
        event: str,
        payload: MsgspecModel,
    ) -> bool:
        """Validate, encode, and publish one Redis envelope."""
        redis_alias = self._redis
        if redis_alias is None:
            raise RuntimeError("distributed SSE is disabled")
        if not isinstance(payload, MsgspecModel):
            raise TypeError("payload must be a MsgspecModel")

        encoded_payload = payload.to_msgpack()
        envelope = SSEPublishedMessage(
            target_type=target_type,
            target=target,
            event=validate_event_name(event),
            payload=encoded_payload,
        )
        encoded = envelope.to_msgpack()
        if len(encoded) > self.config.max_message_size:
            raise SSEMessageTooLargeError(
                f"encoded SSE message exceeds the {self.config.max_message_size}-byte limit"
            )

        try:
            connection = await redis_alias.async_get_bin_conn()
            await connection.publish(self._channel, encoded)
        except Exception as error:
            if not self._failure_active:
                self._logger.error("SSE Redis publish failed: %s", error)
            self._failure_active = True
            return False

        if self._failure_active:
            self._logger.info("SSE Redis publishing recovered")
            self._failure_active = False
        return True


__all__ = [
    "SSEMessageTooLargeError",
    "SSEPublisher",
    "validate_event_name",
    "validate_stream_name",
    "validate_user_id",
]
