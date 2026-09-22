"""Oldman Admin default user tests."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy import Boolean, Column, Integer, MetaData, Numeric, String, Uuid, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Table
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from oldman.auth import (
    authenticate_user,
    ensure_superuser,
    get_user_by_id,
    get_user_model,
    touch_last_login,
    user_identity,
)
from oldman.auth.base import normalize_user_staff_flags
from oldman.auth.models import User
from oldman.auth.settings import AuthSettings
from oldman.db.models import DatabaseModel
from oldman.web.auth import session_data_for_user
from oldman.web.session import SessionData

ROOT = Path(__file__).resolve().parents[1]


class AdminAltUser(DatabaseModel):
    """Custom Admin user with a non-id primary key."""

    __tablename__ = "test_admin_alt_user"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    uid: Mapped[int] = mapped_column(Integer, primary_key=True)


class OldmanAdminDefaultUserTest(unittest.TestCase):
    """验证默认 Admin 用户模型和认证 payload。"""

    def test_default_admin_user_model_has_required_permission_fields(self) -> None:
        """默认用户模型必须包含 Admin 权限字段。"""
        columns = User.__table__.columns

        self.assertEqual("oldman_user", User.__tablename__)
        self.assertIn("is_staff", columns)
        self.assertIn("is_superuser", columns)
        self.assertIn("password_hash", columns)
        table = cast(Table, User.__table__)
        self.assertIn("ck_oldman_user_superuser_is_staff", {constraint.name for constraint in table.constraints})
        for name in ("is_active", "is_staff", "is_superuser"):
            self.assertIsNone(columns[name].server_default)

    def test_default_admin_form_never_exposes_password_hash(self) -> None:
        """User CRUD must not expose password hashes and must keep add/delete available."""
        from oldman.apps.admin.model_admin import AdminUserModelAdmin

        admin = AdminUserModelAdmin(User)
        user = User(username="root", password_hash="secret")
        request = type(
            "Request",
            (),
            {
                "ctx": type(
                    "Context",
                    (),
                    {
                        "session": SessionData(
                            user_id=1,
                            username="root",
                            is_active=True,
                            is_staff=True,
                            is_superuser=True,
                        )
                    },
                )(),
                "method": "GET",
                "form": {},
                "files": {},
            },
        )()
        form = admin.build_form(request, instance=user)

        self.assertNotIn("password_hash", form._fields)
        self.assertTrue(admin.has_add_permission(request))
        self.assertTrue(admin.has_delete_permission(request))

    def test_default_admin_user_keeps_source_page_metadata(self) -> None:
        """内置用户管理页必须保留源版文案、图标和表单壳层 metadata。"""
        from oldman.apps.admin.model_admin import AdminUserModelAdmin, ModelAdmin

        admin = AdminUserModelAdmin(User)
        user = User(id=1, username="root", password_hash="")

        self.assertEqual("User", str(admin.verbose_name))
        self.assertEqual("Users", str(admin.verbose_name_plural))
        self.assertEqual("ri-user-add-line", admin.add_button_icon)
        self.assertEqual("New User", str(admin.get_form_page_title(None)))
        self.assertEqual("Edit User", str(admin.get_form_page_title(user)))
        self.assertEqual("User", str(admin.get_form_document_title(user)))
        self.assertEqual("Users", str(admin.form_back_label))
        self.assertEqual("", admin.form_card_classes)
        self.assertFalse(admin.show_form_card_header)
        self.assertEqual("Save", str(admin.get_form_submit_label(None)))

        neutral_admin = ModelAdmin(AdminAltUser)
        self.assertEqual("Admin Alt User", neutral_admin.verbose_name)
        self.assertEqual("ri-add-line", neutral_admin.add_button_icon)
        self.assertEqual("max-w-3xl", neutral_admin.form_card_classes)
        self.assertTrue(neutral_admin.show_form_card_header)
        self.assertEqual("Create", neutral_admin.get_form_submit_label(None))

    def test_superuser_implies_staff_normalization(self) -> None:
        """超级用户归一化后必须自动拥有 staff 权限。"""
        user = User(username="root", password_hash="", is_staff=False, is_superuser=True)

        normalize_user_staff_flags(user)

        self.assertTrue(user.is_staff)

    def test_password_helpers_work_for_default_model(self) -> None:
        """默认模型必须能设置和校验密码。"""
        user = User(username="root", password_hash="")

        user.set_password("secret")

        self.assertTrue(user.check_password("secret"))
        self.assertFalse(user.check_password("wrong"))

    def test_session_mapping_contains_the_shared_authorization_snapshot(self) -> None:
        """Admin login should use the public typed Web Auth mapping."""
        user = User(
            id=1,
            username="root",
            display_name="Root",
            password_hash="",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        session = session_data_for_user(SessionData, user, expiry=600)

        self.assertEqual(1, session.user_id)
        self.assertEqual("root", session.username)
        self.assertTrue(session.is_staff)
        self.assertTrue(session.is_superuser)
        self.assertEqual(600, session.expiry)

    def test_ensure_superuser_preserves_fixed_source_create_and_update_branches(self) -> None:
        """真实 SQLite 会话必须区分新建空密码和既有用户更新。"""
        result = asyncio.run(exercise_default_admin_branches())

        self.assertTrue(result.empty_password_matches)
        self.assertEqual("empty-password", result.empty_display_name)
        self.assertEqual(result.existing_hash_before, result.existing_hash_after)
        self.assertIsNone(result.existing_display_name)
        # The service stores one spelling per address, whatever the CLI or a script passed in.
        self.assertEqual("existing@example.test", result.existing_email)

    def test_touch_last_login_persists_the_utc_clock_in_real_sqlite(self) -> None:
        """登录时间服务必须在无视觉门禁 trigger 的真实数据库中持久化。"""
        instant = dt.datetime(2026, 7, 12, 22, 45, 30, tzinfo=dt.UTC)

        persisted = asyncio.run(exercise_touch_last_login(instant))

        self.assertEqual(instant.replace(tzinfo=None), persisted)

    def test_auth_settings_resolves_default_user_model(self) -> None:
        """Auth App settings should default to the built-in User."""
        self.assertIs(User, get_user_model(AuthSettings()))

    def test_user_identity_uses_the_fixed_integer_id(self) -> None:
        """登录写 Session 时直接读取已冻结的 User.id。"""
        user = User(id=42, username="root", password_hash="")

        self.assertEqual(42, user_identity(user))

    def test_authentication_api_is_owned_by_top_level_auth(self) -> None:
        """Admin must consume public Auth without retaining a second auth package."""
        from oldman import auth as auth_package

        self.assertIs(authenticate_user, auth_package.authenticate_user)
        self.assertIs(get_user_by_id, auth_package.get_user_by_id)
        self.assertIs(get_user_model, auth_package.get_user_model)
        self.assertNotIn("User", auth_package.__all__)
        legacy_auth = ROOT / "oldman" / "apps" / "admin" / "auth"
        self.assertFalse((legacy_auth / "__init__.py").exists())
        self.assertFalse((legacy_auth / "services.py").exists())

class OldmanAdminCoerceValueTest(unittest.TestCase):
    """Verify direct SQLAlchemy column coercion contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        metadata = MetaData()
        cls.table = Table(
            "test_admin_coerce_value",
            metadata,
            Column("name", String(64), nullable=False),
            Column("user_id", Uuid(as_uuid=True), nullable=False),
            Column("amount", Numeric(12, 2), nullable=False),
            Column("ratio", Numeric(asdecimal=False), nullable=False),
            Column("enabled", Boolean, nullable=False),
            Column("optional_amount", Numeric(12, 2), nullable=True),
        )

    def test_string_uuid_and_decimal_follow_column_python_types(self) -> None:
        """String、UUID 和 Numeric 必须返回 column.python_type 对应值。"""
        from oldman.apps.admin.crud import coerce_value

        user_id = uuid.uuid4()

        self.assertEqual("42", coerce_value(self.table.c.name, 42))
        self.assertEqual("alice", coerce_value(self.table.c.name, ["alice", "ignored"]))
        self.assertEqual(user_id, coerce_value(self.table.c.user_id, str(user_id)))
        self.assertIs(user_id, coerce_value(self.table.c.user_id, user_id))
        self.assertEqual(Decimal("12.30"), coerce_value(self.table.c.amount, "12.30"))
        self.assertIsInstance(coerce_value(self.table.c.amount, "12.30"), Decimal)
        self.assertEqual(12.5, coerce_value(self.table.c.ratio, "12.5"))
        self.assertIsInstance(coerce_value(self.table.c.ratio, "12.5"), float)
        self.assertIsNone(coerce_value(self.table.c.optional_amount, ""))

    def test_boolean_strings_are_parsed_instead_of_using_truthiness(self) -> None:
        """字符串 false/0/off 不能被 Python 字符串真值误判为 True。"""
        from oldman.apps.admin.crud import coerce_value

        for value in ("1", "true", "yes", "on", True):
            with self.subTest(value=value):
                self.assertIs(coerce_value(self.table.c.enabled, value), True)
        for value in ("0", "false", "no", "off", False):
            with self.subTest(value=value):
                self.assertIs(coerce_value(self.table.c.enabled, value), False)

    def test_invalid_typed_values_raise_value_error(self) -> None:
        """非法 Boolean、UUID 和 Decimal 输入必须直接失败。"""
        from oldman.apps.admin.crud import coerce_value

        for column, value in (
            (self.table.c.enabled, "sometimes"),
            (self.table.c.user_id, "not-a-uuid"),
            (self.table.c.amount, "not-a-decimal"),
        ):
            with self.subTest(column=column.name):
                with self.assertRaises(ValueError):
                    coerce_value(column, value)


