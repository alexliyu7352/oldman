"""High-level asynchronous Cache helpers and Sanic response caching."""

from __future__ import annotations

import base64
import functools
import hashlib
import inspect
import logging
import pickle
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import orjson
from sanic import Request
from sanic.response import BaseHTTPResponse, raw

from oldman.cache.backends.redis import redis_cache
from oldman.cache.exceptions import InvalidRequestError

logger = logging.getLogger(__name__)

VaryBy = Callable[[Request], object]

_READ_METHODS = frozenset(("GET", "HEAD"))
_WRITE_METHODS = frozenset(("POST", "PUT", "PATCH", "DELETE"))
_UNSAFE_RESPONSE_HEADERS = frozenset(
    (
        "connection",
        "content-length",
        "content-type",
        "date",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "server",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    )
)


class _DecodedCacheHit:
    """Distinguish a decoded falsey Cache hit from a backend miss."""

    def __init__(self, value: Any) -> None:
        """Store the value returned by the selected response decoder."""
        self.value = value


async def set_cache(method: str, content: Any, expiration_time: int = 60 * 60, *args: Any) -> None:
    """Store content under the historical underscore-delimited helper key."""
    key = "_".join([method] + [str(param) for param in args])
    await redis_cache.set(key, content, ttl=expiration_time)


async def get_cache(method: str, *args: Any) -> Any:
    """Return content stored under the historical helper key."""
    key = "_".join([method] + [str(param) for param in args])
    return await redis_cache.get(key)


async def get_cache_expiration(method: str, *args: Any) -> float | int:
    """Return the remaining lifetime of the historical helper key."""
    key = "_".join([method] + [str(param) for param in args])
    return await redis_cache.ttl(key)


async def delete_cache(method: str, *args: Any) -> None:
    """Delete one historical helper key."""
    key = "_".join([method] + [str(param) for param in args])
    await redis_cache.delete(key)


async def delete_cache_many(method: str, *args: Any) -> int:
    """Delete all historical helper keys sharing the requested prefix."""
    key = f"{method}_" + "_".join(map(str, args)) + "*"
    return await redis_cache.delete_match(key)


def cache_async_response(timeout: int = 60 * 60, prefix: str = "cache_fun_response") -> Callable:
    """Cache the return value of a general asynchronous callable."""

    def decorator(func: Callable) -> Callable:
        """Bind Cache configuration to one asynchronous callable."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Return a cached value or execute and cache the callable once."""
            key = f"{prefix}_{func.__name__}_{'_'.join(map(str, args))}_{'_'.join(f'{name}_{value}' for name, value in kwargs.items())}"
            try:
                result = await redis_cache.get(key)
            except Exception as error:
                logger.warning("Failed to read cache key %s: %s", key, error)
            else:
                if result is not None:
                    return result

            result = await func(*args, **kwargs)
            try:
                await redis_cache.set(key, result, ttl=timeout)
            except Exception as error:
                logger.warning("Failed to write cache key %s: %s", key, error)
            return result

        return wrapper

    return decorator


def _sha256(value: str) -> str:
    """Return the lowercase SHA-256 digest for a UTF-8 string."""
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_request_path(request: Request) -> str:
    """Return the pre-i18n path when available, otherwise the active Sanic path."""
    original_path = getattr(request.ctx, "original_path", None)
    return str(original_path if original_path is not None else request.path)


def _canonical_query_string(request: Request) -> str:
    """Sort query names while preserving the order of repeated values."""
    pairs: list[tuple[str, str]] = []
    query = request.args
    for name in sorted(query):
        values = query.getlist(name) if hasattr(query, "getlist") else query[name]
        if not isinstance(values, (list, tuple)):
            values = (values,)
        pairs.extend((str(name), str(value)) for value in values)
    return urlencode(pairs)


def _response_cache_key(request: Request, key_prefix: str, vary_by: VaryBy | None) -> str:
    """Build the versioned fixed-length response Cache key."""
    path = _canonical_request_path(request)
    query = _canonical_query_string(request)
    vary_value = "" if vary_by is None else str(vary_by(request))
    return f"http:v1:{key_prefix}:{_sha256(path)}:{_sha256(query)}:{_sha256(vary_value)}"


