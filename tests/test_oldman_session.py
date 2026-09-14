"""Pure behavior tests for the typed Session extension boundary."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, assert_type, cast
from unittest.mock import AsyncMock, patch

import msgspec
from sanic import Request, Sanic
from sanic.response import BaseHTTPResponse, empty

import oldman.conf as conf
from oldman.conf.schemas import DefaultSettings, SessionConfig, WebConfig
from oldman.web.session import DefaultSessionInterface, Session, SessionData, get_session_data


class AdminSessionData(SessionData, kw_only=True):
    """Application-specific session model used to verify static typing."""

    account_label: str = ""


class OtherSessionData(SessionData, kw_only=True):
    """Distinct model used to verify runtime mismatch detection."""

    label: str = ""


class FakeApp:
    """Record extension registrations without starting a Sanic server."""

    def __init__(self) -> None:
        self.ctx = SimpleNamespace()
        self.middlewares: list[tuple[Any, str, int | None]] = []
        self.listeners: list[tuple[Any, str]] = []

    def register_middleware(self, middleware: Any, location: str, priority: int | None = None) -> None:
        """Record one middleware registration."""
        self.middlewares.append((middleware, location, priority))

    def register_listener(self, listener: Any, event: str) -> None:
        """Record one listener registration."""
        self.listeners.append((listener, event))


class SessionPublicBehaviorTest(unittest.IsolatedAsyncioTestCase):
    """Verify public typing and installation without opening Redis."""

    def test_session_data_authentication_properties(self) -> None:
        """Base identity fields expose consistent authenticated/anonymous states."""
        anonymous = AdminSessionData()
        authenticated = AdminSessionData(
            user_id=1,
            username="alice",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        self.assertTrue(anonymous.is_anonymous)
        self.assertFalse(anonymous.is_authenticated())
        self.assertEqual("", anonymous.username)
        self.assertEqual("", anonymous.display_name)
        self.assertEqual("", anonymous.login_ip)
        self.assertEqual(0, anonymous.login_time)
        self.assertFalse(anonymous.is_staff)
        self.assertFalse(anonymous.is_superuser)
        self.assertFalse(authenticated.is_anonymous)
        self.assertTrue(authenticated.is_authenticated())
        self.assertEqual("alice", authenticated.username)
        self.assertTrue(authenticated.is_staff)
        self.assertTrue(authenticated.is_superuser)

        for user_id in (0, -1):
            with self.subTest(user_id=user_id):
                value = AdminSessionData(user_id=user_id, is_active=True)
                restored = msgspec.msgpack.decode(value.to_msgpack(), type=AdminSessionData)
                self.assertEqual(user_id, restored.user_id)
                self.assertTrue(restored.is_authenticated())
                self.assertFalse(restored.is_anonymous)

        invalid = msgspec.msgpack.encode({"user_id": "1", "is_active": True})
        with self.assertRaises(msgspec.ValidationError):
            msgspec.msgpack.decode(invalid, type=AdminSessionData)

    def test_generic_accessor_preserves_subclass_type_and_checks_runtime_model(self) -> None:
        """The helper gives static analyzers the configured application model."""
        interface = DefaultSessionInterface(session_model=AdminSessionData)
        manager = Session()
        manager.interface = interface
        value = AdminSessionData(
            user_id=1,
            username="alice",
            is_active=True,
            is_staff=True,
        )
        request = cast(
            Request,
            SimpleNamespace(
                app=SimpleNamespace(ctx=SimpleNamespace(session=manager)),
                ctx=SimpleNamespace(session=value),
            ),
        )

        typed = get_session_data(request, AdminSessionData)
        assert_type(typed, AdminSessionData)
        self.assertIs(typed, value)
        self.assertTrue(typed.is_staff)
        with self.assertRaisesRegex(TypeError, "OtherSessionData"):
            get_session_data(request, OtherSessionData)

    def test_accessor_reports_uninitialized_request(self) -> None:
        """Missing request middleware state is not converted into an anonymous model."""
        manager = Session()
        manager.interface = DefaultSessionInterface(session_model=AdminSessionData)
        request = cast(
            Request,
            SimpleNamespace(
                app=SimpleNamespace(ctx=SimpleNamespace(session=manager)),
                ctx=SimpleNamespace(),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "middleware has not initialized"):
            get_session_data(request, AdminSessionData)

        with self.assertRaisesRegex(RuntimeError, "middleware has not initialized"):
            manager.get_session_id(request)

    def test_interface_class_is_instantiated_without_redis_lifecycle_listeners(self) -> None:
        """Installation accepts an interface class without owning provider lifecycle."""
        app = FakeApp()
        manager = Session(cast(Sanic, app), DefaultSessionInterface)

        self.assertIsInstance(manager.interface, DefaultSessionInterface)
        self.assertEqual(["REQUEST", "RESPONSE"], [location for _handler, location, _priority in app.middlewares])
        self.assertEqual([], app.listeners)

    def test_default_install_builds_the_typed_interface_from_session_settings(self) -> None:
        """The extension owns settings-to-interface mapping and remains Redis-lazy."""
        app = FakeApp()
        manager = Session()
        session_config = SessionConfig(
            enabled=True,
            redis_alias="ADMIN_SESSION",
            expiry=120,
            prefix="admin-session:",
            user_prefix="admin-user-session:",
            cookie_name="admin_session_id",
            cookie_domain="example.test",
            cookie_httponly=False,
            cookie_secure=True,
            cookie_samesite="Strict",
        )
        settings = DefaultSettings.model_validate(
            {"web": WebConfig(session=session_config).model_dump()}
        )

        with patch.dict(conf.__dict__, {"settings": settings}):
            manager.init_app(cast(Sanic, app), session_model=AdminSessionData)

        interface = manager.interface
        self.assertIsInstance(interface, DefaultSessionInterface)
        assert interface is not None
        self.assertEqual("ADMIN_SESSION", interface.redis_alias)
        self.assertEqual(120, interface.expiry)
        self.assertEqual("admin-session:", interface.prefix)
        self.assertEqual("admin-user-session:", interface.user_prefix)
        self.assertEqual("admin_session_id", interface.cookie_name)
        self.assertEqual("example.test", interface.domain)
        self.assertFalse(interface.httponly)
        self.assertTrue(interface.secure)
        self.assertEqual("Strict", interface.samesite)
        self.assertIs(AdminSessionData, interface.session_model)
        self.assertIs(manager, app.ctx.session)
        self.assertEqual([], app.listeners)

    async def test_manager_methods_fail_before_init_app(self) -> None:
        """Using an uninstalled manager returns one explicit lifecycle error."""
        manager = Session()

        with self.assertRaisesRegex(RuntimeError, "Session.init_app"):
            await manager.login(AdminSessionData(user_id=1, is_active=True))

    async def test_request_and_response_middleware_propagate_cancellation(self) -> None:
        """Request cancellation is never converted into an HTTP error response."""
        app = FakeApp()
        interface = DefaultSessionInterface(session_model=AdminSessionData)
        Session(cast(Sanic, app), interface)
        request_middleware = app.middlewares[0][0]
        response_middleware = app.middlewares[1][0]
        request = cast(Request, SimpleNamespace())
        response = cast(BaseHTTPResponse, empty())

        with patch.object(interface, "open", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await request_middleware(request)
        with patch.object(interface, "save", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await response_middleware(request, response)


if __name__ == "__main__":
    unittest.main()
