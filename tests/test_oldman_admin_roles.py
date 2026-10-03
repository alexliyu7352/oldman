"""Admin role management: roles edited with the shared RoleForm, each save or delete refreshing the role's cache key."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError
from sanic.exceptions import ServiceUnavailable
from sqlalchemy.schema import Table
from sqlmodel import select

import oldman.conf as conf
from oldman.apps import AppNotInstalledError
from oldman.apps.admin.roles import RoleModelAdmin
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.site import AdminSite
from oldman.apps.roles.forms import RoleForm, permission_choices
from oldman.apps.roles.models import Role, UserRole
from oldman.auth import Permission, PermissionSet
from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig, DefaultSettings
from oldman.db.session import DatabaseManager
from oldman.providers.redis import RedisClientRegistry
from oldman.web.auth.forms import user_edit_form_class
from oldman.web.components.forms import SanicFormData
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server
from tests.test_oldman_admin_runtime import (
    USER_MANAGEMENT,
    FakeApp,
    FakeSession,
    grants,
    install_admin,
    make_request,
    render_with_request_environment,
)

ROLES_PATH = "/control/oldman_role"
USER_EDIT_PATH = "/control/oldman_user/<object_id>/edit"


class RoleAdminPermissions(PermissionSet, namespace="role_admin_test"):
    view = Permission("View reports")
    export = Permission("Export reports")


class TwinPermissions(PermissionSet, namespace="role_admin_twin"):
    approve = Permission("Approve reports")


class FakeRegistry:
    """The App registry surface the Admin and the role form read."""

    def __init__(self, labels: tuple[str, ...] = ("auth", "admin", "roles", "role_admin_test")) -> None:
        self.labels = labels

    def get_model_metadata(self, model: type[Any]) -> None:
        del model

    def get_by_package(self, package: str) -> Any:
        raise AppNotInstalledError(package)

    def get_by_label(self, label: str) -> Any:
        if label == "role_admin_test":
            return SimpleNamespace(display_name="Reports")
        raise AppNotInstalledError(label)


def superuser_session() -> FakeSession:
    return FakeSession(user_id=1, is_active=True, is_staff=True, is_superuser=True)


def staff_session() -> FakeSession:
    """A staff operator who is not a superuser; what their role grants is set with `grants`."""
    return FakeSession(user_id=2, is_active=True, is_staff=True, is_superuser=False, role_ids=(1,))


class RoleFormTest(unittest.TestCase):
    def test_permissions_are_offered_grouped_by_the_app_that_declares_them(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace(app_registry=FakeRegistry())))
        choices = permission_choices(request)
        self.assertEqual(
            [("role_admin_test.export", RoleAdminPermissions.export.label), ("role_admin_test.view", RoleAdminPermissions.view.label)],
            choices["Reports"],
        )
        # Without a registry to ask, a group is named after its namespace.
        self.assertIn("role_admin_test", permission_choices(SimpleNamespace()))

    def test_two_apps_with_one_display_name_keep_both_groups(self) -> None:
        class SameNames(FakeRegistry):
            def get_by_label(self, label: str) -> Any:
                if label in {"role_admin_test", "role_admin_twin"}:
                    return SimpleNamespace(display_name="Reports")
                raise AppNotInstalledError(label)

        choices = permission_choices(SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace(app_registry=SameNames()))))
        self.assertIn("role_admin_test.view", [name for name, _label in choices["Reports"]])
        self.assertEqual(["role_admin_twin.approve"], [name for name, _label in choices["Reports (role_admin_twin)"]])


class AdminWithRolesCase(unittest.IsolatedAsyncioTestCase):
    """The Admin's own handlers against in-memory SQLite and a test-owned redis-server, roles App installed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "role-admin")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        settings = DefaultSettings()
        settings.core.namespace = "svc"
        settings.web.security.secret_key = "role-admin-test-root-secret-0123456789"
        settings.web.static.root = str(Path("oldman/apps/admin/static").resolve())
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.redis = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"SESSION": 5}))
        self.enterContext(patch("oldman.providers.redis.redis_client", self.redis))
        self.connection = await self.redis.using("SESSION").async_get_conn()
        await self.connection.flushdb()

        self.database = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        await self.database.initialize()
        async with self.database.engine.begin() as connection:
            for model in (User, Role, UserRole):
                await connection.run_sync(cast(Table, model.__table__).create)

        self.app = FakeApp()
        self.app.ctx.app_registry = FakeRegistry()
        self.site = AdminSite("role_admin_test")
        install_admin(self.app, db_manager=self.database, admin_site=self.site, admin_settings=AdminSettings(prefix="/control"))
        self.enterContext(patch("oldman.apps.admin.site.render_template", side_effect=render_with_request_environment))

    async def asyncTearDown(self) -> None:
        await self.database.close()
        await self.redis.close()

    def post(self, path: str, form: dict[str, Any], session: FakeSession | None = None) -> Any:
        request = make_request(self.app, path=path, session=session or superuser_session())
        request.method = "POST"
        request.headers = {"accept": "application/json", "Origin": "http://example.test"}
        request.form = {**form, "csrfmiddlewaretoken": self.app.ctx.csrf.generate_token(request)}
        return request

    async def call(self, path: str, methods: tuple[str, ...], request: Any, **kwargs: Any) -> Any:
        return await self.app.route_handlers[(path, methods)](request, **kwargs)  # type: ignore[operator]

    async def cached(self, role_id: int) -> Any:
        raw = await self.connection.get(f"svc:role:{role_id}")
        return None if raw is None else json.loads(raw)

    async def role_named(self, name: str) -> Role | None:
        async with self.database.get_read_session() as session:
            return (await session.exec(select(Role).where(Role.name == name))).one_or_none()


