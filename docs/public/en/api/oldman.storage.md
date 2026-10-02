# `oldman.storage`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public async storage API.

Import with `from oldman.storage import <name>`.

## `default_storage`

value · defined in `oldman.storage.registry`

```python
default_storage = StorageProxy(lambda: storages.using('default'))
```

## `file_column`

function · defined in `oldman.storage.models`

```python
def file_column(*, upload_to: UploadTo, storage: str='default', max_length: int=255, nullable: bool=False, **column_kwargs: Any) -> MappedColumn[Any]
```

声明由 Storage 管理、数据库中仍保存逻辑名称的 String 列。

## `FileInfo`

class · defined in `oldman.storage.streams`

```python
class FileInfo
```

Members:

- `name: str`
- `size: int`
- `modified_at: datetime`

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

## `InvalidStorageName`

class · defined in `oldman.storage.exceptions`

```python
class InvalidStorageName(StorageError)
```

Raised when a storage name is not a safe relative POSIX path.

## `media_storage`

value · defined in `oldman.storage.registry`

```python
media_storage = StorageProxy(lambda: storages.using('default'))
```

## `media_url`

function · defined in `oldman.storage._urls`

```python
def media_url(name: str, *, quote_name: bool=True) -> str
```

The URL the browser can request for one name stored in the media storage.

## `memory_storage`

value · defined in `oldman.storage.registry`

```python
memory_storage = StorageProxy(lambda: storages.using('memory'))
```

## `Storage`

class · defined in `oldman.storage.base`

```python
class Storage(ABC)
```

Constructor:

```python
Storage(alias: str | None=None) -> None
```

Members:

- `property alias: str | None`
- `async def save(name: str, content: StorageContent, *, overwrite: bool=False) -> str`
- `async def open(name: str) -> StoredFile`
- `async def delete(name: str) -> None`
- `async def exists(name: str) -> bool`
- `async def stat(name: str) -> FileInfo`
- `async def get_available_name(name: str) -> str`
- `def get_alternative_name(name: str) -> str`

## `StorageAliasNotConfigured`

class · defined in `oldman.storage.exceptions`

```python
class StorageAliasNotConfigured(StorageError)
```

Raised when an operation requires a storage alias that is absent.

## `StorageBackendError`

class · defined in `oldman.storage.exceptions`

```python
class StorageBackendError(StorageError)
```

Raised when a storage backend fails unexpectedly.

Constructor:

```python
StorageBackendError(message: str, *, operation: str, name: str | None, alias: str | None) -> None
```

## `StorageConfigurationError`

class · defined in `oldman.storage.exceptions`

```python
class StorageConfigurationError(StorageError)
```

Raised when a storage instance has incompatible configuration.

## `StorageContent`

type alias · defined in `oldman.storage.base`

```python
type StorageContent = bytes | AsyncIterable[bytes]
```

## `StorageError`

class · defined in `oldman.storage.exceptions`

```python
class StorageError(Exception)
```

Base exception for storage operations.

## `StorageFileNotFound`

class · defined in `oldman.storage.exceptions`

```python
class StorageFileNotFound(StorageError)
```

Raised when a requested stored file does not exist.

## `StorageProxy`

class · defined in `oldman.storage.registry`

```python
class StorageProxy
```

Typed lazy proxy for one registry-selected Storage instance.

Constructor:

```python
StorageProxy(resolver: StorageResolver) -> None
```

Members:

- `async def save(name: str, content: StorageContent, *, overwrite: bool=False) -> str`
- `async def open(name: str) -> StoredFile`
- `async def delete(name: str) -> None`
- `async def exists(name: str) -> bool`
- `async def stat(name: str) -> FileInfo`
- `async def get_available_name(name: str) -> str`

## `StorageRegistry`

class · defined in `oldman.storage.registry`

```python
class StorageRegistry
```

Construct required named storages eagerly and custom storages on demand.

Constructor:

```python
StorageRegistry(settings_factory: SettingsFactory) -> None
```

Members:

- `def init_app(app: object | None=None) -> None` — Initialize configured required storages once without backend I/O.
- `def using(alias: str) -> Storage` — Return one cached storage by alias, constructing custom aliases lazily.

## `storages`

value · defined in `oldman.storage.registry`

```python
storages = StorageRegistry(_configured_settings)
```

## `StoredFile`

class · defined in `oldman.storage.streams`

```python
class StoredFile(ABC)
```

Constructor:

```python
StoredFile(*, name: str, info: FileInfo, chunk_size: int=64 * 1024) -> None
```

Members:

- `async def read(size: int=-1) -> bytes` — Read up to ``size`` bytes from the file.
- `async def close() -> None` — Release backend resources held by the file.

## `UploadTo`

type alias · defined in `oldman.storage.models`

```python
type UploadTo = str | Callable[[Any, str], str]
```

## `validate_storage_name`

function · defined in `oldman.storage.base`

```python
def validate_storage_name(name: str) -> str
```

Validate and return a safe, relative POSIX storage name unchanged.

## Module `oldman.storage.lifecycle`

根据数据库最终状态清理模型文件列不再引用的 Storage 文件。

Import with `from oldman.storage.lifecycle import <name>`.

### `finalize_model_files`

function · defined in `oldman.storage.lifecycle`

```python
async def finalize_model_files(manager: DatabaseManager, records: tuple[_CleanupRecord, ...]) -> None
```

查询数据库最终值，只删除候选中已不再被引用的文件。

### `install_model_file_lifecycle`

function · defined in `oldman.storage.lifecycle`

```python
def install_model_file_lifecycle(models: Iterable[ModelMetadata]) -> None
```

只为已注册模型中的 file_column 属性安装轻量变化标记。

### `take_file_cleanup_records`

function · defined in `oldman.storage.lifecycle`

```python
def take_file_cleanup_records(session: Any) -> tuple[_CleanupRecord, ...]
```

从已关闭写 Session 取出并冻结本次文件候选。

### `WriteSession`

class · defined in `oldman.storage.lifecycle`

```python
class WriteSession(Session)
```

只供 DatabaseManager 写会话使用的内部同步 Session。
