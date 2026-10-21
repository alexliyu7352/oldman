# `oldman.serializers`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.serializers import <name>`.

## `BaseSerializer`

class · defined in `oldman.serializers.cache`

```python
class BaseSerializer(ABC)
```

Define the Cache serializer wire-format contract.

Constructor:

```python
BaseSerializer(*, encoding: str | None | object=_NOT_SET) -> None
```

Members:

- `DEFAULT_ENCODING: str | None = 'utf-8'`
- `def dumps(value: Any, /) -> Any` — Encode a Python value for backend storage.
- `def loads(value: Any, /) -> Any` — Decode a backend value, preserving None as a Cache miss.

## `create_cache_serializer`

function · defined in `oldman.serializers.cache`

```python
def create_cache_serializer(name: str) -> BaseSerializer
```

Create a built-in Cache serializer by its case-insensitive name.

## `DataclassModelMixin`

class · defined in `oldman.serializers.base`

```python
class DataclassModelMixin
```

Consistent dataclass encoding/decoding APIs and JSON file access.

Members:

- `def to_msgpack() -> bytes`
- `classmethod def from_msgpack(data: bytes) -> Self`
- `def to_json_bytes() -> bytes`
- `def to_json_str() -> str`
- `classmethod def from_json_bytes(data: bytes) -> Self`
- `classmethod def from_json_str(s: str) -> Self`
- `def to_dict() -> dict[str, Any]`
- `classmethod def from_dict(data: dict[str, Any]) -> Self`
- `def to_json_file(path: str | os.PathLike[str]) -> None` — Atomically replace a file with two-space-indented UTF-8 JSON, creating missing parent directories and propagating failures.
- `async def to_json_file_async(path: str | os.PathLike[str]) -> None`
- `classmethod def from_json_file(path: str | os.PathLike[str]) -> Self` — Read from a JSON file.
- `classmethod async def from_json_file_async(path: str | os.PathLike[str]) -> Self`

## `JsonSerializer`

class · defined in `oldman.serializers.cache`

```python
class JsonSerializer(BaseSerializer)
```

Encode JSON-compatible values with orjson bytes.

Members:

- `def dumps(value: Any, /) -> bytes` — Encode one JSON-compatible value as UTF-8 JSON bytes.
- `def loads(value: bytes | str | None, /) -> Any` — Decode JSON bytes or text while preserving None as a Cache miss.

## `MsgpackSerializer`

class · defined in `oldman.serializers.cache`

```python
class MsgpackSerializer(BaseSerializer)
```

Encode structured values with msgspec's MessagePack format.

Members:

- `def dumps(value: Any, /) -> bytes` — Encode one structured value as MessagePack bytes.
- `def loads(value: bytes | None, /) -> Any` — Decode MessagePack bytes while preserving None as a Cache miss.

## `MsgspecModel`

class · defined in `oldman.serializers.base`

```python
class MsgspecModel(msgspec.Struct)
```

Members:

- `def to_msgpack() -> bytes`
- `classmethod def from_msgpack(data: bytes) -> Self`
- `def to_json_bytes() -> bytes`
- `def to_json_str() -> str`
- `classmethod def from_json_bytes(data: bytes) -> Self`
- `classmethod def from_json_str(s: str) -> Self`
- `def to_dict() -> dict[str, Any]`
- `classmethod def from_dict(data: dict[str, Any]) -> Self`

## `NullSerializer`

class · defined in `oldman.serializers.cache`

```python
class NullSerializer(BaseSerializer)
```

Pass values through unchanged for in-process storage.

Members:

- `def dumps(value: Any, /) -> Any` — Return the original Python value unchanged.
- `def loads(value: Any, /) -> Any` — Return the stored Python value unchanged.

## `PickleSerializer`

class · defined in `oldman.serializers.cache`

```python
class PickleSerializer(BaseSerializer)
```

Encode arbitrary Python values with the configured Pickle protocol.

Constructor:

```python
PickleSerializer(*, protocol: int=pickle.DEFAULT_PROTOCOL) -> None
```

Members:

- `def dumps(value: Any, /) -> bytes` — Encode one Python value as Pickle bytes.
- `def loads(value: bytes | None, /) -> Any` — Decode Pickle bytes while preserving None as a Cache miss.

## `resolve_cache_serializer`

function · defined in `oldman.serializers.cache`

```python
def resolve_cache_serializer(value: str | BaseSerializer) -> BaseSerializer
```

Return an existing serializer or create the named built-in serializer.
