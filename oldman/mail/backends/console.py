"""Backend that prints messages to a stream (the default until SMTP is configured)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any, TextIO

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.message import EmailMessage


class ConsoleEmailBackend(BaseEmailBackend):
    """Write each message, followed by a separator line, to `stream` (stdout by default)."""

    def __init__(self, *, fail_silently: bool = False, stream: TextIO | None = None, **options: Any) -> None:
        super().__init__(fail_silently=fail_silently, **options)
        self.stream = stream or sys.stdout

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        sent = 0
        for message in messages:
            # Building the MIME message is the caller's code: a bad header or attachment always raises.
            # as_bytes keeps 8-bit text as written; as_string would re-encode it to base64.
            data = message.message().as_bytes().decode("utf-8", errors="replace")
            try:
                self.stream.write(data)
                self.stream.write("\n" + "-" * 79 + "\n")
                self.stream.flush()
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            sent += 1
        return sent


__all__ = ["ConsoleEmailBackend"]
