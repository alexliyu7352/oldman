"""Oldman HTTP client and Redis/cache integration boundary tests."""

from __future__ import annotations

import asyncio
import pickle
import subprocess
import sys
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]


class StaticAsyncByteStream(httpx.AsyncByteStream):
    """One-shot HTTPX stream used by the shared-session integration fake."""

    def __init__(self, content: bytes) -> None:
        """Store the body returned by the fake transport."""

        self.content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield the complete body once."""

        yield self.content


class FakeHttpxClient:
    """Small fake HTTPX client."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.is_closed = False
        self.request_calls: list[tuple[str, str, dict]] = []
        self.closed = False

    async def request(self, method: str, url: str, **kwargs):
        self.request_calls.append((method, url, kwargs))
        return self.response

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs):
        """Return a fresh raw stream while keeping one fake session instance."""

        self.request_calls.append((method, url, kwargs))
        assert isinstance(self.response, httpx.Response)
        response = httpx.Response(
            self.response.status_code,
            headers=self.response.headers,
            stream=StaticAsyncByteStream(self.response.content),
            request=httpx.Request(method, url),
            extensions={"http_version": b"HTTP/1.1"},
        )
        try:
            yield response
        finally:
            await response.aclose()

    async def aclose(self) -> None:
        self.closed = True
        self.is_closed = True


