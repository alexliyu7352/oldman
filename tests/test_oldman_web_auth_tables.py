"""oldman.web.auth.tables: the shared user list pieces."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from oldman.auth.models import User
from oldman.web.auth import UserTable, user_cell_value, user_row_actions


def make_user(**overrides: Any) -> User:
    values: dict[str, Any] = {"id": 7, "username": "ada", "email": "ada@example.test", "password_hash": "", "is_active": True, "is_staff": True, "is_superuser": False}
    values.update(overrides)
    return User(**values)


class UserCellTest(unittest.TestCase):
    def test_standard_columns_render_link_badges_and_dates(self) -> None:
        user = make_user(last_login_at=dt.datetime(2026, 9, 17, 8, 30))
        self.assertEqual('<a class="link-primary font-medium" href="/users/7/edit">ada</a>', str(user_cell_value(user, "username", edit_url="/users/7/edit")))
        self.assertEqual("ada", user_cell_value(user, "username"))
        self.assertEqual('<span class="om-badge om-badge-success">Active</span>', str(user_cell_value(user, "is_active")))
        self.assertEqual('<span class="om-badge om-badge-info">Staff</span>', str(user_cell_value(user, "is_staff")))
        self.assertEqual('<span class="om-badge om-badge-default">User</span>', str(user_cell_value(user, "is_superuser")))
        self.assertEqual(("2026-09-17 08:30", "2026-09-17T08:30:00"), user_cell_value(user, "last_login_at"))
        display, raw = user_cell_value(make_user(last_login_at=None), "last_login_at")
        self.assertEqual(('<span class="text-default-500">Never</span>', ""), (str(display), raw))
        self.assertIsNone(user_cell_value(user, "email"))

    def test_row_actions_cover_edit_password_status_and_delete(self) -> None:
        html = str(user_row_actions(make_user(is_active=False), edit_url="/u/7/edit", password_modal_url="/u/7/password-modal", status_modal_url="/u/7/status-modal", delete_modal_url="/u/7/delete-modal"))
        self.assertIn('<span class="sr-only">User actions</span>', html)
        self.assertIn('href="/u/7/edit"', html)
        self.assertIn('data-om-modal-target="#user-password-modal" data-om-modal-url="/u/7/password-modal"', html)
        self.assertIn('data-om-modal-target="#user-status-modal" data-om-modal-url="/u/7/status-modal"', html)
        self.assertIn(">Enable</button>", html)
        self.assertIn('class="om-dropdown-item om-dropdown-item-danger" type="button" data-om-modal-target="#user-delete-modal"', html)


class ProjectUserTable(UserTable):
    route_name = "users_table"
    route_path = "/users/table"
    model = User

    def object_url(self, row: Any, action: str) -> str:
        return f"/users/{row.id}/{action}"


class UserTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.table = ProjectUserTable(SimpleNamespace(args={}, ctx=SimpleNamespace()), initial_filters={}, initial_query="")

    def test_columns_and_callbacks_follow_the_shared_contract(self) -> None:
        names = [column.name for column in self.table.get_columns()]
        self.assertEqual(["username", "email", "display_name", "is_active", "is_staff", "is_superuser", "last_login_at", "action"], names)
        action = self.table.get_columns()[-1]
        self.assertFalse(action.exportable)
        self.assertFalse(action.hideable)

        user = make_user()
        display, raw = self.table.get_column_username_data(user)
        self.assertEqual(('<a class="link-primary font-medium" href="/users/7/edit">ada</a>', "ada"), (str(display), raw))
        self.assertEqual((True, False), (self.table.get_column_is_active_data(user)[1], self.table.get_column_is_superuser_data(user)[1]))
        menu, raw = self.table.get_column_action_data(user)
        self.assertEqual("", raw)
        self.assertIn('data-om-modal-url="/users/7/delete-modal"', str(menu))

    def test_filters_apply_to_the_model_columns(self) -> None:
        query = select(User)
        active = str(asyncio.run(self.table.filter_is_active(query, "true", None)))
        self.assertIn("oldman_user.is_active IS", active)
        since = str(asyncio.run(self.table.filter_last_login_from(query, "2026-09-01T00:00", None)))
        self.assertIn("oldman_user.last_login_at >=", since)
        self.assertIs(query, asyncio.run(self.table.filter_last_login_to(query, "", None)))


if __name__ == "__main__":
    unittest.main()
