"""Oldman Admin runtime integration tests."""

from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from jinja2 import DictLoader, Environment
from sanic import Sanic
from sanic import json as sanic_json
from sanic.exceptions import Forbidden, NotFound
from sanic.response import html as sanic_html
from sqlalchemy import Integer, String, Uuid
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

import oldman.conf as conf
from oldman.apps.admin.forms import AdminLoginForm
from oldman.apps.admin.model_admin import AdminUserModelAdmin, ModelAdmin, encode_admin_path_segment
from oldman.apps.admin.runtime import install_admin as _install_admin
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.site import AdminSite, admin_i18n_bootstrap, safe_next_url
from oldman.auth import AuthSettings
from oldman.auth.models import User
from oldman.conf.schemas import (
    I18nConfig,
    I18nLanguageConfig,
    SessionConfig,
    StaticConfig,
    WebConfig,
    WebSecurityConfig,
)
from oldman.db import db_manager as default_db_manager
from oldman.db.models import DatabaseModel
from oldman.web.session import SessionData
from oldman.web.staticfiles import StaticBundleRegistry


class RuntimeAdminRecord(DatabaseModel):
    """Mapped model used to verify Admin route installation."""

    __tablename__ = "test_oldman_admin_runtime_record"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class RuntimeRestrictedRecord(DatabaseModel):
    """Mapped model whose Admin requires a superuser."""

    __tablename__ = "test_oldman_admin_runtime_restricted_record"  # pyright: ignore[reportAssignmentType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class RuntimeNaturalKeyRecord(DatabaseModel):
    """Mapped model whose string key may equal a static route segment."""

    __tablename__ = "test_oldman_admin_runtime_natural_key_record"  # pyright: ignore[reportAssignmentType]

    slug: Mapped[str] = mapped_column(String(32), primary_key=True)


class RuntimeUUIDRecord(DatabaseModel):
    """Mapped model used to verify malformed UUID route handling."""

    __tablename__ = "test_oldman_admin_runtime_uuid_record"  # pyright: ignore[reportAssignmentType]

    record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)


class RuntimeRestrictedAdmin(ModelAdmin):
    """ModelAdmin used to verify authenticated permission denial."""

    require_superuser = True


class FakeSession(SessionData):
    """Concrete typed SessionData used by Admin route fixtures."""


class MissingObjectSession:
    """Database session that never resolves an Admin object."""

    async def get(self, model, object_id):
        del model, object_id
        return None


class AsyncSessionContext:
    """Async context manager returning a configured fake session."""

    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback


class MissingObjectDatabaseManager:
    """Database manager used by missing-object route tests."""

    def get_read_session(self) -> AsyncSessionContext:
        return AsyncSessionContext(MissingObjectSession())

    def get_session(self) -> AsyncSessionContext:
        return AsyncSessionContext(MissingObjectSession())


class ExistingObjectSession:
    """Database-session double that persists one configured Admin user in memory."""

    def __init__(self, instance) -> None:
        self.instance = instance
        self.added: list[object] = []
        self.deleted: list[object] = []

    async def get(self, model, object_id):
        if isinstance(self.instance, model):
            primary_key = list(ModelAdmin(model).mapper.primary_key)[0]
            if getattr(self.instance, primary_key.key, None) == object_id:
                return self.instance
        return None

    def add(self, instance) -> None:
        if isinstance(instance, User) and instance.id is None:
            instance.id = 13
        self.added.append(instance)
        self.instance = instance

    async def flush(self) -> None:
        return None

    async def delete(self, instance) -> None:
        self.deleted.append(instance)

    async def execute(self, statement):
        del statement
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class ExistingObjectDatabaseManager:
    """Database manager exposing the same in-memory session for read and write routes."""

    def __init__(self, instance) -> None:
        self.session = ExistingObjectSession(instance)

    def get_read_session(self) -> AsyncSessionContext:
        return AsyncSessionContext(self.session)

    def get_session(self) -> AsyncSessionContext:
        return AsyncSessionContext(self.session)


def runtime_settings(
    *,
    i18n: I18nConfig | None = None,
    session: SessionConfig | None = None,
    static_url: str = "/static",
) -> SimpleNamespace:
    """Return the minimum typed-settings shape required by Admin tests."""
    return SimpleNamespace(
        i18n=i18n or I18nConfig(),
        web=WebConfig(
            security=WebSecurityConfig(secret_key="oldman-admin-runtime-test-root-secret"),
            session=session or SessionConfig(),
            static=StaticConfig(
                root=str(Path("oldman/apps/admin/static").resolve()),
                url=static_url,
            ),
        ),
    )


DEFAULT_AUTH_SETTINGS = AuthSettings()
DEFAULT_ADMIN_SETTINGS = AdminSettings()


def install_admin(
    app: Any,
    *,
    auth_settings: AuthSettings | None = None,
    admin_settings: AdminSettings | None = None,
    **kwargs: Any,
) -> AdminSite:
    """Install Admin with explicit App settings for isolated unit tests."""
    return _install_admin(
        app,
        auth_settings=auth_settings or DEFAULT_AUTH_SETTINGS,
        admin_settings=admin_settings or DEFAULT_ADMIN_SETTINGS,
        **kwargs,
    )


class FakeApp:
    """Small app double that records routes and static mounts."""

    def __init__(self) -> None:
        self.config = {}
        self.ctx = SimpleNamespace()
        self.ext = SimpleNamespace(environment=Environment(loader=DictLoader({"project.html": "project"}), enable_async=True))
        self.routes: list[tuple[str, tuple[str, ...]]] = []
        self.route_handlers: dict[tuple[str, tuple[str, ...]], object] = {}
        self.static_routes: list[tuple[str, str, str]] = []
        self.listeners: list[tuple[object, str]] = []

    def add_route(self, handler, path: str, *, methods: list[str], name: str) -> None:
        del name
        self.routes.append((path, tuple(methods)))
        self.route_handlers[(path, tuple(methods))] = handler

    def static(self, url: str, directory: str, *, name: str) -> None:
        self.static_routes.append((url, directory, name))

    def register_listener(self, listener, event: str) -> None:
        self.listeners.append((listener, event))


