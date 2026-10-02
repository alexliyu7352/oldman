# `oldman.db`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public database models and lazy sessions; deployments use migrations.

Import with `from oldman.db import <name>`.

## `APP_LABEL_INFO_KEY`

value · defined in `oldman.db.models`

```python
APP_LABEL_INFO_KEY = 'oldman_app_label'
```

## `assign_model_table_app_labels`

function · defined in `oldman.db.models`

```python
def assign_model_table_app_labels(package_labels: Mapping[str, str], model_modules: Mapping[str, str]) -> tuple[ModelMetadata, ...]
```

Assign every Table and return metadata for registered mapped classes.

## `Base`

class · defined in `oldman.db.sqlalchemy.models`

```python
class Base(DeclarativeBase)
```

Base class for all database models

## `DatabaseConfigSource`

value · defined in `oldman.db.session`

```python
DatabaseConfigSource = DatabaseConfig | Callable[[], DatabaseConfig]
```

## `DatabaseManager`

class · defined in `oldman.db.session`

```python
class DatabaseManager
```

Own one lazily initialized async engine and its session factories.

Constructor:

```python
DatabaseManager(config: DatabaseConfigSource, *, debug: DebugSource=False, pool_size: int | None=None, pool_class: type[Pool] | None=None, max_overflow: int | None=None, pool_timeout: float | None=None, pool_recycle: int | None=None, enable_sql_logging: bool | None=None, cache_pool_size: int | None=None, cache_pool_timeout: float | None=None) -> None
```

Members:

- `property is_initialized: bool` — Return whether this process has published an engine.
- `property engine: AsyncEngine` — Return the initialized engine without performing hidden sync setup.
- `async def initialize() -> None` — Create and atomically publish this manager's engine on first use.
- `async def close() -> None` — Dispose this manager's engines and allow later lazy reinitialization.
- `async def transaction() -> AsyncIterator[AsyncSession]` — Yield a new session inside a transaction that commits on success and rolls back on error.
- `async def get_session(request_info: str='') -> AsyncIterator[AsyncSession]` — Yield a write session and optionally summarize its tracked queries.
- `async def get_read_session() -> AsyncIterator[AsyncSession]` — Yield an autoflush-disabled session without an explicit transaction.
- `async def cache_fill_session() -> AsyncIterator[AsyncSession]` — Yield a session for the model cache's fill queries; not for application code.
- `async def create_db_and_tables() -> None` — Create managed metadata for low-level tests, never for deployment.

## `DatabaseModel`

class · defined in `oldman.db.sqlalchemy.models`

```python
class DatabaseModel(Base)
```

Abstract base class for all models with common CRUD operations

Members:

- `def model_dump_dict() -> dict[str, Any]` — This row's loaded columns as JSON values, each encoded by its column type.
- `def model_dump_json() -> str` — ``model_dump_dict()`` as JSON text.
- `classmethod def model_validate_json(data: str | bytes | dict[str, Any]) -> Self` — A new, unsaved instance from what ``model_dump_json`` / ``model_dump_dict`` produced.
- `classmethod async def get_by_id(session: AsyncSession, pk: Any) -> Self | None`
- `classmethod async def get_by_fields(session: AsyncSession, options: Sequence[_AbstractLoad] | None=None, **kwargs) -> Self | None` — 从数据库获取实例
- `classmethod async def get_many_by_ids(session: AsyncSession, ids: list[Any]) -> dict[Any, Self]` — 从数据库批量获取实例
- `classmethod async def get_many(session: AsyncSession, **kwargs) -> Sequence[Self]`
- `classmethod async def execute_query(session: AsyncSession, *conditions, page: int | None=None, page_size: int | None=None) -> list[Self] | PageResult` — 从数据库执行查询
- `classmethod async def execute_query_with_select(session: AsyncSession, query: Select, page: int | None=None, page_size: int | None=None) -> list[Self] | PageResult` — 从数据库执行查询
- `async def save(session: AsyncSession) -> Self` — 独立保存操作，自动提交。
- `def add_to_session(session: AsyncSession) -> Self` — 仅添加到会话，不提交，用于事务操作。
- `async def delete(session: AsyncSession) -> None` — 删除这一行并提交。
- `async def update(session: AsyncSession, **kwargs) -> Self` — 按关键字更新字段并提交。

## `DatabaseNotConfiguredError`

class · defined in `oldman.db.session`

```python
class DatabaseNotConfiguredError(RuntimeError)
```

Report database use before a valid database URL is available.

## `db_manager`

value · defined in `oldman.db.session`

