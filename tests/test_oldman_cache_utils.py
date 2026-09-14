"""Behavior tests for the high-level asynchronous Cache helpers."""

from __future__ import annotations

import hashlib
import pickle
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, call, patch

from sanic import Request, Sanic
from sanic.request import RequestParameters
from sanic.response import ResponseStream
from sanic.response import raw as raw_response
from sanic.views import HTTPMethodView

import oldman.cache.utils as cache_utils
from oldman.cache.backends.memory import MemoryCache
from oldman.cache.exceptions import InvalidRequestError
from oldman.cache.utils import (
    cache_async_response,
    cache_response,
    delete_cache,
    delete_cache_many,
    get_cache,
    get_cache_expiration,
    set_cache,
)


def _request(
    method: str,
    *,
    path: str = "/items/7",
    original_path: str | None = None,
    query: dict[str, list[str]] | None = None,
) -> Any:
    """Build the minimal Sanic request surface used by the decorator."""
    ctx = SimpleNamespace()
    if original_path is not None:
        ctx.original_path = original_path
    return SimpleNamespace(
        method=method,
        path=path,
        ctx=ctx,
        args=RequestParameters(query or {}),
    )


def _path_pattern(prefix: str, path: str) -> str:
    """Build the independently calculated expected invalidation pattern."""
    path_hash = hashlib.sha256(path.encode()).hexdigest()
    return f"http:v1:{prefix}:{path_hash}:*"


