"""Real Redis integration tests for distributed browser SSE routing."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sanic import Sanic

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, RedisConfig, SSEConfig, WebConfig
from oldman.i18n import LazyTranslation, TranslatableMsgspecModel, gettext_lazy
from oldman.providers.redis import RedisClientRegistry
from oldman.serializers import MsgspecModel
from oldman.web.sse import SSEExtension, SSEPublisher, SSEQueueMode, SSEStream
from oldman.web.sse.connection import SSEConnection, SSEWriter


def require_redis_server(resolver: Callable[[str], str | None] = shutil.which) -> str:
    """Fail the Linux integration gate instead of silently skipping Redis."""
    executable = resolver("redis-server")
    if executable is None:
        raise RuntimeError("redis-server is required for the Linux integration gate")
    return executable


class DistributedStatus(MsgspecModel, kw_only=True):
    """Representative JSON payload delivered through Redis Pub/Sub."""

    value: int


class DistributedNotice(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports freezing this wire-only subclass
):
    """Lazy payload used to prove translation survives real Redis routing."""

    title: LazyTranslation


class Catalog:
    """Prefix translations to distinguish simulated browser languages."""

    def __init__(self, language: str) -> None:
        self.language = language

    def gettext(self, message: str) -> str:
        return f"{self.language}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        return f"{self.language}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        return f"{self.language}:{context}:{message}"


class RecordingWriter:
    """Record browser frames produced by one connection writer."""

    def __init__(self) -> None:
        self.frames: list[str] = []
        self.eof_count = 0

    async def send(self, data: str, end_stream: bool | None = None) -> None:
        del end_stream
        self.frames.append(data)

    async def eof(self) -> None:
        self.eof_count += 1


class RedisProcess:
    """Own one redis-server bound only to a temporary Unix socket."""

    def __init__(self, executable: str, directory: Path, name: str) -> None:
        self.socket_path = directory / f"{name}.sock"
        self.process = subprocess.Popen(
            [
                executable,
                "--save",
                "",
                "--appendonly",
                "no",
                "--port",
                "0",
                "--unixsocket",
                str(self.socket_path),
                "--unixsocketperm",
                "700",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while not self.socket_path.exists() and self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.socket_path.exists():
            self.stop()
            raise RuntimeError("redis-server did not create its owned Unix socket")

    def stop(self) -> None:
        """Stop Redis if it is still running."""
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


class SSERedisIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Exercise subscriber fan-out, gaps, recovery, and shutdown against Redis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.redis_executable = require_redis_server()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary_directory.name)
        cls.redis_process = RedisProcess(cls.redis_executable, cls.directory, "shared")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.redis_process.stop()
        cls.temporary_directory.cleanup()

    async def asyncSetUp(self) -> None:
        self.apps: list[Sanic] = []
        self.registries: list[RedisClientRegistry] = []
        self.extensions: list[SSEExtension] = []
        self.writer_tasks: list[asyncio.Task[None]] = []
        self.config = SSEConfig(
            enabled=True,
            redis_alias="SSE",
            channel_prefix=f"tests:sse:{time.time_ns()}",
            heartbeat_interval=60,
        )

    async def asyncTearDown(self) -> None:
        for extension, app in zip(self.extensions, self.apps, strict=False):
            await extension.before_server_stop(app)
        if self.writer_tasks:
            await asyncio.gather(*self.writer_tasks, return_exceptions=True)
        for registry in self.registries:
            await registry.close()
        for app in self.apps:
            Sanic.unregister_app(app)

    async def test_one_publish_reaches_each_worker_but_only_its_local_connection(self) -> None:
        registry = self.registry_for(self.redis_process.socket_path)
        first = self.extension(registry, "worker-one")
        second = self.extension(registry, "worker-two")
        await self.start(first)
        await self.start(second)
        first_writer, first_stream = self.local_user_stream(
            first,
            1,
            translations=Catalog("en"),
        )
        second_writer, second_stream = self.local_user_stream(
            second,
            1,
            translations=Catalog("zh"),
        )
        _other_writer, _other_stream = self.local_user_stream(second, 2)
        publisher = SSEPublisher(self.config, registry=registry)

        self.assertTrue(
            await publisher.publish_user(
                user_id=1,
                event="app.status",
                payload=DistributedNotice(
                    title=gettext_lazy("Import completed"),
                ),
            )
        )
        await self.wait_for(lambda: len(first_writer.frames) == 1 and len(second_writer.frames) == 1)

        self.assertEqual(
            ['event: app.status\ndata: {"title":"en:Import completed"}\n\n'],
            first_writer.frames,
        )
        self.assertEqual(
            ['event: app.status\ndata: {"title":"zh:Import completed"}\n\n'],
            second_writer.frames,
        )
        self.assertEqual((first_stream,), first.user_streams(1))
        self.assertEqual((second_stream,), second.user_streams(1))

    async def test_pubsub_gap_is_not_replayed_and_zero_browser_publish_succeeds(self) -> None:
        registry = self.registry_for(self.redis_process.socket_path)
        publisher = SSEPublisher(self.config, registry=registry)

        # Redis accepts this while neither a worker nor a browser is subscribed.
        self.assertTrue(
            await publisher.publish_user(
                user_id=0,
                event="app.status",
                payload=DistributedStatus(value=1),
            )
        )

        extension = self.extension(registry, "late-worker")
        writer, _stream = self.local_user_stream(extension, 0)
        await self.start(extension)
        await asyncio.sleep(0.03)
        self.assertEqual([], writer.frames)

        self.assertTrue(
            await publisher.publish_user(
                user_id=0,
                event="app.status",
                payload=DistributedStatus(value=2),
            )
        )
        await self.wait_for(lambda: len(writer.frames) == 1)
        self.assertIn('{"value":2}', writer.frames[0])

    async def test_initial_redis_failure_does_not_block_hook_and_later_recovers(self) -> None:
        late_socket = self.directory / f"late-{time.time_ns()}.sock"
        registry = self.registry_for(late_socket)
        extension = self.extension(registry, "recovering-worker")
        extension._retry_delays = (0.01,)
        writer, _stream = self.local_user_stream(extension, -1)

        with self.assertLogs("default.sse", level="INFO") as captured:
            started = time.monotonic()
            await extension.after_server_start(extension._app)  # type: ignore[arg-type]
            self.assertLess(time.monotonic() - started, 0.05)
            await self.wait_for(lambda: any("subscriber failed" in line for line in captured.output))

            late_redis = RedisProcess(self.redis_executable, self.directory, late_socket.stem)
            try:
                await asyncio.wait_for(extension._subscriber_ready.wait(), timeout=2)
                publisher = SSEPublisher(self.config, registry=registry)
                self.assertTrue(
                    await publisher.publish_user(
                        user_id=-1,
                        event="app.status",
                        payload=DistributedStatus(value=3),
                    )
                )
                await self.wait_for(lambda: len(writer.frames) == 1)
            finally:
                late_redis.stop()

        self.assertEqual(1, sum("subscriber failed" in line for line in captured.output))
        self.assertEqual(1, sum("subscriber recovered" in line for line in captured.output))

    async def test_stop_leaves_no_subscriber_task_and_closes_browser_stream(self) -> None:
        registry = self.registry_for(self.redis_process.socket_path)
        extension = self.extension(registry, "stopping-worker")
        writer, stream = self.local_user_stream(extension, 1)
        await self.start(extension)
        subscriber = extension._subscriber_task
        assert subscriber is not None

        app = extension._app
        assert app is not None
        await extension.before_server_stop(app)

        self.assertTrue(subscriber.done())
        self.assertIsNone(extension._subscriber_task)
        self.assertTrue(stream.is_closed)
        self.assertEqual(1, writer.eof_count)

    def registry_for(self, socket_path: Path) -> RedisClientRegistry:
        """Build and track one binary-capable named Redis registry."""
        redis_config = RedisConfig.model_validate(
            {
                "SSE": {
                    "redis_url": f"unix://{socket_path.as_posix()}?db=0",
                    "health_check_interval": 0,
                    "connection_socket_connect_timeout": 0.1,
                    "connection_socket_timeout": 0.1,
                }
            }
        )
        registry = RedisClientRegistry(redis_config)
        self.registries.append(registry)
        return registry

    def extension(self, registry: RedisClientRegistry, name: str) -> SSEExtension:
        """Initialize one simulated Web worker without touching Redis."""
        app = Sanic(f"oldman-sse-redis-{name}-{time.time_ns()}")
        extension = SSEExtension()
        settings = DefaultSettings.model_validate(
            {"web": WebConfig(sse=self.config).model_dump()}
        )
        with (
            patch.dict(conf.__dict__, {"settings": settings}),
            patch("oldman.web.sse.extension.redis_client", registry),
        ):
            extension.init_app(app)
        self.apps.append(app)
        self.extensions.append(extension)
        return extension

    async def start(self, extension: SSEExtension) -> None:
        """Start one subscriber and wait until Redis confirms SUBSCRIBE."""
        app = extension._app
        assert app is not None
        await extension.after_server_start(app)
        await asyncio.wait_for(extension._subscriber_ready.wait(), timeout=2)

    def local_user_stream(
        self,
        extension: SSEExtension,
        user_id: int,
        *,
        translations: Any = None,
    ) -> tuple[RecordingWriter, SSEStream]:
        """Register one local browser connection and run its sole writer."""
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
        return writer, stream

    async def wait_for(self, predicate: Callable[[], bool], timeout: float = 2) -> None:
        """Poll one event-loop-local condition with a bounded deadline."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                self.fail("timed out waiting for SSE integration condition")
            await asyncio.sleep(0.005)


if __name__ == "__main__":
    unittest.main()