```python
db_manager = DatabaseManager(_configured_database, debug=_configured_debug)
```

## `explicit_primary_key_column`

function · defined in `oldman.db.introspection`

```python
def explicit_primary_key_column(mapper: Any, *, dialect: Any=None) -> Any | None
```

Return the single primary key column when the active dialect cannot generate it, else None.

## `MANAGED_INFO_KEY`

value · defined in `oldman.db.models`

```python
MANAGED_INFO_KEY = 'oldman_managed'
```

## `ModelMetadata`

class · defined in `oldman.db.models`

```python
class ModelMetadata
```

Framework metadata resolved for one SQLAlchemy mapped class.

Members:

- `model: type[Any]`
- `table: Table`
- `app_label: str`
- `verbose_name: str | LazyTranslation`
- `verbose_name_plural: str | LazyTranslation`
- `managed: bool`

## `resolve_model_display_names`

function · defined in `oldman.db.models`

```python
def resolve_model_display_names(model: type[Any]) -> tuple[str | LazyTranslation, str | LazyTranslation]
```

Resolve the two supported Model.Meta labels without translating them.

## `session_dialect`

function · defined in `oldman.db.introspection`

```python
def session_dialect(session: Any) -> Any | None
```

Return the SQLAlchemy dialect bound to a sync or async session.

## Module `oldman.db.fixtures`

Deterministic JSON fixture import and export for registered models.

Import with `from oldman.db.fixtures import <name>`.

### `dump_data`

function · defined in `oldman.db.fixtures`

```python
async def dump_data(registry: _ModelRegistry, database_manager: DatabaseManager, selector: str) -> str
```

Return one deterministic UTF-8 JSON fixture document.

### `load_data`

function · defined in `oldman.db.fixtures`

```python
async def load_data(registry: _ModelRegistry, database_manager: DatabaseManager, fixture_path: Path) -> int
```

Validate and atomically create or update every record in one JSON file.

### `resolve_fixture_path`

function · defined in `oldman.db.fixtures`

```python
def resolve_fixture_path(registry: _PackageRegistry, value: str | Path) -> Path
```

Resolve a direct file or one unambiguous installed-App fixture name.

## Module `oldman.db.models`

Database model primitives and model discovery.

Import with `from oldman.db.models import <name>`.

### `NativeTimestampsMixin`

class · defined in `oldman.db.sqlalchemy.models`

```python
class NativeTimestampsMixin
```

Mixin 定义时间戳的类, 使用是数据库服务器当前时区, 不包含时区信息.

Members:

- `created_at: Mapped[datetime] = mapped_column(__created_at_name__, TIMESTAMP(timezone=False), default=datetime.now, server_default=…`
- `updated_at: Mapped[datetime | None] = mapped_column(__updated_at_name__, TIMESTAMP(timezone=False), default=datetime.now, onupdate=dateti…`

### `SoftDeleteMixin`

class · defined in `oldman.db.sqlalchemy.models`

```python
class SoftDeleteMixin
```

Members:

- `deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)`
- `is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)`

### `UtcTimestampsMixin`

class · defined in `oldman.db.sqlalchemy.models`

```python
class UtcTimestampsMixin
```

Mixin 定义时间戳的类, 使用是UTC时区, 不包含时区信息。

Members:

- `created_at: Mapped[datetime] = mapped_column(__created_at_name__, TIMESTAMP(timezone=False), default=naive_utcnow, server_default=…`
- `updated_at: Mapped[datetime | None] = mapped_column(__updated_at_name__, TIMESTAMP(timezone=False), default=naive_utcnow, onupdate=naive_…`

### `UUIDMixin`

class · defined in `oldman.db.sqlalchemy.models`

```python
class UUIDMixin
```

UUIDv7 主键，值由 Python 端生成。

Members:

- `uuid: Mapped[uuid_pkg.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)`

## Module `oldman.db.session`

Database engine and async session lifecycle management.

Import with `from oldman.db.session import <name>`.

### `DATABASE_DRIVER_PACKAGES`

value · defined in `oldman.db.session`

```python
DATABASE_DRIVER_PACKAGES = {'aiosqlite': 'aiosqlite', 'aiomysql': 'aiomysql', 'asyncpg': 'asyncpg', 'psycopg': 'psycopg'}
```

### `SERVER_POOL_DEFAULTS`

value · defined in `oldman.db.session`

```python
SERVER_POOL_DEFAULTS: dict[str, Any] = {'pool_size': 100, 'poolclass': AsyncAdaptedQueuePool, 'max_overflow': 10, 'pool_timeout': 30, 'poo…
```
