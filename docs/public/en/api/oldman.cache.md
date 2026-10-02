# `oldman.cache`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Native cache contracts.

Import with `from oldman.cache import <name>`.

## `BaseCache`

class · defined in `oldman.cache.base`

```python
class BaseCache(ABC)
```

Common orchestration for asynchronous cache backends.

Constructor:

```python
BaseCache(serializer: BaseSerializer | None=None, namespace: str='', timeout: float | None=5, ttl: float | None=None) -> None
```

Members:

- `def serializer(value: BaseSerializer) -> None` — Replace the serializer used by subsequent operations.
- `async def add(key: CacheKey, value: Any, ttl: float | None | object=SENTINEL, dumps_fn: Callable[[Any], Any] | None=None, *, timeout: float | None | object=SENTINEL) -> bool` — Add a value only when its namespaced key does not already exist.
- `async def get(key: CacheKey, default: Any=None, loads_fn: Callable[[Any], Any] | None=None, *, timeout: float | None | object=SENTINEL) -> Any` — Return a decoded value or the supplied default for a Cache miss.
- `async def multi_get(keys: Iterable[CacheKey], loads_fn: Callable[[Any], Any] | None=None, *, timeout: float | None | object=SENTINEL) -> list[Any | None]` — Return decoded values for multiple keys while preserving input order.
- `async def set(key: CacheKey, value: Any, ttl: float | None | object=SENTINEL, dumps_fn: Callable[[Any], Any] | None=None, *, timeout: float | None | object=SENTINEL) -> bool` — Serialize and store one value using the selected TTL and timeout.
- `async def multi_set(pairs: Iterable[tuple[CacheKey, Any]], ttl: float | None | object=SENTINEL, dumps_fn: Callable[[Any], Any] | None=None, *, timeout: float | None | object=SENTINEL) -> bool` — Serialize and store multiple key-value pairs with one TTL policy.
- `async def delete(key: CacheKey, *, timeout: float | None | object=SENTINEL) -> int` — Delete one namespaced key and return the backend deletion count.
- `async def delete_match(pattern: str, *, timeout: float | None | object=SENTINEL) -> int` — Delete namespaced keys matching a backend-safe pattern.
- `async def exists(key: CacheKey, *, timeout: float | None | object=SENTINEL) -> bool` — Return whether one namespaced key exists.
- `async def expire(key: CacheKey, ttl: float, *, timeout: float | None | object=SENTINEL) -> bool` — Set, replace, or remove the expiry for one key.
- `async def ttl(key: CacheKey, *, timeout: float | None | object=SENTINEL) -> float | int` — Return seconds remaining, or the backend's negative TTL sentinel.
- `async def clear(*, timeout: float | None | object=SENTINEL) -> bool` — Delete every entry owned by this Cache instance.
- `async def close(*, timeout: float | None | object=SENTINEL) -> None` — Release backend-owned resources within the selected timeout.
- `def build_key(key: CacheKey) -> str` — Prefix a key with this instance's namespace when configured.

## `cache_async_response`

function · defined in `oldman.cache.utils`

```python
def cache_async_response(timeout: int=60 * 60, prefix: str='cache_fun_response') -> Callable
```

Cache the return value of a general asynchronous callable.

## `cache_response`

function · defined in `oldman.cache.utils`

```python
def cache_response(key_prefix: str='response', *, expiration: int=3600, invalidate_paths: tuple[str, ...]=(), vary_by: VaryBy | None=None, use_pickle: bool=True) -> Callable
```

Cache successful Sanic responses and invalidate path-scoped entries after writes.

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

## `TwoLevelCache`

class · defined in `oldman.cache.two_level`

```python
class TwoLevelCache
```

Compose process-local memory with Redis as the authoritative Cache.

Constructor:

```python
TwoLevelCache(memory: BaseCache, redis: BaseCache) -> None
```

Members:

- `async def get(key: CacheKey, default: Any=None, ttl: float | None | object=SENTINEL) -> Any` — Read memory first and backfill it from Redis with a compatible TTL.
- `async def set(key: CacheKey, value: Any, ttl: float | None=None) -> None` — Write Redis first, then update the process-local copy.
- `async def delete(key: CacheKey) -> None` — Delete from Redis first, then from process-local memory.
- `async def clear() -> None` — Clear Redis first, then process-local memory.

## Module `oldman.cache.base`

Import with `from oldman.cache.base import <name>`.

### `CacheKey`

value · defined in `oldman.cache.base`

```python
CacheKey = str | int
```

### `SENTINEL`

value · defined in `oldman.cache.base`

```python
SENTINEL = object()
```

## Module `oldman.cache.utils`

High-level asynchronous Cache helpers and Sanic response caching.

Import with `from oldman.cache.utils import <name>`.

### `delete_cache`

function · defined in `oldman.cache.utils`

```python
async def delete_cache(method: str, *args: Any) -> None
```

Delete one historical helper key.

### `delete_cache_many`

function · defined in `oldman.cache.utils`

```python
async def delete_cache_many(method: str, *args: Any) -> int
```

Delete all historical helper keys sharing the requested prefix.

### `get_cache`

function · defined in `oldman.cache.utils`

```python
async def get_cache(method: str, *args: Any) -> Any
```

Return content stored under the historical helper key.

### `get_cache_expiration`

function · defined in `oldman.cache.utils`

```python
async def get_cache_expiration(method: str, *args: Any) -> float | int
```

Return the remaining lifetime of the historical helper key.

### `set_cache`

function · defined in `oldman.cache.utils`

```python
async def set_cache(method: str, content: Any, expiration_time: int=60 * 60, *args: Any) -> None
```

Store content under the historical underscore-delimited helper key.
