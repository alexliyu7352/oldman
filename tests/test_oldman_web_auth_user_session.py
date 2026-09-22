"""Shared Web user-session behavior tests."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from jinja2 import DictLoader, Environment
from sqlalchemy.schema import Table

import oldman.conf as conf
from oldman.auth.models import User
from oldman.auth.settings import AuthSettings
from oldman.conf.schemas import DatabaseConfig, SessionConfig
from oldman.db.session import DatabaseManager
from oldman.i18n import LanguageRegistry
from oldman.web.auth import (
    SessionPasswordForm,
    UserPasswordForm,
    render_session_password_modal,
    save_language_preference,
    session_profile,
    update_session_password,
)
from oldman.web.session import Session, SessionData


class SharedUserSessionBehaviorTest(unittest.IsolatedAsyncioTestCase):
    """Exercise shared account behavior against a real SQLite User."""

    async def asyncSetUp(self) -> None:
        """Create one isolated configured User and template environment."""
        self.manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        self.auth_settings = AuthSettings()
        await self.manager.initialize()
        async with self.manager.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)
        async with self.manager.get_session() as database_session:
            user = User(
                username="alice",
                display_name="Alice",
                password_hash="",
                is_active=True,
                is_staff=True,
                is_superuser=False,
            )
            user.set_password("OldPass2026")
            database_session.add(user)
            await database_session.flush()
            assert user.id is not None
            self.user_id = user.id

        environment = Environment(
            loader=DictLoader(
                {"oldman/auth/partials/password_form.html": ('<form action="{{ action }}">{{ user.username }}|{{ form.password.label.text }}</form>')}
            ),
            autoescape=True,
            enable_async=True,
        )
        # The double sits at the interface seam, because the views reach the store through
        # the installed Session extension rather than through whatever object ctx happens to hold.
        self.session_interface = SimpleNamespace(
            force_logout_user=AsyncMock(return_value=("first-sid", "second-sid")),
            _logout_request=AsyncMock(),
        )
        self.session_manager = Session()
        self.session_manager.interface = cast(Any, self.session_interface)
        self.app = SimpleNamespace(
            ctx=SimpleNamespace(session=self.session_manager),
            ext=SimpleNamespace(environment=environment),
        )

    async def asyncTearDown(self) -> None:
        """Close the per-test database engine."""
        await self.manager.close()

    def test_session_profile_formats_only_the_typed_login_snapshot(self) -> None:
        """The page view model should need no database-backed User fields."""
        profile = session_profile(
            SessionData(
                user_id=self.user_id,
                username="alice",
                display_name="Alice",
                login_ip="127.0.0.1",
                login_time=1_700_000_000,
                is_active=True,
                is_staff=True,
            )
        )
        unknown = session_profile(SessionData())

        self.assertEqual("Alice", profile.display_name)
        self.assertEqual("127.0.0.1", profile.login_ip)
        self.assertEqual("2023-11-14 22:13 UTC", profile.login_time)
        self.assertEqual("-", unknown.login_time)
        self.assertEqual("-", unknown.login_ip)

    async def test_password_form_preserves_the_existing_policy(self) -> None:
        """Shared password validation should retain complexity and confirmation rules."""
        request = self.make_request(
            method="POST",
            form={"password": "short", "confirm_password": "different"},
        )
        form = UserPasswordForm.from_request(request)

        self.assertFalse(await form.validate())
        self.assertIn("password", form.errors)
        self.assertIn("confirm_password", form.errors)

    async def test_password_modal_uses_the_session_identity_and_supplied_action(self) -> None:
        """A caller cannot select another User through the current-session endpoint."""
        async with self.manager.get_session() as database_session:
            user = await database_session.get(User, self.user_id)
            assert user is not None
            user.username = '<img src=x onerror="alert(1)">'

        response = await render_session_password_modal(
            self.make_request(),
            action="/admin/user-session/password",
            auth_settings=self.auth_settings,
            db_manager=self.manager,
        )
        assert response.body is not None
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertIn("&lt;img", payload["title"])
        self.assertNotIn("<img", payload["title"])
        self.assertIn('action="/admin/user-session/password"', payload["html"])
        self.assertIn("&lt;img", payload["html"])
        self.assertNotIn("<img", payload["html"])

    async def test_password_submit_updates_the_current_user_and_reports_missing_user(self) -> None:
        """A valid form should update exactly the User stored in SessionData."""
        response = await update_session_password(
            self.make_request(
                method="POST",
                form={
                    "current_password": "OldPass2026",
                    "password": "NewPass2026",
                    "confirm_password": "NewPass2026",
                },
            ),
            login_url="/admin/login",
            auth_settings=self.auth_settings,
            db_manager=self.manager,
        )
        assert response.body is not None
        payload = json.loads(response.body)

        async with self.manager.get_read_session() as database_session:
            updated = await database_session.get(User, self.user_id)
        self.assertEqual(200, response.status)
        self.assertEqual(
            ["feedback", "close_modal", "redirect"],
            [action["action"] for action in payload["actions"]],
        )
        self.assertEqual("/admin/login", payload["actions"][-1]["url"])
        self.assertEqual("Session password changed", payload["actions"][0]["title"])
        self.assertEqual({}, payload["data"])
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertTrue(updated.check_password("NewPass2026"))

        missing_request = self.make_request(
            method="POST",
            form={
                "current_password": "OldPass2026",
                "password": "OtherPass2026",
                "confirm_password": "OtherPass2026",
            },
            session=SessionData(
                user_id=999999,
                username="missing",
                is_active=True,
            ),
        )
        missing_response = await update_session_password(
            missing_request,
            auth_settings=self.auth_settings,
            db_manager=self.manager,
        )
        self.assertEqual(404, missing_response.status)
        assert missing_response.body is not None
        missing_payload = json.loads(missing_response.body)
        self.assertEqual(1100, missing_payload["error_code"])
        self.assertEqual("Current session user not found", missing_payload["message"])
        self.assertEqual([], missing_payload["actions"])

    async def test_changing_your_own_password_ends_every_session_you_had(self) -> None:
        """No session may outlive the password it was opened under, this browser's included."""
        request = self.make_request(
            method="POST",
            form={
                "current_password": "OldPass2026",
                "password": "NewPass2026",
                "confirm_password": "NewPass2026",
            },
        )

        response = await update_session_password(
            request,
            auth_settings=self.auth_settings,
            db_manager=self.manager,
        )

        self.assertEqual(200, response.status)
        # Every session the user held, wherever it was opened...
        self.session_interface.force_logout_user.assert_awaited_once_with(self.user_id)
        # ...and this request's own cookie, so no new one is issued to take its place.
        self.session_interface._logout_request.assert_awaited_once_with(request)

    async def test_a_wrong_current_password_changes_nothing(self) -> None:
        """Holding a session is not by itself permission to take the account over."""
        response = await update_session_password(
            self.make_request(
                method="POST",
                form={
                    "current_password": "NotTheOldPass2026",
                    "password": "NewPass2026",
                    "confirm_password": "NewPass2026",
                },
            ),
            auth_settings=self.auth_settings,
            db_manager=self.manager,
        )
        assert response.body is not None
        payload = json.loads(response.body)

        async with self.manager.get_read_session() as database_session:
            unchanged = await database_session.get(User, self.user_id)
        assert unchanged is not None

        self.assertEqual(1100, payload["error_code"])
        self.assertIn("current_password", payload["errors"])
        self.assertTrue(unchanged.check_password("OldPass2026"))
        self.session_interface.force_logout_user.assert_not_awaited()

    async def test_the_current_password_is_required_at_all(self) -> None:
        """The form an administrator uses for someone else must not be the one used here."""
        form = SessionPasswordForm.from_request(
            self.make_request(
                method="POST",
                form={"password": "NewPass2026", "confirm_password": "NewPass2026"},
            )
        )

        self.assertFalse(await form.validate())
        self.assertIn("current_password", form.errors)

    def test_language_preference_normalizes_alias_and_writes_both_cookies(self) -> None:
        """Both public language routes should consume one canonical cookie response."""
        registry = LanguageRegistry(
            {
                "en": {},
                "zh-Hans": {"aliases": ["zh-CN"]},
            }
        )
        request = self.make_request()
        request.json = {"language": "zh-CN"}

        settings = SimpleNamespace(
            web=SimpleNamespace(session=SessionConfig(cookie_secure=True)),
        )
        with patch.dict(conf.__dict__, {"settings": settings}):
            response = save_language_preference(request, registry=registry)
        assert response.body is not None
        payload = json.loads(response.body)
        language_cookie = response.cookies.get_cookie("lang")
        preference_cookie = response.cookies.get_cookie("preferred_language")
        assert language_cookie is not None
        assert preference_cookie is not None

        self.assertEqual(200, response.status)
        self.assertEqual("zh-Hans", payload["data"]["language"])
        self.assertEqual("zh-Hans", language_cookie.value)
        self.assertEqual(
            "zh-Hans",
            preference_cookie.value,
        )
        self.assertTrue(language_cookie.secure)

        request.json = {"language": "not-supported"}
        invalid = save_language_preference(request, registry=registry)
        self.assertEqual(200, invalid.status)
        assert invalid.body is not None
        self.assertEqual(1100, json.loads(invalid.body)["error_code"])

    def make_request(
        self,
        *,
        method: str = "GET",
        form: dict[str, str] | None = None,
        session: SessionData | None = None,
    ) -> Any:
        """Build the request surface consumed by shared user-session helpers."""
        return SimpleNamespace(
            app=self.app,
            ctx=SimpleNamespace(
                csrf_token="test-csrf",
                session=session
                or SessionData(
                    user_id=self.user_id,
                    username="alice",
                    display_name="Alice",
                    login_ip="127.0.0.1",
                    login_time=1_700_000_000,
                    is_active=True,
                    is_staff=True,
                ),
            ),
            files={},
            form=form or {},
            json=None,
            method=method,
        )


if __name__ == "__main__":
    unittest.main()
