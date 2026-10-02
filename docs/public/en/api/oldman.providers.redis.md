# `oldman.providers.redis`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Async Redis provider core.

Import with `from oldman.providers.redis import <name>`.

## `AsyncRedis`

class · defined in `oldman.providers.redis.redis`

```python
class AsyncRedis
```

Manage one lazily initialized redis-py asyncio connection pool.

Constructor:

```python
AsyncRedis(redis_url: str='', decode_responses: bool=True, *, max_connections: int=1024, health_check_interval: int=30, protocol: Literal[2, 3]=2, retry_attempts: int=3, retry_on_timeout: bool=True, backoff_base: float=0.1, backoff_cap: float=2.0, socket_keepalive: bool=True, socket_keepalive_idle: int=60, socket_keepalive_interval: int=10, socket_keepalive_count: int=3, **connection_options: Any) -> None
```

Members:

- `async def async_get_conn() -> aioredis.Redis` — Return the shared Redis client, initializing its pool once on first use.
- `async def close() -> None` — Close this client and pool, allowing a later access to reinitialize them.
- `async def get_db_lock(key: str, expire_timeout: int=60) -> bool` — Atomically create a short-lived presence lock; its key lives under the service namespace.
- `async def is_db_lock(key: str) -> bool` — Return whether a presence lock exists.
- `async def acquire_lock(lock_name: str, acquire_timeout: int=10, retry_interval: float=0.001, expire_timeout: int | None=None) -> str | bool` — Acquire a token-owned lock with a bounded retry period.
- `async def release_lock(lock_name: str, identifier: str) -> bool` — Release a token-owned lock atomically.
- `async def get_locker(lock_key: str, blocking_timeout: int=10, expire_timeout: int=60, sleep: float=0.01) -> Lock` — Return redis-py's distributed lock object.

## `redis_client`

value · defined in `oldman.providers.redis.client`

```python
redis_client = RedisClientRegistry(_configured_redis)
```

## `redis_key`

function · defined in `oldman.providers.redis.keys`

```python
def redis_key(*parts: object) -> str
```

A key under this service's namespace: ``redis_key("session", sid)`` is ``<namespace>:session:<sid>``.

## `redis_namespace`

function · defined in `oldman.providers.redis.keys`

```python
def redis_namespace() -> str
```

The namespace this service's Redis keys live under, read from the settings on each call.

## `RedisAliasClient`

class · defined in `oldman.providers.redis.client`

```python
class RedisAliasClient
```

Lightweight view that binds registry operations to one alias.

Constructor:

```python
RedisAliasClient(registry: RedisClientRegistry, alias: str) -> None
```

Members:

- `async def async_get_conn() -> Any` — Return this alias's configured Redis connection.
- `async def async_get_bin_conn() -> Any` — Return this alias's binary Redis connection.
- `async def get_db_lock(key: str, expire_timeout: int=60) -> bool` — Delegate a presence lock to this alias's normal client.
- `async def is_db_lock(key: str) -> bool` — Delegate a presence-lock check to this alias's normal client.
- `async def acquire_lock(lock_name: str, acquire_timeout: int=10, retry_interval: float=0.001, expire_timeout: int | None=None) -> str | bool` — Delegate token-lock acquisition to this alias's normal client.
- `async def release_lock(lock_name: str, identifier: str) -> bool` — Delegate token-lock release to this alias's normal client.
- `async def get_locker(lock_key: str, blocking_timeout: int=10, expire_timeout: int=60, sleep: float=0.01) -> Any` — Return redis-py's distributed lock for this alias.

## `RedisAliasNotConfiguredError`

class · defined in `oldman.providers.redis.client`

```python
class RedisAliasNotConfiguredError(LookupError)
```

Raised when a requested Redis connection alias is not configured.

## `RedisClientRegistry`

class · defined in `oldman.providers.redis.client`

```python
class RedisClientRegistry
```

Resolve named settings and cache normal or binary async Redis clients.

Constructor:

```python
RedisClientRegistry(config: RedisConfigSource) -> None
```

Members:

- `def using(alias: str) -> RedisAliasClient` — Return a case-sensitive alias view without creating a Redis pool.
- `async def async_get_conn() -> Any` — Return the normal connection for the DEFAULT alias.
- `async def async_get_bin_conn() -> Any` — Return the binary connection for the DEFAULT alias.
- `async def get_db_lock(key: str, expire_timeout: int=60) -> bool` — Use the DEFAULT alias for a presence lock.
- `async def is_db_lock(key: str) -> bool` — Use the DEFAULT alias for a presence-lock check.
- `async def acquire_lock(lock_name: str, acquire_timeout: int=10, retry_interval: float=0.001, expire_timeout: int | None=None) -> str | bool` — Use the DEFAULT alias for token-lock acquisition.
- `async def release_lock(lock_name: str, identifier: str) -> bool` — Use the DEFAULT alias for token-lock release.
- `async def get_locker(lock_key: str, blocking_timeout: int=10, expire_timeout: int=60, sleep: float=0.01) -> Any` — Use the DEFAULT alias for redis-py's distributed lock.
- `async def close() -> None` — Close every initialized client and clear the concrete-client cache.
