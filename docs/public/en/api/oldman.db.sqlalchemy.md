# `oldman.db.sqlalchemy`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

The package itself exports nothing; import from the modules below.

## Module `oldman.db.sqlalchemy.cache`

Redis cache for SQLAlchemy models: single rows by primary key or unique fields, and query results.

Import with `from oldman.db.sqlalchemy.cache import <name>`.

### `CacheableModel`

class · defined in `oldman.db.sqlalchemy.cache`

```python
class CacheableModel(DatabaseModel)
```

可缓存模型的基类

Members:

- `classmethod def get_cache_manager() -> AsyncQueryCache[Any]` — 获取缓存管理器实例
- `classmethod def set_cache_manager(cache_manager: AsyncQueryCache[Any]) -> None` — 设置缓存管理器实例
- `classmethod async def cached_get(session: AsyncSession, *, use_cache: bool=True, **fields: Any) -> Self | None`
- `classmethod async def cached_get_many(session: AsyncSession, ids: list[Any], *, use_cache: bool=True) -> dict[Any, Self]`
- `classmethod async def cached_filter(session: AsyncSession, *conditions: Any, page: int | None=None, page_size: int | None=None, use_cache: bool=True, expire_seconds: int | None=None) -> list[Self] | PageResult[Self]`
- `classmethod async def invalidate_cache() -> None`
- `classmethod def invalidate_cache_on_commit(session: AsyncSession | Session) -> None`

### `cached_model`

function · defined in `oldman.db.sqlalchemy.cache`

```python
def cached_model(instance_expire_seconds: int=3600, query_expire_seconds: int=300, *, partition_by: Sequence[str]=(), invalidate_on: Sequence[type]=(), db_manager: 'DatabaseManager | None'=None)
```

Declare a `CacheableModel` cached; its writes through the ORM invalidate what they affect.

### `CacheStats`

class · defined in `oldman.db.sqlalchemy.cache`

```python
class CacheStats
```

How one cached model's reads were served in this process, counted per entry read.

Members:

- `hits: int = 0`
- `misses: int = 0`
- `bypassed: int = 0`
- `fallbacks: int = 0`

### `wait_for_invalidations`

function · defined in `oldman.db.sqlalchemy.cache`

```python
async def wait_for_invalidations() -> None
```

Wait until the invalidations this process started after its commits have reached Redis.

## Module `oldman.db.sqlalchemy.session`

SQLAlchemy-facing exports for the canonical database manager.

Import with `from oldman.db.sqlalchemy.session import <name>`.

### `connect_args`

value · defined in `oldman.db.sqlalchemy.session`

```python
connect_args = {'check_same_thread': False}
```

### `POOL_CLASS`

value · defined in `oldman.db.sqlalchemy.session`

```python
POOL_CLASS = AsyncAdaptedQueuePool
```
