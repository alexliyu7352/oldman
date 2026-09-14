"""Configured native NATS security; real cases own their server and certificates.

Set NATS_SERVER to a binary. NATS_TEST_CREDS_DIR may point to the public nats.py
v2.15.0 nkeys fixtures (op.jwt, resolver_preload.conf, foo-user.creds).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from nats.aio.client import Client
from nats.aio.transport import TcpTransport
from nats.errors import Error as NatsError

from oldman.conf.schemas import NATSConnectionConfig
from oldman.providers.nats import NATSConnection
from oldman.providers.nats._compat import install_close_fix, install_tls_requirement
from oldman.providers.nats.config import nats_connection_options

NATS_SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")
CREDS_DIRECTORY = os.environ.get("NATS_TEST_CREDS_DIR")


class NATSOptionsTest(unittest.TestCase):
    """Pure parameter conversion has no client or authentication side effects."""

    def test_url_credentials_are_decoded_separately_and_removed_from_address(self) -> None:
        """Encoded delimiters stay inside credentials, including IPv6 endpoints."""
        for url, expected in (
            ("nats://demo:p%40ss%3Aword@[::1]:4222", {"user": "demo", "password": "p@ss:word"}),
            ("nats://my%2Btoken@[::1]:4222", {"token": "my+token"}),
        ):
            options = nats_connection_options(NATSConnectionConfig(nats_url=url))
            self.assertEqual(["nats://[::1]:4222"], options["servers"])
            for key, value in expected.items():
                self.assertEqual(value, options[key])
            self.assertEqual(-1, options["max_reconnect_attempts"])
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            nats_connection_options(NATSConnectionConfig(nats_url="nats://%ff@localhost"))

    def test_tls_context_and_instance_hook_do_not_change_other_clients(self) -> None:
        """Explicit TLS keeps hostname/certificate verification; missing files fail."""
        options = nats_connection_options(NATSConnectionConfig(nats_url="tls://localhost:4222"))
        self.assertTrue(options["tls"].check_hostname)
        self.assertEqual(ssl.CERT_REQUIRED, options["tls"].verify_mode)
        with self.assertRaises(FileNotFoundError):
            nats_connection_options(NATSConnectionConfig(nats_url="tls://localhost", tls_ca_file=Path("/missing/oldman-ca.pem")))
        original = Client._process_info
        client, unrelated = Client(), Client()
        install_close_fix(client)
        install_tls_requirement(client)
        installed = client._process_info
        install_tls_requirement(client)
        self.assertEqual(installed, client._process_info)
        self.assertIs(original, Client._process_info)
        self.assertEqual(original.__get__(unrelated, Client), unrelated._process_info)


@unittest.skipUnless(NATS_SERVER, "Set NATS_SERVER to run real TLS checks")
class NATSTLSIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Verify the actual public options through NATS TLS, rejection and reconnect."""

    @classmethod
    def setUpClass(cls) -> None:
        """Prepare short-lived local test identities, never using operator secrets."""
        cls.temporary = tempfile.TemporaryDirectory(prefix="oldman-nats-tls-", dir="/tmp")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        (cls.root / "extensions.conf").write_text("subjectAltName=DNS:localhost\n", encoding="utf-8")
        commands = [
            ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=OldmanTestCA", "-days", "1"],
        ]
        for name in ("server", "client"):
            commands.extend([
                ["req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                ["x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", f"{name}.crt", "-days", "1", "-extfile", "extensions.conf"],
            ])
        for command in commands:
            subprocess.run(["openssl", *command], cwd=cls.root, check=True, capture_output=True, timeout=15)

    async def asyncSetUp(self) -> None:
        """Allocate one loopback endpoint and track every client and server."""
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.clients: list[Client] = []
        self.server: subprocess.Popen[bytes] | None = None
        self.errors: list[Exception] = []
        self.cleanup_timeouts = 0
        self.log = self.enterContext((self.root / "server.log").open("wb"))
        self.addAsyncCleanup(self.cleanup)

    async def record_error(self, error: Exception) -> None:
        """Keep actual native failures observable without printing authentication data."""
        self.errors.append(error)

    async def start_server(self, *, mutual: bool = False, credentials: bool = False, authentication: str = "") -> None:
        """Start this test's real NATS with the supplied TLS/authentication policy."""
        configuration = (
            f'host: "127.0.0.1"\nport: {self.port}\n'
            f'tls {{ cert_file: "{self.root / "server.crt"}", key_file: "{self.root / "server.key"}", '
            f'ca_file: "{self.root / "ca.crt"}", verify: {str(mutual).lower()} }}\n'
        )
        if credentials:
            assert CREDS_DIRECTORY is not None
            directory = Path(CREDS_DIRECTORY)
            configuration += (directory / "resolver_preload.conf").read_text(encoding="utf-8")
        configuration += authentication
        path = self.root / "server.conf"
        path.write_text(configuration, encoding="utf-8")
        self.server = subprocess.Popen([str(NATS_SERVER), "-c", str(path)], stdout=self.log, stderr=self.log)
        async with asyncio.timeout(5):
            while True:
                if self.server.poll() is not None:
                    raise RuntimeError((self.root / "server.log").read_text(encoding="utf-8")[-1800:])
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", self.port)
                except OSError:
                    await asyncio.sleep(0.02)
                else:
                    writer.close()
                    await writer.wait_closed()
                    break

    async def stop_server(self) -> None:
        """Stop only the process created by this case."""
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            await asyncio.to_thread(self.server.wait, 5)

    async def cleanup(self) -> None:
        """Bound failed certificate cleanup too; do not mask a prior assertion/error."""
        for client in self.clients:
            try:
                async with asyncio.timeout(5):
                    await client.close()
            except TimeoutError:
                self.cleanup_timeouts += 1
                print("Expected native failed-TLS cleanup timeout (bounded at 5 seconds)")
        await self.stop_server()

    def config(self, **changes: Any) -> NATSConnectionConfig:
        """Construct production settings, with short waits only for this experiment."""
        return NATSConnectionConfig.model_validate({
            "nats_url": f"tls://localhost:{self.port}", "tls_ca_file": self.root / "ca.crt",
            "connect_timeout": 1, "reconnect_time_wait": 0.1, **changes,
        })

    async def connect(self, config: NATSConnectionConfig, *, reconnect: bool = False) -> Client:
        """Use production conversion and both instance hooks before native connect."""
        client = Client()
        self.clients.append(client)
        options = nats_connection_options(config)
        install_close_fix(client)
        if options.get("tls") is not None:
            install_tls_requirement(client)
        async with asyncio.timeout(5):
            await client.connect(**options, allow_reconnect=reconnect, error_cb=self.record_error)
        return client

    async def round_trip(self, client: Client) -> None:
        """Prove encrypted pub/sub, not just a connected flag."""
        assert isinstance(client._transport, TcpTransport)
        assert client._transport._io_writer is not None
        self.assertIsNotNone(client._transport._io_writer.get_extra_info("ssl_object"))
        subscription = await client.subscribe("oldman.security.check")
        await client.publish("oldman.security.check", "中文".encode())
        await client.flush(timeout=2)
        message = await subscription.next_msg(timeout=2)
        self.assertEqual("中文".encode(), message.data)
        await subscription.unsubscribe()

    async def test_core_provider_tls_and_failed_handshake_cleanup(self) -> None:
        """The public provider installs security before connect and closes rejected TLS."""
        await self.start_server(authentication='authorization { user: "demo", password: "p@ss:word" }\n')
        for hostname in ("localhost", "127.0.0.1"):
            options = nats_connection_options(self.config(nats_url=f"tls://demo:p%40ss%3Aword@{hostname}:{self.port}"))
            provider = NATSConnection(namespace="security", allow_reconnect=False, **options)
            self.addAsyncCleanup(provider.stop)
            if hostname == "localhost":
                async with provider:
                    client = provider.broker._connection
                    assert client is not None
                    self.clients.append(client)
                    await self.round_trip(client)
                self.assertTrue(client.is_closed)
            else:
                task = asyncio.create_task(provider.start())
                await asyncio.sleep(0)
                client = provider.broker._connection
                assert client is not None
                async with asyncio.timeout(15):
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        await task
                # nats-py may wait on the old writer after failed TLS upgrade.
                # Bounded cleanup failure is not a successful reusable close.
                self.assertTrue(client.is_closed)
                self.assertEqual({}, client._subs)
                assert isinstance(client._transport, TcpTransport)
                writer = client._transport._io_writer
                assert writer is not None
                self.assertTrue(writer.is_closing())
                # uvloop may remove the socket entirely once TLS cleanup closes it.
                closed_socket = writer.get_extra_info("socket")
                self.assertTrue(closed_socket is None or closed_socket.fileno() == -1)
                self.assertEqual(set(), asyncio.all_tasks() - {asyncio.current_task()})
                with self.assertRaises(RuntimeError):
                    await provider.start()
            self.assertIsNone(provider.broker._connection)

    async def test_core_provider_never_sends_credentials_to_plaintext(self) -> None:
        """Exercise the actual pre-connect install, not just the standalone TLS hook."""
        frames: list[bytes] = []
        finished = asyncio.Event()

        async def plaintext(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Record frames from a peer that explicitly does not offer TLS."""
            writer.write(b'INFO {"server_id":"PLAIN","version":"2.12.0","max_payload":1048576,"tls_required":false}\r\n')
            await writer.drain()
            try:
                while line := await reader.readline():
                    frames.append(line)
            finally:
                writer.close()
                await writer.wait_closed()
                finished.set()

        async with await asyncio.start_server(plaintext, "127.0.0.1", self.port):
            options = nats_connection_options(self.config(nats_url=f"tls://secret-token@127.0.0.1:{self.port}"))
            provider = NATSConnection(namespace="security", allow_reconnect=False, **options)
            self.addAsyncCleanup(provider.stop)
            with self.assertRaises(ssl.SSLError):
                await provider.start()
            await asyncio.wait_for(finished.wait(), 2)
            self.assertFalse(any(frame.startswith(b"CONNECT") for frame in frames))
            self.assertIsNone(provider.broker._connection)

    async def test_tls_encoded_password_and_certificate_rejection(self) -> None:
        """Valid encoded URL auth works; wrong CA and hostname never connect."""
        await self.start_server(authentication='authorization { user: "demo", password: "p@ss:word" }\n')
        client = await self.connect(self.config(nats_url=f"tls://demo:p%40ss%3Aword@localhost:{self.port}"))
        await self.round_trip(client)
        for config in (
            self.config(tls_ca_file=None),
            self.config(nats_url=f"tls://127.0.0.1:{self.port}"),
        ):
            with self.assertRaises(ssl.SSLCertVerificationError):
                await self.connect(config)

    async def test_mutual_tls_requires_client_certificate(self) -> None:
        """Server-enforced client certificate verification works through our options."""
        await self.start_server(mutual=True)
        client = await self.connect(self.config(tls_cert_file=self.root / "client.crt", tls_key_file=self.root / "client.key"))
        await self.round_trip(client)
        with self.assertRaises((ssl.SSLError, NatsError, ConnectionError)):
            await self.connect(self.config())
        self.assertFalse(self.clients[-1].is_connected)

    @unittest.skipUnless(CREDS_DIRECTORY, "Set NATS_TEST_CREDS_DIR to the public upstream nkeys fixtures")
    async def test_native_credentials(self) -> None:
        """Use nats-py's real credentials parser/signature, never a fake login."""
        await self.start_server(credentials=True)
        assert CREDS_DIRECTORY is not None
        client = await self.connect(self.config(credentials_file=Path(CREDS_DIRECTORY) / "foo-user.creds"))
        await self.round_trip(client)
        with self.assertRaisesRegex(NatsError, "Authorization"):
            await self.connect(self.config())
        self.assertFalse(self.clients[-1].is_connected)

    async def test_plaintext_rejected_before_connect_and_reconnect_recovers(self) -> None:
        """The same client never downgrades after TLS disappears at its endpoint."""
        await self.start_server()
        client = await self.connect(self.config(nats_url=f"tls://test-token@localhost:{self.port}"), reconnect=True)
        await self.round_trip(client)
        rejected_writers: list[asyncio.StreamWriter] = []

        async def observe_rejection(error: Exception) -> None:
            """Keep rejected client sockets alive so GC cannot conceal a cleanup leak."""
            if isinstance(error, ssl.SSLError):
                assert isinstance(client._transport, TcpTransport)
                assert client._transport._io_writer is not None
                rejected_writers.append(client._transport._io_writer)
            await self.record_error(error)

        client._error_cb = observe_rejection
        await self.stop_server()
        writers: list[asyncio.StreamWriter] = []
        frames: list[bytes] = []

        async def plaintext(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Negative endpoint advertises no TLS and records any leaked CONNECT."""
            writers.append(writer)
            info = {"server_id": "PLAINTEXT", "version": "2.14.6", "max_payload": 1048576, "auth_required": True, "tls_required": False}
            writer.write(b"INFO " + json.dumps(info).encode() + b"\r\n")
            await writer.drain()
            try:
                while line := await reader.readline():
                    if line.startswith(b"CONNECT"):
                        frames.append(line)
                    elif line.startswith(b"PING"):
                        writer.write(b"PONG\r\n")
                        await writer.drain()
            finally:
                writer.close()

        peer = await asyncio.start_server(plaintext, "127.0.0.1", self.port)
        try:
            # Test a first connection as well as repeated handshakes of the old client.
            with self.assertRaises(ssl.SSLError):
                await self.connect(self.config(nats_url=f"tls://test-token@localhost:{self.port}"))
            async with asyncio.timeout(5):
                while len(rejected_writers) < 2:
                    await asyncio.sleep(0.02)
            self.assertEqual([], frames)
            self.assertTrue(all(writer.is_closing() for writer in rejected_writers))
            self.assertTrue(any(isinstance(error, ssl.SSLError) for error in self.errors))
        finally:
            peer.close()
            for writer in writers:
                writer.close()
            await peer.wait_closed()
        await self.start_server()
        async with asyncio.timeout(5):
            while not client.is_connected:
                await asyncio.sleep(0.02)
        await self.round_trip(client)


if __name__ == "__main__":
    unittest.main()
