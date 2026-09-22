"""SMTP backend round trips against a local aiosmtpd server."""

from __future__ import annotations

import socket
import unittest
from email import message_from_bytes
from email.policy import default as default_policy
from typing import Any
from unittest.mock import patch

import aiosmtplib
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from oldman.conf.schemas import MailConfig
from oldman.mail import EmailMessage, EmailMultiAlternatives, send_mail, use_mail_config
from oldman.mail.backends.smtp import SMTPEmailBackend

SMTP_BACKEND = "oldman.mail.backends.smtp.SMTPEmailBackend"


class RecordingHandler:
    """Keep every accepted envelope so tests can inspect sender, recipients and content."""

    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.envelopes.append(envelope)
        return "250 Message accepted for delivery"


def _authenticator(server: Any, session: Any, envelope: Any, mechanism: str, auth_data: Any) -> AuthResult:
    if isinstance(auth_data, LoginPassword) and auth_data.login == b"mailer" and auth_data.password == b"secret":
        return AuthResult(success=True)
    return AuthResult(success=False, handled=False)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class SMTPBackendTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.handler = RecordingHandler()
        self.port = _free_port()
        self.controller = Controller(
            self.handler,
            hostname="127.0.0.1",
            port=self.port,
            authenticator=_authenticator,
            auth_require_tls=False,
        )
        self.controller.start()
        self._server_running = True
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        if self._server_running:
            self._server_running = False
            self.controller.stop()

    def _use(self, **smtp: object):
        values: dict[str, object] = {"host": "127.0.0.1", "port": self.port}
        values.update(smtp)
        return use_mail_config(MailConfig.model_validate({"backend": SMTP_BACKEND, "default_from_email": "noreply@example.com", "smtp": values}))

    async def test_send_mail_delivers_envelope_and_content_without_authentication(self) -> None:
        with self._use():
            message = EmailMultiAlternatives("Round trip 你好", "plain body", "Oldman <noreply@example.com>", ["To One <one@example.com>"], bcc=["hidden@example.com"], cc=["cc@example.com"])
            message.attach_alternative("<p>html body</p>", "text/html")
            message.attach("data.csv", "a,b\n", "text/csv")

            self.assertEqual(1, await message.send())

        envelope = self.handler.envelopes[0]
        self.assertEqual("noreply@example.com", envelope.mail_from)
        self.assertEqual(["one@example.com", "cc@example.com", "hidden@example.com"], envelope.rcpt_tos)
        received = message_from_bytes(envelope.content, policy=default_policy)
        self.assertEqual("Round trip 你好", received["Subject"])
        self.assertIsNone(received["Bcc"])
        self.assertEqual("multipart/mixed", received.get_content_type())
        alternatives = [part.get_content_type() for part in list(received.iter_parts())[0].iter_parts()]
        self.assertEqual(["text/plain", "text/html"], alternatives)
        # The wire format is CRLF; the receiver keeps it, so compare line-ending agnostic.
        self.assertEqual("a,b\n", list(received.iter_parts())[1].get_content().replace("\r\n", "\n"))

    async def test_one_connection_carries_several_messages_and_authenticates(self) -> None:
        with self._use(username="mailer", password="secret"):
            async with SMTPEmailBackend() as connection:
                sent = await connection.send_messages([
                    EmailMultiAlternatives("First", "1", None, ["a@example.com"]),
                    EmailMultiAlternatives("Second", "2", None, ["b@example.com"]),
                ])
                self.assertIsNotNone(connection.connection)
            self.assertIsNone(connection.connection)

        self.assertEqual(2, sent)
        self.assertEqual(["a@example.com", "b@example.com"], [envelope.rcpt_tos[0] for envelope in self.handler.envelopes])

    async def test_bad_credentials_raise_unless_fail_silently(self) -> None:
        with self._use(username="mailer", password="wrong"):
            with self.assertRaises(aiosmtplib.SMTPAuthenticationError):
                await send_mail("x", "y", None, ["a@example.com"])
            self.assertEqual(0, await send_mail("x", "y", None, ["a@example.com"], fail_silently=True))
        self.assertEqual([], self.handler.envelopes)

    async def test_unreachable_server_raises_unless_fail_silently(self) -> None:
        self._stop_server()
        with self._use():
            with self.assertRaises((aiosmtplib.SMTPException, OSError)):
                await send_mail("x", "y", None, ["a@example.com"])
            self.assertEqual(0, await send_mail("x", "y", None, ["a@example.com"], fail_silently=True))


