"""UserManagementFlow and the rules both hosts share: who may change which account, whose logins end."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from jinja2 import DictLoader, Environment
from sanic.response import HTTPResponse, text
from sqlalchemy import select
from sqlalchemy.schema import Table

import oldman.conf as conf
from oldman.auth.models import User
from oldman.auth.settings import AuthSettings
from oldman.conf.schemas import DatabaseConfig
from oldman.db.session import DatabaseManager
from oldman.web.auth import UserManagementFlow, can_manage_user, user_change_text
from oldman.web.security.csrf import StatelessCSRFManager
from oldman.web.template import install_template_loaders
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    make_post_request,
    make_request,
    render_with_request_environment,
    runtime_settings,
)

TEMPLATES = {
    "account/users/index.html": "list|{{ users_url }}|{{ new_url }}|{{ table.route_path }}",
    "account/users/form.html": "form|{{ action }}|{{ users_url }}|{{ 'new' if user is none else user.username }}",
}


class RoutesApp(FakeApp):
    """FakeApp that also keeps the route names and builds a URL from one, as the table shell does."""

    name = "site"

    def __init__(self) -> None:
        super().__init__()
        self.route_names: dict[tuple[str, tuple[str, ...]], str] = {}
        self.ext.environment = Environment(loader=DictLoader(TEMPLATES), enable_async=True)

    def add_route(self, handler, path: str, *, methods: list[str], name: str) -> None:
        super().add_route(handler, path, methods=methods, name=name)
        self.route_names[(path, tuple(methods))] = name

    def url_for(self, view_name: str, **kwargs: Any) -> str:
        del kwargs
        route_name = view_name.removeprefix(f"{self.name}.")
        return next(path for (path, _methods), name in self.route_names.items() if name == route_name)


def operator(user_id: int, *, is_staff: bool = False, is_superuser: bool = False) -> FakeSession:
    return FakeSession(user_id=user_id, username=f"op{user_id}", is_active=True, is_staff=is_staff, is_superuser=is_superuser)


class CanManageUserTest(unittest.TestCase):
    """The one rule the user form and every user action apply."""

    def request(self, **flags: bool) -> Any:
        return make_request(cast(Any, FakeApp()), path="/", session=operator(1, **flags))

    def test_a_superuser_manages_any_account_and_may_make_staff(self) -> None:
        staff = User(username="s", is_active=True, is_staff=True, is_superuser=False)
        self.assertTrue(can_manage_user(self.request(is_staff=True, is_superuser=True), staff, makes_privileged=True))

    def test_anyone_else_manages_ordinary_accounts_only_and_never_makes_staff(self) -> None:
        request = self.request(is_staff=True)
        ordinary = User(username="o", is_active=True, is_staff=False, is_superuser=False)
        staff = User(username="s", is_active=True, is_staff=True, is_superuser=False)

        self.assertTrue(can_manage_user(request, ordinary))
        self.assertFalse(can_manage_user(request, staff))
        self.assertFalse(can_manage_user(request, ordinary, makes_privileged=True))
        self.assertTrue(can_manage_user(request))
        self.assertFalse(can_manage_user(request, makes_privileged=True))

    def test_both_hosts_say_the_same_sentence(self) -> None:
        self.assertEqual("mia is now disabled.", user_change_text("disabled", username="mia"))
        self.assertEqual("mia was created.", user_change_text("created", username="mia"))


class UserManagementFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": runtime_settings()}))
        self.enterContext(patch("oldman.web.auth.flows.render_template", side_effect=render_with_request_environment))
        self.revoked: list[int] = []
        self.signed_out_ids: set[int] = set()

        async def revoke(request: Any, user_id: int) -> bool:
            del request
            self.revoked.append(user_id)
            return user_id in self.signed_out_ids

        self.enterContext(patch("oldman.web.auth.user_management.revoke_user_logins", side_effect=revoke))
        self.manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        await self.manager.initialize()
        async with self.manager.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)
        self.ids: dict[str, int] = {}
        async with self.manager.get_session() as session:
            for name, staff, superuser in (("root", True, True), ("staffer", True, False), ("member", False, False)):
                user = User(username=name, display_name=name, password_hash="", is_active=True, is_staff=staff, is_superuser=superuser)
                user.set_password("Initial2026")
                session.add(user)
                await session.flush()
                assert user.id is not None
                self.ids[name] = user.id
        self.app = RoutesApp()
        StatelessCSRFManager(cast(Any, self.app))
        UserManagementFlow(
            base_path="/people", login_path="/signin", user_model=User, auth_settings=AuthSettings(), db_manager=self.manager
        ).register_routes(cast(Any, self.app), template_prefix="account", name_prefix="site_")

    async def asyncTearDown(self) -> None:
        await self.manager.close()

    async def call(self, path: str, method: str, request: Any, **kwargs: Any) -> Any:
        handler = cast(Any, self.app.route_handlers[(path, (method,))])
        return await handler(request, **kwargs)

    def post(self, path: str, session: FakeSession, form: dict[str, str] | None = None) -> Any:
        return make_post_request(cast(Any, self.app), path=path, session=session, accept="application/json", form=form or {})

    @staticmethod
    def payload(response: Any) -> dict[str, Any]:
        return json.loads(response.body)

    async def test_routes_and_names_follow_the_base_path(self) -> None:
        names = self.app.route_names
        self.assertEqual("site_users", names[("/people", ("GET",))])
        self.assertEqual("site_users_table", names[("/people/table", ("GET",))])
        self.assertEqual("site_users_password_submit", names[("/people/<user_id:int>/password", ("POST",))])
        self.assertEqual("site_users_delete_submit", names[("/people/<user_id:int>/delete", ("POST",))])
        self.assertEqual(12, len(names))

    async def test_every_page_and_the_table_data_need_the_user_permissions(self) -> None:
        """A signed-in member without auth.users.view gets 403; a visitor is sent to the login page."""
        page = make_request(cast(Any, self.app), path="/people", session=operator(self.ids["member"]))
        page.headers = {"accept": "application/json"}
        self.assertEqual(403, (await self.call("/people", "GET", page)).status)
        visitor = make_request(cast(Any, self.app), path="/people")
        self.assertEqual("/signin?next=%2Fpeople", (await self.call("/people", "GET", visitor)).headers["Location"])

        table_view = cast(Any, self.app.route_handlers[("/people/table", ("GET",))]).view_class
        allowed, _message = await table_view().check_permission(page, method_name="get", route_kwargs={})
        self.assertFalse(allowed)
        root = make_request(cast(Any, self.app), path="/people", session=operator(self.ids["root"], is_staff=True, is_superuser=True))
        self.assertEqual("list|/people|/people/new|/people/table", (await self.call("/people", "GET", root)).body.decode())

    async def test_an_operator_who_is_not_a_superuser_cannot_reset_a_staff_account(self) -> None:
        operator_session = operator(99, is_staff=True)
        form = {"password": "NewPass2026", "confirm_password": "NewPass2026"}
        with patch("oldman.web.auth.user_management.has_perm", AsyncMock(return_value=True)):
            refused = await self.call("/people/<user_id:int>/password", "POST", self.post("/x", operator_session, form), user_id=self.ids["staffer"])
            changed = await self.call("/people/<user_id:int>/password", "POST", self.post("/x", operator_session, form), user_id=self.ids["member"])

        self.assertEqual("Permission denied", self.payload(refused)["message"])
        self.assertEqual("Password changed", self.payload(changed)["message"])
        self.assertEqual([self.ids["member"]], self.revoked)

    async def test_changing_your_own_password_here_sends_you_to_sign_in_again(self) -> None:
        root_id = self.ids["root"]
        self.signed_out_ids.add(root_id)
        root = operator(root_id, is_staff=True, is_superuser=True)

        response = await self.call(
            "/people/<user_id:int>/password",
            "POST",
            self.post("/x", root, {"password": "NewPass2026", "confirm_password": "NewPass2026"}),
            user_id=root_id,
        )

        redirects = [action["url"] for action in self.payload(response)["actions"] if action.get("action") == "redirect"]
        self.assertEqual(["/signin"], redirects)

    async def test_disabling_ends_the_logins_and_enabling_does_not(self) -> None:
        root = operator(self.ids["root"], is_staff=True, is_superuser=True)
        member_id = self.ids["member"]

        disabled = await self.call("/people/<user_id:int>/status", "POST", self.post("/x", root, {"is_active": "false"}), user_id=member_id)
        enabled = await self.call("/people/<user_id:int>/status", "POST", self.post("/x", root, {"is_active": "true"}), user_id=member_id)

        self.assertIn("member is now disabled.", json.dumps(self.payload(disabled)))
        self.assertIn("member is now active.", json.dumps(self.payload(enabled)))
        self.assertEqual([member_id], self.revoked)

    async def test_deleting_ends_the_logins_and_nobody_deletes_themselves(self) -> None:
        root_id = self.ids["root"]
        root = operator(root_id, is_staff=True, is_superuser=True)

        own = await self.call("/people/<user_id:int>/delete", "POST", self.post("/x", root), user_id=root_id)
        deleted = await self.call("/people/<user_id:int>/delete", "POST", self.post("/x", root), user_id=self.ids["member"])

        self.assertEqual("cannot delete current user", self.payload(own)["message"])
        self.assertIn("member was deleted.", json.dumps(self.payload(deleted)))
        self.assertEqual([self.ids["member"]], self.revoked)
        async with self.manager.get_read_session() as session:
            self.assertIsNone(await session.get(User, self.ids["member"]))

    async def test_an_edit_that_changes_access_ends_the_logins_and_one_that_does_not_leaves_them(self) -> None:
        root = operator(self.ids["root"], is_staff=True, is_superuser=True)
        member_id = self.ids["member"]
        profile = {"username": "member", "email": "", "display_name": "Member", "is_active": "y"}

        await self.call("/people/<user_id:int>/edit", "POST", self.post("/x", root, profile), user_id=member_id)
        self.assertEqual([], self.revoked)
        await self.call("/people/<user_id:int>/edit", "POST", self.post("/x", root, {**profile, "is_staff": "y"}), user_id=member_id)
        self.assertEqual([member_id], self.revoked)

    async def test_creating_a_user_answers_with_the_shared_sentence(self) -> None:
        root = operator(self.ids["root"], is_staff=True, is_superuser=True)
        form = {"username": "newbie", "email": "", "display_name": "", "is_active": "y", "password": "Welcome2026", "confirm_password": "Welcome2026"}

        response = await self.call("/people/new", "POST", self.post("/people/new", root, form))

        self.assertIn("newbie was created.", json.dumps(self.payload(response)))
        async with self.manager.get_read_session() as session:
            self.assertIsNotNone((await session.execute(select(User).where(User.username == "newbie"))).scalar_one_or_none())

    async def test_the_shared_pages_render_inside_the_project_base(self) -> None:
        root = operator(self.ids["root"], is_staff=True, is_superuser=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "base.html").write_text("<main>{% block content %}{% endblock %}</main>", encoding="utf-8")
            app = RoutesApp()
            app.ext.environment = install_template_loaders(Environment(enable_async=True), tmp_dir)
            StatelessCSRFManager(cast(Any, app))
            flow = UserManagementFlow(
                base_path="/people", login_path="/signin", user_model=User, auth_settings=AuthSettings(), db_manager=self.manager
            )
            flow.register_routes(cast(Any, app), template_prefix="oldman/dashboard/account")
            listing = await cast(Any, app.route_handlers[("/people", ("GET",))])(make_request(cast(Any, app), path="/people", session=root))
            new = await cast(Any, app.route_handlers[("/people/new", ("GET",))])(make_request(cast(Any, app), path="/people/new", session=root))

        page = listing.body.decode()
        self.assertTrue(page.startswith("<main>"), "the project's base wraps the page")
        self.assertIn('id="users-table"', page)
        self.assertIn('href="/people/new"', page)
        for modal_id in ("user-password-modal", "user-status-modal", "user-delete-modal"):
            self.assertIn(f'id="{modal_id}"', page)
        form = new.body.decode()
        self.assertIn('action="/people/new"', form)
        self.assertIn('id="users-form-feedback"', form)

    async def test_a_new_user_starts_active_and_an_edit_shows_the_stored_state(self) -> None:
        """Like the model's default: a user created without touching the box can sign in; an edit shows what is stored."""
        root = operator(self.ids["root"], is_staff=True, is_superuser=True)
        async with self.manager.get_session() as session:
            member = await session.get(User, self.ids["member"])
            assert member is not None
            member.is_active = False
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "base.html").write_text("{% block content %}{% endblock %}", encoding="utf-8")
            app = RoutesApp()
            app.ext.environment = install_template_loaders(Environment(enable_async=True), tmp_dir)
            StatelessCSRFManager(cast(Any, app))
            UserManagementFlow(
                base_path="/people", login_path="/signin", user_model=User, auth_settings=AuthSettings(), db_manager=self.manager
            ).register_routes(cast(Any, app), template_prefix="oldman/dashboard/account")
            new = await cast(Any, app.route_handlers[("/people/new", ("GET",))])(make_request(cast(Any, app), path="/people/new", session=root))
            edit = await cast(Any, app.route_handlers[("/people/<user_id:int>/edit", ("GET",))])(
                make_request(cast(Any, app), path=f"/people/{self.ids['member']}/edit", session=root), user_id=self.ids["member"]
            )

        active_box = re.compile(r'<input[^>]*name="is_active"[^>]*>')
        new_box = active_box.search(new.body.decode())
        edit_box = active_box.search(edit.body.decode())
        assert new_box is not None and edit_box is not None
        self.assertIn("checked", new_box.group(0))
        self.assertNotIn("checked", edit_box.group(0))


