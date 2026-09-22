"""Reset and close are the high-traffic path; pin what happens when the close fails."""

from __future__ import annotations

import gc
import unittest
import weakref
from unittest.mock import patch

from oldman.contrib.http.multi_client import MultiHttpClient
from oldman.contrib.http.schemas import ClientType


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


if __name__ == "__main__":
    unittest.main()
