"""Password reset tokens, user-id encoding and the email lookup."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from typing import cast

from pydantic import ValidationError
from sqlalchemy.schema import Table

from oldman.auth import (
    AuthSettings,
    PasswordResetSettings,
    PasswordResetTokenGenerator,
    decode_user_id,
    encode_user_id,
    get_user_by_email,
)
from oldman.auth.models import User
from oldman.conf.schemas import DatabaseConfig
from oldman.db.session import DatabaseManager

SECRET = "unit-test-secret-key"


def make_user(**overrides: object) -> User:
    values: dict[str, object] = {
        "id": 7,
        "username": "ada",
        "email": "Ada@Example.test",
        "password_hash": "",
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "last_login_at": dt.datetime(2026, 9, 1, 12, 0, 0),
    }
    values.update(overrides)
    user = User(**values)  # type: ignore[arg-type]
    user.set_password("OldPass!2026")
    return user


class PasswordResetTokenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = dt.datetime(2026, 9, 17, 10, 0, tzinfo=dt.UTC)
        self.generator = PasswordResetTokenGenerator(SECRET, expiry=3600, now=lambda: self.clock)

    def test_token_round_trips_until_it_expires(self) -> None:
        user = make_user()
        token = self.generator.make_token(user)

        self.assertRegex(token, r"^[0-9a-z]+-[0-9a-f]{32}$")
        self.assertTrue(self.generator.check_token(user, token))

        self.clock += dt.timedelta(seconds=3599)
        self.assertTrue(self.generator.check_token(user, token))
        self.clock += dt.timedelta(seconds=2)
        self.assertFalse(self.generator.check_token(user, token))

    def test_token_dies_when_the_password_login_time_or_email_changes(self) -> None:
        user = make_user()
        token = self.generator.make_token(user)

        changed = make_user()
        changed.set_password("NewPass!2026")
        self.assertFalse(self.generator.check_token(changed, token))

        logged_in = make_user(last_login_at=dt.datetime(2026, 9, 17, 10, 5, 0))
        self.assertFalse(self.generator.check_token(logged_in, token))

        other_email = make_user(email="other@example.test")
        self.assertFalse(self.generator.check_token(other_email, token))

        # The unchanged user still validates; the token carries no server-side record.
        self.assertTrue(self.generator.check_token(user, token))

    def test_tampered_missing_and_foreign_tokens_are_rejected(self) -> None:
        user = make_user()
        token = self.generator.make_token(user)
        stamp, digest = token.split("-")

        self.assertFalse(self.generator.check_token(user, None))
        self.assertFalse(self.generator.check_token(user, ""))
        self.assertFalse(self.generator.check_token(user, "no-dash"))
        self.assertFalse(self.generator.check_token(user, f"{stamp}-{'0' * 32}"))
        self.assertFalse(self.generator.check_token(user, f"zz!-{digest}"))
        self.assertFalse(self.generator.check_token(None, token))
        other_secret = PasswordResetTokenGenerator("another-secret", expiry=3600, now=lambda: self.clock)
        self.assertFalse(other_secret.check_token(user, token))
        # A token "from the future" (clock skew or forgery) is not accepted either.
        future = PasswordResetTokenGenerator(SECRET, expiry=3600, now=lambda: self.clock + dt.timedelta(hours=2)).make_token(user)
        self.assertFalse(self.generator.check_token(user, future))

    def test_user_id_encoding_round_trips_and_rejects_garbage(self) -> None:
        for user_id in (1, 7, 123456789):
            encoded = encode_user_id(user_id)
            self.assertNotIn("=", encoded)
            self.assertEqual(user_id, decode_user_id(encoded))
        for value in ("", "not base64!", "YWJj", "x" * 40, encode_user_id(5) + "/.."):
            with self.subTest(value=value):
                self.assertIsNone(decode_user_id(value))


class PasswordResetSettingsTest(unittest.TestCase):
    def test_defaults_match_the_agreed_limits(self) -> None:
        settings = AuthSettings().password_reset
        self.assertEqual(PasswordResetSettings(expiry=86400, ip_limit=5, ip_window=900, email_limit=3, email_window=3600), settings)

    def test_windows_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            PasswordResetSettings(ip_window=0)
        with self.assertRaises(ValidationError):
            PasswordResetSettings(expiry=-1)


class UserByEmailTest(unittest.TestCase):
    def test_lookup_ignores_case_and_blank_input(self) -> None:
        async def scenario() -> None:
            manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
            config = AuthSettings()
            try:
                await manager.initialize()
                async with manager.engine.begin() as connection:
                    await connection.run_sync(cast(Table, User.__table__).create)
                async with manager.get_session() as session:
                    # A legacy row that differs only in case and is no longer active must not win the lookup.
                    session.add(User(username="ada-old", email="ADA@example.test", password_hash="x", is_active=False, is_staff=False, is_superuser=False))
                    session.add(make_user(id=None))
                    session.add(User(username="no-mail", password_hash="x", is_active=True, is_staff=False, is_superuser=False))

                found = await get_user_by_email("  ADA@example.TEST ", auth_settings=config, db_manager=manager)
                self.assertIsNotNone(found)
                self.assertEqual("ada", found.username)  # type: ignore[union-attr]
                self.assertIsNone(await get_user_by_email("nobody@example.test", auth_settings=config, db_manager=manager))
                self.assertIsNone(await get_user_by_email("   ", auth_settings=config, db_manager=manager))
            finally:
                await manager.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
