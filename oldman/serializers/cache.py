# Adapted from aiocache commit ae5948b2d99dcaa68fe02fd3086a3351a867c85b.
# Original path: aiocache/serializers/serializers.py.
# BSD 3-Clause notice: LICENSES/aiocache-BSD-3-Clause.txt.

from __future__ import annotations

import pickle
from abc import ABC, abstractmethod
from typing import Any, cast

import msgspec
import orjson

_NOT_SET = object()


class BaseSerializer(ABC):
    """Define the Cache serializer wire-format contract."""

    DEFAULT_ENCODING: str | None = "utf-8"

    def __init__(self, *, encoding: str | None | object = _NOT_SET) -> None:
        """Resolve an explicit encoding without conflating None with omission."""
        self.encoding = self.DEFAULT_ENCODING if encoding is _NOT_SET else cast(str | None, encoding)

    @abstractmethod
    def dumps(self, value: Any, /) -> Any:
        """Encode a Python value for backend storage."""
        ...

    @abstractmethod
    def loads(self, value: Any, /) -> Any:
        """Decode a backend value, preserving None as a Cache miss."""
        ...


class NullSerializer(BaseSerializer):
    """Pass values through unchanged for in-process storage."""

    def dumps(self, value: Any, /) -> Any:
        """Return the original Python value unchanged."""
        return value

    def loads(self, value: Any, /) -> Any:
        """Return the stored Python value unchanged."""
        return value


class PickleSerializer(BaseSerializer):
    """Encode arbitrary Python values with the configured Pickle protocol."""

    DEFAULT_ENCODING = None

    def __init__(self, *, protocol: int = pickle.DEFAULT_PROTOCOL) -> None:
        """Configure the Pickle wire protocol."""
        super().__init__()
        self.protocol = protocol

    def dumps(self, value: Any, /) -> bytes:
        """Encode one Python value as Pickle bytes."""
        return pickle.dumps(value, protocol=self.protocol)

    def loads(self, value: bytes | None, /) -> Any:
        """Decode Pickle bytes while preserving None as a Cache miss."""
        return None if value is None else pickle.loads(value)


class JsonSerializer(BaseSerializer):
    """Encode JSON-compatible values with orjson bytes."""

    DEFAULT_ENCODING = None

    def dumps(self, value: Any, /) -> bytes:
        """Encode one JSON-compatible value as UTF-8 JSON bytes."""
        return orjson.dumps(value)

    def loads(self, value: bytes | str | None, /) -> Any:
        """Decode JSON bytes or text while preserving None as a Cache miss."""
        return None if value is None else orjson.loads(value)


class MsgpackSerializer(BaseSerializer):
    """Encode structured values with msgspec's MessagePack format."""

    DEFAULT_ENCODING = None

    def dumps(self, value: Any, /) -> bytes:
        """Encode one structured value as MessagePack bytes."""
        return msgspec.msgpack.encode(value)

    def loads(self, value: bytes | None, /) -> Any:
        """Decode MessagePack bytes while preserving None as a Cache miss."""
        return None if value is None else msgspec.msgpack.decode(value)


def create_cache_serializer(name: str) -> BaseSerializer:
    """Create a built-in Cache serializer by its case-insensitive name."""
    match name.casefold():
        case "pickle":
            return PickleSerializer()
        case "msgpack":
            return MsgpackSerializer()
        case "json":
            return JsonSerializer()
        case "null":
            return NullSerializer()
        case _:
            raise ValueError(f"unknown cache serializer: {name}")


def resolve_cache_serializer(value: str | BaseSerializer) -> BaseSerializer:
    """Return an existing serializer or create the named built-in serializer."""
    if isinstance(value, BaseSerializer):
        return value
    return create_cache_serializer(value)
