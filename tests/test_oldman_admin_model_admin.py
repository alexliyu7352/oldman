"""Oldman ModelAdmin tests."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Table, select
from sqlalchemy.dialects import oracle
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from oldman.apps.admin import crud
from oldman.apps.admin.model_admin import ModelAdmin
from oldman.apps.admin.site import AdminSite
from oldman.db.models import DatabaseModel, ModelMetadata
from oldman.i18n import gettext_lazy
from oldman.web.components.forms import TailwindModelForm
from oldman.web.components.forms.models import model_column_requires_input


class AdminTestArticle(DatabaseModel):
    """Test model for ModelAdmin metadata inference."""

    __tablename__ = "test_admin_article"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AdminNaturalKeyArticle(DatabaseModel):
    """Test model whose primary key must be supplied by the create form."""

    __tablename__ = "test_admin_natural_key_article"  # pyright: ignore[reportAssignmentType]

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminNaturalKeyOnlyRecord(DatabaseModel):
    """Test model proving a primary-key-only create form is not empty."""

    __tablename__ = "test_admin_natural_key_only"  # pyright: ignore[reportAssignmentType]

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)


class AdminRequiredBooleanRecord(DatabaseModel):
    """Test model whose unchecked non-null Boolean must remain a legal False."""

    __tablename__ = "test_admin_required_boolean"  # pyright: ignore[reportAssignmentType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AdminBigIntegerRecord(DatabaseModel):
    """Generic Admin model whose SQLite BigInteger key must be submitted."""

    __tablename__ = "test_admin_big_integer"  # pyright: ignore[reportAssignmentType]

    record_key: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminBooleanKeyRecord(DatabaseModel):
    """Generic Admin model whose unchecked Boolean primary key is valid False."""

    __tablename__ = "test_admin_boolean_key"  # pyright: ignore[reportAssignmentType]

    flag: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminBooleanForeignRecord(DatabaseModel):
    """Generic Admin model selecting a Boolean foreign-key value."""

    __tablename__ = "test_admin_boolean_foreign"  # pyright: ignore[reportAssignmentType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flag: Mapped[bool] = mapped_column(Boolean, ForeignKey("test_admin_boolean_key.flag"), nullable=False)


class AdminMetaReport(DatabaseModel):
    """Model with explicit singular and irregular plural display names."""

    __tablename__ = "test_admin_meta_report"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    class Meta:
        verbose_name = "Status report"
        verbose_name_plural = "Status reports"


class AdminLazyEvent(DatabaseModel):
    """Model whose display names must remain lazy until request rendering."""

    __tablename__ = "test_admin_lazy_event"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    class Meta:
        verbose_name = gettext_lazy("Event")
        verbose_name_plural = gettext_lazy("Events")


class OverrideReportAdmin(ModelAdmin):
    """ModelAdmin whose explicit labels take precedence over model metadata."""

    @property
    def verbose_name(self) -> str:
        return "Report override"

    @property
    def verbose_name_plural(self) -> str:
        return "Report overrides"


class OldmanModelAdminTest(unittest.TestCase):
    """验证 ModelAdmin 自动 CRUD 基础能力。"""

    def test_model_admin_infers_list_search_ordering_and_shared_form(self) -> None:
        """ModelAdmin 应从 SQLAlchemy metadata 推断列表并使用共享 ModelForm。"""
        admin = ModelAdmin(AdminTestArticle)

        self.assertEqual("test_admin_article", admin.model_path)
        self.assertIn("id", admin.get_list_display())
        self.assertIn("title", admin.get_list_display())
        self.assertIn("title", admin.get_search_fields())
        self.assertEqual(("id",), admin.get_ordering())
        form_class = admin.get_form_class()
        self.assertTrue(issubclass(form_class, TailwindModelForm))
        self.assertEqual({"title", "slug", "is_public"}, set(form_class()._fields))
        self.assertEqual(["InputRequired"], [type(validator).__name__ for validator in form_class().title.validators])

    def test_manual_primary_key_create_and_edit_use_real_sqlite(self) -> None:
        """通用 CRUD 必须收集显式主键、拒绝重复值且不允许编辑身份。"""
        admin = ModelAdmin(AdminNaturalKeyArticle)
        create_form_class = admin.get_form_class()
        edit_form_class = admin.get_form_class(create=False)

        self.assertEqual({"slug", "title"}, set(create_form_class()._fields))
        self.assertEqual({"title"}, set(edit_form_class()._fields))
        self.assertEqual(["InputRequired"], [type(validator).__name__ for validator in create_form_class().slug.validators])
        self.assertEqual(
            {"slug"},
            set(ModelAdmin(AdminNaturalKeyOnlyRecord).get_form_class()()._fields),
        )
        self.assertEqual(
            {},
            ModelAdmin(AdminNaturalKeyOnlyRecord).get_form_class(create=False)()._fields,
        )

        result = asyncio.run(round_trip_natural_key_admin())

        self.assertEqual("first", result.created_slug)
        self.assertEqual("Updated title", result.updated_title)
        self.assertEqual("first", result.updated_slug)
        self.assertFalse(result.duplicate_valid)
        self.assertEqual(["Slug already exists"], result.duplicate_errors["slug"])

    def test_boolean_false_and_autoincrement_primary_key_keep_source_semantics(self) -> None:
        """必要必填改进不得让 checkbox=False 非法或要求提交数据库生成主键。"""
        admin = ModelAdmin(AdminRequiredBooleanRecord)
        form_class = admin.get_form_class()

        self.assertEqual({"enabled"}, set(form_class()._fields))
        self.assertEqual((), form_class().enabled.validators)
        self.assertFalse(model_column_requires_input(AdminRequiredBooleanRecord.__table__.c.enabled, checkbox=True))
        self.assertTrue(model_column_requires_input(AdminRequiredBooleanRecord.__table__.c.enabled))
        self.assertFalse(model_column_requires_input(AdminRequiredBooleanRecord.__table__.c.id))

        result = asyncio.run(round_trip_required_boolean_admin())
        boolean_key_result = asyncio.run(round_trip_boolean_key_admin())
        boolean_foreign_result = asyncio.run(round_trip_boolean_foreign_admin())

        self.assertTrue(result.valid)
        self.assertFalse(result.enabled)
        self.assertTrue(boolean_key_result.valid)
        self.assertFalse(boolean_key_result.flag)
        self.assertFalse(boolean_foreign_result.missing_valid)
        self.assertIn("flag", boolean_foreign_result.missing_errors)
        self.assertEqual((False, True), boolean_foreign_result.flags)
        self.assertEqual((bool, bool), boolean_foreign_result.flag_types)
        self.assertFalse(boolean_foreign_result.invalid_valid)
        self.assertIn("flag", boolean_foreign_result.invalid_errors)

    def test_generic_big_integer_primary_key_is_required_and_flushes_in_sqlite(self) -> None:
        """Generic ModelAdmin 必须在 SQLite 收集 BigInteger 主键并于缺失时提前失败。"""
        result = asyncio.run(round_trip_big_integer_admin())

        self.assertFalse(result.missing_valid)
        self.assertIn("record_key", result.missing_errors)
        self.assertTrue(result.valid)
        self.assertEqual(9_223_372_036_854_775_000, result.record_key)
        oracle_form_class = ModelAdmin(AdminTestArticle).get_form_class(dialect=oracle.dialect())
        self.assertIn("id", oracle_form_class()._fields)
        self.assertEqual(["InputRequired"], [type(validator).__name__ for validator in oracle_form_class().id.validators])

    def test_model_admin_has_no_parallel_crud_api(self) -> None:
        """Admin 不得在共享 Table/ModelForm 之外保留第二套 CRUD。"""

        for name in ("get_form_fields", "list_objects", "build_instance", "update_instance"):
            self.assertFalse(hasattr(ModelAdmin, name), name)
        self.assertFalse(hasattr(crud, "AdminFormField"))
        self.assertFalse(hasattr(crud, "AdminListResult"))

    def test_admin_site_registers_model_admins_and_menu(self) -> None:
        """AdminSite 应维护模型 registry 和中立菜单。"""
        site = AdminSite()
        admin = site.register(AdminTestArticle)

        self.assertIs(admin, site.get_model_admin(AdminTestArticle))
        self.assertEqual(
            [
                {
                    "label": "Admin Test Articles",
                    "path": "test_admin_article",
                    "url": "/admin/test_admin_article",
                    "app_label": "",
                    "app_display_name": "",
                    "icon": "ri-database-2-line",
                }
            ],
            site.menu_items(),
        )
        with self.assertRaises(ValueError):
            site.register(AdminTestArticle)

    def test_model_meta_and_model_admin_override_drive_display_names(self) -> None:
        """Display labels use ModelAdmin, then Model.Meta, then class-name fallback."""
        meta_admin = ModelAdmin(AdminMetaReport)
        lazy_admin = ModelAdmin(AdminLazyEvent)
        override_admin = OverrideReportAdmin(AdminMetaReport)

        self.assertEqual("Status report", meta_admin.verbose_name)
        self.assertEqual("Status reports", meta_admin.verbose_name_plural)
        self.assertIs(
            AdminLazyEvent.Meta.verbose_name,
            lazy_admin.verbose_name,
        )
        self.assertIs(
            AdminLazyEvent.Meta.verbose_name_plural,
            lazy_admin.verbose_name_plural,
        )
        self.assertEqual("Report override", override_admin.verbose_name)
        self.assertEqual("Report overrides", override_admin.verbose_name_plural)
        self.assertEqual("test_admin_meta_report", meta_admin.model_path)

    def test_registered_models_share_their_app_icon_and_display_name(self) -> None:
        """Admin groups model links under their owning App presentation."""
        model_metadata = {
            AdminTestArticle: ModelMetadata(
                model=AdminTestArticle,
                table=cast(Table, AdminTestArticle.__table__),
                app_label="editorial",
                verbose_name="Article",
                verbose_name_plural="Articles",
                managed=True,
            ),
            AdminMetaReport: ModelMetadata(
                model=AdminMetaReport,
                table=cast(Table, AdminMetaReport.__table__),
                app_label="editorial",
                verbose_name="Status report",
                verbose_name_plural="Status reports",
                managed=True,
            ),
        }
        app_config = SimpleNamespace(
            label="editorial",
            display_name=gettext_lazy("Editorial"),
            icon="ri-newspaper-line",
        )
        registry = SimpleNamespace(
            get_model_metadata=model_metadata.__getitem__,
            get_by_label=lambda label: app_config,
        )
        site = AdminSite(app_registry=cast(Any, registry))
        site.register(AdminTestArticle)
        site.register(AdminMetaReport)

        items = site.menu_items()
        groups = site.menu_groups()

        self.assertEqual(["ri-newspaper-line", "ri-newspaper-line"], [item["icon"] for item in items])
        self.assertEqual([app_config.display_name, app_config.display_name], [item["app_display_name"] for item in items])
        self.assertEqual(["Articles", "Status reports"], [item["label"] for item in items])
        self.assertEqual(
            [
                {
                    "app_label": "editorial",
                    "label": app_config.display_name,
                    "icon": "ri-newspaper-line",
                    "models": items,
                }
            ],
            groups,
        )


def make_request(form: dict[str, Any]) -> SimpleNamespace:
    """Build the minimal request protocol used by shared ModelForm."""
    return SimpleNamespace(method="POST", form=form, files={})


async def round_trip_natural_key_admin() -> SimpleNamespace:
    """Exercise generic create/edit and duplicate validation through SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, AdminNaturalKeyArticle.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            admin = ModelAdmin(AdminNaturalKeyArticle)
            create_form = admin.build_form(
                make_request({"slug": "first", "title": "First title"}),
                session=session,
            )
            if not await create_form.validate():
                raise AssertionError(create_form.errors)
            created = await create_form.save()
            await admin.save_model(session, created)

            duplicate_form = admin.build_form(
                make_request({"slug": "first", "title": "Duplicate title"}),
                session=session,
            )
            duplicate_valid = await duplicate_form.validate()

            edit_form = admin.build_form(
                make_request({"slug": "changed", "title": "Updated title"}),
                instance=created,
                session=session,
            )
            if not await edit_form.validate():
                raise AssertionError(edit_form.errors)
            updated = await edit_form.save()
            await admin.save_model(session, updated)
            return SimpleNamespace(
                created_slug=created.slug,
                duplicate_errors=duplicate_form.errors,
                duplicate_valid=duplicate_valid,
                updated_slug=updated.slug,
                updated_title=updated.title,
            )
    finally:
        await engine.dispose()