class CacheResponseTest(unittest.IsolatedAsyncioTestCase):
    """Verify the Sanic-native response Cache contract."""

    async def test_miss_writes_plain_response_attributes_with_pickle(self) -> None:
        """A GET miss must execute once and store serializable response attributes."""
        backend = AsyncMock()
        backend.get.return_value = None
        calls: list[int] = []

        @cache_response("items", expiration=30, vary_by=lambda request: "tenant-9")
        async def item(request: Any, item_id: int) -> Any:
            """Return one cacheable Sanic response."""
            calls.append(item_id)
            return raw_response(
                b"payload",
                status=200,
                headers={"X-Source": "handler", "Connection": "close"},
                content_type="application/x-item",
            )

        request = _request(
            "GET",
            original_path="/zh-hans/items/7",
            query={"b": ["2", "3"], "a": ["1"]},
        )
        with patch("oldman.cache.utils.redis_cache", backend):
            response = await item(request, 7)

        path_hash = hashlib.sha256(b"/zh-hans/items/7").hexdigest()
        query_hash = hashlib.sha256(b"a=1&b=2&b=3").hexdigest()
        vary_hash = hashlib.sha256(b"tenant-9").hexdigest()
        expected_key = f"http:v1:items:{path_hash}:{query_hash}:{vary_hash}"
        self.assertEqual([7], calls)
        self.assertEqual(b"payload", response.body)
        backend.get.assert_awaited_once()
        self.assertEqual(expected_key, backend.get.await_args.args[0])
        backend.set.assert_awaited_once()
        set_call = backend.set.await_args
        self.assertEqual(expected_key, set_call.args[0])
        self.assertEqual(
            {
                "body": "cGF5bG9hZA==",
                "status": 200,
                "content_type": "application/x-item",
                "headers": {"X-Source": "handler"},
            },
            set_call.args[1],
        )
        self.assertEqual(30, set_call.kwargs["ttl"])
        self.assertIs(pickle.dumps, set_call.kwargs["dumps_fn"])

    async def test_hit_rebuilds_a_fresh_sanic_response(self) -> None:
        """A decoded hit must not execute the handler or reuse a live response object."""
        attributes = {
            "body": "cGF5bG9hZA==",
            "status": 201,
            "content_type": "application/x-item",
            "headers": {"X-Source": "cache"},
        }
        backend = AsyncMock()
        backend.get.return_value = cache_utils._DecodedCacheHit(attributes)
        calls = 0

        @cache_response("items")
        async def item(request: Any) -> Any:
            """Return a response only when the Cache misses."""
            nonlocal calls
            calls += 1
            return raw_response(b"fresh")

        with patch("oldman.cache.utils.redis_cache", backend):
            first = await item(_request("GET"))
            second = await item(_request("GET"))

        self.assertEqual(0, calls)
        self.assertIsNot(first, second)
        for response in (first, second):
            self.assertEqual(b"payload", response.body)
            self.assertEqual(201, response.status)
            self.assertEqual("application/x-item", response.content_type)
            self.assertEqual("cache", response.headers["X-Source"])
        backend.set.assert_not_awaited()

    async def test_orjson_round_trip_handles_binary_body(self) -> None:
        """JSON mode must round-trip the same attribute mapping through Base64."""
        backend = MemoryCache()
        calls = 0

        @cache_response("binary", expiration=0, use_pickle=False)
        async def item(request: Any) -> Any:
            """Return one response containing non-UTF-8 bytes."""
            nonlocal calls
            calls += 1
            return raw_response(b"\xff\x00", content_type="application/octet-stream")

        with patch("oldman.cache.utils.redis_cache", backend):
            first = await item(_request("GET"))
            second = await item(_request("GET"))

        self.assertEqual(1, calls)
        self.assertEqual(b"\xff\x00", first.body)
        self.assertEqual(b"\xff\x00", second.body)

    async def test_get_and_head_share_the_same_key(self) -> None:
        """HEAD must use the GET representation key rather than a second entry."""
        backend = AsyncMock()
        backend.get.return_value = cache_utils._DecodedCacheHit(
            {"body": "", "status": 200, "content_type": "text/plain", "headers": {}}
        )

        @cache_response("items")
        async def item(request: Any) -> Any:
            """Return an unreachable response for Cache-hit requests."""
            return raw_response(b"fresh")

        with patch("oldman.cache.utils.redis_cache", backend):
            await item(_request("GET"))
            await item(_request("HEAD"))

        keys = [entry.args[0] for entry in backend.get.await_args_list]
        self.assertEqual(2, len(keys))
        self.assertEqual(keys[0], keys[1])

    async def test_concrete_http_method_view_handler_is_supported(self) -> None:
        """A decorator on HTTPMethodView.get must locate request after self."""
        backend = AsyncMock()
        backend.get.return_value = None

        class ItemView(HTTPMethodView):
            """Expose one decorated concrete method."""

            @cache_response("items")
            async def get(self, request: Any) -> Any:
                """Return a cacheable response."""
                return raw_response(b"method")

        with patch("oldman.cache.utils.redis_cache", backend):
            response = await ItemView().get(_request("GET"))

        self.assertEqual(b"method", response.body)
        backend.get.assert_awaited_once()
        backend.set.assert_awaited_once()

    async def test_real_sanic_routes_reuse_function_and_method_responses(self) -> None:
        """Real Sanic routing must exercise one handler call across two requests."""
        app = Sanic(f"cache-response-{id(self)}")
        backend = MemoryCache()
        calls: list[tuple[str, int]] = []

        @app.get("/function/<item_id:int>")
        @cache_response("function", use_pickle=False)
        async def function_handler(request: Request, item_id: int) -> Any:
            """Return one function-route response."""
            calls.append(("function", item_id))
            return raw_response(b"function", headers={"X-Source": "handler"})

        class ItemView(HTTPMethodView):
            """Expose one cached method route through Sanic dispatch."""

            @cache_response("method", use_pickle=False)
            async def get(self, request: Request, item_id: int) -> Any:
                """Return one method-route response."""
                calls.append(("method", item_id))
                return raw_response(b"method")

        app.add_route(ItemView.as_view(), "/method/<item_id:int>")
        try:
            with patch("oldman.cache.utils.redis_cache", backend):
                _, first_function = await app.asgi_client.get("/function/7?a=1")
                _, second_function = await app.asgi_client.get("/function/7?a=1")
                _, first_method = await app.asgi_client.get("/method/8")
                _, second_method = await app.asgi_client.get("/method/8")
        finally:
            await backend.close()

        self.assertEqual([("function", 7), ("method", 8)], calls)
        self.assertEqual((b"function", b"function"), (first_function.body, second_function.body))
        self.assertEqual((b"method", b"method"), (first_method.body, second_method.body))
        self.assertEqual("handler", second_function.headers["X-Source"])

    async def test_ineligible_responses_are_not_written(self) -> None:
        """Streams, errors, and cookie-bearing responses must bypass Cache writes."""

        async def stream(response: Any) -> None:
            """Provide the inert callback required by ResponseStream."""
            return None

        responses = (
            ResponseStream(stream),
            raw_response(b"error", status=503),
            raw_response(b"private", headers={"Set-Cookie": "session=secret"}),
        )
        for source in responses:
            with self.subTest(response_type=type(source).__name__, status=getattr(source, "status", None)):
                backend = AsyncMock()
                backend.get.return_value = None

                @cache_response("items")
                async def item(request: Any, response: Any = source) -> Any:
                    """Return the selected non-cacheable response."""
                    return response

                with patch("oldman.cache.utils.redis_cache", backend):
                    result = await item(_request("GET"))

                self.assertIs(source, result)
                backend.set.assert_not_awaited()

    async def test_read_and_write_failures_are_fail_open(self) -> None:
        """Cache failures must not duplicate or suppress handler execution."""
        backend = AsyncMock()
        backend.get.side_effect = ConnectionError("offline")
        backend.set.side_effect = ConnectionError("offline")
        calls = 0

        @cache_response("items")
        async def item(request: Any) -> Any:
            """Return a response while the backend is unavailable."""
            nonlocal calls
            calls += 1
            return raw_response(b"fresh")

        logger = Mock()
        with (
            patch("oldman.cache.utils.redis_cache", backend),
            patch("oldman.cache.utils.logger", logger),
        ):
            response = await item(_request("GET"))

        self.assertEqual(b"fresh", response.body)
        self.assertEqual(1, calls)
        self.assertEqual(2, logger.warning.call_count)

    async def test_reads_reject_invalidation_paths_before_cache_io(self) -> None:
        """GET and HEAD cannot be combined with write invalidation options."""
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                backend = AsyncMock()
                calls = 0

                @cache_response("items", invalidate_paths=("/related",))
                async def item(request: Any) -> Any:
                    """Return an unreachable response for invalid configuration."""
                    nonlocal calls
                    calls += 1
                    return raw_response(b"fresh")

                with (
                    patch("oldman.cache.utils.redis_cache", backend),
                    self.assertRaisesRegex(InvalidRequestError, "read requests"),
                ):
                    await item(_request(method))

                self.assertEqual(0, calls)
                backend.get.assert_not_awaited()

    async def test_writes_invalidate_current_and_formatted_related_paths(self) -> None:
        """Mutations must clear every query and vary entry for selected paths."""
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                backend = AsyncMock()
                calls = 0

                @cache_response("items", invalidate_paths=("/users/{user_id}/items",))
                async def item(request: Any, *, user_id: int) -> Any:
                    """Return one successful mutation response."""
                    nonlocal calls
                    calls += 1
                    return raw_response(b"updated")

                request = _request(method, original_path="/zh-hans/items/7")
                with patch("oldman.cache.utils.redis_cache", backend):
                    response = await item(request, user_id=9)

                self.assertEqual(b"updated", response.body)
                self.assertEqual(1, calls)
                self.assertEqual(
                    [
                        call(_path_pattern("items", "/zh-hans/items/7")),
                        call(_path_pattern("items", "/users/9/items")),
                    ],
                    backend.delete_match.await_args_list,
                )
                backend.get.assert_not_awaited()
                backend.set.assert_not_awaited()

    async def test_invalidation_failure_does_not_skip_later_paths(self) -> None:
        """One failed deletion must not prevent the remaining paths from being cleared."""
        backend = AsyncMock()
        backend.delete_match.side_effect = [ConnectionError("offline"), 2, 1]

        @cache_response("items", invalidate_paths=("/users/{user_id}", "/summary"))
        async def item(request: Any, *, user_id: int) -> Any:
            """Return one successful mutation response."""
            return raw_response(b"updated")

        logger = Mock()
        with (
            patch("oldman.cache.utils.redis_cache", backend),
            patch("oldman.cache.utils.logger", logger),
        ):
            response = await item(_request("POST"), user_id=9)

        self.assertEqual(b"updated", response.body)
        self.assertEqual(3, backend.delete_match.await_count)
        logger.warning.assert_called_once()

    async def test_options_bypasses_all_cache_operations(self) -> None:
        """Unsupported methods must invoke only the original handler."""
        backend = AsyncMock()
        calls = 0

        @cache_response("items", invalidate_paths=("/related",))
        async def item(request: Any) -> Any:
            """Return one OPTIONS response."""
            nonlocal calls
            calls += 1
            return raw_response(b"options")

        with patch("oldman.cache.utils.redis_cache", backend):
            response = await item(_request("OPTIONS"))

        self.assertEqual(b"options", response.body)
        self.assertEqual(1, calls)
        backend.get.assert_not_awaited()
        backend.set.assert_not_awaited()
        backend.delete_match.assert_not_awaited()

    async def test_missing_invalidation_field_fails_before_mutation(self) -> None:
        """Invalid path templates must not allow a partially executed mutation."""
        backend = AsyncMock()
        calls = 0

        @cache_response("items", invalidate_paths=("/users/{missing_id}",))
        async def item(request: Any, *, user_id: int) -> Any:
            """Return an unreachable mutation response."""
            nonlocal calls
            calls += 1
            return raw_response(b"updated")

        with (
            patch("oldman.cache.utils.redis_cache", backend),
            self.assertRaises(KeyError),
        ):
            await item(_request("POST"), user_id=9)

        self.assertEqual(0, calls)
        backend.delete_match.assert_not_awaited()