class RoleAdminTest(AdminWithRolesCase):
    async def test_the_admin_manages_roles_only_where_the_roles_app_is_installed(self) -> None:
        self.assertIsInstance(self.site.get_model_admin(Role), RoleModelAdmin)
        listed = await self.call(ROLES_PATH, ("GET",), make_request(self.app, path=ROLES_PATH, session=superuser_session()))
        self.assertEqual(200, listed.status)
        # Checkboxes grouped by App, from the permissions the service declares.
        response = await self.call(f"{ROLES_PATH}/new", ("GET",), make_request(self.app, path=f"{ROLES_PATH}/new", session=superuser_session()))
        self.assertEqual(200, response.status)
        self.assertIn(b"data-om-checkbox-group", response.body)
        self.assertIn(b'value="role_admin_test.export"', response.body)

        without_roles = FakeApp()
        without_roles.ctx.app_registry = FakeRegistry(labels=("auth", "admin"))
        plain_site = AdminSite("role_admin_test_without_roles")
        install_admin(without_roles, db_manager=self.database, admin_site=plain_site, admin_settings=AdminSettings(prefix="/control"))
        self.assertFalse(plain_site.is_registered(Role))

    async def test_saving_and_deleting_a_role_rewrites_and_drops_its_cache_key(self) -> None:
        created = await self.call(
            f"{ROLES_PATH}/new",
            ("POST",),
            self.post(f"{ROLES_PATH}/new", {"name": "Analysts", "description": "", "permissions": ["role_admin_test.view"]}),
        )
        self.assertEqual(0, json.loads(created.body)["error_code"])
        role = await self.role_named("Analysts")
        assert role is not None
        self.assertEqual(["role_admin_test.view"], await self.cached(role.id))

        edit_path = f"{ROLES_PATH}/<object_id>/edit"
        edited = await self.call(
            edit_path,
            ("POST",),
            self.post(
                edit_path, {"name": "Analysts", "description": "Reads and exports", "permissions": ["role_admin_test.view", "role_admin_test.export"]}
            ),
            object_id=str(role.id),
        )
        self.assertEqual(0, json.loads(edited.body)["error_code"])
        self.assertEqual(["role_admin_test.export", "role_admin_test.view"], await self.cached(role.id))

        delete_path = f"{ROLES_PATH}/<object_id>/delete"
        await self.call(delete_path, ("POST",), self.post(delete_path, {}), object_id=str(role.id))
        self.assertIsNone(await self.role_named("Analysts"))
        self.assertIsNone(await self.cached(role.id))

    async def test_a_second_role_cannot_take_a_name_or_an_undeclared_permission(self) -> None:
        async with self.database.get_session() as session:
            session.add(Role(name="Analysts", permissions=[]))
        form_path = f"{ROLES_PATH}/new"
        for form in (
            {"name": "Analysts", "permissions": []},
            {"name": "Auditors", "permissions": ["role_admin_test.delete"]},
        ):
            with self.subTest(form=form):
                response = await self.call(form_path, ("POST",), self.post(form_path, form))
                self.assertNotEqual(0, json.loads(response.body)["error_code"])
        self.assertIsNone(await self.role_named("Auditors"))

    async def test_saving_a_role_keeps_the_permissions_another_service_declares(self) -> None:
        """G2-2: services sharing the role table declare different names; this one used to drop the ones it did not know."""
        async with self.database.get_session() as session:
            session.add(Role(name="Analysts", permissions=["billing.invoices.export", "role_admin_test.view"]))
        role = await self.role_named("Analysts")
        assert role is not None

        edit_path = f"{ROLES_PATH}/<object_id>/edit"
        edited = await self.call(
            edit_path,
            ("POST",),
            self.post(edit_path, {"name": "Analysts", "description": "", "permissions": ["role_admin_test.export"]}),
            object_id=str(role.id),
        )

        self.assertEqual(0, json.loads(edited.body)["error_code"], edited.body)
        expected = ["billing.invoices.export", "role_admin_test.export"]
        self.assertEqual(expected, getattr(await self.role_named("Analysts"), "permissions", None))
        self.assertEqual(expected, await self.cached(role.id))

    async def test_staff_may_add_to_a_role_only_permissions_they_hold(self) -> None:
        """G2-1: an operator who could edit roles could add any permission to a role they held themselves."""
        async with self.database.get_session() as session:
            session.add(Role(name="Analysts", permissions=["role_admin_test.export"]))
        role = await self.role_named("Analysts")
        assert role is not None
        edit_path = f"{ROLES_PATH}/<object_id>/edit"
        role_admin = self.site.get_model_admin(Role)
        editing = (role_admin.permission("view").name, role_admin.permission("change").name)

        async def save(permissions: list[str]) -> int:
            request = self.post(edit_path, {"name": "Analysts", "description": "", "permissions": permissions}, staff_session())
            with grants(*editing, "role_admin_test.view"):
                response = await self.call(edit_path, ("POST",), request, object_id=str(role.id))
            return json.loads(response.body)["error_code"]

        self.assertNotEqual(0, await save(["role_admin_test.export", "role_admin_twin.approve"]), "approve is not theirs to give")
        self.assertEqual(["role_admin_test.export"], getattr(await self.role_named("Analysts"), "permissions", None))
        # What the role already had stays, whoever holds it; what they hold may be added; anything may be taken away.
        self.assertEqual(0, await save(["role_admin_test.export", "role_admin_test.view"]))
        self.assertEqual(0, await save(["role_admin_test.view"]))
        self.assertEqual(["role_admin_test.view"], getattr(await self.role_named("Analysts"), "permissions", None))

    async def test_a_role_missing_from_the_cache_is_read_from_the_admins_own_database(self) -> None:
        """G2-5: on a cache miss the permission check read roles through the process's default database."""
        role_admin = self.site.get_model_admin(Role)
        async with self.database.get_session() as session:
            session.add(Role(id=1, name="Viewers", permissions=[role_admin.permission("view").name]))
        await self.connection.delete("svc:role:1")

        request = make_request(self.app, path=ROLES_PATH, session=staff_session())
        listed = await self.call(ROLES_PATH, ("GET",), request)

        self.assertEqual(200, listed.status)
        self.assertEqual([role_admin.permission("view").name], await self.cached(1))

    async def test_a_role_saved_while_redis_is_down_is_kept_and_the_response_says_so(self) -> None:
        """G6-7: the 503 was Sanic's own error body, without error_code, so the Admin could only say "Request failed"."""
        form_path = f"{ROLES_PATH}/new"
        with patch("oldman.apps.roles.store.publish_role", AsyncMock(side_effect=RedisConnectionError("down"))):
            response = await self.call(form_path, ("POST",), self.post(form_path, {"name": "Analysts", "permissions": ["role_admin_test.view"]}))
        payload = json.loads(response.body)
        self.assertEqual((503, 1503, "The permission store is unavailable"), (response.status, payload["error_code"], payload["message"]))
        role = await self.role_named("Analysts")
        assert role is not None
        self.assertEqual(["role_admin_test.view"], role.permissions)

    async def test_a_role_is_not_deleted_while_redis_cannot_drop_its_key(self) -> None:
        # The other order would leave a key nothing can remove: the role gone, a second delete finding nothing.
        async with self.database.get_session() as session:
            role = Role(name="Analysts", permissions=["role_admin_test.view"])
            session.add(role)
        async with self.database.get_read_session() as session:
            role_id = (await session.exec(select(Role.id).where(Role.name == "Analysts"))).one()
        await self.connection.set(f"svc:role:{role_id}", json.dumps(["role_admin_test.view"]))
        delete_path = f"{ROLES_PATH}/<object_id>/delete"

        with (
            patch("oldman.apps.roles.store.forget_role", AsyncMock(side_effect=RedisConnectionError("down"))),
            self.assertRaises(ServiceUnavailable),
        ):
            await self.call(delete_path, ("POST",), self.post(delete_path, {}), object_id=str(role_id))
        self.assertIsNotNone(await self.role_named("Analysts"))
        self.assertEqual(["role_admin_test.view"], await self.cached(role_id))

        # Once the key is gone and the row deleted, a failure to drop it again is only logged.
        forget = AsyncMock(side_effect=[None, RedisConnectionError("down")])
        with patch("oldman.apps.roles.store.forget_role", forget), self.assertLogs("oldman.apps.admin.roles", "WARNING"):
            await self.call(delete_path, ("POST",), self.post(delete_path, {}), object_id=str(role_id))
        self.assertIsNone(await self.role_named("Analysts"))
        self.assertEqual(2, forget.await_count)

    async def test_the_cache_is_written_only_after_the_transaction_commits(self) -> None:
        events: list[str] = []
        open_session = self.database.get_session

        @asynccontextmanager
        async def recording_session() -> AsyncIterator[Any]:
            async with open_session() as session:
                yield session
            events.append("committed")

        form_path = f"{ROLES_PATH}/new"
        with (
            patch.object(self.database, "get_session", recording_session),
            patch("oldman.apps.roles.store.publish_role", AsyncMock(side_effect=lambda role: events.append("published"))),
        ):
            await self.call(form_path, ("POST",), self.post(form_path, {"name": "Analysts", "permissions": []}))
        self.assertEqual(["committed", "published"], events)

    async def test_the_role_form_normalises_what_it_saves(self) -> None:
        async with self.database.get_session() as session:
            # A superuser: an operator who is not one adds only permissions they hold.
            request = SimpleNamespace(app=self.app, method="POST", ctx=SimpleNamespace(session=superuser_session()))
            form = RoleForm(
                formdata=SanicFormData({"name": "  Analysts ", "permissions": ["role_admin_test.view", "role_admin_test.export"]}),
                request=request,
                session=session,
            )
            self.assertTrue(await form.validate(), form.errors)
            role = await form.save(commit=True)
        self.assertEqual("Analysts", role.name)
        self.assertEqual(["role_admin_test.export", "role_admin_test.view"], role.permissions)


