"""RoleManagementFlow: a dashboard's role pages, keeping each role's cache key in step like the Admin."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from jinja2 import DictLoader, Environment
from redis.exceptions import ConnectionError as RedisConnectionError
from sanic import Sanic
from sqlalchemy import select
from sqlalchemy.schema import Table

import oldman.conf as conf
from oldman.apps.roles.management import RoleManagementFlow
from oldman.apps.roles.models import Role, UserRole
from oldman.auth import Permission, PermissionSet
from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig
from oldman.db.session import DatabaseManager
from oldman.providers.redis import RedisClientRegistry
from oldman.web.security.csrf import StatelessCSRFManager
from oldman.web.template import install_template_loaders
from tests.redis_support import RedisProcess, owned_redis_config, require_redis_server
from tests.test_oldman_admin_roles import FakeRegistry
from tests.test_oldman_admin_runtime import FakeSession, grants, make_request, render_with_request_environment, runtime_settings
from tests.test_oldman_web_auth_user_management import RoutesApp

TEMPLATES = {
    "account/roles/index.html": "list|{{ roles_url }}|{{ new_url }}|{{ table.route_path }}",
    "account/roles/form.html": "form|{{ action }}|{{ roles_url }}|{{ 'new' if role is none else role.name }}",
}
ROLES_MANAGED = tuple(f"roles.{action}" for action in ("view", "add", "change", "delete"))


class ReportPermissions(PermissionSet, namespace="role_flow_test"):
    view = Permission("View reports")
    export = Permission("Export reports")


def superuser() -> FakeSession:
    return FakeSession(user_id=1, username="root", is_active=True, is_staff=True, is_superuser=True)


def member() -> FakeSession:
    """A signed-in account that is no superuser; what its role grants is set with `grants`."""
    return FakeSession(user_id=2, username="member", is_active=True, is_staff=False, is_superuser=False, role_ids=(1,))


class RoleManagementFlowTest(unittest.IsolatedAsyncioTestCase):
    """The flow's own handlers against in-memory SQLite and a test-owned redis-server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls._redis = RedisProcess(require_redis_server(), Path(cls._directory.name), "role-flow")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._redis.stop()
        cls._directory.cleanup()

    async def asyncSetUp(self) -> None:
        settings = runtime_settings()
        settings.core.namespace = "svc"
        self.enterContext(patch.dict(conf.__dict__, {"settings": settings}))
        self.enterContext(patch("oldman.web.auth.flows.render_template", side_effect=render_with_request_environment))
        self.redis = RedisClientRegistry(owned_redis_config(self._redis.socket_path, {"SESSION": 5}))
        self.enterContext(patch("oldman.providers.redis.redis_client", self.redis))
        self.connection = await self.redis.using("SESSION").async_get_conn()
        await self.connection.flushdb()

        self.manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        await self.manager.initialize()
        async with self.manager.engine.begin() as connection:
            for model in (User, Role, UserRole):
                await connection.run_sync(cast(Table, model.__table__).create)

        self.app = RoutesApp()
        self.app.ctx.app_registry = FakeRegistry(labels=("auth", "roles", "role_flow_test"))
        self.app.ext.environment = Environment(loader=DictLoader(TEMPLATES), enable_async=True)
        StatelessCSRFManager(cast(Any, self.app))
        self.flow = RoleManagementFlow(base_path="/team-roles", login_path="/signin", db_manager=self.manager)
        self.flow.register_routes(cast(Any, self.app), template_prefix="account", name_prefix="site_")

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        await self.redis.close()

    async def call(self, path: str, method: str, request: Any, **kwargs: Any) -> Any:
        handler = cast(Any, self.app.route_handlers[(path, (method,))])
        return await handler(request, **kwargs)

    def get(self, path: str, session: FakeSession | None = None) -> Any:
        request = make_request(cast(Any, self.app), path=path, session=session)
        request.headers = {"accept": "application/json"}
        return request

    def post(self, path: str, form: dict[str, Any], session: FakeSession | None = None) -> Any:
        request = make_request(cast(Any, self.app), path=path, session=session or superuser())
        request.method = "POST"
        request.headers = {"accept": "application/json", "Origin": "http://example.test"}
        request.form = {**form, "csrfmiddlewaretoken": self.app.ctx.csrf.generate_token(request)}
        return request

    @staticmethod
    def payload(response: Any) -> dict[str, Any]:
        return json.loads(response.body)

    async def cached(self, role_id: int) -> Any:
        raw = await self.connection.get(f"svc:role:{role_id}")
        return None if raw is None else json.loads(raw)

    async def role_named(self, name: str) -> Role | None:
        async with self.manager.get_read_session() as session:
            return (await session.exec(select(Role).where(Role.name == name))).one_or_none()

    async def add_role(self, name: str, permissions: list[str]) -> int:
        async with self.manager.get_session() as session:
            role = Role(name=name, permissions=permissions)
            session.add(role)
            await session.flush()
            return role.id

    async def test_routes_and_names_follow_the_base_path(self) -> None:
        names = self.app.route_names
        self.assertEqual("site_roles", names[("/team-roles", ("GET",))])
        self.assertEqual("site_roles_table", names[("/team-roles/table", ("GET",))])
        self.assertEqual("site_roles_update", names[("/team-roles/<role_id:int>/edit", ("POST",))])
        self.assertEqual("site_roles_delete_submit", names[("/team-roles/<role_id:int>/delete", ("POST",))])
        self.assertEqual(8, len(names))

    async def test_every_page_and_the_table_data_need_the_role_permissions(self) -> None:
        """A signed-in account without roles.view gets 403; a visitor is sent to the login page; each action has its own."""
        with grants("role_flow_test.view"):
            refused = await self.call("/team-roles", "GET", self.get("/team-roles", member()))
        self.assertEqual(403, refused.status)
        visitor = make_request(cast(Any, self.app), path="/team-roles")
        self.assertEqual("/signin?next=%2Fteam-roles", (await self.call("/team-roles", "GET", visitor)).headers["Location"])

        table_view = cast(Any, self.app.route_handlers[("/team-roles/table", ("GET",))]).view_class
        with grants("role_flow_test.view"):
            allowed, _message = await table_view().check_permission(self.get("/team-roles", member()), method_name="get", route_kwargs={})
        self.assertFalse(allowed)

        # roles.view opens the list only; creating needs roles.add.
        with grants("roles.view"):
            listed = await self.call("/team-roles", "GET", self.get("/team-roles", member()))
            creating = await self.call("/team-roles/new", "GET", self.get("/team-roles/new", member()))
        self.assertEqual("list|/team-roles|/team-roles/new|/team-roles/table", listed.body.decode())
        self.assertEqual(403, creating.status)

        role_id = await self.add_role("Analysts", [])
        with grants("roles.view", "roles.change"):
            deleting = await self.call("/team-roles/<role_id:int>/delete", "POST", self.post("/x", {}, member()), role_id=role_id)
        self.assertEqual(403, deleting.status)
        self.assertIsNotNone(await self.role_named("Analysts"))

    async def test_saving_and_deleting_a_role_rewrites_and_drops_its_cache_key(self) -> None:
        form = {"name": "Analysts", "description": "", "permissions": ["role_flow_test.view"]}
        created = await self.call("/team-roles/new", "POST", self.post("/team-roles/new", form))
        self.assertEqual(0, self.payload(created)["error_code"], created.body)
        self.assertIn("Analysts was created.", json.dumps(self.payload(created)))
        role = await self.role_named("Analysts")
        assert role is not None
        self.assertEqual(["role_flow_test.view"], await self.cached(role.id))

        edited = await self.call(
            "/team-roles/<role_id:int>/edit",
            "POST",
            self.post(
                "/x", {"name": "Analysts", "description": "Reads and exports", "permissions": ["role_flow_test.view", "role_flow_test.export"]}
            ),
            role_id=role.id,
        )
        self.assertEqual(0, self.payload(edited)["error_code"], edited.body)
        self.assertEqual(["role_flow_test.export", "role_flow_test.view"], await self.cached(role.id))

        deleted = await self.call("/team-roles/<role_id:int>/delete", "POST", self.post("/x", {}), role_id=role.id)
        self.assertIn("Analysts was deleted.", json.dumps(self.payload(deleted)))
        self.assertIsNone(await self.role_named("Analysts"))
        self.assertIsNone(await self.cached(role.id))

    async def test_the_key_is_dropped_before_the_row_and_again_after_the_commit(self) -> None:
        role_id = await self.add_role("Analysts", ["role_flow_test.view"])
        forget = AsyncMock(side_effect=[None, RedisConnectionError("down")])
        with patch("oldman.apps.roles.store.forget_role", forget), self.assertLogs("oldman.apps.roles.management", "WARNING"):
            response = await self.call("/team-roles/<role_id:int>/delete", "POST", self.post("/x", {}), role_id=role_id)
        # The second drop failing is only logged: the delete already stands.
        self.assertEqual(0, self.payload(response)["error_code"])
        self.assertIsNone(await self.role_named("Analysts"))
        self.assertEqual(2, forget.await_count)

    async def test_a_role_saved_while_redis_is_down_is_kept_and_the_answer_says_so(self) -> None:
        form = {"name": "Analysts", "permissions": ["role_flow_test.view"]}
        with patch("oldman.apps.roles.store.publish_role", AsyncMock(side_effect=RedisConnectionError("down"))):
            response = await self.call("/team-roles/new", "POST", self.post("/team-roles/new", form))
        payload = self.payload(response)
        self.assertEqual((503, 1503, "The permission store is unavailable"), (response.status, payload["error_code"], payload["message"]))
        role = await self.role_named("Analysts")
        assert role is not None
        self.assertEqual(["role_flow_test.view"], role.permissions)

    async def test_a_role_is_not_deleted_while_redis_cannot_drop_its_key(self) -> None:
        role_id = await self.add_role("Analysts", ["role_flow_test.view"])
        await self.connection.set(f"svc:role:{role_id}", json.dumps(["role_flow_test.view"]))
        with patch("oldman.apps.roles.store.forget_role", AsyncMock(side_effect=RedisConnectionError("down"))):
            response = await self.call("/team-roles/<role_id:int>/delete", "POST", self.post("/x", {}), role_id=role_id)
        payload = self.payload(response)
        self.assertEqual((503, 1503, "The permission store is unavailable"), (response.status, payload["error_code"], payload["message"]))
        self.assertIsNotNone(await self.role_named("Analysts"))
        self.assertEqual(["role_flow_test.view"], await self.cached(role_id))

    async def test_an_operator_who_is_not_a_superuser_adds_only_permissions_they_hold(self) -> None:
        role_id = await self.add_role("Analysts", ["role_flow_test.view"])

        async def save(permissions: list[str]) -> int:
            request = self.post("/x", {"name": "Analysts", "description": "", "permissions": permissions}, member())
            with grants(*ROLES_MANAGED, "role_flow_test.view"):
                response = await self.call("/team-roles/<role_id:int>/edit", "POST", request, role_id=role_id)
            return self.payload(response)["error_code"]

        self.assertNotEqual(0, await save(["role_flow_test.view", "role_flow_test.export"]), "export is not theirs to give")
        self.assertEqual(0, await save([]))
        self.assertEqual([], getattr(await self.role_named("Analysts"), "permissions", None))

    async def test_a_name_another_role_has_is_refused(self) -> None:
        await self.add_role("Analysts", [])
        response = await self.call("/team-roles/new", "POST", self.post("/team-roles/new", {"name": "Analysts", "permissions": []}))
        self.assertNotEqual(0, self.payload(response)["error_code"])

    async def test_the_shared_pages_render_inside_the_project_base(self) -> None:
        role_id = await self.add_role("Analysts", ["role_flow_test.export"])
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "base.html").write_text("<main>{% block content %}{% endblock %}</main>", encoding="utf-8")
            app = RoutesApp()
            app.ctx.app_registry = FakeRegistry(labels=("auth", "roles", "role_flow_test"))
            app.ext.environment = install_template_loaders(Environment(enable_async=True), tmp_dir)
            StatelessCSRFManager(cast(Any, app))
            RoleManagementFlow(base_path="/team-roles", login_path="/signin", db_manager=self.manager).register_routes(
                cast(Any, app), template_prefix="oldman/dashboard/account"
            )

            async def page(path: str, route: str, **kwargs: Any) -> str:
                response = await cast(Any, app.route_handlers[(route, ("GET",))])(
                    make_request(cast(Any, app), path=path, session=superuser()), **kwargs
                )
                return response.body.decode()

            listing = await page("/team-roles", "/team-roles")
            new = await page("/team-roles/new", "/team-roles/new")
            edit = await page(f"/team-roles/{role_id}/edit", "/team-roles/<role_id:int>/edit", role_id=role_id)
            modal = json.loads(await page(f"/team-roles/{role_id}/delete-modal", "/team-roles/<role_id:int>/delete-modal", role_id=role_id))

        self.assertTrue(listing.startswith("<main>"), "the project's base wraps the page")
        self.assertIn('id="roles-table"', listing)
        self.assertIn('id="role-delete-modal"', listing)
        self.assertIn('href="/team-roles/new"', listing)
        self.assertIn('action="/team-roles/new"', new)
        self.assertIn("data-om-checkbox-group", new)
        self.assertIn('value="role_flow_test.export"', new)
        self.assertIn(f'action="/team-roles/{role_id}/edit"', edit)
        self.assertIn('checked class="om-check"', edit)
        self.assertEqual("Delete Role · Analysts", modal["title"])
        self.assertIn(f'action="/team-roles/{role_id}/delete"', modal["html"])

    async def test_a_service_without_the_roles_app_cannot_install_the_pages(self) -> None:
        app = Sanic("role_flow_without_roles")
        app.ctx.app_registry = FakeRegistry(labels=("auth",))
        with self.assertRaisesRegex(RuntimeError, "needs the oldman.apps.roles App"):
            RoleManagementFlow(base_path="/roles", login_path="/login").register_routes(app, template_prefix="oldman/dashboard/account")


if __name__ == "__main__":
    unittest.main()