class CacheHelperTest(unittest.IsolatedAsyncioTestCase):
    """Verify the direct key-based Cache helpers."""

    async def test_set_cache_uses_cache_set(self) -> None:
        """set_cache must preserve its historical underscore key format."""
        backend = AsyncMock()
        with patch("oldman.cache.utils.redis_cache", backend):
            result = await set_cache("user", {"id": 7}, 12, 7)
        self.assertIsNone(result)
        backend.set.assert_awaited_once_with("user_7", {"id": 7}, ttl=12)

    async def test_get_cache_uses_cache_get(self) -> None:
        """get_cache must delegate one namespaced key to the backend."""
        backend = AsyncMock()
        backend.get.return_value = {"id": 7}
        with patch("oldman.cache.utils.redis_cache", backend):
            result = await get_cache("user", 7)
        self.assertEqual({"id": 7}, result)
        backend.get.assert_awaited_once_with("user_7")

    async def test_get_cache_expiration_uses_cache_ttl(self) -> None:
        """get_cache_expiration must return the backend TTL unchanged."""
        backend = AsyncMock()
        backend.ttl.return_value = 12.5
        with patch("oldman.cache.utils.redis_cache", backend):
            result = await get_cache_expiration("user", 7)
        self.assertEqual(12.5, result)
        backend.ttl.assert_awaited_once_with("user_7")

    async def test_delete_cache_uses_cache_delete(self) -> None:
        """delete_cache must delete one exact helper key."""
        backend = AsyncMock()
        with patch("oldman.cache.utils.redis_cache", backend):
            result = await delete_cache("user", 7)
        self.assertIsNone(result)
        backend.delete.assert_awaited_once_with("user_7")

    async def test_delete_cache_many_uses_safe_pattern_delete(self) -> None:
        """delete_cache_many must use the backend's SCAN-based pattern deletion."""
        backend = AsyncMock()
        backend.delete_match.return_value = 3
        with patch("oldman.cache.utils.redis_cache", backend):
            result = await delete_cache_many("user", 7)
        self.assertEqual(3, result)
        backend.delete_match.assert_awaited_once_with("user_7*")

    async def test_direct_helper_cache_failure_propagates(self) -> None:
        """Direct helpers must expose backend failures to their callers."""
        error = ConnectionError("offline")
        backend = AsyncMock()
        backend.get.side_effect = error
        with (
            patch("oldman.cache.utils.redis_cache", backend),
            self.assertRaises(ConnectionError) as caught,
        ):
            await get_cache("user", 7)
        self.assertIs(error, caught.exception)


