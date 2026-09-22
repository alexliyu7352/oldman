"""The shared user row-action modals: enable/disable and delete."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jinja2 import Environment, FileSystemLoader

from oldman.auth.models import User
from oldman.web.auth import user_delete_modal_response, user_status_modal_response

TEMPLATES = Path(__file__).resolve().parents[1] / "oldman" / "web" / "templates"


def make_request() -> Any:
    """A request carrying only what the partials need: the environment and the CSRF token."""
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, enable_async=True)
    environment.globals["_"] = lambda message: message
    return SimpleNamespace(
        app=SimpleNamespace(ext=SimpleNamespace(environment=environment)),
        ctx=SimpleNamespace(csrf_token="csrf-token"),
    )


def make_user(*, is_active: bool = True, username: str = "alice") -> User:
    return User(id=12, username=username, email="alice@example.test", display_name="Alice", password_hash="", is_active=is_active, is_staff=True)


def payload(response: Any) -> dict[str, Any]:
    return json.loads(response.body)


class UserStatusModalTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_disabled_user_is_offered_the_enabling_form(self) -> None:
        response = await user_status_modal_response(make_request(), make_user(is_active=False), action="/users/12/status")
        body = payload(response)

        self.assertEqual(200, response.status)
        self.assertEqual("Enable User · alice", body["title"])
        self.assertIn('action="/users/12/status"', body["html"])
        self.assertIn('name="csrfmiddlewaretoken" value="csrf-token"', body["html"])
        self.assertIn('name="is_active" value="true"', body["html"])
        self.assertIn("Enable user?", body["html"])
        self.assertIn("om-confirm-icon-success", body["html"])

    async def test_an_active_user_is_offered_the_disabling_form(self) -> None:
        body = payload(await user_status_modal_response(make_request(), make_user(is_active=True), action="/users/12/status"))

        self.assertEqual("Disable User · alice", body["title"])
        self.assertIn('name="is_active" value="false"', body["html"])
        self.assertIn("Disable user?", body["html"])
        self.assertIn("om-button-danger", body["html"])

    async def test_a_missing_user_answers_the_not_found_modal(self) -> None:
        response = await user_status_modal_response(make_request(), None, action="")

        # 行已经没了也要让弹窗打得开，才能把这句话显示出来。
        self.assertEqual(200, response.status)
        self.assertEqual({"title": "Change Status", "html": '<p class="text-default-500 mb-0">User not found.</p>'}, payload(response))


class UserModalTitleEscapingTest(unittest.IsolatedAsyncioTestCase):
    """标题按 HTML 写入（组件用 innerHTML），所以用户名必须转义后才拼进去。"""

    async def test_both_modals_escape_the_username_in_the_title(self) -> None:
        hostile = make_user(username='<img src=x onerror="alert(1)">')

        status = payload(await user_status_modal_response(make_request(), hostile, action="/status"))
        delete = payload(await user_delete_modal_response(make_request(), hostile, action="/delete"))

        for title in (status["title"], delete["title"]):
            self.assertNotIn("<img", title)
            self.assertIn("&lt;img", title)


class UserDeleteModalTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_delete_form_posts_to_the_given_action(self) -> None:
        response = await user_delete_modal_response(make_request(), make_user(is_active=True), action="/users/12/delete")
        body = payload(response)

        self.assertEqual(200, response.status)
        self.assertEqual("Delete User · alice", body["title"])
        self.assertIn('action="/users/12/delete"', body["html"])
        self.assertIn('name="csrfmiddlewaretoken" value="csrf-token"', body["html"])
        self.assertIn("Delete user?", body["html"])
        self.assertNotIn('name="is_active"', body["html"])

    async def test_a_missing_user_answers_the_not_found_modal(self) -> None:
        response = await user_delete_modal_response(make_request(), None, action="")

        # 行已经没了也要让弹窗打得开，才能把这句话显示出来。
        self.assertEqual(200, response.status)
        self.assertEqual({"title": "Delete User", "html": '<p class="text-default-500 mb-0">User not found.</p>'}, payload(response))


if __name__ == "__main__":
    unittest.main()
