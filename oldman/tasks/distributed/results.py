"""Owned binary Redis pools and the native Taskiq result contract."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis.asyncio import BlockingConnectionPool, Redis
from taskiq import TaskiqResult
from taskiq_redis import RedisAsyncResultBackend

from oldman.conf.schemas import RedisConnectionConfig
from oldman.providers.redis.redis import redis_pool_options


def binary_redis_options(config: RedisConnectionConfig) -> tuple[str, dict[str, Any]]:
    """Reuse provider conversion while keeping these independent pools byte-oriented."""
    values = config.model_dump(exclude=set(config.model_extra or {}))
    values["decode_responses"] = False
    options = redis_pool_options(**values, connection_options=config.connection_options)
    options["max_connection_pool_size"] = options.pop("max_connections")
    # redis-py gives query parameters priority over kwargs. Remove only this one
    # override; credentials, database, TLS and other explicit URL options survive.
    url = urlsplit(config.redis_url)
    query = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True) if key != "decode_responses"]
    return urlunsplit(url._replace(query=urlencode(query))), options


class OptionalResultBackend(RedisAsyncResultBackend[Any]):
    """Skip unwanted results before serialization, otherwise retain native behavior."""

    def __init__(self, redis_url: str, **options: Any) -> None:
        """Keep only constructor options needed to reopen this owned pool after close."""
        super().__init__(redis_url, **options)
        self._redis_url = redis_url
        self._pool_options = {
            key: value for key, value in options.items()
            if key not in {"serializer", "prefix_str", "result_ex_time", "keep_results"}
        }
        self._pool_options["max_connections"] = self._pool_options.pop("max_connection_pool_size")
        self.closed = False
        self.close_attempted = False

    def reopen_pool(self) -> None:
        """A completed lifecycle must not lend a loop-bound pool to the next one."""
        if self.closed:
            self.redis_pool = BlockingConnectionPool.from_url(self._redis_url, **self._pool_options)
            self.closed = False
            self.close_attempted = False

    async def startup(self) -> None:
        """Prove this owned pool is usable within the broker's startup deadline."""
        await super().startup()
        async with Redis(connection_pool=self.redis_pool) as client:
            await client.ping()

    async def shutdown(self) -> None:
        """Expose actual close completion so failed broker hooks cannot skip the pool."""
        self.close_attempted = True
        await super().shutdown()
        self.closed = True

    async def set_result(self, task_id: str, result: TaskiqResult[Any]) -> None:
        """Ignoring a result also supports an otherwise nonserializable return value."""
        if str(result.labels.get("ignore_result", False)).lower() == "true":
            return
        await super().set_result(task_id, result)
