"""Offline settings and real managed lifecycles without production singleton resets."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import oldman.conf as conf
from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings, NATSBusConfig
from oldman.providers.nats import NATSConnection
from oldman.providers.nats.bus import _ConfiguredNATSConnection
from oldman.runtime import ServiceDefinition
from oldman.serializers import MsgspecModel

NATS_SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")


class Query(MsgspecModel):
    """Use the actual bytes codec and typed reply conversion."""

    value: int


class NatsBusConfigTest(unittest.TestCase):
    """Configuration never creates network resources or silently changes identity."""

    def test_defaults_and_validation_are_offline(self) -> None:
        """Check every default, disabled receive settings and invalid supplied values."""
        with patch("socket.socket", side_effect=AssertionError("settings must stay offline")):
            self.assertEqual(DefaultSettings().nats_bus.model_dump(), {
                "enabled": False, "nats_alias": "DEFAULT", "consume": False,
                "namespace": None, "peer_id": None, "serializer_mode": "msgpack",
                "startup_timeout": 30, "graceful_timeout": 10,
            })
            NATSBusConfig.model_validate({"consume": True, "nats_alias": "absent"})
            settings = DefaultSettings.model_validate({
                "nats": {"BUS": {"nats_url": "tls://localhost", "tls_ca_file": "/missing/ca.pem"}},
                "nats_bus": {"enabled": True, "namespace": "Mixed_App-1", "nats_alias": "BUS"},
            })
            self.assertEqual(settings.nats_bus.namespace, "Mixed_App-1")
        for values in ({"enabled": True}, {"serializer_mode": "legacy"}, {"nats_alias": ""}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                NATSBusConfig.model_validate(values)
        for field in ("namespace", "peer_id"):
            for value in ("", " ", "a.b", "a\nb", ">", "中文"):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    NATSBusConfig.model_validate({field: value})
        for field in ("startup_timeout", "graceful_timeout"):
            for value in (0, -1, float("inf"), float("nan")):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    NATSBusConfig.model_validate({field: value})
        with self.assertRaisesRegex(ValidationError, "nats_bus.nats_alias"):
            DefaultSettings.model_validate({"nats_bus": {"enabled": True, "namespace": "x", "nats_alias": "missing"}})

    def test_init_sync_preserve_values_and_comments(self) -> None:
        """Use the existing service configuration writer, including its non-Web rule."""
        with tempfile.TemporaryDirectory(prefix="oldman-bus-config-", dir="/tmp") as directory:
            root = Path(directory)
            path = root / "data" / "worker_settings.yaml"
            service = ServiceDefinition("worker", root / "services" / "worker.py", "simple")
            manager = SettingsManager(DefaultSettings, service, path)
            with patch("socket.socket", side_effect=AssertionError("init/sync must stay offline")):
                manager.init_config()
                self.assertFalse(manager.read_config()["nats_bus"]["enabled"])
                self.assertNotIn("web", manager.read_config())
                path.write_text("# operator settings\nnats_bus:\n  enabled: true\n  namespace: EPG-dev\n  consume: true\n  startup_timeout: 4\n", encoding="utf-8")
                manager.sync_config()
                settings = manager.load()
            self.assertTrue(settings.nats_bus.consume)
            self.assertEqual(settings.nats_bus.startup_timeout, 4)
            self.assertEqual(settings.nats_bus.namespace, "EPG-dev")
            self.assertIn("# operator settings", path.read_text())
            self.assertNotIn("web", manager.read_config())

    def test_import_and_declare_without_settings_or_sockets(self) -> None:
        """A fresh interpreter must import the actual singleton before bootstrap."""
        result = subprocess.run([sys.executable, "-c", '''
from unittest.mock import patch
with patch("socket.socket", side_effect=AssertionError("import opened socket")):
    import oldman.conf as conf
    from oldman.providers.nats import bus, NATSConnection
    from oldman.serializers import MsgspecModel
    assert conf._settings_instance is None
    assert isinstance(bus, NATSConnection)
    class Message(MsgspecModel):
        value: int
    @bus.subscriber("status", peer=True)
    async def receive(message: Message) -> Message:
        return message
    @bus.publisher("report")
    async def report(message: Message) -> Message:
        return message
    assert bus.broker._connection is None
    assert not bus.broker.running
'''], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_context_and_unstarted_call_fail(self) -> None:
        """An explicit managed scope cannot bypass the configured switch."""
        async def check() -> None:
            """No server is needed to reject lifecycle misuse."""
            bus = _ConfiguredNATSConnection()
            with self.assertRaisesRegex(RuntimeError, "not open"):
                await bus.publish(Query(value=1), "test")
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                async with bus:
                    self.fail("disabled context entered")
            self.assertIsNone(bus.broker._connection)
        with patch.dict(conf.__dict__, settings=DefaultSettings()):
            asyncio.run(check())

    @unittest.skipUnless(NATS_SERVER, "Set NATS_SERVER to a local executable")
    def test_typed_context_concurrency_and_cross_loop_reopen(self) -> None:
        """Late-bound native declarations survive both codecs and fresh event loops."""
        with tempfile.TemporaryDirectory(prefix="oldman-bus-live-", dir="/tmp") as directory:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            url = f"nats://127.0.0.1:{port}"
            with open(Path(directory) / "server.log", "wb") as log:
                server = subprocess.Popen([str(NATS_SERVER), "-a", "127.0.0.1", "-p", str(port)], stdout=log, stderr=log)
                try:
                    for codec in ("msgpack", "msgspec_json"):
                        settings = DefaultSettings.model_validate({
                            "nats": {"LOCAL": {"nats_url": url, "reconnect_time_wait": 0.01}},
                            "nats_bus": {"enabled": True, "consume": True, "namespace": "bus_test",
                                         "peer_id": "sender", "nats_alias": "LOCAL", "serializer_mode": codec},
                        })
                        bus = _ConfiguredNATSConnection()

                        @bus.subscriber("local", peer=True)
                        async def local(message: Query) -> Query:
                            """This declaration must not run in a sending-only scope."""
                            return message

                        async def exercise(bus: NATSConnection, settings: DefaultSettings) -> None:
                            """Observe explicit cleanup before the test's fallback cleanup."""
                            from nats.errors import NoRespondersError

                            receiver = NATSConnection(servers=[url], namespace="bus_test", serializer_mode=settings.nats_bus.serializer_mode)

                            @receiver.subscriber("query")
                            async def receive(message: Query) -> Query:
                                """Reply through the native decoder and publisher."""
                                return Query(value=message.value + 1)

                            await receiver.start()
                            try:
                                async with bus:
                                    self.assertFalse(bus.broker.running)
                                    client = bus.broker._connection
                                    with self.assertRaisesRegex(RuntimeError, "cannot enter again"):
                                        async with bus:
                                            self.fail("nested lifecycle entered")
                                    replies = await asyncio.gather(*(bus.request(Query(value=i), "query", Query) for i in range(3)))
                                    self.assertEqual([r.value for r in replies], [1, 2, 3])
                                    with self.assertRaises(NoRespondersError):
                                        await receiver.request(Query(value=1), "local", Query, peer_id="sender")
                                self.assertIsNotNone(client)
                                assert client is not None
                                self.assertTrue(client.is_closed)
                                self.assertIsNone(bus.broker._connection)
                                await bus.start()
                                try:
                                    self.assertIsNot(bus.broker._connection, client)
                                    reply = await receiver.request(Query(value=9), "local", Query, peer_id="sender")
                                    self.assertEqual(reply.value, 9)
                                finally:
                                    await bus.stop()
                            finally:
                                await receiver.stop()
                            self.assertFalse([t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()])

                        with patch.dict(conf.__dict__, settings=settings):
                            asyncio.run(exercise(bus, settings))
                            asyncio.run(exercise(bus, settings))
                finally:
                    server.terminate()
                    try:
                        server.wait(5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(5)


if __name__ == "__main__":
    unittest.main()