def _response_path_pattern(path: str, key_prefix: str) -> str:
    """Build the namespace-local pattern covering every query/vary entry for one path."""
    return f"http:v1:{key_prefix}:{_sha256(path)}:*"


def _cacheable_response_attributes(response: Any) -> dict[str, Any] | None:
    """Return safe serializable attributes for one eligible Sanic response."""
    if not isinstance(response, BaseHTTPResponse) or response.status != 200:
        return None
    if "set-cookie" in response.headers:
        return None

    headers = {
        str(name): str(value)
        for name, value in response.headers.items()
        if str(name).lower() not in _UNSAFE_RESPONSE_HEADERS
    }
    return {
        "body": base64.b64encode(response.body or b"").decode("ascii"),
        "status": response.status,
        "content_type": response.content_type or "application/octet-stream",
        "headers": headers,
    }


def _restore_response(attributes: Mapping[str, Any]) -> BaseHTTPResponse:
    """Build a fresh Sanic response from cached plain attributes."""
    return raw(
        base64.b64decode(attributes["body"], validate=True),
        status=int(attributes["status"]),
        headers=dict(attributes["headers"]),
        content_type=str(attributes["content_type"]),
    )


def _request_argument(func: Callable, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request:
    """Locate the Sanic request in a function or concrete HTTPMethodView handler call."""
    parameters = tuple(inspect.signature(func).parameters)
    request_index = 1 if parameters and parameters[0] in {"self", "cls"} else 0
    if len(args) > request_index:
        return args[request_index]
    return kwargs[parameters[request_index]]


def cache_response(
    key_prefix: str = "response",
    *,
    expiration: int = 3600,
    invalidate_paths: tuple[str, ...] = (),
    vary_by: VaryBy | None = None,
    use_pickle: bool = True,
) -> Callable:
    """Cache successful Sanic responses and invalidate path-scoped entries after writes.

    GET and HEAD share an automatic path/query/vary key. Only status-200,
    non-streaming, cookie-free Sanic responses are stored as plain response
    attributes. Backend failures are fail-open. Mutation methods clear all
    query/vary variants for the current path and explicitly related paths.
    """

    def decorator(func: Callable) -> Callable:
        """Bind response Cache behavior to one Sanic handler method."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Execute the read, write-invalidation, or pass-through request path."""
            request = _request_argument(func, args, kwargs)
            method = request.method.upper()

            if method in _READ_METHODS:
                if invalidate_paths:
                    raise InvalidRequestError("Cache read requests cannot define invalidation paths")
                cache_key = _response_cache_key(request, key_prefix, vary_by)
                decoder = pickle.loads if use_pickle else orjson.loads

                def loads_fn(value: Any) -> Any:
                    """Preserve the distinction between a backend miss and a falsey decoded hit."""
                    return None if value is None else _DecodedCacheHit(decoder(value))

                try:
                    cached_data = await redis_cache.get(cache_key, loads_fn=loads_fn)
                    if isinstance(cached_data, _DecodedCacheHit):
                        return _restore_response(cached_data.value)
                except Exception as error:
                    logger.warning("Failed to read response cache key %s: %s", cache_key, error)

                result = await func(*args, **kwargs)
                attributes = _cacheable_response_attributes(result)
                if attributes is not None:
                    try:
                        dumps_fn = pickle.dumps if use_pickle else orjson.dumps
                        await redis_cache.set(cache_key, attributes, ttl=expiration, dumps_fn=dumps_fn)
                    except Exception as error:
                        logger.warning("Failed to write response cache key %s: %s", cache_key, error)
                return result

            if method in _WRITE_METHODS:
                # Resolve every template before the mutation so invalid configuration cannot
                # leave persisted state behind without its corresponding Cache invalidation.
                paths = [_canonical_request_path(request)]
                paths.extend(path.format(**kwargs) for path in invalidate_paths)
                result = await func(*args, **kwargs)
                for path in paths:
                    pattern = _response_path_pattern(path, key_prefix)
                    try:
                        await redis_cache.delete_match(pattern)
                    except Exception as error:
                        logger.warning("Failed to invalidate response cache pattern %s: %s", pattern, error)
                return result

            return await func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = (
    "cache_async_response",
    "cache_response",
    "delete_cache",
    "delete_cache_many",
    "get_cache",
    "get_cache_expiration",
    "set_cache",
)
