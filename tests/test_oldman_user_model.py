"""Framework User model extension contract tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import cast

from pydantic import ValidationError
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session

from oldman.apps import AppNotInstalledError
from oldman.apps.admin.apps import app as admin_app
from oldman.apps.admin.settings import AdminSettings
from oldman.auth import AbstractUser, AuthSettings, get_user_model
from oldman.auth.apps import app as auth_app
from oldman.auth.models import User
from oldman.conf.schemas import DefaultSettings
from oldman.i18n import LazyTranslation

ROOT = Path(__file__).resolve().parents[1]


def run_contract_script(source: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated User mapping because a process may map one concrete User."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class OldmanUserModelTest(unittest.TestCase):
    """Verify the fixed table and ordinary SQLAlchemy extension boundary."""

    def test_default_user_has_the_fixed_database_identity(self) -> None:
        """The built-in User uses the stable table and database-generated integer id."""
        table = cast(Table, User.__table__)
        primary_key = tuple(table.primary_key.columns)

        self.assertEqual("oldman_user", table.name)
        self.assertEqual((table.c.id,), primary_key)
        self.assertEqual("INTEGER", str(table.c.id.type))
        self.assertIs(True, table.c.id.autoincrement)
        self.assertEqual(
            1,
            sum(
                constraint.name == "ck_oldman_user_superuser_is_staff"
                for constraint in table.constraints
            ),
        )
        self.assertTrue(issubclass(User, AbstractUser))
        self.assertIs(User, get_user_model(AuthSettings()))

    def test_project_user_extends_one_table_with_normal_sqlalchemy(self) -> None:
        """Fields, indexes, constraints, relationships and table options remain native."""
        result = run_contract_script(
            """
            from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, create_engine, select
            from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

            import oldman.auth.base as user_base
            from oldman.auth import AbstractUser
            from oldman.auth.contracts import validate_user_table_contract
            from oldman.db.models import Base, DatabaseModel

            class Tenant(DatabaseModel):
                __tablename__ = "test_user_tenant"
                id: Mapped[int] = mapped_column(Integer, primary_key=True)

            class ProjectUser(AbstractUser):
                phone: Mapped[str | None] = mapped_column(String(32), index=True)
                tenant_id: Mapped[int] = mapped_column(
                    ForeignKey("test_user_tenant.id"),
                    index=True,
                )
                tenant: Mapped[Tenant] = relationship()
                __table_args__ = (
                    UniqueConstraint(
                        "tenant_id",
                        "phone",
                        name="uq_project_user_tenant_phone",
                    ),
                    {"sqlite_autoincrement": True},
                )

            table = ProjectUser.__table__
            assert ProjectUser.__tablename__ == "oldman_user"
            assert set(table.c) >= {
                table.c.id,
                table.c.username,
                table.c.email,
                table.c.phone,
                table.c.tenant_id,
            }
            assert table.dialect_options["sqlite"]["autoincrement"] is True
            assert {
                constraint.name for constraint in table.constraints
            } >= {
                "ck_oldman_user_superuser_is_staff",
                "uq_project_user_tenant_phone",
            }
            validate_user_table_contract(ProjectUser)
            validate_user_table_contract(ProjectUser)
            assert sum(
                constraint.name == "ck_oldman_user_superuser_is_staff"
                for constraint in table.constraints
            ) == 1

            engine = create_engine("sqlite:///:memory:")
            Tenant.__table__.create(engine)
            table.create(engine)
            try:
                original_validator = user_base.validate_user_table_contract

                def reject_hot_path_validation(model):
                    raise AssertionError("User table validation entered the ORM hot path")

                user_base.validate_user_table_contract = reject_hot_path_validation
                with Session(engine) as session:
                    tenant = Tenant(id=7)
                    user = ProjectUser(
                        username="alice",
                        password_hash="",
                        phone="123",
                        tenant=tenant,
                        is_staff=False,
                        is_superuser=True,
                    )
                    user.set_password("StrongPass123")
                    session.add(user)
                    session.flush()
                    assert user.id == 1
                    assert user.is_staff is True
                    assert user.check_password("StrongPass123")
                    assert session.scalar(
                        select(ProjectUser).where(ProjectUser.id == 1)
                    ) is user
                user_base.validate_user_table_contract = original_validator
            finally:
                engine.dispose()

            assert "oldman.auth.models" not in __import__("sys").modules
            assert set(Base.metadata.tables) == {"test_user_tenant", "oldman_user"}
            """
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_invalid_user_shapes_fail_while_the_model_is_declared(self) -> None:
        """Table, primary-key, core-column and core-constraint drift fail immediately."""
        cases = {
            "table": (
                """
                class BrokenUser(AbstractUser):
                    __tablename__ = "project_user"
                """,
                "oldman_user",
            ),
            "primary key type": (
                """
                class BrokenUser(AbstractUser):
                    id: Mapped[str] = mapped_column(String(32), primary_key=True)
                """,
                "Integer",
            ),
            "primary key name": (
                """
                class BrokenUser(AbstractUser):
                    id = None
                    uid: Mapped[int] = mapped_column(Integer, primary_key=True)
                """,
                "id",
            ),
            "autoincrement": (
                """
                class BrokenUser(AbstractUser):
                    id: Mapped[int] = mapped_column(
                        Integer,
                        primary_key=True,
                        autoincrement=False,
                    )
                """,
                "autoincrement",
            ),
            "composite primary key": (
                """
                class BrokenUser(AbstractUser):
                    tenant_id: Mapped[int] = mapped_column(
                        Integer,
                        primary_key=True,
                    )
                """,
                "primary key",
            ),
            "missing core field": (
                """
                class BrokenUser(AbstractUser):
                    email = None
                """,
                "email",
            ),
            "changed core field": (
                """
                class BrokenUser(AbstractUser):
                    username: Mapped[str] = mapped_column(
                        String(32),
                        unique=True,
                        index=True,
                        nullable=False,
                    )
                """,
                "username",
            ),
            "conflicting core constraint": (
                """
                class BrokenUser(AbstractUser):
                    __table_args__ = (
                        CheckConstraint(
                            "is_staff = 0",
                            name="ck_oldman_user_superuser_is_staff",
                        ),
                    )
                """,
                "ck_oldman_user_superuser_is_staff",
            ),
        }
        for name, (model_source, expected_message) in cases.items():
            with self.subTest(name=name):
                indented_model = textwrap.indent(
                    textwrap.dedent(model_source).strip(),
                    "    ",
                )
                result = run_contract_script(
                    "from sqlalchemy import CheckConstraint, Integer, String\n"
                    "from sqlalchemy.orm import Mapped, mapped_column\n\n"
                    "from oldman.auth import AbstractUser\n"
                    "from oldman.auth.contracts import UserModelContractError\n\n"
                    "try:\n"
                    f"{indented_model}\n"
                    "except UserModelContractError as exc:\n"
                    f"    assert {expected_message!r} in str(exc), str(exc)\n"
                    "else:\n"
                    "    raise AssertionError('invalid User model was accepted')\n"
                )

                self.assertEqual(0, result.returncode, result.stderr)

    def test_core_constraint_validation_is_not_part_of_flush(self) -> None:
        """Repeated inserts and selects do not rerun the mapping-only contract work."""
        engine = create_engine("sqlite:///:memory:")
        table = cast(Table, User.__table__)
        table.create(engine)
        try:
            import oldman.auth.base as user_base

            original_validator = getattr(
                user_base,
                "validate_user_table_contract",
                None,
            )
            self.assertIsNotNone(original_validator)
            assert original_validator is not None

            def reject_hot_path_validation(model: object) -> None:
                raise AssertionError("User table validation entered the ORM hot path")

            try:
                user_base.validate_user_table_contract = reject_hot_path_validation
                with Session(engine) as session:
                    session.add(User(username="root", password_hash=""))
                    session.flush()
                    self.assertIsNotNone(session.scalar(select(User)))
            finally:
                user_base.validate_user_table_contract = original_validator
        finally:
            engine.dispose()

    def test_auth_app_settings_select_one_project_user_model(self) -> None:
        """The Auth App settings remain the sole configured model source."""
        result = run_contract_script(
            """
            from sqlalchemy import String
            from sqlalchemy.orm import Mapped, mapped_column

            from oldman.auth import AbstractUser, AuthSettings, get_user_model

            class ProjectUser(AbstractUser):
                phone: Mapped[str | None] = mapped_column(String(32))

            config = AuthSettings(user_model="__main__.ProjectUser")
            assert get_user_model(config) is ProjectUser
            """
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("auth", DefaultSettings.model_fields)
        self.assertNotIn("admin", DefaultSettings.model_fields)
        self.assertNotIn("user_model", AdminSettings.model_fields)

    def test_admin_settings_reject_the_removed_user_model_source(self) -> None:
        """A stale Admin-local model setting must not be silently ignored."""
        with self.assertRaisesRegex(ValidationError, "user_model"):
            AdminSettings.model_validate(
                {"user_model": "apps.accounts.models.User"}
            )

    def test_resolver_rejects_an_import_that_is_not_a_user_model(self) -> None:
        """Invalid configured objects should fail at the model boundary."""
        with self.assertRaisesRegex(TypeError, "configured User model"):
            get_user_model(AuthSettings(user_model=f"{__name__}.ROOT"))

    def test_builtin_apps_expose_typed_metadata_and_require_installation(self) -> None:
        """Auth and Admin should be normal Apps with isolated settings owners."""
        self.assertEqual("auth", auth_app.label)
        self.assertIsInstance(auth_app.display_name, LazyTranslation)
        assert isinstance(auth_app.display_name, LazyTranslation)
        self.assertEqual("Authentication", auth_app.display_name.singular)
        self.assertEqual("ri-shield-user-line", auth_app.icon)
        self.assertIs(AuthSettings, auth_app.settings_model)
        self.assertEqual("admin", admin_app.label)
        self.assertIsInstance(admin_app.display_name, LazyTranslation)
        assert isinstance(admin_app.display_name, LazyTranslation)
        self.assertEqual("Administration", admin_app.display_name.singular)
        self.assertEqual("ri-admin-line", admin_app.icon)
        self.assertIs(AdminSettings, admin_app.settings_model)
        with self.assertRaises(AppNotInstalledError):
            _ = auth_app.settings
        with self.assertRaises(AppNotInstalledError):
            _ = admin_app.settings

    def test_builtin_app_settings_are_bound_per_service_process(self) -> None:
        """Two services may bind different values without defining two settings types."""
        script = """
        import sys
        from pathlib import Path
        from oldman.apps.admin.apps import app as admin_app
        from oldman.auth.apps import app as auth_app
        from oldman.conf.manager import SettingsManager
        from oldman.conf.schemas import DefaultSettings
        from oldman.runtime import ServiceDefinition

        path = Path(sys.argv[1])
        definition = ServiceDefinition(
            "worker",
            path.parent / "services/worker.py",
            "simple",
        )
        SettingsManager(DefaultSettings, definition, path).load()
        assert auth_app.settings.user_model == sys.argv[2]
        assert admin_app.settings.require_superuser is (sys.argv[3] == "true")
        if sys.argv[2] == "oldman.auth.models.User":
            from oldman.auth import get_user_model
            assert get_user_model().__name__ == "User"
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases = (
                ("first", "oldman.auth.models.User", False),
                ("second", "project.users.SecondUser", True),
            )
            for name, user_model, require_superuser in cases:
                settings_file = root / f"{name}.yaml"
                settings_file.write_text(
                    "apps:\n"
                    "  - oldman.auth\n"
                    "  - oldman.apps.admin\n"
                    "app_settings:\n"
                    "  auth:\n"
                    f"    user_model: {user_model}\n"
                    "  admin:\n"
                    f"    require_superuser: {str(require_superuser).lower()}\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        textwrap.dedent(script),
                        str(settings_file),
                        user_model,
                        str(require_superuser).lower(),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