class FakeClient:
    """Stand-in for aiosmtplib.SMTP: scripts what send_message and quit do, records the transport teardown."""

    send_error: BaseException | None = None
    quit_error: BaseException | None = None
    instances: list[FakeClient] = []

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.connected = False
        self.closed = False
        self.quit_calls = 0
        FakeClient.instances.append(self)

    async def connect(self) -> None:
        self.connected = True

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def send_message(self, *_args: Any, **_kwargs: Any) -> None:
        if self.send_error is not None:
            # aiosmtplib tears the transport down itself on a timeout or a server disconnect.
            self.connected = False
            raise self.send_error

    async def quit(self) -> None:
        self.quit_calls += 1
        if self.quit_error is not None:
            raise self.quit_error

    def close(self) -> None:
        self.closed = True
        self.connected = False


class SMTPConnectionTeardownTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        token = use_mail_config(MailConfig.model_validate({"backend": SMTP_BACKEND, "default_from_email": "noreply@example.com", "smtp": {"host": "127.0.0.1", "port": 2525}}))
        token.__enter__()
        self.addCleanup(token.__exit__, None, None, None)
        FakeClient.instances.clear()

    async def test_a_dead_transport_keeps_the_send_error_and_closes_quietly(self) -> None:
        class Dying(FakeClient):
            send_error = aiosmtplib.SMTPTimeoutError("Timed out waiting for server response")
            quit_error = aiosmtplib.SMTPServerDisconnected("Server not connected")

        with patch("oldman.mail.backends.smtp.aiosmtplib.SMTP", Dying):
            per_call = SMTPEmailBackend()
            with self.assertRaises(aiosmtplib.SMTPTimeoutError):
                await per_call.send_messages([EmailMessage("x", "y", None, ["a@example.com"])])
            self.assertIsNone(per_call.connection)
            # Nothing is left to say goodbye to; the old code raised "Server not connected" from here.
            await per_call.close()

            held = SMTPEmailBackend()
            with self.assertRaises(aiosmtplib.SMTPTimeoutError):
                async with held:
                    await held.send_messages([EmailMessage("x", "y", None, ["a@example.com"])])
            self.assertIsNone(held.connection)
        # QUIT was never attempted on a transport that had already gone away.
        self.assertEqual([0, 0], [client.quit_calls for client in FakeClient.instances])

    async def test_an_empty_username_means_no_login(self) -> None:
        with patch("oldman.mail.backends.smtp.aiosmtplib.SMTP", FakeClient):
            backend = SMTPEmailBackend(username="", password="")
            self.assertTrue(await backend.open())
            await backend.close()
        self.assertEqual((None, None), (FakeClient.instances[-1].options["username"], FakeClient.instances[-1].options["password"]))

    async def test_a_failing_quit_still_closes_the_transport(self) -> None:
        class RudeServer(FakeClient):
            quit_error = aiosmtplib.SMTPResponseException(421, "Service not available")

        with patch("oldman.mail.backends.smtp.aiosmtplib.SMTP", RudeServer):
            loud = SMTPEmailBackend()
            with self.assertRaises(aiosmtplib.SMTPResponseException):
                await loud.send_messages([EmailMessage("x", "y", None, ["a@example.com"])])
            self.assertIsNone(loud.connection)

            quiet = SMTPEmailBackend(fail_silently=True)
            self.assertEqual(1, await quiet.send_messages([EmailMessage("x", "y", None, ["a@example.com"])]))
            self.assertIsNone(quiet.connection)

        # Both backends asked the transport to close after the failed QUIT.
        self.assertEqual([(1, True), (1, True)], [(client.quit_calls, client.closed) for client in FakeClient.instances])


if __name__ == "__main__":
    unittest.main()
