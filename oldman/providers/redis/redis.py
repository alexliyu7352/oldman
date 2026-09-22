"""Concrete async Redis client with an explicit connection lifecycle."""

from __future__ import annotations

import asyncio
import socket
import time
import uuid
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from redis import asyncio as aioredis
from redis.asyncio.lock import Lock
from redis.asyncio.retry import Retry as AsyncRetry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from oldman.logging import logger

_TCP_REDIS_SCHEMES = frozenset({"redis", "rediss"})
_DECLARED_CONNECTION_OPTIONS = frozenset(
    {
        "redis_url",
        "decode_responses",
        "max_connections",
        "health_check_interval",
        "protocol",
        "retry_attempts",
        "retry_on_timeout",
        "backoff_base",
        "backoff_cap",
        "connection_pool",
        "socket_keepalive",
        "socket_keepalive_idle",
        "socket_keepalive_interval",
        "socket_keepalive_count",
        "socket_keepalive_options",
        "retry",
        "url",
    }
)


def redis_pool_options(
    *,
    redis_url: str,
    decode_responses: bool,
    max_connections: int,
    health_check_interval: int,
    protocol: int,
    retry_attempts: int,
    retry_on_timeout: bool,
    backoff_base: float,
    backoff_cap: float,
    socket_keepalive: bool,
    socket_keepalive_idle: int,
    socket_keepalive_interval: int,
    socket_keepalive_count: int,
    connection_options: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert validated Oldman options for an independently owned native pool.

    Extensions already have their ``connection_`` prefix removed. This function
    neither mutates the supplied options nor creates a client or connection pool.
    """
    supported_errors = (ConnectionError, TimeoutError) if retry_on_timeout else (ConnectionError,)
    options: dict[str, Any] = {
        "retry_on_timeout": retry_on_timeout,
        "decode_responses": decode_responses,
        "retry": AsyncRetry(
            backoff=ExponentialBackoff(cap=backoff_cap, base=backoff_base),
            retries=retry_attempts,
            supported_errors=supported_errors,
        ),
        "max_connections": max_connections,
        "health_check_interval": health_check_interval,
        "protocol": protocol,
        **connection_options,
    }
    if urlsplit(redis_url).scheme in _TCP_REDIS_SCHEMES:
        options["socket_keepalive"] = socket_keepalive
        if socket_keepalive:
            options["socket_keepalive_options"] = {
                socket.TCP_KEEPIDLE: socket_keepalive_idle,
                socket.TCP_KEEPINTVL: socket_keepalive_interval,
                socket.TCP_KEEPCNT: socket_keepalive_count,
            }
    return options


class AsyncRedis:
    """Manage one lazily initialized redis-py asyncio connection pool."""

    def __init__(
        self,
        redis_url: str = "",
        decode_responses: bool = True,
        *,
        max_connections: int = 1024,
        health_check_interval: int = 30,
        protocol: Literal[2, 3] = 2,
        retry_attempts: int = 3,
        retry_on_timeout: bool = True,
        backoff_base: float = 0.1,
        backoff_cap: float = 2.0,
        socket_keepalive: bool = True,
        socket_keepalive_idle: int = 60,
        socket_keepalive_interval: int = 10,
        socket_keepalive_count: int = 3,
        **connection_options: Any,
    ) -> None:
        self.redis_url = redis_url
        self.decode_responses = decode_responses
        self.max_connections = max_connections
        self.health_check_interval = health_check_interval
        self.protocol = protocol
        self.retry_attempts = retry_attempts
        self.retry_on_timeout = retry_on_timeout
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.socket_keepalive = socket_keepalive
        self.socket_keepalive_idle = socket_keepalive_idle
        self.socket_keepalive_interval = socket_keepalive_interval
        self.socket_keepalive_count = socket_keepalive_count
        self._connection_options = self._normalize_connection_options(connection_options)
        self._conn: aioredis.Redis | None = None
        self._pool: aioredis.ConnectionPool | None = None
        self._init_lock = asyncio.Lock()
        self.retry_strategy: AsyncRetry | None = None

    @staticmethod
    def _normalize_connection_options(options: dict[str, Any]) -> dict[str, Any]:
        """Strip settings prefixes and reject options with duplicate meanings."""
        normalized: dict[str, Any] = {}
        for field_name, value in options.items():
            if not field_name.startswith("connection_") or field_name == "connection_":
                raise TypeError(f"redis-py extension {field_name!r} requires a connection_ prefix")
            option_name = field_name.removeprefix("connection_")
            if option_name in _DECLARED_CONNECTION_OPTIONS:
                raise TypeError(f"connection option {option_name!r} duplicates a declared AsyncRedis argument")
            normalized[option_name] = value
        return normalized

    def _pool_options(self) -> dict[str, Any]:
        """Build redis-py pool options from the concrete client parameters."""
        options = redis_pool_options(
            redis_url=self.redis_url,
            decode_responses=self.decode_responses,
            max_connections=self.max_connections,
            health_check_interval=self.health_check_interval,
            protocol=self.protocol,
            retry_attempts=self.retry_attempts,
            retry_on_timeout=self.retry_on_timeout,
            backoff_base=self.backoff_base,
            backoff_cap=self.backoff_cap,
            socket_keepalive=self.socket_keepalive,
            socket_keepalive_idle=self.socket_keepalive_idle,
            socket_keepalive_interval=self.socket_keepalive_interval,
            socket_keepalive_count=self.socket_keepalive_count,
            connection_options=self._connection_options,
        )
        self.retry_strategy = options["retry"]
        return options

    async def async_get_conn(self) -> aioredis.Redis:
        """Return the shared Redis client, initializing its pool once on first use."""
        if self._conn is not None:
            return self._conn
        async with self._init_lock:
            if self._conn is None:
                if not self.redis_url:
                    raise ValueError("You must specify a redis_url")
                logger.info("[redis] connecting")
                pool = aioredis.ConnectionPool.from_url(self.redis_url, **self._pool_options())
                try:
                    connection = aioredis.Redis(connection_pool=pool)
                except BaseException as exc:
                    try:
                        await pool.disconnect()
                    except BaseException as cleanup_error:
                        exc.add_note(f"Redis pool cleanup also failed: {cleanup_error}")
                    raise
                self._pool = pool
                self._conn = connection
            return self._conn

    async def close(self) -> None:
        """Close this client and pool, allowing a later access to reinitialize them."""
        async with self._init_lock:
            connection, self._conn = self._conn, None
            pool, self._pool = self._pool, None
            if connection is None and pool is None:
                return
            logger.info("[redis] closing")
            connection_error: BaseException | None = None
            if connection is not None:
                try:
                    await connection.aclose()
                except BaseException as exc:
                    connection_error = exc
            if pool is not None:
                try:
                    await pool.disconnect()
                except BaseException as exc:
                    if connection_error is None:
                        connection_error = exc
                    else:
                        connection_error.add_note(f"Redis pool disconnect also failed: {exc}")
            if connection_error is not None:
                raise connection_error

    async def get_db_lock(self, key: str, expire_timeout: int = 60) -> bool:
        """Atomically create a short-lived presence lock."""
        conn = await self.async_get_conn()
        result = await conn.set(key, 1, nx=True, ex=expire_timeout)
        return result is True

    async def is_db_lock(self, key: str) -> bool:
        """Return whether a presence lock exists."""
        conn = await self.async_get_conn()
        result = await conn.get(key)
        return bool(result and int(result) > 0)

    async def acquire_lock(
        self,
        lock_name: str,
        acquire_timeout: int = 10,
        retry_interval: float = 0.001,
        expire_timeout: int | None = None,
    ) -> str | bool:
        """Acquire a token-owned lock with a bounded retry period.

        `acquire_timeout` is how long to keep trying; `expire_timeout` is how long the
        lock survives once held. They used to be the same number, which made the two
        settings pull against each other: a caller willing to wait longer also got a
        lock held longer, and a caller that wanted a short wait got a lock that could
        expire in the middle of its own critical section. `get_locker` already keeps them
        apart (`blocking_timeout` vs `expire_timeout`) and `get_db_lock` names its
        hold-time unambiguously; this brings the third API in line.

        `expire_timeout` defaults to `acquire_timeout` so existing callers keep the
        behaviour they have today.
        """
        conn = await self.async_get_conn()
        hold_timeout = acquire_timeout if expire_timeout is None else expire_timeout
        identifier = str(uuid.uuid4())
        end = time.time() + acquire_timeout
        while time.time() < end:
            if await conn.set(lock_name, identifier, nx=True, ex=hold_timeout):
                return identifier
            await asyncio.sleep(retry_interval)
        return False

    async def release_lock(self, lock_name: str, identifier: str) -> bool:
        """Release a token-owned lock atomically."""
        conn = await self.async_get_conn()
        lua = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        try:
            result = await conn.eval(lua, 1, lock_name, identifier)
            return bool(result)
        except Exception:
            return False

    async def get_locker(
        self,
        lock_key: str,
        blocking_timeout: int = 10,
        expire_timeout: int = 60,
        sleep: float = 0.01,
    ) -> Lock:
        """Return redis-py's distributed lock object."""
        conn = await self.async_get_conn()
        return conn.lock(
            name=lock_key,
            timeout=expire_timeout,
            blocking=True,
            blocking_timeout=blocking_timeout,
            sleep=sleep,
        )
