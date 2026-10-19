"""Reset and close are the high-traffic path; pin what happens when the close fails."""

from __future__ import annotations

import asyncio
import gc
import unittest
import weakref
from collections.abc import AsyncIterator
from unittest.mock import patch

from oldman.contrib.http.multi_client import MultiHttpClient
from oldman.contrib.http.schemas import ClientType, HttpMethod
from tests.raw_http_origin import RawOrigin, response_head


def session_of(backend: object) -> object | None:
    """Return a backend's live session through the attribute it declares."""
    return getattr(backend, backend.session_attribute, None)  # type: ignore[attr-defined]


class BackendLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Every backend goes through one template now, so every backend is checked."""

    async def build(self, client_type: ClientType) -> MultiHttpClient:
        """Build a client whose backend already holds a live session."""
        client = MultiHttpClient(client_type, retry_count=0)
        await client.init_client()
        await client.client.get_client()
        self.assertIsNotNone(session_of(client.client), "the backend should hold a session")
        return client

    async def test_a_failed_close_keeps_both_sides_able_to_retry(self) -> None:
        """Dropping the reference while the session lives is how a connection leaks."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = await self.build(client_type)
                backend = client.client

                with patch.object(backend, "close_session", side_effect=RuntimeError("boom")):
                    released = await client.close_client()

                self.assertFalse(released, "a failed close must report itself")
                self.assertIs(backend, client._impl, "the backend reference must survive")
                self.assertIsNotNone(session_of(backend), "the session must survive so it can be closed")

                # 第二次关闭恢复正常，两边都释放。
                self.assertTrue(await client.close_client())
                self.assertIsNone(client._impl)
                self.assertIsNone(session_of(backend))

    async def test_close_never_raises_an_ordinary_exception(self) -> None:
        """Callers are business shutdown paths; they must not be forced to catch."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = await self.build(client_type)
                with patch.object(client.client, "close_session", side_effect=ValueError("broken")):
                    self.assertFalse(await client.close_client())
                await client.close_client()

    async def test_closing_twice_and_closing_unused_clients_is_harmless(self) -> None:
        """Shutdown paths call close more than once; it stays idempotent."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(client_type, retry_count=0)
                await client.init_client()
                self.assertTrue(await client.close_client())
                self.assertTrue(await client.close_client())

    async def test_reset_replaces_the_session_without_leaking_the_old_one(self) -> None:
        """check_health resets on repeated timeouts and on a timer; the old sessions must go."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = await self.build(client_type)
                backend = client.client
                seen: list[weakref.ref[object]] = []
                session: object | None = None
                try:
                    for _ in range(3):
                        session = session_of(backend)
                        assert session is not None
                        try:
                            seen.append(weakref.ref(session))
                        except TypeError:  # pragma: no cover - not every session is weak-referenceable
                            pass
                        self.assertTrue(await backend.reset_client())
                        self.assertIsNone(session_of(backend), "reset must drop the session")
                        await backend.get_client()
                        self.assertIsNotNone(session_of(backend))
                finally:
                    await client.close_client()

                del session
                gc.collect()
                alive = [ref for ref in seen if ref() is not None]
                self.assertEqual([], alive, f"{len(alive)} session(s) survived their reset")

    async def test_a_failed_reset_still_discards_the_session(self) -> None:
        """Reset means discard; close means keep. A failed close must not blur the two."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = await self.build(client_type)
                backend = client.client
                doomed = session_of(backend)

                with patch.object(backend, "close_session", side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError, msg="a failed reset must report itself"):
                        await backend.reset_client()

                self.assertIsNone(session_of(backend), "a failed reset must still drop the session")

                # 关键在下一次请求：拿到的必须是新会话，而不是那个关不掉的旧会话。
                # MultiHttpClient 捕获这次异常后只记日志、设冷却，不会替你换掉会话。
                await backend.get_client()
                self.assertIsNot(doomed, session_of(backend), "the next request must not reuse the dead session")

                # 被丢弃的会话确实没人再关它——这就是本改动接受的代价，这里替它收尾，
                # 免得测试输出里出现 "Unclosed client session"。
                await backend.close_session(doomed)
                await client.close_client()

    async def test_backends_declare_where_their_session_lives(self) -> None:
        """The template manages the session through these two declarations."""
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(client_type, retry_count=0)
                await client.init_client()
                backend = client.client
                self.assertTrue(backend.session_attribute, "session_attribute must be declared")
                self.assertTrue(hasattr(backend, backend.session_attribute))
                self.assertNotEqual("HTTP", backend.backend_label, "label should name the backend")
                await client.close_client()


