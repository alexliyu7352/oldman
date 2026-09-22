"""Lazy Jinja access to the active request's flash messages."""

from __future__ import annotations

from collections.abc import Iterator

from sanic.exceptions import SanicException

from oldman.web.messages.flash import FlashMessage, _get_request_storage
from oldman.web.request import get_current_request


class _MessagesProxy:
    """Resolve request-local storage on every template operation."""

    def __iter__(self) -> Iterator[FlashMessage]:
        """Iterate and consume the current request's visible snapshot."""
        return iter(self._storage())

    def __len__(self) -> int:
        """Return the current request's message count without consuming."""
        return len(self._storage())

    def __bool__(self) -> bool:
        """Test for current messages without consuming them."""
        return bool(self._storage())

    @staticmethod
    def _storage():
        """Resolve storage without retaining a request across operations."""
        try:
            request = get_current_request()
        except SanicException as exc:
            raise RuntimeError("The messages template global requires an active request") from exc
        return _get_request_storage(request)


messages_proxy = _MessagesProxy()

__all__ = ["messages_proxy"]