class FakeRedisConnection:
    """Small fake async Redis connection."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def execute_command(self, command: str, key: str, *args, **kwargs):
        del args, kwargs
        if command == "GET":
            return self.values.get(key)
        raise AssertionError(f"unexpected command: {command}")

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: bytes, **kwargs) -> bool:
        del kwargs
        self.values[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: bytes) -> bool:
        del ttl
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        self.values.pop(key, None)
        return 1


class FoundationIntegrationsTest(unittest.TestCase):
    """Verify foundation integrations are lazy and usable."""

    def test_importing_http_client_and_cache_does_not_create_external_clients(self) -> None:
        """Package imports must not create HTTP sessions or Redis pools."""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from unittest.mock import patch; "
                "patches = ["
                "patch('httpx.AsyncClient'), "
                "patch('aiohttp.ClientSession'), "
                "patch('curl_cffi.requests.AsyncSession'), "
                "patch('redis.asyncio.ConnectionPool.from_url'), "
                "patch('redis.connection.ConnectionPool.from_url'), "
                "patch('redis.Redis')]; "
                "mocks = [item.start() for item in patches]; "
                "import oldman.contrib.http, oldman.cache; "
                "assert all(mock.call_count == 0 for mock in mocks)",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_http_client_initialization_does_not_create_backend_session_until_request(self) -> None:
        """MultiHttpClient creates backend objects before it creates network sessions."""

        async def run_case() -> None:
            client = MultiHttpClient(ClientType.HTTPX, max_connections=10, user_agent="TestAgent/1")
            with patch("oldman.contrib.http.backends.httpx.httpx.AsyncClient") as httpx_client:
                await client.init_client()
                self.assertTrue(client.is_initialized())
                httpx_client.assert_not_called()
                await client.close_client()

        from oldman.contrib.http import ClientType, MultiHttpClient

        asyncio.run(run_case())

    def test_http_client_request_uses_shared_backend_session(self) -> None:
        """Requests should create one backend session and reuse it."""
        response = httpx.Response(
            200,
            content=b"ok",
            request=httpx.Request("GET", "https://example.test/path"),
        )
        fake_client = FakeHttpxClient(response)

        async def run_case() -> None:
            client = MultiHttpClient(max_connections=5, user_agent="TestAgent/1", retry_count=0)
            with patch(
                "oldman.contrib.http.backends.httpx.httpx.AsyncClient",
                return_value=fake_client,
            ) as httpx_client:
                await client.init_client()
                result = await client.get("https://example.test/path", headers={"User-Agent": "TestAgent/1"})
                second = await client.get("https://example.test/second", headers={"User-Agent": "TestAgent/1"})
                await client.close_client()

            self.assertEqual(b"ok", result.content)
            self.assertEqual(b"ok", second.content)
            self.assertIsInstance(result.native_response, httpx.Response)
            self.assertIsInstance(second.native_response, httpx.Response)
            httpx_client.assert_called_once()

        from oldman.contrib.http import MultiHttpClient

        asyncio.run(run_case())
        self.assertEqual("GET", fake_client.request_calls[0][0])
        self.assertEqual("TestAgent/1", fake_client.request_calls[0][2]["headers"]["User-Agent"])
        self.assertTrue(fake_client.closed)

    def test_http_request_retry_controls_do_not_leak_to_backend(self) -> None:
        """Per-request retry controls belong to the facade, not backend kwargs."""
        response = Mock(status_code=200)
        response.is_success = True
        backend = FakeHttpxClient(response)

        async def run_case() -> None:
            client = MultiHttpClient(max_connections=10, user_agent="TestAgent/1", retry_count=3)
            client._impl = backend  # type: ignore[assignment]

            result = await client.get(
                "https://example.test/path",
                retries=0,
                no_retry_statuses=[418],
                retry_backoff=0,
                headers={"X-Test": "yes"},
            )

            self.assertIs(result, response)

        from oldman.contrib.http import MultiHttpClient

        asyncio.run(run_case())
        backend_kwargs = backend.request_calls[0][2]
        self.assertEqual({"X-Test": "yes"}, backend_kwargs["headers"])
        self.assertNotIn("retries", backend_kwargs)
        self.assertNotIn("no_retry_statuses", backend_kwargs)
        self.assertNotIn("retry_backoff", backend_kwargs)

    def test_async_redis_client_does_not_connect_until_initialized(self) -> None:
        """Canonical AsyncRedis construction must not create a Redis pool."""
        from oldman.providers.redis import AsyncRedis

        async def run_case() -> None:
            client = AsyncRedis("redis://localhost:6379/0")
            fake_pool = object()
            fake_conn = object()
            with (
                patch(
                    "oldman.providers.redis.redis.aioredis.ConnectionPool.from_url",
                    return_value=fake_pool,
                ) as pool_factory,
                patch(
                    "oldman.providers.redis.redis.aioredis.Redis",
                    return_value=fake_conn,
                ) as redis_factory,
            ):
                pool_factory.assert_not_called()
                redis_factory.assert_not_called()
                conn = await client.async_get_conn()

            self.assertIs(conn, fake_conn)
            pool_factory.assert_called_once()
            redis_factory.assert_called_once()

        asyncio.run(run_case())

    def test_redis_cache_uses_backend_protocol(self) -> None:
        """RedisCache should implement get/set/delete through its lazy client."""
        from oldman.cache import RedisCache

        class FakeRedisClient:
            def __init__(self) -> None:
                self.conn = FakeRedisConnection()

            async def async_get_bin_conn(self) -> FakeRedisConnection:
                return self.conn

        async def run_case() -> None:
            client = FakeRedisClient()
            cache = RedisCache(client=client, namespace="test")
            await cache.set("answer", {"value": 42}, ttl=10)
            raw = client.conn.values["test:answer"]
            self.assertEqual({"value": 42}, pickle.loads(raw))
            self.assertEqual({"value": 42}, await cache.get("answer"))
            await cache.delete("answer")
            self.assertEqual(["test:answer"], client.conn.deleted)

        asyncio.run(run_case())

    def test_redis_fixed_window_limiter_uses_injected_client(self) -> None:
        """The fixed-window security limiter should use its injected client."""
        from oldman.web.security.rate_limiter import RedisFixedWindowRateLimiter

        class FakeRateRedis:
            def __init__(self) -> None:
                self.count = 0
                self.expired: list[tuple[str, int]] = []

            async def incr(self, key: str) -> int:
                self.key = key
                self.count += 1
                return self.count

            async def expire(self, key: str, period: int) -> None:
                self.expired.append((key, period))

        class FakeRateClient:
            def __init__(self) -> None:
                self.conn = FakeRateRedis()

            async def async_get_conn(self) -> FakeRateRedis:
                return self.conn

        async def run_case() -> None:
            client = FakeRateClient()
            with self.assertRaisesRegex(ValueError, "namespace"):
                RedisFixedWindowRateLimiter(client, namespace="")
            limiter = RedisFixedWindowRateLimiter(client)
            with patch("oldman.web.security.rate_limiter.fixed_window.time.time", return_value=125):
                self.assertFalse(await limiter.is_rate_limited(7, "/api/users", limit=1, period=60))
                self.assertTrue(await limiter.is_rate_limited(7, "/api/users", limit=1, period=60))
            self.assertEqual("ratelimit:7:api_users:120", client.conn.key)
            self.assertEqual(1, len(client.conn.expired))

            root_client = FakeRateClient()
            root_limiter = RedisFixedWindowRateLimiter(root_client)
            with patch("oldman.web.security.rate_limiter.fixed_window.time.time", return_value=125):
                self.assertFalse(await root_limiter.is_rate_limited("service", "/", limit=1, period=60))
            self.assertEqual("ratelimit:service::120", root_client.conn.key)

            failing_client = FakeRateClient()
            failing_client.conn.incr = AsyncMock(side_effect=RuntimeError("redis failed"))
            with self.assertRaisesRegex(RuntimeError, "redis failed"):
                await RedisFixedWindowRateLimiter(failing_client).is_rate_limited(
                    "user", "/api/users", limit=1, period=60
                )

            with self.assertRaisesRegex(ValueError, "period"):
                await limiter.is_rate_limited(7, "/api", limit=1, period=0)
            with self.assertRaisesRegex(ValueError, "limit"):
                await limiter.is_rate_limited(7, "/api", limit=-1, period=60)

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