class ClosedClientStreamTest(unittest.IsolatedAsyncioTestCase):
    """A stream still reading when its client closes, and a stream whose release is cancelled."""

    async def test_a_stream_still_reading_after_close_builds_no_new_session(self) -> None:
        """Resuming on a backend its owner has closed fails instead of opening a session nobody will close."""

        body = bytes(range(256)) * 400
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                cut = asyncio.Event()

                async def answer(attempt: int, headers: dict[str, str], cut: asyncio.Event = cut) -> AsyncIterator[bytes]:
                    yield response_head("200 OK", {"Content-Length": len(body), "Accept-Ranges": "bytes"}) + body[:30000]
                    await cut.wait()

                origin = RawOrigin(answer)
                client = MultiHttpClient(client_type, retry_count=3, retry_backoff_factor=0, connect_timeout=3, read_timeout=3)
                await client.init_client()
                async with origin.serve() as base_url:
                    with self.assertRaises(RuntimeError):
                        async with client.reconnect_stream(HttpMethod.GET, f"{base_url}/file") as stream:
                            backend = stream.client
                            pieces = stream.aiter_bytes(8192)
                            await anext(pieces)
                            self.assertTrue(await client.close_client())
                            cut.set()
                            async for _ in pieces:
                                pass
                self.assertIsNone(session_of(backend), "no session may be left on a backend its owner dropped")
                self.assertEqual(1, len(origin.requests))

    async def test_a_release_cancelled_halfway_still_ends_the_active_request(self) -> None:
        """active_requests is what reset waits for; a cancel during release must not leave it counting one."""

        body = b"x" * 1000
        origin = RawOrigin(lambda attempt, headers: response_head("200 OK", {"Content-Length": len(body)}) + body)
        client = MultiHttpClient(ClientType.AIOHTTP, retry_count=0, connect_timeout=3, read_timeout=3)
        await client.init_client()
        releasing = asyncio.Event()

        async def use() -> None:
            async with client.reconnect_stream(HttpMethod.GET, f"{base_url}/file") as stream:
                release = stream.release_response

                async def slow_release() -> None:
                    releasing.set()
                    try:
                        await asyncio.sleep(1)
                    finally:
                        # The cancellation lands in the sleep; the response is still released, then the cancel goes on.
                        await release()

                stream.release_response = slow_release  # type: ignore[method-assign]

        try:
            async with origin.serve() as base_url:
                task = asyncio.ensure_future(use())
                await releasing.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        finally:
            await client.close_client()
        self.assertEqual(0, client.active_requests)

    async def test_a_client_whose_close_failed_keeps_working(self) -> None:
        """A close that reports failure keeps the backend and its session: the client stays usable until closed again."""

        origin = RawOrigin(lambda attempt, headers: response_head("200 OK", {"Content-Length": 2}) + b"ok")
        for client_type in ClientType:
            with self.subTest(client_type=client_type):
                client = MultiHttpClient(client_type, retry_count=0, connect_timeout=3, read_timeout=3)
                await client.init_client()
                async with origin.serve() as base_url:
                    await client.get(f"{base_url}/warm")
                    with patch.object(client.client, "close_session", side_effect=RuntimeError("boom")):
                        self.assertFalse(await client.close_client())
                    response = await client.get(f"{base_url}/after")
                self.assertEqual(b"ok", response.content)
                self.assertTrue(await client.close_client())


class ExitCleanupTest(unittest.TestCase):
    """The interpreter-exit hook runs its own event loop, so it is called outside one here."""

    def test_only_clients_still_holding_a_backend_are_closed_and_reported(self) -> None:
        """A client that never opened was reported too, as a log line on stdout after a script's own output."""
        self.addCleanup(asyncio.set_event_loop, None)
        unused = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        opened = MultiHttpClient(ClientType.HTTPX, retry_count=0)
        asyncio.run(opened.init_client())

        with (
            patch.object(MultiHttpClient, "_instances", weakref.WeakSet([unused])),
            patch("oldman.contrib.http.multi_client.logger") as logger,
        ):
            MultiHttpClient._cleanup_all_instances()
        logger.info.assert_not_called()

        with (
            patch.object(MultiHttpClient, "_instances", weakref.WeakSet([unused, opened])),
            patch("oldman.contrib.http.multi_client.logger") as logger,
        ):
            MultiHttpClient._cleanup_all_instances()
        logger.info.assert_any_call("程序退出时清理 1 个HTTP客户端实例")
        self.assertIsNone(opened._impl)


if __name__ == "__main__":
    unittest.main()