class UserRolesTest(AdminWithRolesCase):
    """The shared user form offers the roles; saving it replaces what the user holds."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.database.get_session() as session:
            session.add(User(id=12, username="alice", password_hash="", is_active=True, is_staff=True, is_superuser=False))
            session.add_all([Role(name="Analysts", permissions=[]), Role(name="Editors", permissions=[])])
        async with self.database.get_read_session() as session:
            self.role_ids = {role.name: role.id for role in (await session.exec(select(Role))).all()}

    async def held(self) -> list[int]:
        async with self.database.get_read_session() as session:
            return sorted((await session.exec(select(UserRole.role_id).where(UserRole.user_id == 12))).all())

    def user_form(self, **roles: Any) -> dict[str, Any]:
        return {"username": "alice", "email": "", "display_name": "", "is_active": "y", "is_staff": "y", **roles}

    async def save_user(self, form: dict[str, Any]) -> Any:
        with patch("oldman.web.auth.user_management.revoke_user_logins", AsyncMock()) as revoke:
            response = await self.call(USER_EDIT_PATH, ("POST",), self.post(USER_EDIT_PATH, form), object_id="12")
        self.assertEqual(0, json.loads(response.body)["error_code"], response.body)
        return revoke

    async def test_saving_the_user_form_replaces_the_roles_and_ends_logins_when_they_change(self) -> None:
        revoke = await self.save_user(self.user_form(roles=[str(self.role_ids["Analysts"]), str(self.role_ids["Editors"])]))
        self.assertEqual(sorted(self.role_ids.values()), await self.held())
        # Sessions and tokens carry the role ids they were opened with.
        revoke.assert_awaited_once()

        unchanged = await self.save_user(self.user_form(roles=[str(self.role_ids["Analysts"]), str(self.role_ids["Editors"])]))
        unchanged.assert_not_awaited()

        await self.save_user(self.user_form())
        self.assertEqual([], await self.held())

    async def test_staff_may_hand_out_only_roles_whose_permissions_they_hold(self) -> None:
        """G2-1: an operator allowed to edit users could give an ordinary account the most powerful role."""
        async with self.database.get_session() as session:
            session.add(User(id=13, username="bob", password_hash="", is_active=True, is_staff=False, is_superuser=False))
            for role in (await session.exec(select(Role))).all():
                role.permissions = {"Analysts": ["role_admin_test.view"], "Editors": ["role_admin_test.export"]}[role.name]
            session.add(UserRole(user_id=13, role_id=self.role_ids["Editors"]))
        path = USER_EDIT_PATH

        async def save(*roles: str) -> int:
            form = {"username": "bob", "email": "", "display_name": "", "is_active": "y", "roles": [str(self.role_ids[name]) for name in roles]}
            with grants(*USER_MANAGEMENT, "role_admin_test.view"), patch("oldman.web.auth.user_management.revoke_user_logins", AsyncMock()):
                response = await self.call(path, ("POST",), self.post(path, form, staff_session()), object_id="13")
            return json.loads(response.body)["error_code"]

        async def held() -> list[str]:
            async with self.database.get_read_session() as session:
                rows = await session.exec(select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == 13))
                return sorted(rows.all())

        # Editors grants export, which the operator does not hold: they may keep it on bob, not give it anew.
        self.assertEqual(0, await save("Editors", "Analysts"))
        self.assertEqual(["Analysts", "Editors"], await held())
        self.assertEqual(0, await save("Analysts"))
        self.assertNotEqual(0, await save("Analysts", "Editors"))
        self.assertEqual(["Analysts"], await held())

    async def test_a_new_user_gets_the_checked_roles_once_it_has_an_id(self) -> None:
        path = "/control/oldman_user/new"
        form = {
            **self.user_form(roles=[str(self.role_ids["Editors"])]),
            "username": "bob",
            "password": "NewPass!2026",
            "confirm_password": "NewPass!2026",
        }
        response = await self.call(path, ("POST",), self.post(path, form))
        self.assertEqual(0, json.loads(response.body)["error_code"], response.body)
        async with self.database.get_read_session() as session:
            bob = (await session.exec(select(User).where(User.username == "bob"))).one()
            held = (await session.exec(select(UserRole.role_id).where(UserRole.user_id == bob.id))).all()
        self.assertEqual([self.role_ids["Editors"]], list(held))

    async def test_the_edit_page_shows_the_roles_the_user_holds(self) -> None:
        async with self.database.get_session() as session:
            session.add(UserRole(user_id=12, role_id=self.role_ids["Editors"]))
        path = "/control/oldman_user/<object_id>/edit"
        response = await self.call(path, ("GET",), make_request(self.app, path=path, session=superuser_session()), object_id="12")
        self.assertEqual(200, response.status)
        body = response.body.decode()
        self.assertIn(f'checked class="om-check" id="id_roles-1" name="roles" type="checkbox" value="{self.role_ids["Editors"]}"', body)
        self.assertIn(f'class="om-check" id="id_roles-0" name="roles" type="checkbox" value="{self.role_ids["Analysts"]}"', body)
        self.assertNotIn('checked class="om-check" id="id_roles-0"', body)

    async def test_the_form_has_no_roles_without_the_roles_app_or_without_any_role(self) -> None:
        async with self.database.get_session() as session:
            user = await session.get(User, 12)
            without_app = SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace()), method="GET")
            form = user_edit_form_class(User)(request=without_app, instance=user, session=session)
            self.assertNotIn("roles", form._fields)

            for role in (await session.exec(select(Role))).all():
                await session.delete(role)
            await session.flush()
            form = user_edit_form_class(User)(request=SimpleNamespace(app=self.app, method="GET"), instance=user, session=session)
            await form.prepare_async_fields()
            self.assertNotIn("roles", form._fields)


if __name__ == "__main__":
    unittest.main()
