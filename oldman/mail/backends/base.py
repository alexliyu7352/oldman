"""Backend contract: take a batch of messages, return how many went out."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from oldman.mail.message import EmailMessage


class BaseEmailBackend:
    """Base class for outgoing mail backends.

    A backend may hold a connection between `open()` and `close()`; `send_messages` opens one when
    none is open and closes it again afterwards, so single sends need no ceremony while bulk sends
    can wrap several calls in `async with backend:`.
    """

    def __init__(self, *, fail_silently: bool = False, **options: Any) -> None:
        self.fail_silently = fail_silently
        self.options = options

    async def open(self) -> bool:
        """Open a connection; return True when this call created one (so the caller closes it)."""
        return False

    async def close(self) -> None:
        """Close the connection opened by `open()`, if any."""
        return None

    async def __aenter__(self) -> Self:
        try:
            await self.open()
        except Exception:
            await self.close()
            raise
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        await self.close()

    async def send_messages(self, messages: Sequence[EmailMessage]) -> int:
        """Send every message and return the number delivered to the transport."""
        raise NotImplementedError("subclasses of BaseEmailBackend must implement send_messages()")


__all__ = ["BaseEmailBackend"]
