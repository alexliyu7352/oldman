"""Backend that accepts everything and sends nothing."""

from __future__ import annotations

from collections.abc import Sequence

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.message import EmailMessage


class DummyEmailBackend(BaseEmailBackend):
    """Count the messages as sent without doing anything."""

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        return len(messages)


__all__ = ["DummyEmailBackend"]
