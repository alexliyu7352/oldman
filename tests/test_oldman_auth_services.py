"""Authentication service contracts backed by a real async SQLite database."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from typing import Any, cast

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Table

from oldman.auth import AuthSettings, UserIdentityError
from oldman.auth.contracts import UserModelContractError
from oldman.auth.models import User
from oldman.auth.services import (
    authenticate_user,
    change_user_password,
    ensure_superuser,
    get_user_by_id,
    get_user_by_username,
    has_staff_access,
    touch_last_login,
    user_identity,
)
from oldman.conf.schemas import DatabaseConfig
from oldman.db.models import DatabaseModel
from oldman.db.session import DatabaseManager


class IndependentUser(DatabaseModel):
    """Mapped class that must not qualify as a configured User."""

    __tablename__ = "test_independent_auth_user"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class OldmanAuthServicesTest(unittest.TestCase):
    """Verify integer User services without importing Admin behavior."""

    def test_authentication_and_staff_authorization_are_separate(self) -> None:
        """An active non-staff user authenticates while failing the staff policy."""
        result = asyncio.run(exercise_user_services())

        self.assertTrue(result["ordinary_authenticated"])
        self.assertFalse(result["ordinary_staff_access"])
        self.assertFalse(result["wrong_password_authenticated"])
        self.assertFalse(result["inactive_authenticated"])
        self.assertTrue(result["staff_access"])
        self.assertFalse(result["staff_superuser_access"])
        self.assertTrue(result["superuser_access"])

    def test_integer_identity_login_time_and_bootstrap_use_real_sqlite(self) -> None:
        """Every identity-bearing service uses the same database-generated int."""
        result = asyncio.run(exercise_user_services())

        self.assertEqual("ordinary", result["username_lookup"])
        self.assertEqual("ordinary", result["identity_lookup"])
        self.assertIsInstance(result["identity"], int)
        self.assertIsInstance(result["last_login_at"], dt.datetime)
        self.assertEqual("root", result["superuser_username"])
        self.assertTrue(result["superuser_is_staff"])
        self.assertTrue(result["superuser_is_superuser"])
        self.assertTrue(result["superuser_password_matches"])
        self.assertEqual("ordinary", result["password_user"])
        self.assertTrue(result["changed_password_matches"])
        self.assertIsNone(result["missing_password_user"])
        self.assertIsNone(result["zero_identity_user"])
        self.assertIsNone(result["negative_identity_user"])

    def test_identity_parameters_reject_non_integer_values(self) -> None:
        """Transport strings and bools cannot leak into Auth's Python API."""
        asyncio.run(assert_non_integer_identity_rejected(self))

    def test_user_identity_requires_a_persisted_integer_value(self) -> None:
        """The mapped User value is returned unchanged and never coerced."""
        self.assertEqual(7, user_identity(User(id=7, username="a", password_hash="")))

        with self.assertRaisesRegex(UserIdentityError, "before persistence"):
            user_identity(User(username="pending", password_hash=""))

        wrong_type = User(id=8, username="wrong", password_hash="")
        wrong_type.id = cast(Any, "8")
        with self.assertRaisesRegex(UserModelContractError, "integer"):
            user_identity(wrong_type)

        bool_identity = User(id=9, username="bool", password_hash="")
        bool_identity.id = cast(Any, True)
        with self.assertRaisesRegex(UserModelContractError, "integer"):
            user_identity(bool_identity)

    def test_resolver_rejects_a_model_outside_abstract_user(self) -> None:
        """A matching-looking independent mapper cannot replace AbstractUser."""
        from oldman.auth import get_user_model

        try:
            get_user_model(AuthSettings(user_model=(f"{IndependentUser.__module__}.{IndependentUser.__name__}")))
        except Exception as exc:
            self.assertIsInstance(exc, UserModelContractError)
            self.assertIn("AbstractUser", str(exc))
        else:
            self.fail("independent User model was accepted")


