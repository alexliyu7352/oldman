"""Release delivery renewals around, not instead of, Taskiq's native callback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from taskiq import AckableMessage
from taskiq.receiver import Receiver


class RenewingMessage(AckableMessage):
    """Internal delivery with an idempotent release; wire payload remains native bytes."""

    release: Callable[[], Awaitable[None]]


class RenewingReceiver(Receiver):
    """Keep native execution/results and end renewal even when parsing or ACK fails."""

    async def callback(self, message: bytes | AckableMessage, raise_err: bool = False) -> None:
        """Stop this delivery's renewal on every native callback exit path."""
        try:
            await super().callback(message, raise_err=raise_err)
        finally:
            if isinstance(message, RenewingMessage):
                await message.release()
