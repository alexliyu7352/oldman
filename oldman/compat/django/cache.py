"""Interop with Django's default Redis keys (empty KEY_PREFIX, VERSION=1).

Use settings.cache.client for the shared Redis database, without the Native
Cache namespace. Pickle values require a trusted Redis store and matching Python
types. Custom Django key functions, prefixes, versions and codecs are not adapted.
"""

import functools
import random
import string
from collections.abc import Awaitable, Callable
from typing import Any

from oldman.compat.django.serializers import django_serializer
from oldman.providers.redis import redis_client


async def _connection() -> Any:
    """Resolve the configured binary provider lazily; do not own another pool."""
    from oldman.conf import settings

    return await redis_client.using(settings.cache.client).async_get_bin_conn()


async def get_django_cache(key: str, default: Any = None) -> Any:
    """Read a Django key, distinguishing a missing key from a stored None."""
    connection = await _connection()
    value = await connection.get(f":1:{key}")
    return default if value is None else django_serializer.loads(value)


async def set_django_cache(key: str, value: Any, lock_timeout: int | None = 60 * 60) -> None:
    """Write with Django expiry semantics: None persists, nonpositive deletes."""
    connection = await _connection()
    cache_key = f":1:{key}"
    if lock_timeout is not None and lock_timeout <= 0:
        await connection.delete(cache_key)
    else:
        await connection.set(cache_key, django_serializer.dumps(value), ex=lock_timeout)


async def set_api_cache(method: str, content: Any, expiration_time: int | None = 60 * 60, *args: Any) -> None:
    """添加缓存。"""
    key = "_".join([method] + [str(param) for param in args])
    await set_django_cache(key, content, expiration_time)


async def get_api_cache(method: str, *args: Any) -> Any:
    """获取缓存。"""
    key = "_".join([method] + [str(param) for param in args])
    return await get_django_cache(key)


async def delete_api_cache(method: str, *args: Any) -> None:
    """删除单一缓存。"""
    key = "_".join([method] + [str(param) for param in args])
    connection = await _connection()
    await connection.delete(f":1:{key}")


async def delete_api_cache_many(method: str, *args: Any) -> None:
    """Delete matching Django keys incrementally, never Native Cache keys."""
    key = f"{method}_" + "_".join(map(str, args)) + "*"
    connection = await _connection()
    cursor = 0
    while True:
        cursor, keys = await connection.scan(cursor=cursor, match=f":1:{key}", count=100)
        if keys:
            await connection.delete(*keys)
        if cursor == 0:
            return


async def get_cached_random_key_from_pk(pk: Any, length: int = 8, ttl: int = 60 * 30) -> str:
    """Store an ID under the existing short random-key convention."""
    random_key = "".join(random.sample(string.ascii_letters + string.digits, length)).lower()
    await set_api_cache(f"cached_random_key_{random_key}", pk, ttl)
    return random_key


async def get_cached_id_from_random_key(random_key: str) -> int:
    """Resolve a cached ID, returning zero when the short key has expired."""
    key = f"cached_random_key_{random_key}"
    pk = await get_api_cache(key)
    if pk:
        return int(pk)
    return 0


def cache_async_response(timeout: int = 60 * 60, prefix: str = "cache_fun_response"):
    """Cache an async result with the same key convention as the Django helper."""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """Bind the function without resolving settings or connecting to Redis."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Read once and compute on a miss; preserve false and zero results."""
            key = f"{prefix}_{func.__name__}_{'_'.join(map(str, args))}_{'_'.join(f'{k}_{v}' for k, v in kwargs.items())}"
            result = await get_django_cache(key)
            if result is None:
                result = await func(*args, **kwargs)
                await set_django_cache(key, result, timeout)
            return result

        return wrapper

    return decorator
