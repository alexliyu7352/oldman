"""Shared login helpers: form values, error redirects and opening the session."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import oldman.conf as conf
from oldman.auth import AuthSettings
from oldman.web.auth import (
    LoginRateLimit,
    form_value,
    login_error_message,
    login_error_url,
    login_user,
    logout_user,
    remember_me_requested,
)
from oldman.web.response import redirect_response
from tests.test_oldman_admin_runtime import (
    FakeApp,
    FakeSession,
    MemoryWindowCounter,
    make_admin_user,
    make_request,
    runtime_settings,
)


class LoginHelperTest(unittest.TestCase):
    def test_form_values_and_remember_me(self) -> None:
        request = SimpleNamespace(form={"username": ["ada"], "remember_me": ["on"], "next": []})
        self.assertEqual("ada", form_value(request, "username"))
        # 空列表表示"这个字段没提上来"，回退到 default；
        self.assertEqual("/fallback", form_value(request, "next", "/fallback"))
        self.assertEqual("", form_value(SimpleNamespace(form=None), "username"))
        # 提交上来的空串是用户的输入，不能被 default 顶掉。
        self.assertEqual("", form_value(SimpleNamespace(form={"next": [""]}), "next", "/fallback"))
        self.assertTrue(remember_me_requested(request))
        for value in ("", "0", "false", "off", "no"):
            self.assertFalse(remember_me_requested(SimpleNamespace(form={"remember_me": [value]})))

    def test_error_redirects_and_messages(self) -> None:
        self.assertEqual("/login?next=%2Fdash&error=invalid_credentials", login_error_url("/login", "/dash", "invalid_credentials"))
        self.assertEqual("Invalid username or password.", login_error_message("invalid_credentials"))
        self.assertEqual("Invalid username or password.", login_error_message(["invalid_credentials"]))
        self.assertEqual("", login_error_message("something_else"))
        self.assertEqual("", login_error_message(None))
        self.assertEqual("Too many sign-in attempts. Please try again later.", login_error_message("rate_limited"))


class LoginRateLimitTest(unittest.TestCase):
    """Failed sign-ins are counted per address and per username, and only failures count."""

    def setUp(self) -> None:
        self.counter = MemoryWindowCounter()
        self.auth_settings = AuthSettings()
        self.limit = LoginRateLimit(auth_settings=self.auth_settings, counter=self.counter)
        self.request = SimpleNamespace(client_ip="203.0.113.10", ip="203.0.113.10")

    def test_nothing_is_counted_until_an_attempt_fails(self) -> None:
        """A visitor who signs in first time never touches a counter."""
        self.assertIsNone(asyncio.run(self.limit.retry_after(self.request, "ada")))
        self.assertEqual({}, self.counter.windows)

    def test_one_failure_charges_both_the_address_and_the_username(self) -> None:
        """Either budget alone can be exhausted, so both have to be charged."""
        asyncio.run(self.limit.record_failure(self.request, "ada"))

        self.assertEqual({("ip:203.0.113.10", "login"): 1, ("user:ada", "login"): 1}, self.counter.windows)

    def test_case_variants_of_a_username_share_one_budget(self) -> None:
        """Otherwise "ada", "Ada" and "ADA" would each get a fresh budget for the same account."""
        self.auth_settings.login.username_limit = 2
        self.auth_settings.login.ip_limit = 0
        for attempted in ("ada", "Ada", " ADA "):
            asyncio.run(self.limit.record_failure(self.request, attempted))

        self.assertEqual({("user:ada", "login"): 3}, self.counter.windows)
        self.assertIsNotNone(asyncio.run(self.limit.retry_after(self.request, "AdA")))

    def test_the_wait_is_whatever_is_left_of_the_window(self) -> None:
        """Retry-After has to name the moment the count actually resets."""
        self.auth_settings.login.username_limit = 1
        asyncio.run(self.limit.record_failure(self.request, "ada"))

        waited = asyncio.run(self.limit.retry_after(self.request, "ada"))

        self.assertIn(waited, range(1, self.auth_settings.login.username_window + 1))

    def test_a_zero_limit_disables_that_counter_entirely(self) -> None:
        """Turning a limit off must not leave it still reading or writing Redis."""
        self.auth_settings.login.ip_limit = 0
        self.auth_settings.login.username_limit = 0

        asyncio.run(self.limit.record_failure(self.request, "ada"))

        self.assertEqual({}, self.counter.windows)
        self.assertIsNone(asyncio.run(self.limit.retry_after(self.request, "ada")))

    def test_an_empty_username_counts_only_against_the_address(self) -> None:
        """A blank submission is still an attempt, but there is no account to attribute it to."""
        asyncio.run(self.limit.record_failure(self.request, "   "))

        self.assertEqual({("ip:203.0.113.10", "login"): 1}, self.counter.windows)


class LoginUserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = runtime_settings()
        self.enterContext(patch.dict(conf.__dict__, {"settings": self.settings}))
        self.app = FakeApp()
        self.manager = SimpleNamespace(exclusive_login=AsyncMock(return_value="new-session-id"), update_session_id_to_cookie=Mock())
        self.app.ctx.session = self.manager
        self.user = make_admin_user()

    def test_login_user_opens_an_exclusive_session_and_sets_the_cookie(self) -> None:
        request = make_request(self.app, path="/login", session=FakeSession())
        request.client_ip = "198.51.100.7"
        request.ip = "10.0.0.1"
        response = redirect_response("/dash")

        with patch("oldman.web.auth.login.touch_last_login", AsyncMock()) as stamp:
            result = asyncio.run(login_user(request, self.user, response=response, remember=True))

        self.assertIs(response, result)
        session_data = self.manager.exclusive_login.await_args.args[0]
        self.assertIsInstance(session_data, FakeSession)
        self.assertEqual(
            (self.user.id, "198.51.100.7", self.settings.web.session.remember_expiry),
            (session_data.user_id, session_data.login_ip, session_data.expiry),
        )
        stamp.assert_awaited_once_with(self.user.id, auth_settings=None, db_manager=None)
        self.manager.update_session_id_to_cookie.assert_called_once_with(response, "new-session-id", session_data)

    def test_login_user_needs_the_session_middleware(self) -> None:
        request = make_request(self.app, path="/login", session=FakeSession())
        request.ctx.session = None
        with self.assertRaisesRegex(RuntimeError, "Session middleware"):
            asyncio.run(login_user(request, self.user, response=redirect_response("/")))

    def test_logout_user_ends_the_session_and_redirects(self) -> None:
        request = make_request(self.app, path="/logout", session=FakeSession())
        with patch("oldman.web.auth.login.Session.logout_session", AsyncMock()) as logout:
            response = asyncio.run(logout_user(request, "/login"))
        logout.assert_awaited_once_with(request)
        self.assertEqual((302, "/login"), (response.status, response.headers["Location"]))


if __name__ == "__main__":
    unittest.main()