class OldmanAdminRuntimeTest(unittest.TestCase):
    """Verify the public Admin installer creates a runnable integration."""

    def setUp(self) -> None:
        """Keep one global configuration active through installation and requests."""
        self.settings = runtime_settings()
        self.enterContext(patch.dict(conf.__dict__, {"settings": self.settings}))

    def test_installer_wires_templates_assets_helpers_and_routes(self) -> None:
        app = FakeApp()
        self.assertFalse(hasattr(app.ctx, "settings"))
        site = AdminSite("runtime_test_admin")
        site.register(RuntimeAdminRecord)

        installed = install_admin(app, db_manager=object(), admin_site=site, prefix="/control")  # type: ignore[arg-type]

        self.assertIs(site, installed)
        self.assertIsInstance(app.ctx.static_bundle_registry, StaticBundleRegistry)
        template_request = make_request(app, path="/control/login")
        template_request.ctx.csrf_token = "test-token"
        common_context = {
            "menu_items": [
                {
                    "label": "Records",
                    "path": "records",
                    "url": "/control/records",
                    "icon": "ri-archive-line",
                    "app_display_name": "Inventory",
                }
            ],
            "admin_prefix": "/control",
            "admin_bundle_name": "oldman:admin",
            "admin_is_authenticated": False,
            "admin_extension_bundle_name": None,
            "admin_csrf_token": "test-token",
            "admin_i18n": {},
            "dashboard_body_classes": " oldman-auth-page",
            "page_entry": "admin",
            "request": template_request,
        }
        rendered = app.ext.environment.get_template("admin/index.html").render(
            **common_context,
        )
        self.assertIn("Oldman Admin", rendered)
        self.assertIn("ri-archive-line", rendered)
        self.assertIn("Inventory", rendered)
        self.assertIn("bundle_script", app.ext.environment.globals)
        self.assertIsNotNone(app.ctx.csrf)
        login_html = app.ext.environment.get_template("admin/login.html").render(
            **common_context,
            login_error="",
            next_url="/control",
            login_form=AdminLoginForm(request=template_request),
        )
        self.assertIn('name="csrfmiddlewaretoken" value="test-token"', login_html)
        self.assertTrue(any(path == "/control" for path, _methods in app.routes))
        self.assertTrue(any(path == "/control/login" for path, _methods in app.routes))
        self.assertIn(("/control/user-session", ("GET",)), app.routes)
        self.assertIn(("/control/user-session/password-modal", ("GET",)), app.routes)
        self.assertIn(("/control/user-session/password", ("POST",)), app.routes)
        self.assertIn(("/control/preferences/language", ("POST",)), app.routes)
        self.assertIn(("/control/user-session/language", ("POST",)), app.routes)
        self.assertTrue(any(path == "/control/test_oldman_admin_runtime_record/table" for path, _methods in app.routes))
        self.assertEqual([], app.static_routes)

    def test_installer_uses_the_framework_default_database_manager(self) -> None:
        """普通项目安装 Admin 时不需要重复声明默认数据库 manager。"""
        app = FakeApp()
        site = AdminSite("runtime_default_manager_admin")

        with patch.object(site, "register_routes") as register_routes:
            installed = install_admin(app, admin_site=site, prefix="/control")

        self.assertIs(site, installed)
        register_routes.assert_called_once_with(
            app,
            prefix="/control",
            db_manager=default_db_manager,
            auth_settings=DEFAULT_AUTH_SETTINGS,
            admin_settings=DEFAULT_ADMIN_SETTINGS,
            notifications_enabled=False,
            sse_enabled=False,
        )

    def test_edit_routes_use_an_explicit_suffix_for_natural_keys(self) -> None:
        """String keys named ``new`` or ``table`` must not shadow static routes."""
        app = FakeApp()
        site = AdminSite("runtime_natural_key_admin")
        admin = site.register(RuntimeNaturalKeyRecord)

        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )

        model_prefix = "/control/test_oldman_admin_runtime_natural_key_record"
        self.assertIn((f"{model_prefix}/new", ("GET",)), app.routes)
        self.assertIn((f"{model_prefix}/table", ("GET",)), app.routes)
        self.assertIn((f"{model_prefix}/<object_id>/edit", ("GET",)), app.routes)
        self.assertIn((f"{model_prefix}/<object_id>/edit", ("POST",)), app.routes)
        self.assertNotIn((f"{model_prefix}/<object_id>", ("GET",)), app.routes)
        self.assertNotIn((f"{model_prefix}/<object_id>", ("POST",)), app.routes)
        for slug in ("new", "table"):
            with self.subTest(slug=slug):
                action = str(admin.table_action_html(RuntimeNaturalKeyRecord(slug=slug), admin_prefix="/control"))
                self.assertIn(f"{model_prefix}/{slug}/edit", action)

    def test_safe_next_url_rejects_browser_normalized_cross_origin_paths(self) -> None:
        """Protocol-relative paths must remain blocked after browser slash normalization."""
        for value in ("//evil.example/path", "///evil.example/path", "/\\evil.example/path", "/\tevil.example/path"):
            with self.subTest(value=value):
                self.assertEqual("/control", safe_next_url(value, "/control"))

        self.assertEqual("/control/users?page=2", safe_next_url("/control/users?page=2", "/control"))

    def test_encoded_primary_keys_round_trip_through_real_sanic_routing(self) -> None:
        """Reserved characters, including slash, remain one reversible route segment."""
        app = Sanic("runtime_encoded_admin_primary_keys")
        admin = ModelAdmin(RuntimeNaturalKeyRecord)
        records = {
            slug: RuntimeNaturalKeyRecord(slug=slug)
            for slug in (
                "hash#value",
                "query?value",
                "space value",
                "slash/value",
                ".",
                "..",
                "%2E",
                "%",
                "~b~collision",
            )
        }

        class RouteSession:
            async def get(self, model, object_id):
                return records.get(object_id) if model is RuntimeNaturalKeyRecord else None

        @app.get("/control/test_oldman_admin_runtime_natural_key_record/<object_id>/edit")
        async def edit_route(_request, object_id: str):
            instance = await admin.get_object(RouteSession(), object_id)  # type: ignore[arg-type]
            return sanic_json({"slug": instance.slug if instance is not None else None})

        expected_segments = {slug: encode_admin_path_segment(slug) for slug in records}
        self.assertNotIn(expected_segments["."], {".", "%2E"})
        self.assertNotIn(expected_segments[".."], {"..", ".%2E", "%2E."})
        for slug, segment in expected_segments.items():
            with self.subTest(slug=slug):
                record = records[slug]
                url = admin.get_object_url(record, admin_prefix="/control", action="edit")
                self.assertEqual(f"/control/test_oldman_admin_runtime_natural_key_record/{segment}/edit", url)
                _request, response = app.test_client.get(url)
                self.assertEqual(200, response.status)
                self.assertEqual({"slug": slug}, response.json)

    def test_admin_post_routes_reject_missing_csrf_before_business_logic(self) -> None:
        app = FakeApp()
        site = AdminSite("runtime_csrf_admin")
        site.register(RuntimeAdminRecord)
        install_admin(app, db_manager=object(), admin_site=site, prefix="/control")  # type: ignore[arg-type]
        handler = app.route_handlers[("/control/test_oldman_admin_runtime_record/new", ("POST",))]
        request = SimpleNamespace(
            app=app,
            ctx=SimpleNamespace(session={}),
            form={},
            headers={},
            host="example.test",
            json=None,
            path="/control/test_oldman_admin_runtime_record/new",
        )

        with self.assertRaisesRegex(Forbidden, "CSRF token missing"):
            asyncio.run(handler(request))  # type: ignore[operator]

    def test_login_route_wires_the_configured_last_login_service(self) -> None:
        """成功登录必须把配置和数据库交给登录时间服务。"""
        self.settings.web.session.expiry = 12345
        app = FakeApp()
        admin_settings = AdminSettings()
        auth_settings = AuthSettings()
        site = AdminSite("runtime_login_persistence_admin")
        manager = object()
        install_admin(
            app,
            db_manager=manager,  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
            auth_settings=auth_settings,
            admin_settings=admin_settings,
        )
        session_manager = SimpleNamespace(
            exclusive_login=AsyncMock(return_value="new-session-id"),
            update_session_id_to_cookie=MagicMock(),
        )
        app.ctx.session = session_manager
        user = make_admin_user()
        request = make_post_request(
            app,
            path="/control/login",
            session=FakeSession(),
            accept="text/html",
            form={
                "username": user.username,
                "password": "OldPass!2026",
                "next": "/control/oldman_user?page=2",
            },
        )
        request.ip = "127.0.0.1"
        request.client_ip = None
        handler = app.route_handlers[("/control/login", ("POST",))]

        with (
            patch("oldman.apps.admin.site.authenticate_user", AsyncMock(return_value=user)),
            patch("oldman.apps.admin.site.touch_last_login", AsyncMock()) as touch_last_login_mock,
        ):
            response = asyncio.run(handler(request))  # type: ignore[operator]

        self.assertEqual(302, response.status)
        self.assertEqual("/control/oldman_user?page=2", response.headers["Location"])
        touch_last_login_mock.assert_awaited_once_with(user.id, auth_settings=auth_settings, db_manager=manager)
        session_data = session_manager.exclusive_login.await_args.args[0]
        self.assertIsInstance(session_data, SessionData)
        self.assertEqual(user.id, session_data.user_id)
        self.assertEqual("Alice", session_data.display_name)
        self.assertEqual("127.0.0.1", session_data.login_ip)
        self.assertGreater(session_data.login_time, 0)
        self.assertEqual(12345, session_data.expiry)
        session_manager.update_session_id_to_cookie.assert_called_once_with(
            response,
            "new-session-id",
            session_data,
        )

    def test_installer_uses_the_configured_collected_static_root(self) -> None:
        """Typed static settings govern Admin manifest and entry URLs."""
        app = FakeApp()
        self.settings.web.static.url = "/assets"
        site = AdminSite("runtime_custom_static_admin")
        site.register(RuntimeAdminRecord)

        install_admin(
            app,
            db_manager=object(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )

        registry = app.ctx.static_bundle_registry
        self.assertEqual(
            "/assets/oldman/admin",
            registry.get("oldman:admin").static_url,
        )
        self.assertEqual([], app.static_routes)
        self.assertIn(
            "/assets/oldman/admin/assets/",
            str(registry.entry_tags("oldman:admin")),
        )

    def test_authenticated_permission_denial_returns_403_without_login_redirect(self) -> None:
        """已登录 staff 的页面和 Table 权限不足时必须 403，不能形成登录循环。"""
        app = FakeApp()
        site = AdminSite("runtime_permission_admin")
        site.register(RuntimeRestrictedRecord, RuntimeRestrictedAdmin)
        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        request = make_request(
            app,
            path="/control/test_oldman_admin_runtime_restricted_record",
            session=FakeSession(user_id=7, is_active=True, is_staff=True, is_superuser=False),
        )

        route_cases = (
            ("/control/test_oldman_admin_runtime_restricted_record", ("GET",), {}),
            ("/control/test_oldman_admin_runtime_restricted_record/new", ("GET",), {}),
            ("/control/test_oldman_admin_runtime_restricted_record/<object_id>/edit", ("GET",), {"object_id": "7"}),
            ("/control/test_oldman_admin_runtime_restricted_record/<object_id>/delete", ("GET",), {"object_id": "7"}),
            ("/control/test_oldman_admin_runtime_restricted_record/table", ("GET",), {}),
        )
        for path, methods, kwargs in route_cases:
            with self.subTest(path=path):
                handler = app.route_handlers[(path, methods)]
                response = asyncio.run(handler(request, **kwargs))  # type: ignore[operator]
                self.assertEqual(403, response.status)
                self.assertNotIn("Location", response.headers)
                self.assertIn("text/html", response.content_type)
                self.assertIn(b"403", response.body)

    def test_language_preference_uses_cookies_with_typed_session_data(self) -> None:
        """Admin 语言偏好不得把未声明字段写入强类型 Session。"""
        app = FakeApp()
        self.settings.i18n = I18nConfig(
            use_i18n=True,
            default_language="en",
            languages={"en": I18nLanguageConfig(), "zh-Hans": I18nLanguageConfig()},
        )
        self.settings.web.session.cookie_secure = True
        site = AdminSite("runtime_language_preference_admin")
        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        session = FakeSession(
            user_id=7,
            username="admin",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        request = make_request(
            app,
            path="/control/preferences/language",
            session=session,
        )
        request.method = "POST"
        request.json = {"language": "zh-CN"}
        request.headers = {
            "X-CSRFToken": app.ctx.csrf.generate_token(request),
            "content-type": "application/json",
        }
        handler = app.route_handlers[("/control/preferences/language", ("POST",))]

        response = asyncio.run(handler(request))  # type: ignore[operator]

        self.assertEqual(200, response.status)
        self.assertEqual("zh-Hans", json.loads(response.body)["data"]["language"])
        self.assertEqual("zh-Hans", response.cookies.get_cookie("lang").value)
        self.assertTrue(response.cookies.get_cookie("lang").secure)
        self.assertEqual(
            "zh-Hans",
            response.cookies.get_cookie("preferred_language").value,
        )
        self.assertEqual("admin", session.username)

        alias_request = make_request(
            app,
            path="/control/user-session/language",
            session=session,
        )
        alias_request.method = "POST"
        alias_request.json = {"language": "en"}
        alias_request.headers = {
            "X-CSRFToken": app.ctx.csrf.generate_token(alias_request),
            "content-type": "application/json",
        }
        alias_handler = app.route_handlers[("/control/user-session/language", ("POST",))]

        alias_response = asyncio.run(alias_handler(alias_request))  # type: ignore[operator]

        self.assertEqual(200, alias_response.status)
        self.assertEqual("en", json.loads(alias_response.body)["data"]["language"])

    def test_current_session_page_reads_typed_snapshot_without_database_access(self) -> None:
        """Admin Session 页面只消费登录快照，并复用共享页面与账户菜单。"""
        app = FakeApp()
        site = AdminSite("runtime_current_session_admin")
        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        request = make_request(
            app,
            path="/control/user-session",
            session=FakeSession(
                user_id=12,
                username="alice",
                display_name="Alice",
                login_ip="127.0.0.1",
                login_time=1_690_000_000,
                is_active=True,
                is_staff=True,
                is_superuser=False,
            ),
        )
        request.headers = {"accept": "text/html"}
        handler = app.route_handlers[("/control/user-session", ("GET",))]

        with patch(
            "oldman.apps.admin.site.render_template",
            side_effect=render_with_request_environment,
        ):
            response = asyncio.run(handler(request))  # type: ignore[operator]

        self.assertEqual(200, response.status)
        self.assertIn(b"Alice", response.body)
        self.assertIn(b"127.0.0.1", response.body)
        self.assertIn(b'data-om-modal-url="/control/user-session/password-modal"', response.body)
        self.assertIn(b'href="/control/user-session"', response.body)
        self.assertIn(b'href="/control/sign-out"', response.body)
        self.assertIn(b'data-om-component="dropdown"', response.body)

    def test_current_session_password_routes_change_only_the_signed_in_user(self) -> None:
        """Admin 当前用户密码流程复用共享 Form、Modal 与业务服务。"""
        user = make_admin_user()
        app, _model_path = install_user_admin(user)
        session = FakeSession(
            user_id=12,
            username="alice",
            display_name="Alice",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )

        modal_request = make_request(
            app,
            path="/control/user-session/password-modal",
            session=session,
        )
        modal_request.headers = {"accept": "application/json"}
        modal_handler = app.route_handlers[
            ("/control/user-session/password-modal", ("GET",))
        ]
        modal_response = asyncio.run(modal_handler(modal_request))  # type: ignore[operator]
        modal_payload = json.loads(modal_response.body)

        self.assertEqual(200, modal_response.status)
        self.assertIn('action="/control/user-session/password"', modal_payload["html"])
        self.assertIn("alice@example.test", modal_payload["html"])
        self.assertNotIn("om-badge", modal_payload["html"])

        password_request = make_post_request(
            app,
            path="/control/user-session/password",
            session=session,
            accept="application/json",
            form={
                "password": "CurrentPass!2026",
                "confirm_password": "CurrentPass!2026",
            },
        )
        password_handler = app.route_handlers[
            ("/control/user-session/password", ("POST",))
        ]
        password_response = asyncio.run(password_handler(password_request))  # type: ignore[operator]
        password_payload = json.loads(password_response.body)

        self.assertEqual(200, password_response.status)
        self.assertEqual(
            ["feedback", "dashboard_activity", "close_modal"],
            [action["action"] for action in password_payload["actions"]],
        )
        self.assertEqual("Session password changed", password_payload["actions"][0]["title"])
        self.assertTrue(user.check_password("CurrentPass!2026"))

    def test_admin_language_urls_remove_stale_query_language(self) -> None:
        """Cookie-mode language links preserve user query state without a stale lang override."""
        app = FakeApp()
        self.settings.i18n = I18nConfig(
            use_i18n=True,
            default_language="en",
            languages={"en": I18nLanguageConfig(), "zh-Hans": I18nLanguageConfig()},
        )
        request = make_request(
            app,
            path="/control/users",
            query_string="page=2&lang=en&filter.status=active",
        )
        request.ctx.locale = "en"

        bootstrap = admin_i18n_bootstrap(cast(Any, request), "/control")

        self.assertEqual(
            {"/control/users?page=2&filter.status=active"},
            {str(language["url"]) for language in bootstrap["languages"]},
        )

    def test_admin_language_urls_use_clean_path_and_one_language_prefix(self) -> None:
        """Path-mode links replace the current prefix instead of nesting language segments."""
        app = FakeApp()
        self.settings.i18n = I18nConfig(
            use_i18n=True,
            use_i18n_path=True,
            default_language="en",
            languages={
                "en": I18nLanguageConfig(),
                "zh-Hans": I18nLanguageConfig(),
                "zh-Hant": I18nLanguageConfig(),
            },
        )
        request = make_request(
            app,
            path="/zh-Hans/control/users",
            query_string="lang=zh-Hans&page=3",
        )
        request.ctx.clean_path = "/control/users"
        request.ctx.locale = "zh-Hans"

        bootstrap = admin_i18n_bootstrap(cast(Any, request), "/control")
        urls = {str(language["code"]): str(language["url"]) for language in bootstrap["languages"]}

        self.assertEqual("/control/users?page=3", urls["en"])
        self.assertEqual("/zh-Hans/control/users?page=3", urls["zh-Hans"])
        self.assertEqual("/zh-Hant/control/users?page=3", urls["zh-Hant"])

    def test_unauthenticated_admin_permission_entries_negotiate_html_and_json(self) -> None:
        """Every Admin permission entry must use its own safe login URL after session expiry."""
        app, model_path = install_user_admin(make_admin_user())
        route_cases = (
            ("/control", ("GET",), "/control", {}),
            ("/control/user-session", ("GET",), "/control/user-session", {}),
            (
                "/control/user-session/password-modal",
                ("GET",),
                "/control/user-session/password-modal",
                {},
            ),
            (
                "/control/user-session/password",
                ("POST",),
                "/control/user-session/password",
                {},
            ),
            (f"/control/{model_path}", ("GET",), f"/control/{model_path}", {}),
            (f"/control/{model_path}/table", ("GET",), f"/control/{model_path}/table", {}),
            (f"/control/{model_path}/new", ("GET",), f"/control/{model_path}/new", {}),
            (f"/control/{model_path}/new", ("POST",), f"/control/{model_path}/new", {}),
            (f"/control/{model_path}/<object_id>/edit", ("GET",), f"/control/{model_path}/12/edit", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/edit", ("POST",), f"/control/{model_path}/12/edit", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/delete", ("POST",), f"/control/{model_path}/12/delete", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/password", ("POST",), f"/control/{model_path}/12/password", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/password-modal", ("GET",), f"/control/{model_path}/12/password-modal", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/status", ("POST",), f"/control/{model_path}/12/status", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/status-modal", ("GET",), f"/control/{model_path}/12/status-modal", {"object_id": "12"}),
            (f"/control/{model_path}/<object_id>/delete-modal", ("GET",), f"/control/{model_path}/12/delete-modal", {"object_id": "12"}),
        )

        for route_path, methods, request_path, kwargs in route_cases:
            handler = app.route_handlers[(route_path, methods)]
            next_url = f"{request_path}?page=2"
            expected_login_url = f"/control/login?{urlencode({'next': next_url})}"
            for accept, expected_status in (("text/html", 302), ("application/json", 401)):
                with self.subTest(path=request_path, method=methods[0], accept=accept):
                    request = make_request(app, path=request_path, query_string="page=2")
                    request.headers = {"accept": accept}
                    if methods == ("POST",):
                        request.method = "POST"
                        request.form = {"csrfmiddlewaretoken": app.ctx.csrf.generate_token(request)}

                    response = asyncio.run(handler(request, **kwargs))  # type: ignore[operator]

                    self.assertEqual(expected_status, response.status)
                    if accept == "text/html":
                        self.assertEqual(expected_login_url, response.headers["Location"])
                        continue
                    self.assertEqual(
                        {
                            "error_code": 1401,
                            "message": "Authentication required",
                            "data": {"login_url": "/control/login"},
                            "actions": [],
                        },
                        json.loads(response.body),
                    )

    def test_missing_edit_and_delete_objects_return_404(self) -> None:
        """不存在的对象不能被渲染成新建表单或空删除确认页。"""
        app = FakeApp()
        site = AdminSite("runtime_missing_object_admin")
        site.register(RuntimeAdminRecord)
        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        session = FakeSession(user_id=7, is_active=True, is_staff=True, is_superuser=True)

        for suffix in ("/404/edit", "/404/delete"):
            path = f"/control/test_oldman_admin_runtime_record{suffix}"
            handler = app.route_handlers[
                (
                    "/control/test_oldman_admin_runtime_record/<object_id>/delete"
                    if suffix.endswith("/delete")
                    else "/control/test_oldman_admin_runtime_record/<object_id>/edit",
                    ("GET",),
                )
            ]
            with self.assertRaises(NotFound):
                asyncio.run(handler(make_request(app, path=path, session=session), object_id="404"))  # type: ignore[operator]

        for route_path, request_path in (
            ("/control/test_oldman_admin_runtime_record/<object_id>/edit", "/control/test_oldman_admin_runtime_record/404/edit"),
            ("/control/test_oldman_admin_runtime_record/<object_id>/delete", "/control/test_oldman_admin_runtime_record/404/delete"),
        ):
            request = make_request(app, path=request_path, session=session)
            request.method = "POST"
            request.form = {"csrfmiddlewaretoken": app.ctx.csrf.generate_token(request)}
            handler = app.route_handlers[(route_path, ("POST",))]
            with self.assertRaises(NotFound):
                asyncio.run(handler(request, object_id="404"))  # type: ignore[operator]

    def test_malformed_integer_and_uuid_primary_keys_are_route_level_404s(self) -> None:
        """Typed primary-key coercion failures must never escape as application 500s."""
        session = FakeSession(user_id=7, is_active=True, is_staff=True, is_superuser=True)
        cases = (
            (RuntimeAdminRecord, "not-an-integer"),
            (RuntimeUUIDRecord, "not-a-uuid"),
        )
        for model, object_id in cases:
            with self.subTest(model=model.__name__):
                app = FakeApp()
                site = AdminSite(f"runtime_invalid_{model.__name__.lower()}")
                admin = site.register(model)
                install_admin(
                    app,
                    db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
                    admin_site=site,
                    prefix="/control",
                )
                for action, method in (("edit", "GET"), ("edit", "POST"), ("delete", "GET"), ("delete", "POST")):
                    with self.subTest(model=model.__name__, action=action, method=method):
                        route = f"/control/{admin.model_path}/<object_id>/{action}"
                        request_path = route.replace("<object_id>", object_id)
                        if method == "POST":
                            request = make_post_request(
                                app,
                                path=request_path,
                                session=session,
                                accept="text/html",
                                form={},
                            )
                        else:
                            request = make_request(app, path=request_path, session=session)
                        handler = app.route_handlers[(route, (method,))]
                        with self.assertRaises(NotFound):
                            asyncio.run(handler(request, object_id=object_id))  # type: ignore[operator]

    def test_oversized_integer_primary_key_is_a_route_level_404_with_real_sqlite(self) -> None:
        """A driver-level integer overflow is still an invalid route identity, not a 500."""
        with self.assertRaises(NotFound):
            asyncio.run(request_oversized_integer_admin_route())

    def test_missing_user_edit_redirects_to_list_but_malformed_id_is_404(self) -> None:
        """Match source user-page recovery without hiding malformed typed routes."""
        app = FakeApp()
        site = AdminSite("runtime_missing_user_edit")
        admin = site.register(User, AdminUserModelAdmin)
        install_admin(
            app,
            db_manager=MissingObjectDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        route = f"/control/{admin.model_path}/<object_id>/edit"
        handler = app.route_handlers[(route, ("GET",))]
        session = FakeSession(user_id=7, is_active=True, is_staff=True, is_superuser=True)

        missing_request = make_request(app, path=route.replace("<object_id>", "404"), session=session)
        response = asyncio.run(handler(missing_request, object_id="404"))  # type: ignore[operator]
        self.assertEqual(302, response.status)
        self.assertEqual(f"/control/{admin.model_path}", response.headers["Location"])

        malformed_request = make_request(app, path=route.replace("<object_id>", "invalid"), session=session)
        with self.assertRaises(NotFound):
            asyncio.run(handler(malformed_request, object_id="invalid"))  # type: ignore[operator]

        malformed_cases = (
            ("edit", "POST"),
            ("delete", "POST"),
            ("password", "POST"),
            ("password-modal", "GET"),
            ("status", "POST"),
            ("status-modal", "GET"),
            ("delete-modal", "GET"),
        )
        for action, method in malformed_cases:
            with self.subTest(action=action, method=method):
                action_route = f"/control/{admin.model_path}/<object_id>/{action}"
                request_path = action_route.replace("<object_id>", "invalid")
                if method == "POST":
                    request = make_post_request(
                        app,
                        path=request_path,
                        session=session,
                        accept="application/json",
                        form={},
                    )
                else:
                    request = make_request(app, path=request_path, session=session)
                    request.headers = {"accept": "application/json"}
                action_handler = app.route_handlers[(action_route, (method,))]
                with self.assertRaises(NotFound):
                    asyncio.run(action_handler(request, object_id="invalid"))  # type: ignore[operator]

    def test_user_list_page_keeps_source_user_copy_and_add_icon(self) -> None:
        """User list metadata must render the source Users/New User contract."""
        app, model_path = install_user_admin(make_admin_user())
        route_path = f"/control/{model_path}"
        handler = app.route_handlers[(route_path, ("GET",))]
        session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)
        request = make_request(app, path=route_path, session=session)
        request.headers = {"accept": "text/html"}

        with patch("oldman.apps.admin.site.render_template", side_effect=render_with_request_environment):
            response = asyncio.run(handler(request))  # type: ignore[operator]

        self.assertEqual(200, response.status)
        self.assertIn(b"<title>Users \xc2\xb7 Oldman Admin</title>", response.body)
        self.assertIn(b'<h1 class="om-page-title">Users</h1>', response.body)
        self.assertIn(b'<h2 class="om-card-title">Users List</h2>', response.body)
        self.assertIn(b'class="ri-user-add-line align-bottom mr-1"', response.body)
        self.assertIn(b"<span>New User</span>", response.body)
        self.assertNotIn(b"Admin User", response.body)

    def test_user_create_route_preserves_shared_form_json_and_html_contracts(self) -> None:
        """Create pages mount shared Form validation/feedback and return source payloads."""
        app, model_path = install_user_admin(make_admin_user())
        route_path = f"/control/{model_path}/new"
        get_handler = app.route_handlers[(route_path, ("GET",))]
        post_handler = app.route_handlers[(route_path, ("POST",))]
        session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)

        page_request = make_request(app, path=route_path, session=session)
        page_request.headers = {"accept": "text/html"}
        with patch("oldman.apps.admin.site.render_template", side_effect=render_with_request_environment):
            response = asyncio.run(get_handler(page_request))  # type: ignore[operator]
        self.assertEqual(200, response.status)
        self.assertIn(b'data-om-component="feedback"', response.body)
        self.assertIn(b'data-om-component="form"', response.body)
        self.assertIn(b"data-om-form-validate", response.body)
        self.assertIn(b'data-om-feedback-target="#admin-oldman_user-form-feedback"', response.body)
        self.assertIn(b'action="/control/oldman_user/new"', response.body)
        self.assertIn(b"<title>User \xc2\xb7 Oldman Admin</title>", response.body)
        self.assertIn(b'<h1 class="om-page-title">New User</h1>', response.body)
        self.assertIn(b'<i class="ri-arrow-left-line align-bottom mr-1"', response.body)
        self.assertIn(b'aria-hidden="true"></i>Users', response.body)
        self.assertIn(b'href="/control/oldman_user" class="om-button om-button-soft-secondary om-button-sm"', response.body)
        self.assertIn(b'<button type="submit" class="om-button om-button-primary">Save</button>', response.body)
        self.assertNotIn(b'class="om-card-header"', response.body)
        self.assertNotIn(b'<div class="om-card max-w-3xl">', response.body)

        invalid_request = make_post_request(
            app,
            path=route_path,
            session=session,
            accept="application/json",
            form={
                "username": "bob",
                "password": "abcdefgh",
                "confirm_password": "different",
                "is_active": "y",
            },
        )
        response = asyncio.run(post_handler(invalid_request))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual(1100, payload["error_code"])
        self.assertIn("password", payload["errors"])
        self.assertIn("confirm_password", payload["errors"])

        valid_form = {
            "username": "bob",
            "email": "bob@example.test",
            "display_name": "Bob",
            "password": "Str0ngPass!2026",
            "confirm_password": "Str0ngPass!2026",
            "is_active": "y",
            "is_staff": "y",
        }
        valid_request = make_post_request(
            app,
            path=route_path,
            session=session,
            accept="application/json",
            form=valid_form,
        )
        response = asyncio.run(post_handler(valid_request))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual(0, payload["error_code"])
        self.assertEqual(["feedback", "dashboard_activity", "redirect"], [action["action"] for action in payload["actions"]])
        self.assertEqual("User created", payload["actions"][0]["title"])
        self.assertEqual("success", payload["actions"][0]["icon"])
        self.assertEqual(f"/control/{model_path}/13/edit", payload["actions"][2]["url"])
        self.assertEqual(1200, payload["actions"][2]["delay_ms"])

        html_app, html_model_path = install_user_admin(make_admin_user())
        html_handler = html_app.route_handlers[(f"/control/{html_model_path}/new", ("POST",))]
        html_request = make_post_request(
            html_app,
            path=f"/control/{html_model_path}/new",
            session=session,
            accept="text/html",
            form=valid_form,
        )
        response = asyncio.run(html_handler(html_request))  # type: ignore[operator]
        self.assertEqual(303, response.status)
        self.assertEqual(f"/control/{html_model_path}/13/edit", response.headers["Location"])

    def test_user_edit_route_preserves_shared_form_json_and_html_contracts(self) -> None:
        """Edit uses ``/<pk>/edit`` and the same Form response protocol as create."""
        user = make_admin_user()
        app, model_path = install_user_admin(user)
        route_path = f"/control/{model_path}/12/edit"
        route_pattern = f"/control/{model_path}/<object_id>/edit"
        get_handler = app.route_handlers[(route_pattern, ("GET",))]
        post_handler = app.route_handlers[(route_pattern, ("POST",))]
        session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)

        page_request = make_request(app, path=route_path, session=session)
        page_request.headers = {"accept": "text/html"}
        with patch("oldman.apps.admin.site.render_template", side_effect=render_with_request_environment):
            response = asyncio.run(get_handler(page_request, object_id="12"))  # type: ignore[operator]
        self.assertEqual(200, response.status)
        self.assertIn(b'data-om-component="feedback"', response.body)
        self.assertIn(b'data-om-component="form"', response.body)
        self.assertIn(b"data-om-form-validate", response.body)
        self.assertIn(b'data-om-feedback-target="#admin-oldman_user-form-feedback"', response.body)
        self.assertIn(b'action="/control/oldman_user/12/edit"', response.body)
        self.assertIn(b"<title>User \xc2\xb7 Oldman Admin</title>", response.body)
        self.assertIn(b'<h1 class="om-page-title">Edit User</h1>', response.body)
        self.assertIn(b'<i class="ri-arrow-left-line align-bottom mr-1"', response.body)
        self.assertIn(b'<button type="submit" class="om-button om-button-primary">Save</button>', response.body)
        self.assertNotIn(b'class="om-card-header"', response.body)
        self.assertNotIn(b'<div class="om-card max-w-3xl">', response.body)

        invalid_request = make_post_request(
            app,
            path=route_path,
            session=session,
            accept="application/json",
            form={"username": "", "email": "alice@example.test", "is_active": "y", "is_staff": "y"},
        )
        response = asyncio.run(post_handler(invalid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual(1100, payload["error_code"])
        self.assertIn("username", payload["errors"])

        valid_form = {
            "username": "alice-updated",
            "email": "alice@example.test",
            "display_name": "Alice Updated",
            "is_active": "y",
            "is_staff": "y",
        }
        valid_request = make_post_request(
            app,
            path=route_path,
            session=session,
            accept="application/json",
            form=valid_form,
        )
        response = asyncio.run(post_handler(valid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual(0, payload["error_code"])
        self.assertEqual(["feedback", "dashboard_activity", "redirect"], [action["action"] for action in payload["actions"]])
        self.assertEqual("User saved", payload["actions"][0]["title"])
        self.assertEqual(route_path, payload["actions"][2]["url"])
        self.assertEqual(1200, payload["actions"][2]["delay_ms"])
        self.assertEqual("alice-updated", user.username)

        html_user = make_admin_user()
        html_app, html_model_path = install_user_admin(html_user)
        html_route_path = f"/control/{html_model_path}/12/edit"
        html_handler = html_app.route_handlers[(f"/control/{html_model_path}/<object_id>/edit", ("POST",))]
        html_request = make_post_request(
            html_app,
            path=html_route_path,
            session=session,
            accept="text/html",
            form=valid_form,
        )
        response = asyncio.run(html_handler(html_request, object_id="12"))  # type: ignore[operator]
        self.assertEqual(303, response.status)
        self.assertEqual(html_route_path, response.headers["Location"])

    def test_user_delete_routes_use_source_modal_and_post_contract(self) -> None:
        """Delete exposes exactly the source ``-modal`` GET and submit POST."""
        user = make_admin_user()
        app, model_path = install_user_admin(user)
        route_path = f"/control/{model_path}/12/delete"
        route_pattern = f"/control/{model_path}/<object_id>/delete"
        modal_handler = app.route_handlers[(f"{route_pattern}-modal", ("GET",))]
        post_handler = app.route_handlers[(route_pattern, ("POST",))]
        self.assertNotIn((route_pattern, ("GET",)), app.route_handlers)
        session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)

        json_request = make_request(app, path=f"{route_path}-modal", session=session)
        json_request.headers = {"accept": "application/json"}
        response = asyncio.run(modal_handler(json_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual("Delete User · alice", payload["title"])
        self.assertIn('action="/control/oldman_user/12/delete"', payload["html"])
        self.assertIn('data-om-component="form"', payload["html"])
        self.assertIn('data-om-form-mode="json"', payload["html"])
        self.assertIn("data-om-modal-close", payload["html"])
        self.assertIn("data-om-form-message", payload["html"])
        self.assertNotIn('data-om-error-for="__all__"', payload["html"])

        delete_request = make_post_request(
            app,
            path=route_path,
            session=session,
            accept="application/json",
            form={},
        )
        response = asyncio.run(post_handler(delete_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)
        self.assertEqual(200, response.status)
        self.assertEqual(0, payload["error_code"])
        self.assertEqual(
            ["feedback", "dashboard_activity", "close_modal", "reload_table"],
            [action["action"] for action in payload["actions"]],
        )
        self.assertEqual("User deleted", payload["actions"][0]["title"])
        self.assertEqual(f"#admin-{model_path}-table", payload["actions"][3]["target"])
        self.assertEqual([user], app.ctx.test_admin_db_manager.session.deleted)

    def test_user_password_routes_use_source_modal_and_post_contract(self) -> None:
        """Password exposes exactly the source ``-modal`` GET and submit POST."""
        user = make_admin_user()
        app, model_path = install_user_admin(user)
        route_pattern = f"/control/{model_path}/<object_id>/password"
        modal_handler = app.route_handlers[(f"/control/{model_path}/<object_id>/password-modal", ("GET",))]
        post_handler = app.route_handlers[(route_pattern, ("POST",))]
        self.assertNotIn((route_pattern, ("GET",)), app.route_handlers)
        session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)

        json_request = make_request(app, path=f"/control/{model_path}/12/password-modal", session=session)
        json_request.headers = {"accept": "application/json"}
        response = asyncio.run(modal_handler(json_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual("Change Password · alice", payload["title"])
        self.assertIn('action="/control/oldman_user/12/password"', payload["html"])
        self.assertIn('data-om-component="form"', payload["html"])
        self.assertIn('data-om-component="form-validator"', payload["html"])
        self.assertIn("data-om-form-validate", payload["html"])
        self.assertIn("data-om-form", payload["html"])
        self.assertIn('data-om-form-mode="json"', payload["html"])
        self.assertIn("data-om-form-message", payload["html"])
        self.assertIn("data-om-modal-close", payload["html"])

        invalid_request = make_post_request(
            app,
            path=f"/control/{model_path}/12/password",
            session=session,
            accept="application/json",
            form={"password": "abcdefgh", "confirm_password": "different"},
        )
        response = asyncio.run(post_handler(invalid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual(1100, payload["error_code"])
        self.assertIn("password", payload["errors"])
        self.assertIn("confirm_password", payload["errors"])

        valid_request = make_post_request(
            app,
            path=f"/control/{model_path}/12/password",
            session=session,
            accept="application/json",
            form={"password": "NewPass!2026", "confirm_password": "NewPass!2026"},
        )
        response = asyncio.run(post_handler(valid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual(0, payload["error_code"])
        self.assertEqual(
            ["feedback", "dashboard_activity", "close_modal", "reload_table"],
            [action["action"] for action in payload["actions"]],
        )
        self.assertEqual("Password changed", payload["actions"][0]["title"])
        self.assertEqual(f"#admin-{model_path}-table", payload["actions"][3]["target"])
        self.assertTrue(user.check_password("NewPass!2026"))

    def test_user_status_routes_use_source_modal_and_post_contract(self) -> None:
        """Status exposes exactly the source ``-modal`` GET and submit POST."""
        user = make_admin_user()
        app, model_path = install_user_admin(user)
        route_pattern = f"/control/{model_path}/<object_id>/status"
        modal_handler = app.route_handlers[(f"/control/{model_path}/<object_id>/status-modal", ("GET",))]
        post_handler = app.route_handlers[(route_pattern, ("POST",))]
        self.assertNotIn((route_pattern, ("GET",)), app.route_handlers)
        current_session = FakeSession(user_id=12, is_active=True, is_staff=True, is_superuser=True)

        json_request = make_request(app, path=f"/control/{model_path}/12/status-modal", session=current_session)
        json_request.headers = {"accept": "application/json"}
        response = asyncio.run(modal_handler(json_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual("Disable User · alice", payload["title"])
        self.assertIn('action="/control/oldman_user/12/status"', payload["html"])
        self.assertIn('name="is_active" value="false"', payload["html"])
        self.assertIn('data-om-component="form"', payload["html"])
        self.assertIn('data-om-form-mode="json"', payload["html"])
        self.assertIn("data-om-modal-close", payload["html"])

        invalid_request = make_post_request(
            app,
            path=f"/control/{model_path}/12/status",
            session=current_session,
            accept="application/json",
            form={"is_active": "false"},
        )
        response = asyncio.run(post_handler(invalid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual(1100, payload["error_code"])
        self.assertEqual("cannot disable current user", payload["message"])
        self.assertEqual({}, payload["errors"])
        self.assertTrue(user.is_active)

        other_session = FakeSession(user_id=99, is_active=True, is_staff=True, is_superuser=True)
        valid_request = make_post_request(
            app,
            path=f"/control/{model_path}/12/status",
            session=other_session,
            accept="application/json",
            form={"is_active": "false"},
        )
        response = asyncio.run(post_handler(valid_request, object_id="12"))  # type: ignore[operator]
        payload = json.loads(response.body)

        self.assertEqual(200, response.status)
        self.assertEqual(
            ["feedback", "dashboard_activity", "close_modal", "reload_table"],
            [action["action"] for action in payload["actions"]],
        )
        self.assertEqual(f"#admin-{model_path}-table", payload["actions"][3]["target"])
        self.assertFalse(user.is_active)



def make_admin_user() -> User:
    """Build a persisted-looking user for password and status route tests."""
    user = User(
        id=12,
        username="alice",
        email="alice@example.test",
        display_name="Alice",
        password_hash="",
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )
    user.set_password("OldPass!2026")
    return user


def install_user_admin(user: Any) -> tuple[FakeApp, str]:
    """Install the built-in user admin against an in-memory object manager."""
    app = FakeApp()
    site = AdminSite("runtime_user_modal_admin")
    user_model = type(user)
    auth_settings = AuthSettings(
        user_model=f"{user_model.__module__}.{user_model.__name__}"
    )
    site.register(user_model, AdminUserModelAdmin)
    manager = ExistingObjectDatabaseManager(user)
    app.ctx.test_admin_db_manager = manager
    install_admin(
        app,
        db_manager=manager,  # type: ignore[arg-type]
        admin_site=site,
        prefix="/control",
        auth_settings=auth_settings,
    )
    return app, site.get_model_admin(user_model).model_path


def make_post_request(
    app: FakeApp,
    *,
    path: str,
    session: FakeSession,
    accept: str,
    form: dict[str, str],
):
    """Build a CSRF-valid form request with the requested response mode."""
    request = make_request(app, path=path, session=session)
    request.method = "POST"
    request.headers = {"accept": accept}
    request.form = dict(form)
    request.form["csrfmiddlewaretoken"] = app.ctx.csrf.generate_token(request)
    return request


async def request_oversized_integer_admin_route() -> None:
    """Invoke the installed edit route against a real SQLite AsyncSession."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(cast(Any, RuntimeAdminRecord.__table__).create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        class RealDatabaseManager:
            def get_read_session(self):
                return session_factory()

            def get_session(self):
                return session_factory()

        app = FakeApp()
        site = AdminSite("runtime_oversized_integer_admin")
        admin = site.register(RuntimeAdminRecord)
        install_admin(
            app,
            db_manager=RealDatabaseManager(),  # type: ignore[arg-type]
            admin_site=site,
            prefix="/control",
        )
        route = f"/control/{admin.model_path}/<object_id>/edit"
        object_id = str(10**100)
        session = FakeSession(user_id=7, is_active=True, is_staff=True, is_superuser=True)
        request = make_request(app, path=route.replace("<object_id>", object_id), session=session)
        handler = app.route_handlers[(route, ("GET",))]
        await handler(request, object_id=object_id)  # type: ignore[operator]
    finally:
        await engine.dispose()


async def render_with_request_environment(template_name: str = "", *, context=None, **kwargs):
    """Render Sanic-Ext templates against the FakeApp carried by test context."""
    del kwargs
    resolved_context = dict(context or {})
    request = resolved_context["request"]
    template = request.app.ext.environment.get_template(template_name)
    content = await template.render_async(**resolved_context)
    return sanic_html(content)


def make_request(
    app: FakeApp,
    *,
    path: str,
    query_string: str = "",
    session: FakeSession | None = None,
):
    """Build the minimum request protocol used by Admin route tests."""
    return SimpleNamespace(
        app=app,
        args={},
        cookies={},
        ctx=SimpleNamespace(session=session or FakeSession()),
        form={},
        headers={},
        host="example.test",
        json=None,
        method="GET",
        path=path,
        query_string=query_string,
    )


if __name__ == "__main__":
    unittest.main()
