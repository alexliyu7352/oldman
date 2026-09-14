"""Distributed SSE publisher behavior tests."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, RedisConfig, SSEConfig
from oldman.i18n import LazyTranslation, TranslatableMsgspecModel, gettext_lazy
from oldman.providers.redis import RedisAliasNotConfiguredError, RedisClientRegistry
from oldman.serializers import MsgspecModel
from oldman.web.sse import SSEPublishedMessage, SSEPublisher, SSETargetType
from oldman.web.sse.publisher import SSEMessageTooLargeError


class ExportFinished(MsgspecModel, kw_only=True):
    """Representative strongly typed browser payload."""

    export_id: str
    rows: int


class NoticePayload(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports freezing this wire-only subclass
):
    """Representative payload translated only after Redis routing."""

    title: LazyTranslation


class FakeRedisConnection:
    """Record Redis publish calls and expose queued failures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.results: list[int | BaseException] = []

    async def publish(self, channel: str, payload: bytes) -> int:
        self.calls.append((channel, payload))
        result = self.results.pop(0) if self.results else 0
        if isinstance(result, BaseException):
            raise result
        return int(result)


class FakeRedisAlias:
    """Delay connection access until the publisher performs real I/O."""

    def __init__(self, connection: FakeRedisConnection) -> None:
        self.connection = connection
        self.connection_requests = 0

    async def async_get_bin_conn(self) -> FakeRedisConnection:
        self.connection_requests += 1
        return self.connection


class FakeRedisRegistry:
    """Provide one configured alias without constructing a Redis pool."""

    def __init__(self, alias: FakeRedisAlias) -> None:
        self.alias = alias
        self.requested_aliases: list[str] = []

    def using(self, alias: str) -> FakeRedisAlias:
        self.requested_aliases.append(alias)
        return self.alias


@contextmanager
def configured_settings(settings: DefaultSettings) -> Iterator[None]:
    """Temporarily publish one process settings object for from_settings()."""
    sentinel = object()
    previous = conf.__dict__.get("settings", sentinel)
    conf.__dict__["settings"] = settings
    try:
        yield
    finally:
        if previous is sentinel:
            conf.__dict__.pop("settings", None)
        else:
            conf.__dict__["settings"] = previous


def distributed_config(*, max_message_size: int = 65536) -> SSEConfig:
    """Return the enabled settings used by publisher tests."""
    return SSEConfig(
        enabled=True,
        redis_alias="SSE",
        channel_prefix="tests:sse",
        max_message_size=max_message_size,
    )


class SSEPublisherTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.connection = FakeRedisConnection()
        self.alias = FakeRedisAlias(self.connection)
        self.registry = FakeRedisRegistry(self.alias)

    def publisher(self, *, max_message_size: int = 65536) -> SSEPublisher:
        return SSEPublisher(
            distributed_config(max_message_size=max_message_size),
            registry=self.registry,  # type: ignore[arg-type] -- narrow behavioral fake
        )

    def test_construction_resolves_only_local_alias_configuration(self) -> None:
        publisher = self.publisher()

        self.assertIsInstance(publisher, SSEPublisher)
        self.assertEqual(["SSE"], self.registry.requested_aliases)
        self.assertEqual(0, self.alias.connection_requests)

    async def test_disabled_publisher_does_not_require_a_redis_alias(self) -> None:
        registry = RedisClientRegistry(RedisConfig())
        publisher = SSEPublisher(SSEConfig(), registry=registry)

        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await publisher.publish_user(
                user_id=42,
                event="status",
                payload=ExportFinished(export_id="x", rows=1),
            )

    def test_enabled_publisher_rejects_a_missing_alias_before_network_io(self) -> None:
        registry = RedisClientRegistry(RedisConfig())

        with self.assertRaises(RedisAliasNotConfiguredError):
            SSEPublisher(distributed_config(), registry=registry)

    async def test_user_envelope_contains_binary_translatable_payload(self) -> None:
        published = await self.publisher().publish_user(
            user_id=42,
            event="status",
            payload=NoticePayload(title=gettext_lazy("Import completed")),
        )

        self.assertTrue(published)
        self.assertEqual(1, self.alias.connection_requests)
        channel, raw = self.connection.calls[0]
        envelope = SSEPublishedMessage.from_msgpack(raw)
        self.assertEqual("tests:sse:events:v1", channel)
        self.assertEqual(SSETargetType.USER, envelope.target_type)
        self.assertEqual("42", envelope.target)
        self.assertEqual("status", envelope.event)
        self.assertIsInstance(envelope.payload, bytes)
        decoded = NoticePayload.from_msgpack(envelope.payload)
        self.assertEqual("Import completed", decoded.title.singular)

    async def test_stream_publish_uses_namespaced_route(self) -> None:
        published = await self.publisher().publish_stream(
            stream="app.metrics.overview",
            event="app.metrics.snapshot",
            payload=ExportFinished(export_id="metrics", rows=0),
        )

        self.assertTrue(published)
        envelope = SSEPublishedMessage.from_msgpack(self.connection.calls[0][1])
        self.assertEqual(SSETargetType.STREAM, envelope.target_type)
        self.assertEqual("app.metrics.overview", envelope.target)

    async def test_zero_redis_subscribers_is_still_a_success(self) -> None:
        self.connection.results.append(0)

        self.assertTrue(
            await self.publisher().publish_user(
                user_id=0,
                event="message",
                payload=ExportFinished(export_id="x", rows=1),
            )
        )

    async def test_invalid_inputs_and_size_fail_before_connection_access(self) -> None:
        publisher = self.publisher(max_message_size=32)
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            (
                "dict payload",
                {"user_id": 42, "event": "status", "payload": {"rows": 1}},
            ),
            (
                "invalid event",
                {"user_id": 42, "event": "bad event", "payload": ExportFinished(export_id="x", rows=1)},
            ),
            (
                "string user",
                {"user_id": "42", "event": "status", "payload": ExportFinished(export_id="x", rows=1)},
            ),
            (
                "boolean user",
                {"user_id": True, "event": "status", "payload": ExportFinished(export_id="x", rows=1)},
            ),
        )
        for label, kwargs in cases:
            with self.subTest(label=label), self.assertRaises((TypeError, ValueError)):
                await publisher.publish_user(**kwargs)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            await publisher.publish_stream(
                stream="metrics",
                event="status",
                payload=ExportFinished(export_id="x", rows=1),
            )
        with self.assertRaisesRegex(SSEMessageTooLargeError, "exceeds"):
            await publisher.publish_user(
                user_id=42,
                event="status",
                payload=ExportFinished(export_id="x" * 100, rows=1),
            )
        self.assertEqual(0, self.alias.connection_requests)

    async def test_connection_failure_logs_once_and_recovery_logs_once(self) -> None:
        self.connection.results.extend([ConnectionError("down"), ConnectionError("still down"), 1])
        publisher = self.publisher()

        with self.assertLogs("default.sse.publisher", level="INFO") as captured:
            first = await publisher.publish_user(
                user_id=42,
                event="status",
                payload=ExportFinished(export_id="1", rows=1),
            )
            second = await publisher.publish_user(
                user_id=42,
                event="status",
                payload=ExportFinished(export_id="2", rows=2),
            )
            third = await publisher.publish_user(
                user_id=42,
                event="status",
                payload=ExportFinished(export_id="3", rows=3),
            )

        self.assertEqual((False, False, True), (first, second, third))
        self.assertEqual(1, sum("publish failed" in line for line in captured.output))
        self.assertEqual(1, sum("recovered" in line for line in captured.output))

    async def test_cancellation_is_not_converted_into_publish_failure(self) -> None:
        self.connection.results.append(asyncio.CancelledError())

        with self.assertRaises(asyncio.CancelledError):
            await self.publisher().publish_user(
                user_id=-42,
                event="status",
                payload=ExportFinished(export_id="x", rows=1),
            )

    def test_from_settings_does_not_open_redis_when_disabled(self) -> None:
        with configured_settings(DefaultSettings()):
            publisher = SSEPublisher.from_settings()

        self.assertFalse(publisher.config.enabled)


if __name__ == "__main__":
    unittest.main()
