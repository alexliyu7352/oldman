"""NATS provider ownership and source-alignment tests."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import types
import unittest
from pathlib import Path
from typing import Any, cast

from oldman.serializers import MsgspecModel

ROOT = Path(__file__).resolve().parents[1]


class Ping(MsgspecModel):
    """Minimal typed payload used by the serializer contract."""

    message: str


class OldmanNatsTest(unittest.TestCase):
    """Verify the concrete NATS provider without requiring a live server."""

    def test_addresses_options_and_injection_signature(self) -> None:
        """Validate public boundaries without connecting or replacing the native DI."""
        from oldman.providers.nats import NATSConnection

        connection = NATSConnection(namespace="My_App", peer_id="worker-1", reconnect_time_wait=0.1)
        self.assertEqual(0.1, connection.broker._connection_kwargs["reconnect_time_wait"])
        self.assertEqual("oldman.bus.My_App.shared.", connection._prefix())
        self.assertEqual("oldman.bus.My_App.peer.worker-2.", connection._prefix("worker-2"))
        headers = {"x-nats-peer-id": "forged", "custom": "kept"}
        self.assertEqual({"x-nats-peer-id": "worker-1", "custom": "kept"}, connection._headers(headers))
        self.assertEqual("forged", headers["x-nats-peer-id"])
        self.assertEqual({"custom": "kept"}, NATSConnection(namespace="test")._headers(headers))
        for value in ("", " ", "a.b", "*", "中文"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                NATSConnection(namespace=value)
        for subject in ("", ".abc", "a..b", "a b", "a.>.b", "a*b", "a\x00b"):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                connection.subscriber(subject)
        for subject in ("status.*", "status.>"):
            with self.assertRaises(ValueError):
                connection.publisher(subject)

        @connection.subscriber("服务器.{server_id}.>")
        async def handler(message: Ping, default: int = 1, *, peer_id: str) -> Ping:
            """Exercise keyword-only source injection after a default-valued argument."""
            return message

        signature = inspect.signature(handler._original_call)
        self.assertNotIn("peer_id", signature.parameters)
        self.assertEqual(inspect.Parameter.KEYWORD_ONLY, signature.parameters["nats_msg"].kind)
        self.assertEqual(1, signature.parameters["default"].default)
        self.assertIs(Ping, signature.return_annotation)

    def test_close_fix_is_instance_scoped_and_does_not_stack(self) -> None:
        """Repeated installation leaves other clients and normal send methods intact."""
        from nats.aio.client import Client

        from oldman.providers.nats._compat import install_close_fix, install_request_fix

        original = Client._close
        managed, unrelated = Client(), Client()
        install_close_fix(managed)
        first = managed._close
        install_close_fix(managed)

        self.assertEqual(first, managed._close)
        self.assertIs(Client._close, original)
        self.assertEqual(original.__get__(unrelated, Client), unrelated._close)
        self.assertEqual(Client.publish.__get__(managed, Client), managed.publish)
        original_request = Client._request_new_style
        self.assertEqual(original_request.__get__(managed, Client), managed._request_new_style)
        install_request_fix(managed)
        self.assertIs(Client._request_new_style, original_request)
        self.assertEqual(original_request.__get__(unrelated, Client), unrelated._request_new_style)

    def test_provider_does_not_depend_on_web_admin_or_tasks(self) -> None:
        """Keep the external provider independent from higher-level policies."""
        for path in sorted((ROOT / "oldman" / "providers" / "nats").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("oldman.web", source, path.as_posix())
            self.assertNotIn("oldman.admin", source, path.as_posix())
            self.assertNotIn("oldman.tasks", source, path.as_posix())

    def test_empty_messaging_facade_is_removed(self) -> None:
        """Do not retain a source-only namespace that disappears from the wheel."""
        self.assertFalse((ROOT / "oldman" / "messaging").exists())
        self.assertIsNone(importlib.util.find_spec("oldman.messaging"))

    def test_package_aggregates_canonical_implementations(self) -> None:
        """Expose one concrete class and one implementation of each serializer."""
        from oldman.providers.nats import (
            MsgpackNatsSerializer as PublicMsgpackNatsSerializer,
        )
        from oldman.providers.nats import (
            MsgspecJsonNatsSerializer as PublicMsgspecJsonNatsSerializer,
        )
        from oldman.providers.nats import NATSConnection as PublicNATSConnection
        from oldman.providers.nats.connection import NATSConnection
        from oldman.providers.nats.serializers import (
            MsgpackNatsSerializer,
            MsgspecJsonNatsSerializer,
        )

        payload = MsgpackNatsSerializer.encode(Ping(message="pong"))
        decoded = Ping.from_msgpack(payload)

        self.assertIs(PublicNATSConnection, NATSConnection)
        self.assertIs(PublicMsgpackNatsSerializer, MsgpackNatsSerializer)
        self.assertIs(PublicMsgspecJsonNatsSerializer, MsgspecJsonNatsSerializer)
        self.assertEqual("pong", decoded.message)

    def test_connection_init_has_no_network_or_handler_side_effects(self) -> None:
        """Construct peer helpers without connecting or owning logging sinks."""
        from oldman.providers.nats import NATSConnection

        logger = logging.getLogger("default.Edge Node-01.nats")
        original_handlers = logger.handlers.copy()
        original_level = logger.level
        original_propagate = logger.propagate
        sentinel = logging.NullHandler()
        logger.handlers = [sentinel]
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        try:
            connection = NATSConnection(name="Edge Node-01")
            fake_message = types.SimpleNamespace(
                raw_message=types.SimpleNamespace(
                    headers={NATSConnection._PEER_ID_HEADER: "controller"},
                ),
            )

            self.assertIsNone(connection.namespace)
            self.assertFalse(hasattr(connection, "prefix"))
            self.assertFalse(connection.connection_info["is_connected"])
            self.assertEqual(
                "controller",
                NATSConnection.peer_id(cast(Any, fake_message)),
            )
            self.assertIs(logger, connection._logger)
            self.assertEqual([sentinel], connection._logger.handlers)
            self.assertEqual(logging.WARNING, connection._logger.level)
            self.assertFalse(connection._logger.propagate)
        finally:
            logger.handlers = original_handlers
            logger.setLevel(original_level)
            logger.propagate = original_propagate


if __name__ == "__main__":
    unittest.main()
