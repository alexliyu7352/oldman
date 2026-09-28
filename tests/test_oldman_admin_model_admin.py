"""Oldman ModelAdmin tests."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Table, select
from sqlalchemy.dialects import oracle
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from oldman.apps.admin import crud
from oldman.apps.admin.model_admin import ModelAdmin
from oldman.apps.admin.site import AdminSite
from oldman.auth import declared_permissions
from oldman.db.models import APP_LABEL_INFO_KEY, DatabaseModel, ModelMetadata
from oldman.i18n import gettext_lazy
from oldman.web.authentication import RequestUser
from oldman.web.components.forms import TailwindModelForm
from oldman.web.components.forms.models import model_column_requires_input


class AdminTestArticle(DatabaseModel):
    """Test model for ModelAdmin metadata inference."""

    __tablename__ = "test_admin_article"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AdminNaturalKeyArticle(DatabaseModel):
    """Test model whose primary key must be supplied by the create form."""

    __tablename__ = "test_admin_natural_key_article"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminNaturalKeyOnlyRecord(DatabaseModel):
    """Test model proving a primary-key-only create form is not empty."""

    __tablename__ = "test_admin_natural_key_only"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)


class AdminRequiredBooleanRecord(DatabaseModel):
    """Test model whose unchecked non-null Boolean must remain a legal False."""

    __tablename__ = "test_admin_required_boolean"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AdminBigIntegerRecord(DatabaseModel):
    """Generic Admin model whose SQLite BigInteger key must be submitted."""

    __tablename__ = "test_admin_big_integer"

    record_key: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminBooleanKeyRecord(DatabaseModel):
    """Generic Admin model whose unchecked Boolean primary key is valid False."""

    __tablename__ = "test_admin_boolean_key"

    flag: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)


class AdminBooleanForeignRecord(DatabaseModel):
    """Generic Admin model selecting a Boolean foreign-key value."""

    __tablename__ = "test_admin_boolean_foreign"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flag: Mapped[bool] = mapped_column(Boolean, ForeignKey("test_admin_boolean_key.flag"), nullable=False)


class AdminMetaReport(DatabaseModel):
    """Model with explicit singular and irregular plural display names."""

    __tablename__ = "test_admin_meta_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    class Meta:
        verbose_name = "Status report"
        verbose_name_plural = "Status reports"


class AdminLegacyOrder(DatabaseModel):
    """Model on a table whose legacy name is not a valid permission name."""

    __tablename__ = "LegacyOrders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class AdminShopItem(DatabaseModel):
    """Model whose table the test labels as belonging to an App."""

    __tablename__ = "test_admin_shop_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class AdminSuperuserOnlyRecord(DatabaseModel):
    """Model registered only with a superuser-only ModelAdmin."""

    __tablename__ = "test_admin_superuser_only_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class AdminLazyEvent(DatabaseModel):
    """Model whose display names must remain lazy until request rendering."""

    __tablename__ = "test_admin_lazy_event"

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
        self.assertEqual(["InputRequired"], [type(validator).__name__ for validator in form_class()["title"].validators])

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

    def test_a_duplicate_manual_key_is_reported_in_the_request_language(self) -> None:
        from babel.support import Translations

        from oldman.i18n import bind_translations, reset_translations

        locales = Path(__file__).resolve().parents[1] / "oldman/apps/admin/locales"
        token = bind_translations(Translations.load(str(locales), ["zh_Hans"]))
        try:
            result = asyncio.run(round_trip_natural_key_admin())
        finally:
            reset_translations(token)
        self.assertEqual(["Slug 已存在"], result.duplicate_errors["slug"])

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

    def test_boolean_and_date_cells_render_badges_and_iso_raw_values(self) -> None:
        """Generic list cells must not print Python's True/False or repr timestamps."""
        import datetime as dt

        admin = ModelAdmin(AdminTestArticle)
        instance = SimpleNamespace(
            is_public=True,
            archived=False,
            published_at=dt.datetime(2026, 1, 5, 9, 1, 30),
            due_on=dt.date(2026, 2, 1),
            title="Plain",
        )

        self.assertEqual(
            '<span class="om-badge om-badge-success">Yes</span>',
            str(admin.table_cell_value(instance, "is_public", admin_prefix="/admin")),
        )
        self.assertEqual(
            '<span class="om-badge om-badge-default">No</span>',
            str(admin.table_cell_value(instance, "archived", admin_prefix="/admin")),
        )
        self.assertEqual(
            ("2026-01-05 09:01", "2026-01-05T09:01:30"),
            admin.table_cell_value(instance, "published_at", admin_prefix="/admin"),
        )
        self.assertEqual(("2026-02-01", "2026-02-01"), admin.table_cell_value(instance, "due_on", admin_prefix="/admin"))
        self.assertEqual("Plain", admin.table_cell_value(instance, "title", admin_prefix="/admin"))

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
            asyncio.run(site.menu_items(as_user(is_superuser=True))),
        )
        with self.assertRaises(ValueError):
            site.register(AdminTestArticle)

    def test_the_menu_lists_only_what_the_user_may_view(self) -> None:
        site = AdminSite()
        admin = site.register(AdminTestArticle)
        # Registering declares the model's permissions, so roles can be given them at once.
        self.assertEqual(
            ["add", "change", "delete", "view"],
            [p.codename.rsplit(".", 1)[1] for p in declared_permissions() if p.codename.startswith("admintestarticle.")],
        )
        # Named after the model class; this test model is loaded outside any App, so there is no App segment.
        self.assertEqual("admin.admintestarticle.view", admin.permission("view").name)
        # A role editor lists every model's permissions together, so the label names the model.
        self.assertEqual("Delete Admin Test Articles", str(admin.permission("delete").label))

        self.assertEqual([], asyncio.run(site.menu_items(as_user())))
        with patch("oldman.apps.roles.store.role_permissions", AsyncMock(return_value=frozenset({"admin.admintestarticle.view"}))):
            items = asyncio.run(site.menu_items(as_user(role_ids=(1,))))
        self.assertEqual(["test_admin_article"], [item["path"] for item in items])

    def test_a_superuser_only_model_declares_no_permissions(self) -> None:
        class SuperuserOnlyAdmin(ModelAdmin):
            require_superuser = True

        admin = AdminSite().register(AdminSuperuserOnlyRecord, SuperuserOnlyAdmin)
        self.assertEqual([], [p.name for p in declared_permissions() if p.name.startswith("admin.adminsuperuseronlyrecord.")])
        # Superusers still open it; nobody else does, whatever their roles.
        self.assertTrue(asyncio.run(admin.has_view_permission(as_user(is_superuser=True))))
        self.assertFalse(asyncio.run(admin.has_view_permission(as_user(role_ids=(1,)))))

    def test_user_management_checks_the_auth_apps_permissions(self) -> None:
        from oldman.auth import user_permissions
        from oldman.auth.models import User

        admin = AdminSite().register_user_model(User)
        self.assertIs(user_permissions.CHANGE_USERS, admin.permission("change"))
        self.assertEqual("auth.users.delete", admin.permission("delete").name)
        self.assertEqual([], [p.name for p in declared_permissions() if p.namespace == "admin" and ".user." in f".{p.codename}"])

    def test_permission_names_follow_the_app_and_class_not_the_table(self) -> None:
        # A legacy table name need not make a valid permission name; the class name always does.
        self.assertEqual("admin.adminlegacyorder.view", AdminSite().register(AdminLegacyOrder).permission("view").name)

        # A model loaded through its App carries the App's label, as Django's app_label.view_model.
        table = cast(Table, AdminShopItem.__table__)
        table.info[APP_LABEL_INFO_KEY] = "shop"
        self.addCleanup(table.info.pop, APP_LABEL_INFO_KEY)
        self.assertEqual("admin.shop.adminshopitem.change", ModelAdmin(AdminShopItem).permission("change").name)

    def test_a_model_registered_before_its_app_was_loaded_stops_the_admin_from_starting(self) -> None:
        """G6-2: registered before load_models(), its permissions were declared without the App and checked with it."""
        early = type(
            "EarlyItem",
            (DatabaseModel,),
            {"__tablename__": "test_admin_early_item", "__module__": "tests.early_app.models", "id": mapped_column(Integer, primary_key=True)},
        )
        site = AdminSite()
        site.register(early)
        # What load_models() assigns once the App is loaded.
        table = cast(Table, cast(Any, early).__table__)
        table.info[APP_LABEL_INFO_KEY] = "early"
        self.addCleanup(table.info.pop, APP_LABEL_INFO_KEY)

        with self.assertRaisesRegex(RuntimeError, "before its App's models were loaded"):
            site.register_routes(Mock(), prefix="/control")

    def test_two_models_never_share_one_admin_permission(self) -> None:
        # Two Apps may both define a Twin; loaded without their Apps the names would meet.
        first = type(
            "Twin",
            (DatabaseModel,),
            {"__tablename__": "test_admin_twin_a", "__module__": "tests.twins_a", "id": mapped_column(Integer, primary_key=True)},
        )
        second = type(
            "Twin",
            (DatabaseModel,),
            {"__tablename__": "test_admin_twin_b", "__module__": "tests.twins_b", "id": mapped_column(Integer, primary_key=True)},
        )
        ModelAdmin(first).permission("view")
        with self.assertRaisesRegex(ValueError, "would share the Admin permission 'admin.twin.view'"):
            ModelAdmin(second).permission("view")

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

        superuser = as_user(is_superuser=True)
        items = asyncio.run(site.menu_items(superuser))
        groups = asyncio.run(site.menu_groups(superuser))

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


def as_user(*, is_superuser: bool = False, role_ids: tuple[int, ...] = ()) -> Any:
    """A request from a staff user, as the Admin permission checks read it."""
    user = RequestUser(id=5, username="staff", is_staff=True, is_superuser=is_superuser, role_ids=role_ids)
    app = SimpleNamespace(ctx=SimpleNamespace(app_registry=SimpleNamespace(labels=("auth", "admin", "roles"))))
    return SimpleNamespace(ctx=SimpleNamespace(user=user), app=app)
