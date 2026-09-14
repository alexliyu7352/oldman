"""Native local SSE stream and one-writer behavior tests."""

from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import msgspec
from redis.exceptions import ConnectionError as RedisConnectionError
from sanic import Sanic

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, SSEConfig, WebConfig
from oldman.i18n import LazyTranslation, TranslatableMsgspecModel, gettext_lazy
from oldman.providers.redis import RedisAliasNotConfiguredError
from oldman.serializers import MsgspecModel
from oldman.web.session import DefaultSessionInterface, Session, SessionData
from oldman.web.sse import (
    ServerSentEvent,
    SSEExtension,
    SSEPublishedMessage,
    SSEQueueMode,
    SSEStream,
    SSETargetType,
    encode_sse_event,
)
from oldman.web.sse.connection import SSEBackpressureError, SSEConnection, SSEWriter
from oldman.web.sse.pool import SSEConnectionPool

conf.__dict__.setdefault("settings", DefaultSettings())


class LocalStatus(MsgspecModel, kw_only=True):
    """Representative strongly typed local event payload."""

    status: str


class DistributedValue(MsgspecModel, kw_only=True):
    """Representative ordinary payload routed through the subscriber."""

    value: int


class DistributedNotice(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports freezing this wire-only subclass
):
    """Representative lazy payload rendered for each browser catalog."""

    title: LazyTranslation


class Catalog:
    """Prefix source messages to expose per-connection language selection."""

    def __init__(self, language: str) -> None:
        self.language = language

    def gettext(self, message: str) -> str:
        return f"{self.language}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        return f"{self.language}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        return f"{self.language}:{context}:{message}"


class FailingCatalog(Catalog):
    """Fail one connection without affecting another target stream."""

    def gettext(self, message: str) -> str:
        raise RuntimeError(f"cannot translate {message}")


class FakeResponse:
    """Record response writes, concurrency, EOF, and controlled failures."""

    def __init__(self, *, block_first: bool = False, fail_first: bool = False) -> None:
        self.frames: list[str] = []
        self.writer_tasks: list[asyncio.Task[Any] | None] = []
        self.eof_count = 0
        self.max_concurrent_writes = 0
        self._active_writes = 0
        self._block_first = block_first
        self._fail_first = fail_first
        self.first_write_started = asyncio.Event()
        self.release_first_write = asyncio.Event()

    async def send(self, data: str, end_stream: bool | None = None) -> None:
        del end_stream
        self._active_writes += 1
        self.max_concurrent_writes = max(self.max_concurrent_writes, self._active_writes)
        self.writer_tasks.append(asyncio.current_task())
        try:
            call_number = len(self.frames)
            if self._fail_first and call_number == 0:
                raise ConnectionError("browser disconnected")
            self.frames.append(data)
            if self._block_first and call_number == 0:
                self.first_write_started.set()
                await self.release_first_write.wait()
        finally:
            self._active_writes -= 1

    async def eof(self) -> None:
        self.eof_count += 1


class FakeRequest:
    """Provide the request fields used by the SSE route decorator."""

    def __init__(self, app: Sanic, response: FakeResponse) -> None:
        self.app = app
        self.ctx = SimpleNamespace(translations="catalog")
        self.cookies: dict[str, str] = {}
        self.response = response
        self.respond_calls: list[dict[str, Any]] = []

    async def respond(self, **kwargs: Any) -> FakeResponse:
        self.respond_calls.append(kwargs)
        return self.response


class SSEStreamTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = Sanic(f"oldman-sse-stream-{time.time_ns()}")
        self.extension = SSEExtension()
        self.extension.init_app(self.app)

    def tearDown(self) -> None:
        Sanic.unregister_app(self.app)

    def connection(
        self,
        response: FakeResponse,
        *,
        queue_mode: SSEQueueMode = SSEQueueMode.FIFO,
        queue_size: int = 4,
        heartbeat_interval: float = 60,
        retry: int | None = None,
        session_guard: Any = None,
        session_check_interval: float | None = None,
    ) -> SSEConnection:
        return SSEConnection(
            cast(SSEWriter, response),
            queue_mode=queue_mode,
            queue_size=queue_size,
            heartbeat_interval=heartbeat_interval,
            retry=retry,
            session_guard=session_guard,
            session_check_interval=session_check_interval,
        )

    def test_encoder_preserves_multiline_utf8_and_protocol_validation(self) -> None:
        frame = encode_sse_event(
            ServerSentEvent(
                comment="第一行\r第二行",
                event="status",
                id="7",
                retry=3000,
                data="开始\r\n完成",
            )
        )

        self.assertEqual(
            ": 第一行\n: 第二行\nevent: status\nid: 7\nretry: 3000\ndata: 开始\ndata: 完成\n\n",
            frame,
        )
        for event in (
            ServerSentEvent(event="bad\nfield"),
            ServerSentEvent(id="bad\0id"),
            ServerSentEvent(retry=cast(Any, True)),
        ):
            with self.subTest(event=event), self.assertRaises((TypeError, ValueError)):
                encode_sse_event(event)

    async def test_real_sanic_handler_drains_two_events_and_finishes(self) -> None:
        @self.app.get("/events")
        @self.extension.streaming()
        async def events(_request: Any, stream: SSEStream) -> None:
            await stream.send(LocalStatus(status="starting"), event="status", id="1")
            await stream.send(LocalStatus(status="ready"), event="status", id="2")

        _request, response = await self.app.asgi_client.get("/events")

        self.assertEqual(200, response.status)
        self.assertEqual("text/event-stream; charset=utf-8", response.content_type)
        self.assertEqual("no-cache, no-store, no-transform", response.headers["cache-control"])
        self.assertEqual(
            (
                b'event: status\nid: 1\ndata: {"status":"starting"}\n\n'
                b'event: status\nid: 2\ndata: {"status":"ready"}\n\n'
            ),
            response.body,
        )

    async def test_retry_precedes_events_and_is_sent_once(self) -> None:
        response = FakeResponse()
        connection = self.connection(response, retry=2500)
        stream = SSEStream(connection)
        await stream.send(LocalStatus(status="ready"), event="status")
        connection.finish()

        await connection.run_writer()

        self.assertEqual("retry: 2500\n\n", response.frames[0])
        self.assertEqual(1, sum(frame.startswith("retry:") for frame in response.frames))
        self.assertEqual(1, response.eof_count)

    async def test_heartbeat_and_business_events_share_one_writer(self) -> None:
        response = FakeResponse()
        connection = self.connection(response, heartbeat_interval=0.01)
        writer = asyncio.create_task(connection.run_writer())
        await asyncio.sleep(0.025)
        await connection.enqueue("event: status\ndata: {}\n\n")
        await asyncio.sleep(0)
        connection.finish()

        await writer

        self.assertTrue(any(frame.startswith(": heartbeat") for frame in response.frames))
        self.assertIn("event: status\ndata: {}\n\n", response.frames)
        self.assertEqual(1, response.max_concurrent_writes)
        self.assertEqual(1, len(set(response.writer_tasks)))

    async def test_full_fifo_queue_aborts_slow_connection(self) -> None:
        response = FakeResponse()
        connection = self.connection(response, queue_size=1)
        await connection.enqueue("first")

        with self.assertRaises(SSEBackpressureError):
            await connection.enqueue("second")
        await connection.run_writer()

        self.assertEqual([], response.frames)
        self.assertEqual(1, response.eof_count)

    async def test_latest_queue_replaces_only_unsent_snapshot(self) -> None:
        response = FakeResponse(block_first=True)
        connection = self.connection(
            response,
            queue_mode=SSEQueueMode.LATEST,
            queue_size=1,
        )
        await connection.enqueue("first")
        writer = asyncio.create_task(connection.run_writer())
        await response.first_write_started.wait()
        await connection.enqueue("stale")
        await connection.enqueue("latest")
        connection.finish()
        response.release_first_write.set()

        await writer

        self.assertEqual(["first", "latest"], response.frames)

    async def test_handler_failure_is_logged_and_connection_is_cleaned(self) -> None:
        response = FakeResponse()
        request = FakeRequest(self.app, response)

        @self.extension.streaming()
        async def failing_handler(_request: Any, _stream: SSEStream) -> None:
            raise RuntimeError("handler exploded")

        with self.assertLogs("default.sse", level="ERROR") as captured:
            await failing_handler(cast(Any, request))

        self.assertTrue(any("handler exploded" in line for line in captured.output))
        self.assertEqual(1, response.eof_count)
        self.assertEqual((), self.extension._pool.all_streams())

    async def test_browser_write_failure_cancels_infinite_handler(self) -> None:
        response = FakeResponse(fail_first=True)
        request = FakeRequest(self.app, response)
        cancelled = asyncio.Event()

        @self.extension.streaming()
        async def infinite_handler(_request: Any, stream: SSEStream) -> None:
            try:
                await stream.send(LocalStatus(status="ready"), event="status")
                await asyncio.Future()
            finally:
                cancelled.set()

        await infinite_handler(cast(Any, request))

        self.assertTrue(cancelled.is_set())
        self.assertEqual(1, response.eof_count)

    async def test_stream_rejects_invalid_payload_and_id_before_enqueue(self) -> None:
        response = FakeResponse()
        connection = self.connection(response)
        stream = SSEStream(connection)

        with self.assertRaises(TypeError):
            await stream.send(cast(Any, {"status": "ready"}), event="status")
        with self.assertRaises(ValueError):
            await stream.send(LocalStatus(status="ready"), event="status", id="bad\nid")
        connection.finish()
        await connection.run_writer()
        self.assertEqual([], response.frames)

    def test_extension_rejects_repeat_init_but_tests_can_use_new_instances(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "already initialized"):
            self.extension.init_app(self.app)

        second_app = Sanic(f"oldman-sse-stream-second-{time.time_ns()}")
        try:
            separate = SSEExtension()
            separate.init_app(second_app)
            self.assertIs(second_app, separate._app)
        finally:
            Sanic.unregister_app(second_app)

    async def test_disabled_server_start_creates_no_redis_task(self) -> None:
        await self.extension.after_server_start(self.app)

        self.assertIsNone(self.extension._subscriber_task)

    async def test_distributed_routes_target_only_matching_local_connections(self) -> None:
        responses = [FakeResponse() for _ in range(3)]
        connections = [self.connection(response) for response in responses]
        pool = self.extension._pool
        streams = [SSEStream(connection, pool=pool, distributed_enabled=True, guarded_user_id=0) for connection in connections]
        for stream in streams:
            pool.add(stream)
        pool.subscribe_user(0, streams[0])
        pool.subscribe_user(-2, streams[1])
        pool.subscribe_stream("app.metrics.overview", streams[2])

        self.extension._handle_redis_payload(
            SSEPublishedMessage(
                target_type=SSETargetType.USER,
                target="0",
                event="app.notice",
                payload=DistributedValue(value=1).to_msgpack(),
            ).to_msgpack()
        )
        self.extension._handle_redis_payload(
            SSEPublishedMessage(
                target_type=SSETargetType.STREAM,
                target="app.metrics.overview",
                event="app.metrics.snapshot",
                payload=DistributedValue(value=10).to_msgpack(),
            ).to_msgpack()
        )
        for connection in connections:
            connection.finish()
        await asyncio.gather(*(connection.run_writer() for connection in connections))

        self.assertEqual(['event: app.notice\ndata: {"value":1}\n\n'], responses[0].frames)
        self.assertEqual([], responses[1].frames)
        self.assertEqual(
            ['event: app.metrics.snapshot\ndata: {"value":10}\n\n'],
            responses[2].frames,
        )
        self.assertEqual((streams[0],), self.extension.user_streams(0))

    async def test_distributed_payload_is_translated_for_each_connection(self) -> None:
        pool = self.extension._pool
        english_response = FakeResponse()
        chinese_response = FakeResponse()
        english_connection = self.connection(english_response)
        chinese_connection = self.connection(chinese_response)
        english = SSEStream(
            english_connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=7,
            translations=Catalog("en"),
        )
        chinese = SSEStream(
            chinese_connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=7,
            translations=Catalog("zh"),
        )
        pool.subscribe_user(7, english)
        pool.subscribe_user(7, chinese)
        payload = DistributedNotice(
            title=gettext_lazy("Import completed"),
        ).to_msgpack()

        self.extension._handle_redis_payload(
            SSEPublishedMessage(
                target_type=SSETargetType.USER,
                target="7",
                event="app.notice",
                payload=payload,
            ).to_msgpack()
        )
        english_connection.finish()
        chinese_connection.finish()
        await asyncio.gather(
            english_connection.run_writer(),
            chinese_connection.run_writer(),
        )

        self.assertEqual(
            ['event: app.notice\ndata: {"title":"en:Import completed"}\n\n'],
            english_response.frames,
        )
        self.assertEqual(
            ['event: app.notice\ndata: {"title":"zh:Import completed"}\n\n'],
            chinese_response.frames,
        )

    async def test_one_broken_catalog_does_not_block_other_connections(self) -> None:
        pool = self.extension._pool
        broken_response = FakeResponse()
        healthy_response = FakeResponse()
        broken_connection = self.connection(broken_response)
        healthy_connection = self.connection(healthy_response)
        broken = SSEStream(
            broken_connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=8,
            translations=FailingCatalog("broken"),
        )
        healthy = SSEStream(
            healthy_connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=8,
            translations=Catalog("en"),
        )
        envelope = SSEPublishedMessage(
            target_type=SSETargetType.USER,
            target="8",
            event="app.notice",
            payload=DistributedNotice(
                title=gettext_lazy("Import completed"),
            ).to_msgpack(),
        ).to_msgpack()

        with (
            patch.object(pool, "user_streams", return_value=(broken, healthy)),
            self.assertLogs("default.sse", level="WARNING") as captured,
        ):
            self.extension._handle_redis_payload(envelope)
        broken_connection.finish()
        healthy_connection.finish()
        await asyncio.gather(
            broken_connection.run_writer(),
            healthy_connection.run_writer(),
        )

        self.assertTrue(any("cannot translate" in line for line in captured.output))
        self.assertEqual([], broken_response.frames)
        self.assertEqual(
            ['event: app.notice\ndata: {"title":"en:Import completed"}\n\n'],
            healthy_response.frames,
        )

    def test_offline_target_does_not_decode_inner_payload(self) -> None:
        envelope = SSEPublishedMessage(
            target_type=SSETargetType.USER,
            target="404",
            event="app.notice",
            payload=b"not-messagepack",
        ).to_msgpack()

        with patch(
            "oldman.web.sse.extension._decode_translatable_msgpack",
            side_effect=AssertionError("offline payload was decoded"),
        ):
            self.extension._handle_redis_payload(envelope)

    async def test_slow_fifo_connection_does_not_block_other_local_targets(self) -> None:
        pool = self.extension._pool
        slow_response = FakeResponse()
        fast_response = FakeResponse()
        slow_connection = self.connection(slow_response, queue_size=1)
        fast_connection = self.connection(fast_response, queue_size=2)
        slow = SSEStream(slow_connection, pool=pool, distributed_enabled=True, guarded_user_id=1)
        fast = SSEStream(fast_connection, pool=pool, distributed_enabled=True, guarded_user_id=1)
        pool.subscribe_user(1, slow)
        pool.subscribe_user(1, fast)
        slow_connection.enqueue_nowait("already full")

        self.extension._handle_redis_payload(
            SSEPublishedMessage(
                target_type=SSETargetType.USER,
                target="1",
                event="app.notice",
                payload=DistributedValue(value=1).to_msgpack(),
            ).to_msgpack()
        )
        fast_connection.finish()
        await asyncio.gather(slow_connection.run_writer(), fast_connection.run_writer())

        self.assertEqual([], slow_response.frames)
        self.assertEqual(['event: app.notice\ndata: {"value":1}\n\n'], fast_response.frames)

    async def test_invalid_redis_payloads_are_dropped_without_poisoning_dispatch(self) -> None:
        config = self.extension._config
        assert config is not None
        response = FakeResponse()
        connection = self.connection(response)
        stream = SSEStream(
            connection,
            pool=self.extension._pool,
            distributed_enabled=True,
            guarded_user_id=1,
        )
        self.extension._pool.subscribe_user(1, stream)

        invalid_messagepack = SSEPublishedMessage(
            target_type=SSETargetType.USER,
            target="1",
            event="app.notice",
            payload=b"not-messagepack",
        ).to_msgpack()
        invalid_root = SSEPublishedMessage(
            target_type=SSETargetType.USER,
            target="1",
            event="app.notice",
            payload=msgspec.msgpack.encode(["not", "an", "object"]),
        ).to_msgpack()
        invalid_target = SSEPublishedMessage(
            target_type=SSETargetType.USER,
            target="not-an-integer",
            event="app.notice",
            payload=DistributedValue(value=1).to_msgpack(),
        ).to_msgpack()
        with self.assertLogs("default.sse", level="WARNING"):
            self.extension._handle_redis_payload(b"broken")
            self.extension._handle_redis_payload(b"x" * (config.max_message_size + 1))
            self.extension._handle_redis_payload(invalid_messagepack)
            self.extension._handle_redis_payload(invalid_root)
            self.extension._handle_redis_payload(invalid_target)
        self.extension._handle_redis_payload(
            SSEPublishedMessage(
                target_type=SSETargetType.USER,
                target="1",
                event="app.notice",
                payload=DistributedValue(value=2).to_msgpack(),
            ).to_msgpack()
        )
        connection.finish()
        await connection.run_writer()

        self.assertEqual(['event: app.notice\ndata: {"value":2}\n\n'], response.frames)

    async def test_subscribe_user_requires_guard_and_matching_identity(self) -> None:
        connection = self.connection(FakeResponse())
        pool = SSEConnectionPool()
        disabled = SSEStream(connection, pool=pool, guarded_user_id=1)
        unguarded = SSEStream(connection, pool=pool, distributed_enabled=True)
        mismatched = SSEStream(
            connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=1,
        )

        with self.assertRaisesRegex(RuntimeError, "distributed SSE is disabled"):
            await disabled.subscribe_user(1)
        with self.assertRaisesRegex(RuntimeError, "session_guard"):
            await unguarded.subscribe_user(1)
        with self.assertRaisesRegex(ValueError, "does not match"):
            await mismatched.subscribe_user(2)

    async def test_subscribe_apis_register_until_connection_close_then_clean_up(self) -> None:
        pool = SSEConnectionPool()
        user_connection = self.connection(FakeResponse())
        business_connection = self.connection(FakeResponse())
        user_stream = SSEStream(
            user_connection,
            pool=pool,
            distributed_enabled=True,
            guarded_user_id=1,
        )
        business_stream = SSEStream(
            business_connection,
            pool=pool,
            distributed_enabled=True,
        )
        user_writer = asyncio.create_task(user_connection.run_writer())
        business_writer = asyncio.create_task(business_connection.run_writer())
        user_subscription = asyncio.create_task(user_stream.subscribe_user(1))
        business_subscription = asyncio.create_task(
            business_stream.subscribe("app.metrics.overview")
        )
        await asyncio.sleep(0)

        self.assertEqual((user_stream,), pool.user_streams(1))
        self.assertEqual(
            (business_stream,),
            pool.business_streams("app.metrics.overview"),
        )

        user_connection.abort()
        business_connection.abort()
        await asyncio.gather(
            user_writer,
            business_writer,
            user_subscription,
            business_subscription,
        )
        self.assertEqual((), pool.user_streams(1))
        self.assertEqual((), pool.business_streams("app.metrics.overview"))

    async def test_initial_session_race_sends_one_translated_event_and_closes(self) -> None:
        response = FakeResponse()
        request = FakeRequest(self.app, response)
        manager = await self._install_authenticated_request(request)
        manager.validate_session = AsyncMock(return_value=False)  # type: ignore[method-assign]

        class Catalog:
            def gettext(self, message: str) -> str:
                return f"translated:{message}"

        request.ctx.translations = Catalog()

        @self.extension.streaming(session_guard=True, login_url=lambda _request: "/admin/login")
        async def guarded(_request: Any, _stream: SSEStream) -> None:
            await asyncio.Future()

        await guarded(cast(Any, request))

        self.assertEqual(1, len(response.frames))
        self.assertIn("event: oldman.session.invalidated", response.frames[0])
        self.assertIn('"title":"translated:Session expired"', response.frames[0])
        self.assertIn('"login_url":"/admin/login"', response.frames[0])
        self.assertEqual(1, response.eof_count)
        manager.validate_session.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_session_revocation_is_detected_by_the_writer_deadline(self) -> None:
        response = FakeResponse()
        request = FakeRequest(self.app, response)
        manager = await self._install_authenticated_request(request)
        manager.validate_session = AsyncMock(side_effect=[True, False])  # type: ignore[method-assign]
        config = self.extension._config
        assert config is not None
        config.session_check_interval = 0.01

        @self.extension.streaming(session_guard=True)
        async def guarded(_request: Any, _stream: SSEStream) -> None:
            await asyncio.Future()

        await guarded(cast(Any, request))

        self.assertEqual(1, len(response.frames))
        self.assertIn("event: oldman.session.invalidated", response.frames[0])
        self.assertEqual(2, manager.validate_session.await_count)  # type: ignore[attr-defined]

    async def test_session_redis_failure_closes_without_false_invalidation(self) -> None:
        response = FakeResponse()
        request = FakeRequest(self.app, response)
        manager = await self._install_authenticated_request(request)
        manager.validate_session = AsyncMock(  # type: ignore[method-assign]
            side_effect=RedisConnectionError("session redis unavailable")
        )

        @self.extension.streaming(session_guard=True)
        async def guarded(_request: Any, _stream: SSEStream) -> None:
            await asyncio.Future()

        await guarded(cast(Any, request))

        self.assertEqual([], response.frames)
        self.assertEqual(1, response.eof_count)

    async def test_login_url_callback_is_validated_before_headers(self) -> None:
        response = FakeResponse()
        request = FakeRequest(self.app, response)
        await self._install_authenticated_request(request)

        @self.extension.streaming(session_guard=True, login_url=lambda _request: "https://evil.test")
        async def guarded(_request: Any, _stream: SSEStream) -> None:
            await asyncio.Future()

        with self.assertRaisesRegex(ValueError, "same-site"):
            await guarded(cast(Any, request))
        self.assertEqual([], request.respond_calls)

    async def test_enabled_init_validates_alias_without_opening_network(self) -> None:
        app = Sanic(f"oldman-sse-enabled-{time.time_ns()}")
        extension = SSEExtension()
        registry = Mock()
        alias = Mock()
        registry.using.return_value = alias
        settings = DefaultSettings.model_validate(
            {
                "web": WebConfig(
                    sse=SSEConfig(enabled=True, channel_prefix="project:test:sse")
                ).model_dump()
            }
        )
        try:
            with (
                patch.dict(conf.__dict__, {"settings": settings}),
                patch("oldman.web.sse.extension.redis_client", registry),
            ):
                extension.init_app(app)

            registry.using.assert_called_once_with("SSE")
            alias.async_get_bin_conn.assert_not_called()
            await extension.after_server_start(app)
            self.assertIsNotNone(extension._subscriber_task)
            await extension.before_server_stop(app)
        finally:
            Sanic.unregister_app(app)

    def test_enabled_init_rejects_missing_redis_alias_deterministically(self) -> None:
        app = Sanic(f"oldman-sse-missing-alias-{time.time_ns()}")
        extension = SSEExtension()
        registry = Mock()
        registry.using.side_effect = RedisAliasNotConfiguredError("missing SSE")
        settings = DefaultSettings.model_validate(
            {
                "web": WebConfig(
                    sse=SSEConfig(enabled=True, channel_prefix="project:test:sse")
                ).model_dump()
            }
        )
        try:
            with (
                patch.dict(conf.__dict__, {"settings": settings}),
                patch("oldman.web.sse.extension.redis_client", registry),
                self.assertRaises(RedisAliasNotConfiguredError),
            ):
                extension.init_app(app)
            registry.using.assert_called_once_with("SSE")
        finally:
            Sanic.unregister_app(app)

    async def _install_authenticated_request(self, request: FakeRequest) -> Session:
        """Attach trusted Session middleware state without contacting Redis."""
        interface = DefaultSessionInterface()
        manager = Session()
        manager.interface = interface
        request.app.ctx.session = manager
        await interface.open(cast(Any, request))
        request.ctx.session = SessionData(
            user_id=1,
            username="alice",
            is_active=True,
        )
        return manager


if __name__ == "__main__":
    unittest.main()
