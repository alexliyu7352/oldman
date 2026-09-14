"""Real Redis delivery for translated notification browser events."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sanic import Sanic

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, RedisConfig, SSEConfig, WebConfig
from oldman.i18n import gettext_lazy
from oldman.providers.redis import RedisClientRegistry
from oldman.web.messages.notifications import (
    NOTIFICATION_CREATED_EVENT,
    NOTIFICATION_PUSH_EVENT,
    NOTIFICATION_SYNC_EVENT,
    NotificationCreatedPayload,
    NotificationPayload,
    NotificationPresentation,
    NotificationPushPayload,
    NotificationSyncPayload,
)
from oldman.web.sse import (
    SSEExtension,
    SSEPublishedMessage,
    SSEPublisher,
    SSEQueueMode,
    SSEStream,
)
from oldman.web.sse.connection import SSEConnection, SSEWriter
from tests.test_oldman_web_sse_redis import (
    Catalog,
    RecordingWriter,
    RedisProcess,
    require_redis_server,
)


class NotificationRedisIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Route notification events through the sole generic SSE Redis channel."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start one test-owned Redis server on a temporary Unix socket."""
        cls.redis_executable = require_redis_server()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary_directory.name)
        cls.redis_process = RedisProcess(
            cls.redis_executable,
            cls.directory,
            "notifications",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop the owned Redis process and remove its socket directory."""
        cls.redis_process.stop()
        cls.temporary_directory.cleanup()

    async def asyncSetUp(self) -> None:
        """Create two simulated workers sharing one namespaced channel."""
        self.apps: list[Sanic] = []
        self.extensions: list[SSEExtension] = []
        self.writer_tasks: list[asyncio.Task[None]] = []
        self.config = SSEConfig(
            enabled=True,
            redis_alias="SSE",
            channel_prefix=f"tests:notifications:{time.time_ns()}",
            heartbeat_interval=60,
        )
        redis_config = RedisConfig.model_validate(
            {
                "SSE": {
                    "redis_url": (f"unix://{self.redis_process.socket_path.as_posix()}?db=0"),
                    "health_check_interval": 0,
                }
            }
        )
        self.registry = RedisClientRegistry(redis_config)

    async def asyncTearDown(self) -> None:
        """Stop subscribers, browser writers and Redis clients."""
        for extension, app in zip(self.extensions, self.apps, strict=False):
            await extension.before_server_stop(app)
        if self.writer_tasks:
            await asyncio.gather(*self.writer_tasks, return_exceptions=True)
        await self.registry.close()
        for app in self.apps:
            Sanic.unregister_app(app)

    async def test_notification_events_translate_per_worker_on_generic_channel(
        self,
    ) -> None:
        """Created, push and sync events must not introduce a private channel."""
        first = self._extension("first")
        second = self._extension("second")
        await self._start(first)
        await self._start(second)
        first_writer = self._local_user_stream(first, 7, Catalog("en"))
        second_writer = self._local_user_stream(second, 7, Catalog("zh"))

        connection = await self.registry.using("SSE").async_get_bin_conn()
        pubsub = connection.pubsub()
        generic_channel = f"{self.config.channel_prefix}:events:v1"
        private_channel = f"{self.config.channel_prefix}:notifications:v1"
        await pubsub.subscribe(generic_channel, private_channel)
        await self._wait_for_subscription_messages(pubsub, count=2)

        notification = NotificationPayload(
            title=gettext_lazy("Import completed"),
            presentation=NotificationPresentation.TOAST,
        )
        publisher = SSEPublisher(self.config, registry=self.registry)
        events = (
            (
                NOTIFICATION_CREATED_EVENT,
                NotificationCreatedPayload(
                    notification_id=1,
                    notification=notification,
                    created_at=datetime.now(UTC),
                ),
            ),
            (
                NOTIFICATION_PUSH_EVENT,
                NotificationPushPayload(notification=notification),
            ),
            (
                NOTIFICATION_SYNC_EVENT,
                NotificationSyncPayload(changed_count=2),
            ),
        )
        for event, payload in events:
            self.assertTrue(
                await publisher.publish_user(
                    user_id=7,
                    event=event,
                    payload=payload,
                )
            )

        await self._wait_for(lambda: len(first_writer.frames) == 3 and len(second_writer.frames) == 3)
        self.assertIn('"title":"en:Import completed"', first_writer.frames[0])
        self.assertIn('"title":"en:Import completed"', first_writer.frames[1])
        self.assertIn('"title":"zh:Import completed"', second_writer.frames[0])
        self.assertIn('"title":"zh:Import completed"', second_writer.frames[1])
        self.assertIn('"changed_count":2', first_writer.frames[2])

        published_messages: list[dict[str, Any]] = []
        while len(published_messages) < 3:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1,
            )
            if message is not None:
                published_messages.append(message)
        self.assertEqual(
            [generic_channel.encode()] * 3,
            [message["channel"] for message in published_messages],
        )
        self.assertEqual(
            [event for event, _payload in events],
            [SSEPublishedMessage.from_msgpack(message["data"]).event for message in published_messages],
        )
        self.assertFalse(any(message["channel"] == private_channel.encode() for message in published_messages))
        await pubsub.aclose()

    def _extension(self, name: str) -> SSEExtension:
        """Initialize one Web worker without creating another Redis registry."""
        app = Sanic(f"oldman-notifications-{name}-{time.time_ns()}")
        extension = SSEExtension()
        settings = DefaultSettings.model_validate({"web": WebConfig(sse=self.config).model_dump()})
        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch("oldman.web.sse.extension.redis_client", self.registry),
        ):
            extension.init_app(app)
        self.apps.append(app)
        self.extensions.append(extension)
        return extension

    async def _start(self, extension: SSEExtension) -> None:
        """Start one worker subscriber and wait for Redis confirmation."""
        app = extension._app
        assert app is not None
        await extension.after_server_start(app)
        await asyncio.wait_for(extension._subscriber_ready.wait(), timeout=2)

    def _local_user_stream(
        self,
        extension: SSEExtension,
        user_id: int,
        translations: Any,
    ) -> RecordingWriter:
        """Attach one translated browser writer to a worker-local user stream."""
        writer = RecordingWriter()
        connection = SSEConnection(
            cast(SSEWriter, writer),
            queue_mode=SSEQueueMode.FIFO,
            queue_size=4,
            heartbeat_interval=60,
            retry=None,
        )
        stream = SSEStream(
            connection,
            pool=extension._pool,
            distributed_enabled=True,
            guarded_user_id=user_id,
            translations=translations,
        )
        extension._pool.add(stream)
        extension._pool.subscribe_user(user_id, stream)
        self.writer_tasks.append(asyncio.create_task(connection.run_writer()))
        return writer

    async def _wait_for_subscription_messages(
        self,
        pubsub: Any,
        *,
        count: int,
    ) -> None:
        """Drain the exact Redis subscription acknowledgements before publishing."""
        received = 0
        while received < count:
            message = await pubsub.get_message(timeout=1)
            if message is not None and message["type"] == "subscribe":
                received += 1

    async def _wait_for(self, predicate: Any, timeout: float = 2) -> None:
        """Poll event-loop-local browser state with a bounded deadline."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("timed out waiting for notification SSE delivery")
            await asyncio.sleep(0.005)


if __name__ == "__main__":
    unittest.main()
