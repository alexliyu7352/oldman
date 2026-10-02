# `oldman.cache.backends`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Import with `from oldman.cache.backends import <name>`.

## `memory_cache`

value · defined in `oldman.cache.backends.memory`

```python
memory_cache = MemoryCache()
```

## `MemoryCache`

class · defined in `oldman.cache.backends.memory`

```python
class MemoryCache(BaseCache)
```

Unbounded in-process cache backed by a dictionary.

Constructor:

```python
MemoryCache(**kwargs: Any) -> None
```

## `redis_cache`

value · defined in `oldman.cache.backends.redis`

```python
redis_cache = RedisCache(settings_source=_configured_cache)
```

## `RedisCache`

class · defined in `oldman.cache.backends.redis`

```python
class RedisCache(BaseCache)
```

Redis cache backed by a lazily resolved binary provider connection.

Constructor:

```python
RedisCache(client: str | BinaryRedisClient | None=None, *, namespace: str | None=None, serializer: str | BaseSerializer | None=None, settings_source: Callable[[], RedisCacheConfig] | None=None, timeout: float | None=5, ttl: float | None=None) -> None
```

Members:

- `def namespace(value: str) -> None` — Permit BaseCache initialization but reject later namespace mutation.

## Module `oldman.cache.backends.redis`

Import with `from oldman.cache.backends.redis import <name>`.

### `BinaryRedisClient`

class · defined in `oldman.cache.backends.redis`

```python
class BinaryRedisClient(Protocol)
```

Describe the provider surface required by RedisCache.

Members:

- `async def async_get_bin_conn() -> Any` — Return a binary async Redis connection.
