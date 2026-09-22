"""Backend that writes one .eml file per message into a directory."""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from oldman.mail.backends.base import BaseEmailBackend
from oldman.mail.config import mail_config
from oldman.mail.exceptions import MailConfigurationError
from oldman.mail.message import EmailMessage

_counter = itertools.count(1)


class FileEmailBackend(BaseEmailBackend):
    """Save messages as `<timestamp>-<n>.eml` under `file_path` (option or `mail.file_path`)."""

    def __init__(self, *, fail_silently: bool = False, file_path: str | Path | None = None, **options: Any) -> None:
        super().__init__(fail_silently=fail_silently, **options)
        raw_path = file_path or mail_config().file_path
        if not raw_path:
            raise MailConfigurationError("the filebased mail backend needs mail.file_path or a file_path option")
        self.file_path = Path(raw_path)

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        sent = 0
        for message in messages:
            data = message.message().as_bytes()  # a malformed message is a programming error, never silenced
            try:
                await asyncio.to_thread(self._write, data)
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            sent += 1
        return sent

    def _write(self, data: bytes) -> Path:
        self.file_path.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.file_path / f"{stamp}-{next(_counter)}.eml"
        target.write_bytes(data)
        return target


__all__ = ["FileEmailBackend"]