async def round_trip_required_boolean_admin() -> SimpleNamespace:
    """Edit a true Boolean to false through an unchecked generic Admin checkbox."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, AdminRequiredBooleanRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            admin = ModelAdmin(AdminRequiredBooleanRecord)
            record = AdminRequiredBooleanRecord(enabled=True)
            session.add(record)
            await session.flush()
            form = admin.build_form(make_request({}), instance=record, session=session)
            valid = await form.validate()
            if not valid:
                return SimpleNamespace(valid=False, enabled=None, errors=form.errors)
            updated = await form.save()
            await admin.save_model(session, updated)
            return SimpleNamespace(valid=True, enabled=updated.enabled, errors={})
    finally:
        await engine.dispose()


async def round_trip_big_integer_admin() -> SimpleNamespace:
    """Exercise generic BigInteger primary-key validation and persistence in SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, AdminBigIntegerRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            admin = ModelAdmin(AdminBigIntegerRecord)
            missing_form = admin.build_form(make_request({"title": "Missing key"}), session=session)
            missing_valid = await missing_form.validate()
            valid_form = admin.build_form(
                make_request({"record_key": "9223372036854775000", "title": "Explicit key"}),
                session=session,
            )
            valid = await valid_form.validate()
            if not valid:
                raise AssertionError(valid_form.errors)
            created = await valid_form.save()
            await admin.save_model(session, created)
            return SimpleNamespace(
                missing_valid=missing_valid,
                missing_errors=missing_form.errors,
                valid=valid,
                record_key=created.record_key,
            )
    finally:
        await engine.dispose()