class SharedUserTableTest(unittest.IsolatedAsyncioTestCase):
    """A project's own UserTable subclass (as the docs show) asks for auth.users.view by itself."""

    async def asyncSetUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": runtime_settings()}))

    async def dispatch(self, session: FakeSession | None) -> Any:
        from oldman.web.auth import UserTable

        class SiteUserTable(UserTable):
            route_name = "users_table"
            route_path = "/users/table"
            model = User

            def object_url(self, row: Any, action: str) -> str:
                return f"/users/{row.id}/{action}"

            async def get(self, request: Any, **route_kwargs: object) -> HTTPResponse:  # stands in for the user list
                return text("USER LIST")

        request = make_request(cast(Any, FakeApp()), path="/users/table", session=session)
        request.headers = {"accept": "application/json"}
        return await SiteUserTable().dispatch_request(request)

    async def test_a_signed_in_member_without_the_permission_gets_403(self) -> None:
        self.assertEqual(403, (await self.dispatch(operator(5))).status)

    async def test_a_signed_out_request_gets_the_login_protocol(self) -> None:
        self.assertEqual(401, (await self.dispatch(None)).status)

    async def test_a_superuser_reaches_the_list(self) -> None:
        self.assertEqual(b"USER LIST", (await self.dispatch(operator(1, is_staff=True, is_superuser=True))).body)


if __name__ == "__main__":
    unittest.main()
