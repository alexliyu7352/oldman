"""Backend that keeps sent messages in memory for tests."""

from __future__ import annotations

from collections.abc import Sequence

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.message import EmailMessage


class LocmemEmailBackend(BaseEmailBackend):
    """Append every message to `oldman.mail.outbox` after building its MIME form."""

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        from oldman import mail

        sent = 0
        for message in messages:
            # Building the MIME message surfaces header and attachment errors like a real send would.
            message.message()
            mail.outbox.append(message)
            sent += 1
        return sent


__all__ = ["LocmemEmailBackend"]
