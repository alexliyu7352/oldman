"""Built-in Admin user-management regression tests."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import BigInteger, Column, Identity, Integer, MetaData, Sequence, String, Table, Uuid, select
from sqlalchemy.dialects import mysql, oracle, postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from oldman.apps.admin.model_admin import AdminUserModelAdmin, ModelAdmin
from oldman.apps.admin.table import AdminModelTable, _AdminUserModelTable
from oldman.auth import UserManagementError, UserModelContractError, set_user_active, validate_user_delete
from oldman.auth.models import User
from oldman.db import explicit_primary_key_column
from oldman.db.models import DatabaseModel
from oldman.web.auth.forms import UserFilterForm, user_create_form_class
from oldman.web.session import SessionData


class UUIDAdminRecord(DatabaseModel):
    """Generic Admin model used to verify UUID identity coercion."""

    __tablename__ = "test_oldman_admin_uuid_record"  # pyright: ignore[reportAssignmentType]

    record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class FakeSession(SessionData):
    """Concrete typed SessionData used by the Admin request fixtures."""


class FakeScalarResult:
    """SQLAlchemy scalar-result double."""

    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeUserLookupSession:
    """Return configured rows in unique-field validation order."""

    def __init__(self, rows) -> None:
        self.rows = list(rows)

    async def execute(self, statement):
        del statement
        return FakeScalarResult(self.rows.pop(0) if self.rows else None)


class OldmanAdminUserManagementTest(unittest.TestCase):
    """Framework user manager contract."""

    def test_create_form_hashes_password_and_rejects_weak_or_mismatched_passwords(self) -> None:
        """User creation must preserve the source password policy and hashing path."""
        admin = AdminUserModelAdmin(User)
        valid = admin.build_form(
            make_request(
                form={
                    "username": "alice",
                    "email": "alice@example.test",
                    "display_name": "Alice",
                    "password": "Str0ngPass!2026",
                    "confirm_password": "Str0ngPass!2026",
                    "is_active": "y",
                    "is_staff": "y",
                }
            )
        )

        self.assertTrue(asyncio.run(valid.validate()))
        user = asyncio.run(valid.save())
        self.assertTrue(user.check_password("Str0ngPass!2026"))
        self.assertNotEqual("Str0ngPass!2026", user.password_hash)
        self.assertNotIn("password_hash", valid._fields)

        weak = admin.build_form(
            make_request(
                form={
                    "username": "weak",
                    "password": "abcdefgh",
                    "confirm_password": "different",
                    "is_active": "y",
                    "is_staff": "y",
                }
            )
        )
        self.assertFalse(asyncio.run(weak.validate()))
        self.assertIn("password", weak.errors)
        self.assertIn("confirm_password", weak.errors)

    def test_create_and_edit_forms_validate_username_and_email_uniqueness(self) -> None:
        """Unique constraint failures must become field errors, not database 500s."""
        existing = User(id=12, username="alice", email="alice@example.test", password_hash="")
        admin = AdminUserModelAdmin(User)
        form = admin.build_form(
            make_request(
                form={
                    "username": "alice",
                    "email": "alice@example.test",
                    "password": "Str0ngPass!2026",
                    "confirm_password": "Str0ngPass!2026",
                    "is_active": "y",
                    "is_staff": "y",
                }
            ),
            session=FakeUserLookupSession([existing, existing]),
        )

        self.assertFalse(asyncio.run(form.validate()))
        self.assertIn("username", form.errors)
        self.assertIn("email", form.errors)

    def test_edit_form_protects_current_user_from_locking_out_their_session(self) -> None:
        """Current users may not disable or remove their own Admin permissions."""
        user = User(
            id=7,
            username="root",
            email="root@example.test",
            password_hash="",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        admin = AdminUserModelAdmin(User)
        form = admin.build_form(
            make_request(
                user_id=7,
                form={
                    "username": "root",
                    "email": "root@example.test",
                    "display_name": "Root",
                    "is_active": "",
                    "is_staff": "",
                    "is_superuser": "",
                },
            ),
            instance=user,
            session=FakeUserLookupSession([user, user]),
        )

        self.assertFalse(asyncio.run(form.validate()))
        self.assertIn("is_active", form.errors)
        self.assertIn("is_staff", form.errors)
        self.assertIn("is_superuser", form.errors)

    def test_password_and_delete_services_preserve_security_boundaries(self) -> None:
        """Password, self-status, self-delete and superuser-delete rules match the source."""
        user = User(id=9, username="alice", password_hash="", is_active=True, is_staff=True, is_superuser=False)
        user.set_password("OldPass!2026")
        old_hash = user.password_hash

        user.set_password("NewPass!2026")
        self.assertNotEqual(old_hash, user.password_hash)
        self.assertFalse(user.check_password("OldPass!2026"))
        self.assertTrue(user.check_password("NewPass!2026"))

        with self.assertRaisesRegex(UserManagementError, "cannot disable current user"):
            set_user_active(user, False, current_user_id=9)
        with self.assertRaisesRegex(UserManagementError, "cannot delete current user"):
            validate_user_delete(user, current_user_id=9)

        superuser = User(id=10, username="root", password_hash="", is_active=True, is_staff=True, is_superuser=True)
        with self.assertRaisesRegex(UserManagementError, "cannot delete superuser"):
            validate_user_delete(superuser, current_user_id=9)

    def test_user_filter_and_table_restore_source_contract(self) -> None:
        """User list keeps filters, ten-row pages, statuses and row-level actions."""
        admin = AdminUserModelAdmin(User)
        request = make_request(args={"q": "alice", "is_staff": "true"})
        table = _AdminUserModelTable(
            request,
            model_admin=admin,
            db_manager=SimpleNamespace(),  # type: ignore[arg-type]
            admin_prefix="/admin",
        )
        filter_form = UserFilterForm.from_query(request)
        filter_html = str(asyncio.run(filter_form.render(table_target="#admin-oldman_user-table")))  # type: ignore[call-arg]

        self.assertEqual(10, table.page_size)
        self.assertTrue(table.selectable)
        self.assertIn('name="is_active"', filter_html)
        self.assertIn('name="is_staff"', filter_html)
        self.assertIn('name="is_superuser"', filter_html)
        self.assertIn('name="last_login_from"', filter_html)
        self.assertIn('name="last_login_to"', filter_html)

        columns = {column.name for column in table.get_columns()}
        labels = {column.name: column.label for column in table.get_columns()}
        self.assertTrue({"username", "is_active", "is_staff", "is_superuser", "last_login_at", "action"}.issubset(columns))
        self.assertEqual("Status", labels["is_active"])
        self.assertEqual("Staff", labels["is_staff"])
        self.assertEqual("Superuser", labels["is_superuser"])
        self.assertEqual("Last Login", labels["last_login_at"])
        self.assertEqual("Action", labels["action"])
        action_html = str(table.get_column_action_data(User(id=12, username="alice", password_hash="", is_active=True)))
        self.assertIn('href="/admin/oldman_user/12/edit"', action_html)
        self.assertIn('data-om-modal-target="#user-password-modal"', action_html)
        self.assertIn('data-om-modal-url="/admin/oldman_user/12/password-modal"', action_html)
        self.assertIn('data-om-modal-target="#user-status-modal"', action_html)
        self.assertIn('data-om-modal-url="/admin/oldman_user/12/status-modal"', action_html)
        self.assertIn('data-om-modal-target="#user-delete-modal"', action_html)
        self.assertIn('data-om-modal-url="/admin/oldman_user/12/delete-modal"', action_html)
        staff_badge = str(admin.table_cell_value(User(id=12, username="alice", password_hash="", is_staff=True), "is_staff", admin_prefix="/admin"))
        self.assertIn('class="om-badge om-badge-info"', staff_badge)
        self.assertNotIn("bg-sky", staff_badge)
        user_badge = str(
            admin.table_cell_value(
                User(id=12, username="alice", password_hash="", is_superuser=False),
                "is_superuser",
                admin_prefix="/admin",
            )
        )
        self.assertIn('class="om-badge om-badge-default"', user_badge)
        self.assertNotIn("om-badge-secondary", user_badge)

    def test_user_table_filters_reject_invalid_values_and_compile_valid_filters(self) -> None:
        """Boolean and last-login filters use the shared SQLAlchemy Table lifecycle."""
        from oldman.web.components.tables.views import TableValidationError

        admin = AdminUserModelAdmin(User)
        table = _AdminUserModelTable(
            make_request(),
            model_admin=admin,
            db_manager=SimpleNamespace(),  # type: ignore[arg-type]
            admin_prefix="/admin",
        )
        table_request = table.build_table_request(make_request(args={"filter.is_staff": "true"}), route_kwargs={})
        query = asyncio.run(table.filter_is_staff(select(User), "true", table_request))
        self.assertIn("oldman_user.is_staff IS true", str(query))

        with self.assertRaises(TableValidationError):
            asyncio.run(table.filter_is_active(select(User), "maybe", table_request))

    def test_admin_table_shell_restores_direct_page_size_page_and_sort(self) -> None:
        """History and reload must rebuild the complete table URL state."""
        table = AdminModelTable(
            make_request(args={"q": "alice", "page_size": "50", "page": "2", "sort": "-username"}),
            model_admin=AdminUserModelAdmin(User),
            db_manager=SimpleNamespace(),  # type: ignore[arg-type]
            admin_prefix="/admin",
        )

        shell = str(asyncio.run(table.render_shell(html_id="users-table")))

        self.assertEqual(50, table.initial_page_size)
        self.assertEqual(2, table.initial_page)
        self.assertEqual("-username", table.initial_sort)
        self.assertIn('data-om-table-page-size="50"', shell)
        self.assertIn('data-om-table-default-page-size="10"', shell)
        self.assertIn('data-om-table-initial-page="2"', shell)
        self.assertIn('data-om-table-initial-sort="-username"', shell)

    def test_admin_user_model_rejects_an_independent_mapper(self) -> None:
        """Admin user management shares Auth's fixed AbstractUser contract."""
        with self.assertRaisesRegex(UserModelContractError, "inherit"):
            AdminUserModelAdmin(UUIDAdminRecord)

    def test_uuid_primary_key_get_object_and_edit_url_use_real_sqlite(self) -> None:
        """String URL UUIDs must coerce back to UUID objects before ``session.get``."""
        record_id = uuid.uuid4()
        loaded_id, action_html = asyncio.run(round_trip_uuid_admin_record(record_id))

        self.assertEqual(record_id, loaded_id)
        self.assertIn(f"/admin/test_oldman_admin_uuid_record/{record_id}/edit", action_html)

    def test_primary_key_generation_is_dialect_identity_and_sequence_aware(self) -> None:
        """Do not apply SQLite's exact-INTEGER rule to server SQL dialects."""
        metadata = MetaData()
        big_table = Table("dialect_big_key", metadata, Column("id", BigInteger, primary_key=True))
        integer_table = Table("dialect_integer_key", metadata, Column("id", Integer, primary_key=True))
        variant_table = Table(
            "dialect_variant_key",
            metadata,
            Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
        )
        identity_table = Table("dialect_identity_key", metadata, Column("id", BigInteger, Identity(), primary_key=True))
        sequence_table = Table(
            "dialect_sequence_key",
            metadata,
            Column("id", BigInteger, Sequence("dialect_sequence_key_seq"), primary_key=True),
        )
        manual_table = Table(
            "dialect_manual_key",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=False),
        )

        def mapper(column: Column[Any]) -> SimpleNamespace:
            return SimpleNamespace(primary_key=[column])

        self.assertIs(big_table.c.id, explicit_primary_key_column(mapper(big_table.c.id), dialect=sqlite.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(big_table.c.id), dialect=postgresql.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(big_table.c.id), dialect=mysql.dialect()))
        self.assertIs(big_table.c.id, explicit_primary_key_column(mapper(big_table.c.id), dialect=oracle.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(integer_table.c.id), dialect=sqlite.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(variant_table.c.id), dialect=sqlite.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(identity_table.c.id), dialect=oracle.dialect()))
        self.assertIsNone(explicit_primary_key_column(mapper(sequence_table.c.id), dialect=oracle.dialect()))
        self.assertIs(manual_table.c.id, explicit_primary_key_column(mapper(manual_table.c.id), dialect=postgresql.dialect()))
        oracle_form = user_create_form_class(User, dialect=oracle.dialect())()
        self.assertIn("id", oracle_form._fields)
        self.assertIn("InputRequired", [type(validator).__name__ for validator in oracle_form._fields["id"].validators])


def make_request(
    *,
    args: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    user_id: int | None = 1,
):
    """Build the request subset used by Admin forms and tables."""
    session = FakeSession(
        user_id=user_id,
        is_active=user_id is not None,
        is_staff=user_id is not None,
        is_superuser=user_id is not None,
    )
    return SimpleNamespace(
        app=SimpleNamespace(),
        args=args or {},
        ctx=SimpleNamespace(session=session, csrf_token="csrf-token"),
        files={},
        form=form or {},
        headers={},
        method="POST" if form is not None else "GET",
        path="/admin/oldman_user",
        query_string="",
    )


async def round_trip_uuid_admin_record(record_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Persist and load a UUID model through the public ModelAdmin identity path."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, UUIDAdminRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            record = UUIDAdminRecord(record_id=record_id, name="UUID record")
            session.add(record)
            await session.flush()
            admin = ModelAdmin(UUIDAdminRecord)
            loaded = await admin.get_object(session, str(record_id))
            if loaded is None:
                raise AssertionError("UUID Admin record was not loaded")
            action_html = str(admin.table_action_html(loaded, admin_prefix="/admin"))
            return loaded.record_id, action_html
    finally:
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