class WriteSessionManager:
    """Expose real committing async sessions through the Admin manager protocol."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    @asynccontextmanager
    async def get_session(self):
        async with self.session_factory() as session, session.begin():
            yield session


async def exercise_default_admin_branches():
    """Run both ``ensure_superuser`` branches against a real database."""
    from types import SimpleNamespace

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, User.__table__).create)
        session_factory = async_sessionmaker(
            engine,
            class_=SQLModelAsyncSession,
            expire_on_commit=False,
        )
        manager = WriteSessionManager(session_factory)

        empty_user = await ensure_superuser(
            "empty-password",
            "",
            auth_settings=AuthSettings(),
            db_manager=cast(Any, manager),
        )
        empty_password_matches = empty_user.check_password("")
        empty_display_name = empty_user.display_name

        existing = await ensure_superuser(
            "existing",
            "InitialPass!2026",
            " Existing@Example.TEST ",
            auth_settings=AuthSettings(),
            db_manager=cast(Any, manager),
        )
        existing_hash_before = existing.password_hash
        existing_email = existing.email
        async with manager.get_session() as session:
            persisted = await session.scalar(select(User).where(User.username == "existing"))
            if persisted is None:
                raise AssertionError("existing user was not persisted")
            persisted.display_name = None

        existing = await ensure_superuser(
            "existing",
            "",
            auth_settings=AuthSettings(),
            db_manager=cast(Any, manager),
        )
        return SimpleNamespace(
            empty_password_matches=empty_password_matches,
            empty_display_name=empty_display_name,
            existing_hash_before=existing_hash_before,
            existing_hash_after=existing.password_hash,
            existing_display_name=existing.display_name,
            existing_email=existing_email,
        )
    finally:
        await engine.dispose()


async def exercise_touch_last_login(instant: dt.datetime) -> dt.datetime | None:
    """Persist one fixed login clock through the real Admin service and a new session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, User.__table__).create)
        session_factory = async_sessionmaker(
            engine,
            class_=SQLModelAsyncSession,
            expire_on_commit=False,
        )
        manager = WriteSessionManager(session_factory)
        user = await ensure_superuser(
            "login-clock",
            "InitialPass!2026",
            auth_settings=AuthSettings(),
            db_manager=cast(Any, manager),
        )

        # 服务用共享的 naive_utcnow 取时间，这里替换它来固定时钟。
        with patch("oldman.auth.services.naive_utcnow", return_value=instant) as clock:
            await touch_last_login(
                user.id,
                auth_settings=AuthSettings(),
                db_manager=cast(Any, manager),
            )

        clock.assert_called_once_with()
        async with session_factory() as session:
            persisted = await session.get(User, user.id)
            if persisted is None:
                raise AssertionError("login-clock user was not persisted")
            return persisted.last_login_at
    finally:
        await engine.dispose()
