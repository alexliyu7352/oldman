# `oldman.storage.backends`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Import with `from oldman.storage.backends import <name>`.

## `FileSystemStorage`

class · defined in `oldman.storage.backends.filesystem`

```python
class FileSystemStorage(Storage)
```

Local storage with streamed writes and inode-anchored atomic publication.

Constructor:

```python
FileSystemStorage(location: str | Path, alias: str | None=None, chunk_size: int=262144) -> None
```

Members:

- `property location: Path`

## `InMemoryStorage`

class · defined in `oldman.storage.backends.memory`

```python
class InMemoryStorage(Storage)
```

Unbounded in-process storage backed by immutable byte entries.

Constructor:

```python
InMemoryStorage(alias: str | None=None, chunk_size: int=262144) -> None
```