async def exercise_user_services() -> dict[str, object]:
    """Exercise the public services through one real DatabaseManager."""
    manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
    config = AuthSettings()
    try:
        await manager.initialize()
        async with manager.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)

        async with manager.get_session() as session:
            ordinary = User(
                username="ordinary",
                password_hash="",
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            ordinary.set_password("OrdinaryPass123")
            inactive = User(
                username="inactive",
                password_hash="",
                is_active=False,
                is_staff=True,
                is_superuser=False,
            )
            inactive.set_password("InactivePass123")
            staff = User(
                username="staff",
                password_hash="",
                is_active=True,
                is_staff=True,
                is_superuser=False,
            )
            staff.set_password("StaffPass123")
            superuser = User(
                username="superuser",
                password_hash="",
                is_active=True,
                is_staff=False,
                is_superuser=True,
            )
            superuser.set_password("SuperPass123")
            session.add_all((ordinary, inactive, staff, superuser))
            await session.flush()
            ordinary_id = ordinary.id

        ordinary_user = await authenticate_user(
            " ordinary ",
            "OrdinaryPass123",
            auth_settings=config,
            db_manager=manager,
        )
        wrong_password = await authenticate_user(
            "ordinary",
            "wrong",
            auth_settings=config,
            db_manager=manager,
        )
        inactive_user = await authenticate_user(
            "inactive",
            "InactivePass123",
            auth_settings=config,
            db_manager=manager,
        )
        staff_user = await authenticate_user(
            "staff",
            "StaffPass123",
            auth_settings=config,
            db_manager=manager,
        )
        superuser_user = await authenticate_user(
            "superuser",
            "SuperPass123",
            auth_settings=config,
            db_manager=manager,
        )
        by_username = await get_user_by_username(
            "ordinary",
            auth_settings=config,
            db_manager=manager,
        )
        by_identity = await get_user_by_id(
            ordinary_id,
            auth_settings=config,
            db_manager=manager,
        )
        await touch_last_login(
            ordinary_id,
            auth_settings=config,
            db_manager=manager,
        )
        refreshed = await get_user_by_id(
            ordinary_id,
            auth_settings=config,
            db_manager=manager,
        )
        root = await ensure_superuser(
            "root",
            "RootPass123",
            "root@example.test",
            auth_settings=config,
            db_manager=manager,
        )
        password_user = await change_user_password(
            ordinary_id,
            "ChangedPass123",
            auth_settings=config,
            db_manager=manager,
        )
        changed_password_user = await get_user_by_id(
            ordinary_id,
            auth_settings=config,
            db_manager=manager,
        )
        missing_password_user = await change_user_password(
            999999,
            "MissingPass123",
            auth_settings=config,
            db_manager=manager,
        )

        assert by_identity is not None
        return {
            "ordinary_authenticated": ordinary_user is not None,
            "ordinary_staff_access": has_staff_access(ordinary_user),
            "wrong_password_authenticated": wrong_password is not None,
            "inactive_authenticated": inactive_user is not None,
            "staff_access": has_staff_access(staff_user),
            "staff_superuser_access": has_staff_access(
                staff_user,
                require_superuser=True,
            ),
            "superuser_access": has_staff_access(
                superuser_user,
                require_superuser=True,
            ),
            "username_lookup": getattr(by_username, "username", None),
            "identity_lookup": getattr(by_identity, "username", None),
            "identity": user_identity(by_identity),
            "last_login_at": getattr(refreshed, "last_login_at", None),
            "superuser_username": root.username,
            "superuser_is_staff": root.is_staff,
            "superuser_is_superuser": root.is_superuser,
            "superuser_password_matches": root.check_password("RootPass123"),
            "password_user": getattr(password_user, "username", None),
            "changed_password_matches": bool(changed_password_user and changed_password_user.check_password("ChangedPass123")),
            "missing_password_user": missing_password_user,
            "zero_identity_user": await get_user_by_id(
                0,
                auth_settings=config,
                db_manager=manager,
            ),
            "negative_identity_user": await get_user_by_id(
                -1,
                auth_settings=config,
                db_manager=manager,
            ),
        }
    finally:
        await manager.close()


async def assert_non_integer_identity_rejected(
    test: unittest.TestCase,
) -> None:
    """Assert every identity-bearing service enforces its Python boundary."""
    manager = DatabaseManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
    config = AuthSettings()
    try:
        await manager.initialize()
        async with manager.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)
        for value in ("1", 1.0, True, None):
            with test.subTest(value=value):
                with test.assertRaisesRegex(TypeError, "user_id must be an int"):
                    await get_user_by_id(
                        cast(Any, value),
                        auth_settings=config,
                        db_manager=manager,
                    )
                with test.assertRaisesRegex(TypeError, "user_id must be an int"):
                    await change_user_password(
                        cast(Any, value),
                        "ChangedPass123",
                        auth_settings=config,
                        db_manager=manager,
                    )
                with test.assertRaisesRegex(TypeError, "user_id must be an int"):
                    await touch_last_login(
                        cast(Any, value),
                        auth_settings=config,
                        db_manager=manager,
                    )
    finally:
        await manager.close()


if __name__ == "__main__":
    unittest.main()