class CacheAsyncResponseTest(unittest.IsolatedAsyncioTestCase):
    """Preserve the generic async-function Cache helper behavior."""

    async def test_hit_does_not_execute_wrapped_function(self) -> None:
        """A hit must return immediately."""
        backend = AsyncMock()
        backend.get.return_value = "cached"
        calls = 0

        @cache_async_response(prefix="report")
        async def build(item_id: int, *, active: bool) -> str:
            """Build a value only on misses."""
            nonlocal calls
            calls += 1
            return "fresh"

        with patch("oldman.cache.utils.redis_cache", backend):
            result = await build(7, active=True)
        self.assertEqual("cached", result)
        self.assertEqual(0, calls)
        backend.get.assert_awaited_once_with("report_build_7_active_True")

    async def test_miss_executes_once_and_caches_result(self) -> None:
        """A miss must write the generated value once."""
        backend = AsyncMock()
        backend.get.return_value = None
        calls = 0

        @cache_async_response(timeout=30, prefix="report")
        async def build(item_id: int, *, active: bool) -> str:
            """Build a value only on misses."""
            nonlocal calls
            calls += 1
            return "fresh"

        with patch("oldman.cache.utils.redis_cache", backend):
            result = await build(7, active=True)
        self.assertEqual("fresh", result)
        self.assertEqual(1, calls)
        backend.set.assert_awaited_once_with("report_build_7_active_True", "fresh", ttl=30)

    async def test_failures_are_fail_open(self) -> None:
        """Backend read and write failures must not duplicate execution."""
        backend = AsyncMock()
        backend.get.side_effect = ConnectionError("offline")
        backend.set.side_effect = ConnectionError("offline")
        calls = 0

        @cache_async_response(timeout=30, prefix="report")
        async def build(item_id: int) -> str:
            """Build the fallback value."""
            nonlocal calls
            calls += 1
            return "fresh"

        logger = Mock()
        with (
            patch("oldman.cache.utils.redis_cache", backend),
            patch("oldman.cache.utils.logger", logger),
        ):
            result = await build(7)
        self.assertEqual("fresh", result)
        self.assertEqual(1, calls)
        self.assertEqual(2, logger.warning.call_count)


class RemovedCacheHelperTest(unittest.TestCase):
    """Ensure removed compatibility helpers stay absent."""

    def test_lock_sync_and_legacy_decorator_helpers_are_not_exposed(self) -> None:
        """The module must not reintroduce removed or misleading helpers."""
        for name in (
            "cache",
            "cache_sync_response",
            "get_db_lock",
            "get_db_lock_ttl",
            "is_db_lock",
            "set_api_cache_lock",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(cache_utils, name))


if __name__ == "__main__":
    unittest.main()
