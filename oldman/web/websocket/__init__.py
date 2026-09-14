"""WebSocket routing and connection protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol, TypeVar, cast

from oldman.web.routing import get_app


class WebSocket(Protocol):
    """Structural type for the runtime's native WebSocket connection."""

    subprotocol: str | None

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def recv(self, timeout: float | None = None) -> str | bytes | None: ...

    async def send(self, message: str | bytes) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...

    async def ping(self, data: bytes = b"") -> None: ...

    async def pong(self, data: bytes = b"") -> None: ...


_Handler = TypeVar("_Handler", bound=Callable[..., Awaitable[object]])


def websocket(
    path: str,
    *,
    name: str | None = None,
    subprotocols: list[str] | None = None,
    strict_slashes: bool | None = None,
) -> Callable[[_Handler], _Handler]:
    """Register a handler on the active runtime application."""
    return cast(
        Callable[[_Handler], _Handler],
        get_app().websocket(path, name=name, subprotocols=subprotocols, strict_slashes=strict_slashes),
    )


__all__ = ["WebSocket", "websocket"]
