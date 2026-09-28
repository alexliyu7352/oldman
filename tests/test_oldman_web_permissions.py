"""Permission checks: superusers hold everything, others what the roles in their login grant."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError
from sanic.exceptions import ServiceUnavailable

import oldman.conf as conf
from oldman.auth import Permission, PermissionSet
from oldman.conf.schemas import DefaultSettings
from oldman.web.auth import has_perm, require_perm, role_ids_for_login, session_data_for_user
from oldman.web.authentication import (
    ANONYMOUS_USER,
    RequestUser,
    issue_access_token,
    read_access_token,
    user_from_access_token,
    user_from_session,
)
from oldman.web.exceptions import Forbidden
from oldman.web.session import SessionData

STORE = "oldman.apps.roles.store.role_permissions"
SECRET = "permissions-test-secret-0123456789abcdef"


class Reports(PermissionSet, namespace="web_perm_reports"):
    view = Permission("View reports")
    export = Permission("Export reports")


def request_for(user: Any, *, roles_installed: bool = True) -> Any:
    registry = SimpleNamespace(labels=("auth", "roles") if roles_installed else ("auth",))
    return SimpleNamespace(ctx=SimpleNamespace(user=user), app=SimpleNamespace(ctx=SimpleNamespace(app_registry=registry)))


def staff(*role_ids: int) -> RequestUser:
    return RequestUser(id=7, username="ops", is_staff=True, role_ids=role_ids)


class HasPermTest(unittest.TestCase):
    def check(self, request: Any, permission: Permission) -> bool:
        return asyncio.run(has_perm(request, permission))

    def test_a_role_grants_what_it_lists_and_nothing_else(self) -> None:
        request = request_for(staff(3))
        with patch(STORE, AsyncMock(return_value=frozenset({"web_perm_reports.view"}))) as store:
            self.assertTrue(self.check(request, Reports.view))
            self.assertFalse(self.check(request, Reports.export))
        # The roles are looked up once per request, through the process's database unless one is given.
        store.assert_awaited_once_with((3,), db_manager=None)

    def test_a_superuser_holds_every_permission_without_a_lookup(self) -> None:
        with patch(STORE, AsyncMock()) as store:
            self.assertTrue(self.check(request_for(RequestUser(id=1, username="root", is_staff=True, is_superuser=True)), Reports.export))
        store.assert_not_awaited()

    def test_no_roles_and_no_user_mean_no_permission_and_no_lookup(self) -> None:
        with patch(STORE, AsyncMock()) as store:
            self.assertFalse(self.check(request_for(staff()), Reports.view))
            self.assertFalse(self.check(request_for(ANONYMOUS_USER), Reports.view))
        store.assert_not_awaited()

    def test_a_service_without_the_roles_app_grants_nothing_through_roles(self) -> None:
        # A login opened by another service sharing the session may carry role ids; this one has no roles to read.
        with patch(STORE, AsyncMock(return_value=frozenset({"web_perm_reports.view"}))) as store:
            self.assertFalse(self.check(request_for(staff(3), roles_installed=False), Reports.view))
        store.assert_not_awaited()

    def test_an_unreachable_store_is_503_rather_than_a_refusal(self) -> None:
        with patch(STORE, AsyncMock(side_effect=RedisConnectionError("down"))), self.assertRaises(ServiceUnavailable):
            self.check(request_for(staff(3)), Reports.view)

    def test_only_declared_permission_objects_are_checked(self) -> None:
        for permission in ("web_perm_reports.view", Permission("Loose")):
            with self.subTest(permission=permission), self.assertRaises(TypeError):
                self.check(request_for(staff(3)), permission)  # type: ignore[arg-type]

    def test_require_perm_refuses_with_403(self) -> None:
        with patch(STORE, AsyncMock(return_value=frozenset())), self.assertRaises(Forbidden):
            asyncio.run(require_perm(request_for(staff(3)), Reports.view))


class LoginRolesTest(unittest.TestCase):
    def test_roles_are_read_at_login_only_when_the_roles_app_is_installed(self) -> None:
        without = SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace(app_registry=SimpleNamespace(labels=("auth",)))))
        installed = SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace(app_registry=SimpleNamespace(labels=("auth", "roles")))))
        with patch("oldman.apps.roles.store.user_role_ids", AsyncMock(return_value=(2, 5))) as lookup:
            self.assertEqual((), asyncio.run(role_ids_for_login(without, 7)))
            lookup.assert_not_awaited()
            self.assertEqual((2, 5), asyncio.run(role_ids_for_login(installed, 7)))
        lookup.assert_awaited_once_with(7, db_manager=None)

    def test_a_session_carries_the_roles_it_was_opened_with(self) -> None:
        user = SimpleNamespace(id=7, username="ops", display_name="", is_active=True, is_staff=True, is_superuser=False)
        with patch("oldman.web.auth.session.user_identity", return_value=7):
            session = session_data_for_user(SessionData, user, role_ids=(2, 5))
        self.assertEqual((2, 5), session.role_ids)
        self.assertEqual((2, 5), user_from_session(session).role_ids)


class TokenRolesTest(unittest.TestCase):
    def setUp(self) -> None:
        settings = DefaultSettings()
        settings.web.auth.jwt.secret = SECRET
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.user = SimpleNamespace(id=7, username="ops", display_name="", is_active=True, is_staff=True, is_superuser=False)

    def test_an_access_token_carries_the_roles_as_a_session_does(self) -> None:
        token = issue_access_token(self.user, role_ids=[5, 2, 5]).token
        claims = read_access_token(token)
        assert claims is not None
        self.assertEqual([2, 5], claims["roles"])
        self.assertEqual((2, 5), user_from_access_token(claims).role_ids)

    def test_a_token_without_a_valid_roles_claim_is_refused(self) -> None:
        from oldman.security.jwt import jwt_encode

        claims = dict(issue_access_token(self.user).claims)
        for roles in (None, "2", [2, "5"], [True]):
            with self.subTest(roles=roles):
                forged = {**claims, "roles": roles} if roles is not None else {key: value for key, value in claims.items() if key != "roles"}
                token = jwt_encode(forged, SECRET, algorithm="HS256")
                self.assertIsNone(read_access_token(token))


if __name__ == "__main__":
    unittest.main()
