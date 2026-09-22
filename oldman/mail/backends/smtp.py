"""SMTP backend on aiosmtplib: one connection per `send_messages()` call, or longer inside `async with`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import aiosmtplib

from oldman.logging import get_logger
from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.config import mail_config
from oldman.mail.message import EmailMessage, envelope_address

logger = get_logger("default.mail.smtp")


class SMTPEmailBackend(BaseEmailBackend):
    """Send through an SMTP server; every option falls back to `mail.smtp` when not given."""

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool | None = None,
        use_ssl: bool | None = None,
        timeout: float | None = None,
        local_hostname: str | None = None,
        fail_silently: bool = False,
        **options: Any,
    ) -> None:
        super().__init__(fail_silently=fail_silently, **options)
        config = mail_config().smtp
        self.host = host or config.host
        self.port = port or config.port
        # An empty string is the usual way to clear a YAML field; it means "no login", like Django.
        self.username = (config.username if username is None else username) or None
        self.password = (config.password if password is None else password) or None
        self.use_tls = config.use_tls if use_tls is None else use_tls
        self.use_ssl = config.use_ssl if use_ssl is None else use_ssl
        self.timeout = config.timeout if timeout is None else timeout
        self.local_hostname = local_hostname or config.local_hostname
        if self.use_tls and self.use_ssl:
            raise ValueError("use_tls (STARTTLS) and use_ssl (implicit TLS) are mutually exclusive")
        self.connection: aiosmtplib.SMTP | None = None

    async def open(self) -> bool:
        if self.connection is not None:
            return False
        client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            local_hostname=self.local_hostname,
            timeout=self.timeout,
            use_tls=self.use_ssl,
            # aiosmtplib would otherwise negotiate STARTTLS whenever the server offers it; mirror the setting.
            start_tls=self.use_tls,
        )
        try:
            await client.connect()
        except (aiosmtplib.SMTPException, OSError):
            if not self.fail_silently:
                raise
            return False
        self.connection = client
        return True

    async def close(self) -> None:
        """Say QUIT and drop the connection; a transport that already died (timeout, disconnect) is just dropped."""
        client = self.connection
        if client is None:
            return
        self.connection = None
        if not client.is_connected:
            return
        try:
            await client.quit()
        except (aiosmtplib.SMTPException, OSError):
            client.close()
            if not self.fail_silently:
                raise

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        if not messages:
            return 0
        opened_here = await self.open()
        if self.connection is None:
            return 0
        sent = 0
        try:
            for message in messages:
                if await self._send(message):
                    sent += 1
        except BaseException:
            # The send error is the one to report; closing must never replace it.
            if opened_here:
                await self._drop_connection()
            raise
        if opened_here:
            await self.close()
        return sent

    async def _drop_connection(self) -> None:
        client = self.connection
        self.connection = None
        if client is None or not client.is_connected:
            return
        try:
            await client.quit()
        except (aiosmtplib.SMTPException, OSError):
            client.close()

    async def _send(self, message: EmailMessage) -> bool:
        recipients = [envelope_address(address) for address in message.recipients()]
        if not recipients or self.connection is None:
            return False
        mime = message.message()
        try:
            await self.connection.send_message(mime, sender=envelope_address(message.from_email), recipients=recipients)
        except (aiosmtplib.SMTPException, OSError):
            logger.warning("SMTP send to %s failed", recipients, exc_info=True)
            if not self.fail_silently:
                raise
            return False
        return True


__all__ = ["SMTPEmailBackend"]
