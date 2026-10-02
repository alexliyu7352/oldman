"""Login backends: the credential checks sign-in and token issuing go through."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import oldman.conf as conf
from oldman.auth.backends import UserTableBackend, authenticate_with, resolve_login_backends
from oldman.conf.schemas import DefaultSettings

SIGNED_IN = SimpleNamespace(id=5, username="device", is_active=True)


class DeviceTokenBackend:
    """A project backend that signs in by a one-field token, not a username and password."""

    name = "device_token"

    async def authenticate(self, request: Any, *, token: Any = None, **credentials: Any) -> Any:
        del request, credentials
        return SIGNED_IN if token == "good" else None


class DisabledAccountBackend:
    """A project backend that vouches for an account someone has since disabled."""

    name = "disabled_account"

    async def authenticate(self, request: Any, *, token: Any = None, **credentials: Any) -> Any:
        del request, credentials
        return SimpleNamespace(id=6, username="former", is_active=False) if token == "good" else None


class NotABackend:
    pass


class UserTableBackendTest(unittest.TestCase):
    def test_it_checks_a_username_and_password_against_the_user_table(self) -> None:
        user = SimpleNamespace(id=1)
        with patch("oldman.auth.backends.authenticate_user", AsyncMock(return_value=user)) as check:
            result = asyncio.run(
                UserTableBackend().authenticate(None, username="alice", password="pw", auth_settings="settings", db_manager="db")
            )
        self.assertIs(user, result)
        check.assert_awaited_once_with("alice", "pw", auth_settings="settings", db_manager="db")

    def test_a_credential_it_does_not_understand_is_not_its_to_answer(self) -> None:
        with patch("oldman.auth.backends.authenticate_user", AsyncMock()) as check:
            self.assertIsNone(asyncio.run(UserTableBackend().authenticate(None, token="good")))
        check.assert_not_awaited()


class ResolveLoginBackendsTest(unittest.TestCase):
    def test_the_user_table_is_built_in_and_project_backends_are_named_by_path(self) -> None:
        (users,) = resolve_login_backends(("users",))
        self.assertIsInstance(users, UserTableBackend)
        (device,) = resolve_login_backends((f"{__name__}.DeviceTokenBackend",))
        self.assertIsInstance(device, DeviceTokenBackend)

    def test_configuration_mistakes_are_refused(self) -> None:
        for names, error in ((("users", "users"), ValueError), (("ldap",), ValueError), ((f"{__name__}.NotABackend",), TypeError)):
            with self.subTest(names=names), self.assertRaises(error):
                resolve_login_backends(names)


class AuthenticateCredentialsTest(unittest.TestCase):
    def test_the_first_backend_to_accept_the_credential_decides(self) -> None:
        backends = (UserTableBackend(), DeviceTokenBackend())
        with patch("oldman.auth.backends.authenticate_user", AsyncMock(return_value=None)):
            self.assertIs(SIGNED_IN, asyncio.run(authenticate_with(backends, None, token="good")))
            self.assertIsNone(asyncio.run(authenticate_with(backends, None, token="bad")))

    def test_the_web_entry_asks_the_configured_backends(self) -> None:
        from oldman.web.auth import authenticate_credentials

        settings = DefaultSettings()
        settings.web.auth.login_backends = [f"{__name__}.DeviceTokenBackend"]
        with patch.dict(conf.__dict__, {"settings": settings}):
            self.assertIs(SIGNED_IN, asyncio.run(authenticate_credentials(SimpleNamespace(), token="good")))

    def test_a_disabled_account_never_signs_in_whichever_backend_vouched_for_it(self) -> None:
        """Being active is the floor of every login; a project backend may still return a disabled account."""
        from oldman.web.auth import authenticate_credentials

        settings = DefaultSettings()
        settings.web.auth.login_backends = [f"{__name__}.DisabledAccountBackend"]
        with patch.dict(conf.__dict__, {"settings": settings}):
            self.assertIsNone(asyncio.run(authenticate_credentials(SimpleNamespace(), token="good")))

    def test_the_default_is_the_user_table(self) -> None:
        self.assertEqual(["users"], DefaultSettings().web.auth.login_backends)


if __name__ == "__main__":
    unittest.main()
