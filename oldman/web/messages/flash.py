"""Strongly typed one-time Web messages and request-local state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from sanic import Request

from oldman.serializers import MsgspecModel

_REQUEST_STORAGE_ATTRIBUTE = "_oldman_flash_message_storage"


class MessageLevel(StrEnum):
    """Visual severity of a one-time page message."""

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class MessageFormat(StrEnum):
    """Whether a message is escaped text or explicitly trusted HTML."""

    TEXT = "text"
    HTML = "html"


class FlashMessage(
    MsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec freezes the generated Struct
):
    """One translated message rendered in the next suitable page response."""

    level: MessageLevel
    content: str
    format: MessageFormat = MessageFormat.TEXT

    def __post_init__(self) -> None:
        """Reject untyped direct construction before data reaches a Cookie."""
        if not isinstance(self.level, MessageLevel):
            raise TypeError("level must be a MessageLevel")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.format, MessageFormat):
            raise TypeError("format must be a MessageFormat")


@dataclass(slots=True)
class _FlashRequestStorage:
    """Track loaded, added, and iterated messages for one request only."""

    loaded: tuple[FlashMessage, ...] = ()
    had_cookie: bool = False
    invalid_cookie: bool = False
    _messages: list[FlashMessage] = field(init=False)
    _loaded_count: int = field(init=False)
    _consumed_through: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._messages = list(self.loaded)
        self._loaded_count = len(self.loaded)

    def add(self, message: FlashMessage) -> None:
        """Append one message without consuming anything already loaded."""
        self._messages.append(message)

    def __iter__(self):
        """Return a stable snapshot and mark that snapshot as displayed."""
        snapshot = tuple(self._messages)
        self._consumed_through = max(self._consumed_through, len(snapshot))
        return iter(snapshot)

    def __len__(self) -> int:
        """Report the visible message count without consuming it."""
        return len(self._messages)

    def __bool__(self) -> bool:
        """Report whether messages exist without consuming them."""
        return bool(self._messages)

    @property
    def pending(self) -> tuple[FlashMessage, ...]:
        """Return messages not covered by the latest iteration snapshot."""
        return tuple(self._messages[self._consumed_through :])

    @property
    def consumed(self) -> bool:
        """Return whether a template started iterating any message."""
        return self._consumed_through > 0

    @property
    def has_unconsumed_additions(self) -> bool:
        """Return whether a new message still needs a future response."""
        retained_boundary = max(self._loaded_count, self._consumed_through)
        return len(self._messages) > retained_boundary


def add_message(
    request: Request,
    level: MessageLevel,
    content: str,
    *,
    format: MessageFormat = MessageFormat.TEXT,
) -> None:
    """Append a translated message to middleware-owned request storage."""
    if not isinstance(level, MessageLevel):
        raise TypeError("level must be a MessageLevel")
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    if not isinstance(format, MessageFormat):
        raise TypeError("format must be a MessageFormat")
    _get_request_storage(request).add(
        FlashMessage(
            level=level,
            content=content,
            format=format,
        )
    )


def success(request: Request, content: str) -> None:
    """Add an escaped success message."""
    add_message(request, MessageLevel.SUCCESS, content)


def info(request: Request, content: str) -> None:
    """Add an escaped informational message."""
    add_message(request, MessageLevel.INFO, content)


def warning(request: Request, content: str) -> None:
    """Add an escaped warning message."""
    add_message(request, MessageLevel.WARNING, content)


def error(request: Request, content: str) -> None:
    """Add an escaped error message."""
    add_message(request, MessageLevel.ERROR, content)


def _get_request_storage(request: Request) -> _FlashRequestStorage:
    """Return initialized storage or report missing Messages middleware."""
    request_context = getattr(request, "ctx", None)
    storage = getattr(request_context, _REQUEST_STORAGE_ATTRIBUTE, None)
    if storage is None:
        raise RuntimeError("Messages middleware has not initialized this request")
    if not isinstance(storage, _FlashRequestStorage):
        raise TypeError("Invalid private flash message storage")
    return storage


def _set_request_storage(
    request: Request,
    storage: _FlashRequestStorage,
) -> None:
    """Attach one internal storage instance to a request context."""
    setattr(request.ctx, _REQUEST_STORAGE_ATTRIBUTE, storage)


__all__ = [
    "FlashMessage",
    "MessageFormat",
    "MessageLevel",
    "add_message",
    "error",
    "info",
    "success",
    "warning",
]
