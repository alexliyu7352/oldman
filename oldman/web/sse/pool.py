"""Process-local indexes for browser SSE connections."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oldman.web.sse.stream import SSEStream


class SSEConnectionPool:
    """Index active streams by user and distributed business stream."""

    def __init__(self) -> None:
        self._all: set[SSEStream] = set()
        self._users: defaultdict[int, set[SSEStream]] = defaultdict(set)
        self._streams: defaultdict[str, set[SSEStream]] = defaultdict(set)

    def add(self, stream: SSEStream) -> None:
        """Track one connection for worker shutdown."""
        self._all.add(stream)

    def discard(self, stream: SSEStream) -> None:
        """Remove one connection and any subscriptions it still owns."""
        self._all.discard(stream)
        self._discard_from_all(self._users, stream)
        self._discard_from_all(self._streams, stream)

    def subscribe_user(self, user_id: int, stream: SSEStream) -> None:
        """Register one guarded connection under its authenticated user."""
        self._users[user_id].add(stream)

    def unsubscribe_user(self, user_id: int, stream: SSEStream) -> None:
        """Remove one user subscription and its empty index bucket."""
        self._discard(self._users, user_id, stream)

    def subscribe_stream(self, name: str, stream: SSEStream) -> None:
        """Register one connection under a distributed business stream."""
        self._streams[name].add(stream)

    def unsubscribe_stream(self, name: str, stream: SSEStream) -> None:
        """Remove one business subscription and its empty index bucket."""
        self._discard(self._streams, name, stream)

    def user_streams(self, user_id: int) -> tuple[SSEStream, ...]:
        """Return a stable snapshot of this worker's user connections."""
        return tuple(self._users.get(user_id, ()))

    def business_streams(self, name: str) -> tuple[SSEStream, ...]:
        """Return a stable snapshot of one distributed business route."""
        return tuple(self._streams.get(name, ()))

    def all_streams(self) -> tuple[SSEStream, ...]:
        """Return a stable snapshot used by worker shutdown."""
        return tuple(self._all)

    @staticmethod
    def _discard[TKey](
        index: defaultdict[TKey, set[SSEStream]],
        key: TKey,
        stream: SSEStream,
    ) -> None:
        """Remove one member without materializing a missing bucket."""
        members = index.get(key)
        if members is None:
            return
        members.discard(stream)
        if not members:
            index.pop(key, None)

    @classmethod
    def _discard_from_all[TKey](
        cls,
        index: defaultdict[TKey, set[SSEStream]],
        stream: SSEStream,
    ) -> None:
        """Defensively remove a closing connection from every remaining bucket."""
        for key in tuple(index):
            cls._discard(index, key, stream)


__all__ = ["SSEConnectionPool"]