async def round_trip_boolean_key_admin() -> SimpleNamespace:
    """Persist a legal false Boolean primary key from an unchecked checkbox."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, AdminBooleanKeyRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            admin = ModelAdmin(AdminBooleanKeyRecord)
            form = admin.build_form(make_request({"title": "False key"}), session=session)
            valid = await form.validate()
            if not valid:
                raise AssertionError(form.errors)
            created = await form.save()
            await admin.save_model(session, created)
            return SimpleNamespace(valid=valid, flag=created.flag)
    finally:
        await engine.dispose()


async def round_trip_boolean_foreign_admin() -> SimpleNamespace:
    """Validate and persist missing/false/true Boolean foreign-key selections."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, AdminBooleanKeyRecord.__table__).create)
            await connection.run_sync(cast(Any, AdminBooleanForeignRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add_all(
                (
                    AdminBooleanKeyRecord(flag=False, title="False choice"),
                    AdminBooleanKeyRecord(flag=True, title="True choice"),
                )
            )
            await session.flush()
            admin = ModelAdmin(AdminBooleanForeignRecord)
            missing_form = admin.build_form(make_request({}), session=session)
            missing_valid = await missing_form.validate()
            flags: list[bool] = []
            for submitted in ("False", "True"):
                form = admin.build_form(make_request({"flag": submitted}), session=session)
                if not await form.validate():
                    raise AssertionError(form.errors)
                created = await form.save()
                await admin.save_model(session, created)
            invalid_form = admin.build_form(make_request({"flag": "definitely-not-bool"}), session=session)
            invalid_valid = await invalid_form.validate()
            session.sync_session.expunge_all()
            records = list(
                (await session.execute(select(AdminBooleanForeignRecord).order_by(AdminBooleanForeignRecord.id)))
                .scalars()
                .all()
            )
            flags.extend(record.flag for record in records)
            return SimpleNamespace(
                missing_valid=missing_valid,
                missing_errors=missing_form.errors,
                flags=tuple(flags),
                flag_types=tuple(type(flag) for flag in flags),
                invalid_valid=invalid_valid,
                invalid_errors=invalid_form.errors,
            )
    finally:
        await engine.dispose()
