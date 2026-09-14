"""Real TCP close regression checks; NATS_SERVER selects an executable, never a live server.

Run with NATS_SERVER=/path/to/nats-server python -m unittest tests.test_oldman_nats_close.
The suite owns its server and temporary storage and runs cases sequentially.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path
from typing import Any

import msgspec
import nats
from faststream import Depends
from faststream import Path as PathParam
from faststream._internal.endpoint.subscriber.mixins import ConcurrentMixin
from faststream.nats import NatsMessage
from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.errors import ConnectionClosedError, ConnectionReconnectingError, NoRespondersError, OutboundBufferLimitError
from nats.errors import TimeoutError as NatsTimeoutError

from oldman.providers.nats import NATSConnection
from oldman.serializers import MsgspecModel

NATS_SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")


class Payload(MsgspecModel):
    """A body peer_id is business data, distinct from the injected source."""
    value: str
    peer_id: str = "body"


async def dependency() -> str:
    """Prove ordinary asynchronous FastStream dependencies still execute."""
    return "dependency"


class ObservedConnection(NATSConnection):
    """Observe real provider callbacks without changing its connection or stop code."""

    def __init__(self, url: str, **kwargs: Any) -> None:
        self.errors: list[Exception] = []
        self.closed_count = 0
        self.fail_error_callback = False
        super().__init__(servers=[url], name="close-test", namespace="close_test", **kwargs)

    async def _error_callback(self, error: Exception) -> None:
        """Record errors; optionally exercise failure in final-flush error reporting."""
        self.errors.append(error)
        if self.fail_error_callback and isinstance(error, (TypeError, RuntimeError)):
            raise RuntimeError("test error callback failed")

    async def _closed_callback(self) -> None:
        """Count the actual native close callback."""
        self.closed_count += 1


@unittest.skipUnless(NATS_SERVER, "Set NATS_SERVER to a local nats-server executable")
class NatsCloseTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the shared fix through the actual Oldman/FastStream lifecycle."""

    async def asyncSetUp(self) -> None:
        """Start one test-owned JetStream server on loopback with an empty store."""
        self.directory = tempfile.TemporaryDirectory(prefix="oldman-nats-close-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.log = self.enterContext(open(Path(self.directory.name) / "server.log", "wb"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"nats://127.0.0.1:{self.port}"
        self.server = self.start_server()
        self.addAsyncCleanup(self.stop_server)
        self.provider = ObservedConnection(self.url)
        self.clients: list[Client] = []
        self.addAsyncCleanup(self.close_clients)

    def start_server(self) -> subprocess.Popen[bytes]:
        """Start or restart only this case's server and its existing store."""
        return subprocess.Popen(
            [str(NATS_SERVER), "-a", "127.0.0.1", "-p", str(self.port), "-js", "-sd", self.directory.name],
            stdout=self.log, stderr=self.log,
        )

    async def stop_server(self) -> None:
        """Stop this child only, including when a test assertion fails."""
        if self.server.poll() is None:
            self.server.terminate()
            try:
                await asyncio.to_thread(self.server.wait, 3)
            except subprocess.TimeoutExpired:
                self.server.kill()
                await asyncio.to_thread(self.server.wait, 3)

    async def close_clients(self) -> None:
        """Best-effort test teardown, always after explicit cleanup assertions."""
        try:
            with suppress(ConnectionClosedError, ConnectionReconnectingError):
                await self.provider.stop()
        finally:
            for client in self.clients:
                if not client.is_closed:
                    await client.close()

    async def connect(self) -> Client:
        """Use the public provider startup; obtain its already-connected native client."""
        async with asyncio.timeout(6):
            await self.provider.start()
        client = await self.provider.broker.connect()
        self.clients.append(client)
        js = client.jetstream()
        await js.add_stream(name="CLOSE_TEST", subjects=["close.test"], max_bytes=1048576)
        await js.publish("close.test", b"initial")
        return client

    async def disconnect(self, client: Client) -> None:
        """Leave real buffered data after the server stops and publishing times out."""
        await self.stop_server()
        async with asyncio.timeout(5):
            while not client.is_reconnecting:
                await asyncio.sleep(0.01)
        with self.assertRaises(NatsTimeoutError):
            await client.jetstream().publish("close.test", b"offline", timeout=0.1)
        self.assertGreater(client._pending_data_size, 0)

    async def assert_released(self, client: Client) -> None:
        """Inspect before loop teardown; CLOSED alone is not proof of cleanup."""
        await asyncio.sleep(0.02)
        self.assertEqual({}, client._subs)
        self.assertEqual(0, client._pending_data_size)
        self.assertEqual(1, self.provider.closed_count)
        self.assertEqual(set(), asyncio.all_tasks() - {asyncio.current_task()})

    async def test_typed_rpc_publisher_source_and_send_only_context(self) -> None:
        """Exercise both actual wire codecs, peer routing, DI and sequential reopening."""
        for codec in ("msgpack", "msgspec_json"):
            receiver = ObservedConnection(self.url, peer_id="Receiver", serializer_mode=codec)
            sender = ObservedConnection(self.url, peer_id="Sender", serializer_mode=codec)
            self.addAsyncCleanup(receiver.stop)
            self.addAsyncCleanup(sender.stop)
            seen: list[tuple[Payload, str]] = []
            arrived = asyncio.Event()

            @receiver.subscriber("echo", peer=True)
            @receiver.publisher("observed")
            async def echo(message: Payload, peer_id: str, dep: str = Depends(dependency)) -> Payload:
                """Injected source does not replace the body's identically named field."""
                return Payload(value=f"{message.value}:{peer_id}:{dep}", peer_id=message.peer_id)

            @receiver.subscriber("observed")
            async def observe(message: Payload, *, peer_id: str, nats_msg: NatsMessage) -> None:
                """Native raw message and keyword-only source injection work together."""
                self.assertIn(".shared.observed", nats_msg.raw_message.subject)
                seen.append((message, peer_id))  # noqa: B023 - This receiver is closed before the next codec.
                arrived.set()  # noqa: B023 - This receiver is closed before the next codec.

            @sender.subscriber("not-started", max_workers=2)
            async def should_not_receive(message: Payload) -> Payload:
                """A sending context must not start this declared subscriber."""
                return message

            @receiver.subscriber("服务器.{server_id}")
            async def by_server(message: Payload, server_id: str = PathParam(), *, peer_id: str) -> Payload:
                """Parameterized native subjects still extract the business path field."""
                return Payload(f"{message.value}:{server_id}:{peer_id}")

            @receiver.subscriber("malformed")
            async def malformed(message: Payload) -> bytes:
                """Invalid bytes must remain a caller decoding error, not a success."""
                return b"\xc1"

            await receiver.start()
            assert receiver.broker._connection is not None
            await receiver.broker._connection.flush()
            previous: Client | None = None
            for _ in range(2):
                async with sender:
                    current = sender.broker._connection
                    self.assertIsNot(previous, current)
                    previous = current
                    self.assertTrue(sender.connection_info["is_connected"])
                    with self.assertRaises(RuntimeError):
                        async with sender:
                            pass
                    reply = await sender.request(Payload("hello"), "echo", Payload, peer_id="Receiver")
                    self.assertEqual(Payload("hello:Sender:dependency", peer_id="body"), reply)
                    reply = await sender.request(Payload("path"), "服务器.node1", Payload)
                    self.assertEqual("path:node1:Sender", reply.value)
                    with self.assertRaises(NoRespondersError):
                        await sender.request(Payload("hello"), "not-started", Payload)
                    with self.assertRaises(msgspec.DecodeError):
                        await sender.request(Payload("hello"), "malformed", Payload)
                    await asyncio.wait_for(arrived.wait(), 2)
                    self.assertEqual("Receiver", seen[-1][1])
                self.assertFalse(sender.connection_info["is_connected"])
            async with NATSConnection(servers=[self.url], namespace="another_app", serializer_mode=codec) as isolated:
                with self.assertRaises(NoRespondersError):
                    await isolated.request(Payload("hello"), "echo", Payload, peer_id="Receiver")
            await receiver.stop()
        self.assertEqual(set(), asyncio.all_tasks() - {asyncio.current_task()})

    async def test_handler_cancellation_finishes_before_stop_returns(self) -> None:
        """A real handler finally may outlive native stop; wait for its actual exit."""
        self.provider = ObservedConnection(self.url, graceful_timeout=0.02)
        entered, exited = asyncio.Event(), asyncio.Event()

        @self.provider.subscriber("slow")
        async def slow(message: Payload) -> None:
            """Simulate cooperative cancellation followed by asynchronous cleanup."""
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.04)
                exited.set()

        await self.provider.start()
        client = self.provider.broker._connection
        assert client is not None
        await self.provider.publish(Payload("slow"), "slow")
        await asyncio.wait_for(entered.wait(), 2)
        await self.provider.stop()
        self.assertTrue(exited.is_set())
        await self.assert_released(client)

    async def test_failed_publish_and_rpc_release_only_their_own_future(self) -> None:
        """A genuine disconnected full buffer rejects sending and does not leak RPC state."""
        self.provider = ObservedConnection(self.url, pending_size=512, reconnect_time_wait=0.05)
        client = await self.connect()
        # Initialize the native multiplexed inbox before disconnecting.
        with self.assertRaises(NoRespondersError):
            await self.provider.request(Payload("missing"), "missing", Payload)
        await self.disconnect(client)
        # One small RPC can still buffer and wait while an oversized one fails.
        waiting = asyncio.create_task(self.provider.request(Payload("wait"), "wait", Payload, request_timeout=5))
        await asyncio.sleep(0)
        before = dict(client._resp_map)
        self.assertEqual(1, len(before))
        with self.assertRaises(OutboundBufferLimitError):
            await self.provider.publish(b"x" * 1024, "full")
        with self.assertRaises(OutboundBufferLimitError):
            await self.provider.request(b"x" * 1024, "full", Payload)
        await asyncio.sleep(0)
        self.assertEqual(before, client._resp_map)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual({}, client._resp_map)
        with self.assertRaises(ConnectionReconnectingError):
            await self.provider.stop()
        await self.assert_released(client)
        with self.assertRaises(RuntimeError):
            await self.provider.start()

    async def test_startup_timeout_and_cancellation_release_partial_client(self) -> None:
        """An unavailable endpoint never leaves native startup resources behind."""
        await self.stop_server()
        for cancel in (False, True):
            self.provider = ObservedConnection(self.url, startup_timeout=0.1, reconnect_time_wait=0.01)
            task = asyncio.create_task(self.provider.start())
            async with asyncio.timeout(2):
                while self.provider.broker._connection is None:
                    await asyncio.sleep(0)
                client = self.provider.broker._connection
                if cancel:
                    await asyncio.sleep(0.02)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    with self.assertRaises(TimeoutError) as caught:
                        await task
                    self.assertIsInstance(caught.exception.__cause__, OSError)
            await self.assert_released(client)
            self.assertIsNone(self.provider.broker._connection)

    async def test_cancel_stop_still_waits_for_receiver_exit(self) -> None:
        """Cancelling the lifecycle waiter does not abandon receiver cleanup."""
        self.provider = ObservedConnection(self.url, graceful_timeout=0.02)
        entered, exited = asyncio.Event(), asyncio.Event()

        @self.provider.subscriber("slow")
        async def slow(message: Payload) -> None:
            """Make cancellation and completion observably separate."""
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.04)
                exited.set()

        await self.provider.start()
        client = self.provider.broker._connection
        assert client is not None
        await self.provider.publish(Payload("slow"), "slow")
        await asyncio.wait_for(entered.wait(), 2)
        task = asyncio.create_task(self.provider.stop())
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(exited.is_set())
        await self.assert_released(client)

    async def test_concurrent_subscriber_can_reopen_in_a_new_loop(self) -> None:
        """IDE-style sequential asyncio.run calls must not reuse closed-loop resources."""
        receiver = ObservedConnection(self.url)

        @receiver.subscriber("repeat", max_workers=2)
        async def echo(message: Payload) -> Payload:
            """Force native concurrency limits to be exercised, not just a serial call."""
            await asyncio.sleep(0.01)
            return message

        async def run() -> Client:
            """Open/close the same declaration on a fresh real event loop."""
            await receiver.start()
            client = receiver.broker._connection
            assert client is not None
            try:
                await client.flush()
                replies = await asyncio.gather(*(receiver.request(Payload(str(i)), "repeat", Payload) for i in range(6)))
                self.assertEqual([str(i) for i in range(6)], [reply.value for reply in replies])
            finally:
                await receiver.stop()
            subscriber = next(iter(receiver.broker.subscribers))
            assert isinstance(subscriber, ConcurrentMixin)
            self.assertEqual(0, subscriber.send_stream.statistics().open_send_streams)
            self.assertEqual(0, subscriber.receive_stream.statistics().open_receive_streams)
            self.assertEqual(set(), asyncio.all_tasks() - {asyncio.current_task()})
            return client

        previous: Client | None = None
        for _ in range(2):
            client = await asyncio.to_thread(asyncio.run, run())
            self.assertIsNot(previous, client)
            self.assertTrue(client.is_closed)
            previous = client

    async def test_final_drain_timeout_reaps_native_callback(self) -> None:
        """The real ten-second drain budget must not orphan a cancelled callback."""
        client = await self.connect()
        entered, exited = asyncio.Event(), asyncio.Event()

        async def raw_callback(message: Msg) -> None:
            """A native subscription is outside the business handler grace stage."""
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.04)
                exited.set()

        await client.subscribe("drain.pending", cb=raw_callback)
        await client.publish("drain.pending", b"pending")
        await asyncio.wait_for(entered.wait(), 2)
        async with asyncio.timeout(13):
            with self.assertRaisesRegex(TimeoutError, "drain exceeded"):
                await self.provider.stop()
        self.assertTrue(exited.is_set())
        await self.assert_released(client)

    async def test_offline_provider_stop_releases_resources_but_keeps_drain_error(self) -> None:
        """A failed drain must still reach the patched close through provider.stop()."""
        client = await self.connect()
        await self.disconnect(client)
        with self.assertRaises(ConnectionReconnectingError):
            await self.provider.stop()
        await self.assert_released(client)
        self.assertTrue(any(isinstance(error, (TypeError, RuntimeError)) for error in self.provider.errors))
        self.assertIsNone(self.provider.broker._connection)
        await self.provider.stop()
        self.assertEqual(1, self.provider.closed_count)

    async def test_healthy_stop_delivers_buffered_message_and_preserves_rpc(self) -> None:
        """Real RPC and a separately observed final message guard the healthy path."""
        client = await self.connect()

        async def echo(message: Msg) -> None:
            await client.publish(message.reply, message.data)

        await client.subscribe("close.echo", cb=echo)
        self.assertEqual(b"ping", (await client.request("close.echo", b"ping", timeout=1)).data)
        await client.publish("close.test", b"buffered")
        self.assertGreater(client._pending_data_size, 0)
        await self.provider.stop()
        await self.assert_released(client)

        observer = await nats.connect(self.url)
        self.clients.append(observer)
        info = await observer.jetstream().stream_info("CLOSE_TEST")
        self.assertEqual(2, info.state.messages)
        await observer.close()

    async def test_error_callback_exception_happens_after_cleanup(self) -> None:
        """Reporting the failed flush may raise without leaving a subscription behind."""
        client = await self.connect()
        await self.disconnect(client)
        self.provider.fail_error_callback = True
        with self.assertRaisesRegex(RuntimeError, "test error callback failed"):
            await client.close()
        await self.assert_released(client)
        # Native drain rejects an already closed client; the broker still releases its reference.
        with self.assertRaises(ConnectionClosedError):
            await self.provider.stop()
        await client.close()
        self.assertEqual(1, self.provider.closed_count)


if __name__ == "__main__":
    unittest.main()
