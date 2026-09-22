"""Admin site registry."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlencode

from babel.support import Translations
from markupsafe import escape
from sanic.response import redirect

import oldman.conf as conf
from oldman.apps.admin.model_admin import (
    AdminUserModelAdmin,
    InvalidAdminObjectId,
    ModelAdmin,
    request_user_id,
)
from oldman.apps.admin.permissions import has_admin_permission, is_authenticated
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.table import AdminModelTable, _AdminUserModelTable
from oldman.auth import (
    AuthSettings,
    UserManagementError,
    authenticate_user,
    has_staff_access,
    user_identity,
)
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n.frontend import frontend_catalog_payload
from oldman.i18n.translations import gettext
from oldman.web.api import (
    ApiErrorCode,
    DefaultApiResponse,
    FeedbackAction,
    RedirectAction,
    accepts_html_form_response,
    accepts_json_form_response,
    form_error_response,
    form_response,
    form_saved_response,
    form_success_response,
    modal_not_found_response,
    modal_response,
    modal_success_response,
)
from oldman.web.auth import (
    SIGN_IN_AGAIN_DELAY_MS,
    PasswordResetFlow,
    render_session_password_modal,
    revoke_user_sessions,
    save_language_preference,
    session_profile,
    staff_required,
    superuser_required,
    update_session_password,
    user_delete_modal_response,
    user_status_modal_response,
)
from oldman.web.auth.forms import LoginForm
from oldman.web.auth.login import (
    INVALID_CREDENTIALS,
    RATE_LIMITED,
    LoginRateLimit,
    form_value,
    login_error_message,
    login_error_url,
    login_user,
    logout_user,
    remember_me_requested,
)
from oldman.web.auth.password_reset import RateLimiter
from oldman.web.auth.redirects import safe_next_url as safe_same_site_url
from oldman.web.exceptions import NotFound
from oldman.web.http import permission_denied_response, resolve_response_mode
from oldman.web.i18n import current_language, language_menu_items, language_registry
from oldman.web.messages.actions import DashboardActivityAction
from oldman.web.messages.notifications import render_center_content
from oldman.web.request import Request
from oldman.web.response import html_response, json_response, redirect_response
from oldman.web.routing import WebApp
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.session import SessionData
from oldman.web.sse import SSEStream, sse
from oldman.web.template import render_fragment, render_template

if TYPE_CHECKING:
    from oldman.apps import AppRegistry
    from oldman.db import ModelMetadata


@dataclass(frozen=True)
class RegisteredModelAdmin:
    """Registered Admin model metadata."""

    model: type[Any]
    admin: ModelAdmin


def _admin_table_class(model_admin: ModelAdmin) -> type[AdminModelTable]:
    """Select the dedicated user Table without leaking its filters to generic models."""
    return _AdminUserModelTable if isinstance(model_admin, AdminUserModelAdmin) else AdminModelTable


class AdminSite:
    """Registry and route installer for the built-in Admin site."""

    def __init__(
        self,
        name: str = "oldman_admin",
        *,
        app_registry: AppRegistry | None = None,
    ) -> None:
        self.name = name
        self._registry: OrderedDict[type[Any], ModelAdmin] = OrderedDict()
        self._app_registry = app_registry

    def bind_app_registry(self, registry: AppRegistry) -> None:
        """Bind the current service Registry without rebuilding registered Admins."""
        if self._app_registry is not None and self._app_registry is not registry:
            raise RuntimeError("AdminSite is already bound to another App Registry.")
        self._app_registry = registry

    def get_model_metadata(self, model: type[Any]) -> ModelMetadata | None:
        """Return current service metadata, or None for standalone AdminSite use."""
        if self._app_registry is None:
            return None
        return self._app_registry.get_model_metadata(model)

    def register(self, model: type[Any], admin_class: type[ModelAdmin] | None = None) -> ModelAdmin:
        """Register a model with an optional ModelAdmin class."""
        if model in self._registry:
            raise ValueError(f"{model.__name__} is already registered")
        resolved_admin_class = admin_class or ModelAdmin
        admin = resolved_admin_class(model, self)
        self._registry[model] = admin
        return admin

    def unregister(self, model: type[Any]) -> None:
        """Unregister a model."""
        self._registry.pop(model)

    def register_user_model(self, model: type[Any]) -> ModelAdmin:
        """Register the configured Admin user model as the sole user manager."""
        current = self._registry.get(model)
        if isinstance(current, AdminUserModelAdmin):
            return current

        for registered_model, registered_admin in list(self._registry.items()):
            if isinstance(registered_admin, AdminUserModelAdmin):
                self.unregister(registered_model)
        if model in self._registry:
            self.unregister(model)
        return self.register(model, AdminUserModelAdmin)

    def get_model_admin(self, model: type[Any]) -> ModelAdmin:
        """Return admin for model."""
        return self._registry[model]

    def each_model_admin(self) -> list[RegisteredModelAdmin]:
        """Return registered admins in menu order."""
        return [RegisteredModelAdmin(model=model, admin=admin) for model, admin in self._registry.items()]

    def menu_items(self, prefix: str = "/admin") -> list[dict[str, Any]]:
        """Return neutral menu metadata from model registry."""
        resolved_prefix = prefix.rstrip("/") or "/admin"
        items: list[dict[str, Any]] = []
        for registered in self.each_model_admin():
            metadata = registered.admin.get_model_metadata()
            app_config = self._app_registry.get_by_label(metadata.app_label) if self._app_registry is not None and metadata is not None else None
            items.append(
                {
                    "label": registered.admin.verbose_name_plural,
                    "path": registered.admin.model_path,
                    "url": f"{resolved_prefix}/{registered.admin.model_path}",
                    "app_label": metadata.app_label if metadata is not None else "",
                    "app_display_name": app_config.display_name if app_config is not None else "",
                    "icon": app_config.icon if app_config is not None else "ri-database-2-line",
                }
            )
        return items

    def menu_groups(self, prefix: str = "/admin") -> list[dict[str, Any]]:
        """Group registered models under their owning App for sidebar rendering."""
        groups: dict[str, dict[str, Any]] = {}
        for item in self.menu_items(prefix):
            app_label = str(item["app_label"] or "models")
            group = groups.setdefault(
                app_label,
                {
                    "app_label": app_label,
                    "label": item["app_display_name"],
                    "icon": item["icon"],
                    "models": [],
                },
            )
            group["models"].append(item)
        return list(groups.values())

    def register_routes(
        self,
        app: WebApp,
        *,
        prefix: str = "/admin",
        db_manager: DatabaseManager | None = None,
        auth_settings: AuthSettings | None = None,
        admin_settings: AdminSettings | None = None,
        notifications_enabled: bool = False,
        sse_enabled: bool = False,
        password_reset_rate_limiter: RateLimiter | None = None,
        login_rate_limit: LoginRateLimit | None = None,
    ) -> str | None:
        """Install neutral Admin CRUD routes into a Sanic app."""
        prefix = prefix.rstrip("/") or "/admin"
        manager = db_manager if db_manager is not None else default_db_manager
        if auth_settings is None:
            from oldman.auth.apps import app as auth_app

            auth_settings = auth_app.settings
        if admin_settings is None:
            from oldman.apps.admin.apps import app as admin_app

            admin_settings = admin_app.settings
        login_path = f"{prefix}/login"
        permission_required = superuser_required if admin_settings.require_superuser else staff_required

        sign_in_limit = login_rate_limit if login_rate_limit is not None else LoginRateLimit(auth_settings=auth_settings)

        async def render_login_page(request: Request, *, error: str, next_url: str):
            """The login page itself, which both the GET route and a refused POST render."""
            return await render_admin_template(
                "admin/login.html",
                request,
                admin_prefix=prefix,
                site=self,
                menu_items=self.menu_items(prefix),
                login_form=LoginForm(request=request),
                login_error=login_error_message(error),
                next_url=next_url,
            )

        @add_csrf_token()
        async def login_page(request: Request):
            next_url = safe_next_url(request.args.get("next"), prefix)
            if has_admin_permission(request):
                return redirect_response(next_url)
            return await render_login_page(request, error=str(request.args.get("error") or ""), next_url=next_url)

        @csrf_protect()
        @add_csrf_token()
        async def login_submit(request: Request):
            next_url = safe_next_url(form_value(request, "next", str(request.args.get("next", "") or "")), prefix)
            username = form_value(request, "username").strip()
            # Before the password is checked, so a spent budget costs no PBKDF2 round.
            retry_after = await sign_in_limit.retry_after(request, username)
            if retry_after is not None:
                response = await render_login_page(request, error=RATE_LIMITED, next_url=next_url)
                response.status = 429
                response.headers["Retry-After"] = str(retry_after)
                return response
            user = await authenticate_user(
                username,
                form_value(request, "password"),
                auth_settings=auth_settings,
                db_manager=manager,
            )
            if user is None or not has_staff_access(
                user,
                require_superuser=admin_settings.require_superuser,
            ):
                await sign_in_limit.record_failure(request, username)
                return redirect_response(login_error_url(login_path, next_url, INVALID_CREDENTIALS), status=303)
            return await login_user(
                request,
                user,
                response=redirect_response(next_url),
                remember=remember_me_requested(request),
                auth_settings=auth_settings,
                db_manager=manager,
            )

        async def sign_out(request: Request):
            return await logout_user(request, login_path)

        reset_flow = PasswordResetFlow(
            request_path=f"{prefix}/password-reset",
            sent_path=f"{prefix}/password-reset/sent",
            done_path=f"{prefix}/password-reset/done",
            login_path=login_path,
            home_path=prefix,
            confirm_path=lambda uidb64, token: f"{prefix}/password-reset/{uidb64}/{token}",
            site_name="Oldman Admin",
            auth_settings=auth_settings,
            db_manager=manager,
            rate_limiter=password_reset_rate_limiter,
        )

        async def render_password_reset(request: Request, page: str, /, **context: Any):
            return await render_admin_template(
                f"admin/password_reset/{page}.html",
                request,
                admin_prefix=prefix,
                site=self,
                menu_items=self.menu_items(prefix),
                **context,
            )

        async def language_catalog(request: Request, language: str, ext: str):
            del ext
            bootstrap = admin_i18n_bootstrap(request, prefix)
            resolved_language = language_registry(request).resolve(language)
            definition = next(
                (item for item in bootstrap["languages"] if item["code"] == resolved_language),
                None,
            )
            if definition is None:
                return json_response(
                    DefaultApiResponse(
                        error_code=ApiErrorCode.NOT_FOUND,
                        message=gettext("Unsupported language.", request=request),
                    ).to_dict(),
                    status=404,
                )

            catalog = admin_translation_catalog(
                request,
                str(definition["code"]),
                bootstrap["currentLanguage"],
            )
            return json_response(
                frontend_catalog_payload(
                    catalog,
                    str(definition["locale"]),
                )
            )

        @csrf_protect()
        async def language_preference(request: Request):
            return save_language_preference(
                request,
                registry=language_registry(request),
            )

        @add_csrf_token()
        async def user_session_page(request: Request):
            if not has_admin_permission(request):
                return await admin_access_denied_response(request, login_path)
            request_session = getattr(request.ctx, "session", None)
            if not isinstance(request_session, SessionData):
                raise RuntimeError("Oldman Admin requires Session middleware")
            return await render_admin_template(
                "admin/user_session.html",
                request,
                admin_prefix=prefix,
                site=self,
                menu_items=self.menu_items(prefix),
                session_profile=session_profile(request_session),
                session_path=f"{prefix}/user-session",
                password_modal_path=f"{prefix}/user-session/password-modal",
                logout_path=f"{prefix}/sign-out",
            )

        @add_csrf_token()
        async def user_session_password_modal(request: Request):
            if not has_admin_permission(request):
                return await admin_access_denied_response(request, login_path)
            return await render_session_password_modal(
                request,
                action=f"{prefix}/user-session/password",
                auth_settings=auth_settings,
                db_manager=manager,
            )

        @csrf_protect()
        @add_csrf_token()
        async def user_session_password_submit(request: Request):
            if not has_admin_permission(request):
                return await admin_access_denied_response(request, login_path)
            request_session = getattr(request.ctx, "session", None)
            if not isinstance(request_session, SessionData):
                raise RuntimeError("Oldman Admin requires Session middleware")
            # No activity entry: the change signs this browser out, so anything added to the
            # dashboard's transient menu would be replaced by the login page before it is read.
            return await update_session_password(
                request,
                login_url=login_path,
                auth_settings=auth_settings,
                db_manager=manager,
            )

        async def index(request: Request):
            if not has_admin_permission(request):
                return await admin_access_denied_response(request, login_path)
            return await render_admin_template(
                "admin/index.html",
                request,
                admin_prefix=prefix,
                site=self,
                menu_items=self.menu_items(prefix),
            )

        app.add_route(cast(Any, index), prefix, methods=["GET"], name=f"{self.name}_index")

        if getattr(app, "strict_slashes", False):
            # The Oldman Web runtime registers routes with strict slashes, so the
            # prefix typed with a trailing slash would 404; send it to the index.
            async def index_with_trailing_slash(request: Request):
                target = f"{prefix}?{request.query_string}" if request.query_string else prefix
                return redirect(target, status=301)

            app.add_route(
                cast(Any, index_with_trailing_slash),
                f"{prefix}/",
                methods=["GET"],
                name=f"{self.name}_index_trailing_slash",
                strict_slashes=True,
            )

        for registered in self.each_model_admin():
            admin = registered.admin
            model_prefix = f"{prefix}/{admin.model_path}"

            async def list_view(request: Request, current_admin: ModelAdmin = admin):
                if not current_admin.has_view_permission(request):
                    return await admin_access_denied_response(request, login_path)
                table = _admin_table_class(current_admin)(request, model_admin=current_admin, db_manager=manager, admin_prefix=prefix)
                table_id = f"admin-{current_admin.model_path}-table"
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                filter_form = user_admin.build_filter_form(request) if user_admin is not None else None
                filter_form_html = ""
                if filter_form is not None:
                    filter_form_html = await filter_form.render(
                        method="get",
                        submit_label=gettext("Filter", request=request),
                        table_target=f"#{table_id}",
                    )
                return await render_admin_template(
                    "admin/model/list.html",
                    request,
                    admin_prefix=prefix,
                    site=self,
                    menu_items=self.menu_items(prefix),
                    model_admin=current_admin,
                    admin_user_management=user_admin is not None,
                    filter_form_html=filter_form_html,
                    table_html=await table.render_shell(html_id=table_id, show_search=filter_form is None),
                )

            async def table_view(request: Request, current_admin: ModelAdmin = admin):
                table = _admin_table_class(current_admin)(
                    request,
                    model_admin=current_admin,
                    db_manager=manager,
                    admin_prefix=prefix,
                    permission_denied_response=lambda current_request: admin_access_denied_response(current_request, login_path),
                )
                return await table.get(request)

            @add_csrf_token()
            async def create_form(request: Request, current_admin: ModelAdmin = admin):
                if not current_admin.has_add_permission(request):
                    return await admin_access_denied_response(request, login_path)
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                cancel_url = f"{prefix}/{current_admin.model_path}"
                feedback_target = f"#admin-{current_admin.model_path}-form-feedback"
                async with manager.get_read_session() as session:
                    form = current_admin.build_form(request, session=session)
                    form_html = await form.render(
                        action=cancel_url + "/new",
                        method="post",
                        form_mode="json",
                        submit_label=current_admin.get_form_submit_label(None),
                        cancel_url=cancel_url,
                        component_name="form",
                        validate=user_admin is not None,
                        feedback_target=feedback_target if user_admin is not None else None,
                    )
                return await render_admin_template(
                    "admin/model/form.html",
                    request,
                    admin_prefix=prefix,
                    site=self,
                    menu_items=self.menu_items(prefix),
                    model_admin=current_admin,
                    admin_user_management=user_admin is not None,
                    form_html=form_html,
                    object=None,
                )

            @csrf_protect()
            @add_csrf_token()
            async def create_submit(request: Request, current_admin: ModelAdmin = admin):
                if not current_admin.has_add_permission(request):
                    return await admin_access_denied_response(request, login_path)
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                async with manager.get_session() as session:
                    form = current_admin.build_form(request, session=session)
                    if not await form.validate():
                        if resolve_response_mode(request) == "json" if user_admin is not None else accepts_json_form_response(request):
                            return json_response(form.to_api_response().to_dict())
                        form_html = await form.render(
                            action=f"{prefix}/{current_admin.model_path}/new",
                            method="post",
                            form_mode="json",
                            submit_label=current_admin.get_form_submit_label(None),
                            cancel_url=f"{prefix}/{current_admin.model_path}",
                            component_name="form",
                            validate=user_admin is not None,
                            feedback_target=f"#admin-{current_admin.model_path}-form-feedback" if user_admin is not None else None,
                        )
                        if user_admin is None and accepts_html_form_response(request):
                            return html_response(str(form_html), status=422)
                        response = await render_admin_template(
                            "admin/model/form.html",
                            request,
                            admin_prefix=prefix,
                            site=self,
                            menu_items=self.menu_items(prefix),
                            model_admin=current_admin,
                            admin_user_management=user_admin is not None,
                            form_html=form_html,
                            object=None,
                        )
                        response.status = 422
                        return response
                    instance = await form.save()
                    await current_admin.save_model(session, instance)
                if user_admin is not None:
                    success = user_admin.get_form_success_payload(instance, created=True, admin_prefix=prefix)
                    if resolve_response_mode(request) == "json":
                        return admin_form_success_response(success)
                    return redirect_response(str(success["url"]), status=303)
                return form_success_response(request, f"{prefix}/{current_admin.model_path}")

            @add_csrf_token()
            async def edit_form(request: Request, object_id: str, current_admin: ModelAdmin = admin):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                async with manager.get_read_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        if user_admin is not None:
                            return redirect_response(f"{prefix}/{current_admin.model_path}")
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                    form = current_admin.build_form(request, instance=instance, session=session)
                    action = current_admin.get_object_url(instance, admin_prefix=prefix, action="edit")
                    form_html = await form.render(
                        action=action,
                        method="post",
                        form_mode="json",
                        submit_label=current_admin.get_form_submit_label(instance),
                        cancel_url=f"{prefix}/{current_admin.model_path}",
                        extra_buttons=current_admin.get_edit_extra_buttons(instance, prefix),
                        component_name="form",
                        validate=user_admin is not None,
                        feedback_target=f"#admin-{current_admin.model_path}-form-feedback" if user_admin is not None else None,
                    )
                return await render_admin_template(
                    "admin/model/form.html",
                    request,
                    admin_prefix=prefix,
                    site=self,
                    menu_items=self.menu_items(prefix),
                    model_admin=current_admin,
                    admin_user_management=user_admin is not None,
                    form_html=form_html,
                    object=instance,
                    show_delete_action=user_admin is None,
                )

            @csrf_protect()
            @add_csrf_token()
            async def edit_submit(request: Request, object_id: str, current_admin: ModelAdmin = admin):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                async with manager.get_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        if user_admin is not None and resolve_response_mode(request) == "json":
                            return form_error_response(
                                gettext("User not found", request=request),
                                status=404,
                            )
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                    form = current_admin.build_form(request, instance=instance, session=session)
                    if not await form.validate():
                        if resolve_response_mode(request) == "json" if user_admin is not None else accepts_json_form_response(request):
                            return json_response(form.to_api_response().to_dict())
                        form_html = await form.render(
                            action=current_admin.get_object_url(instance, admin_prefix=prefix, action="edit"),
                            method="post",
                            form_mode="json",
                            submit_label=current_admin.get_form_submit_label(instance),
                            cancel_url=f"{prefix}/{current_admin.model_path}",
                            extra_buttons=current_admin.get_edit_extra_buttons(instance, prefix),
                            component_name="form",
                            validate=user_admin is not None,
                            feedback_target=f"#admin-{current_admin.model_path}-form-feedback" if user_admin is not None else None,
                        )
                        if user_admin is None and accepts_html_form_response(request):
                            return html_response(str(form_html), status=422)
                        response = await render_admin_template(
                            "admin/model/form.html",
                            request,
                            admin_prefix=prefix,
                            site=self,
                            menu_items=self.menu_items(prefix),
                            model_admin=current_admin,
                            admin_user_management=user_admin is not None,
                            form_html=form_html,
                            object=instance,
                            show_delete_action=user_admin is None,
                        )
                        response.status = 422
                        return response
                    # 统一经过 ModelForm.save()，保留 User 等专用表单的
                    # 归一化与安全边界；instance 已在 build_form 时绑定。
                    instance = await form.save()
                    await current_admin.save_model(session, instance)
                if user_admin is not None:
                    success = user_admin.get_form_success_payload(instance, created=False, admin_prefix=prefix)
                    if resolve_response_mode(request) == "json":
                        return admin_form_success_response(success)
                    return redirect_response(str(success["url"]), status=303)
                return form_success_response(request, f"{prefix}/{current_admin.model_path}")

            @add_csrf_token()
            async def delete_modal(
                request: Request,
                object_id: str,
                current_admin: AdminUserModelAdmin = cast(AdminUserModelAdmin, admin),
            ):
                if not current_admin.has_delete_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_read_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    return await user_delete_modal_response(
                        request,
                        instance,
                        action=current_admin.get_object_url(instance, admin_prefix=prefix, action="delete") if instance is not None else "",
                    )

            @add_csrf_token()
            async def delete_form(request: Request, object_id: str, current_admin: ModelAdmin = admin):
                if not current_admin.has_delete_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_read_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                return await render_admin_template(
                    "admin/model/confirm_delete.html",
                    request,
                    admin_prefix=prefix,
                    site=self,
                    menu_items=self.menu_items(prefix),
                    model_admin=current_admin,
                    object=instance,
                )

            @csrf_protect()
            @add_csrf_token()
            async def delete_submit(request: Request, object_id: str, current_admin: ModelAdmin = admin):
                if not current_admin.has_delete_permission(request):
                    return await admin_access_denied_response(request, login_path)
                user_admin = current_admin if isinstance(current_admin, AdminUserModelAdmin) else None
                username: str | None = None
                async with manager.get_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        if user_admin is not None:
                            return form_error_response(
                                gettext("User not found", request=request),
                                status=404,
                            )
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                    if user_admin is not None:
                        try:
                            user_admin.validate_delete(instance, current_user_id=request_user_id(request))
                        except UserManagementError as exc:
                            message = gettext(str(exc), request=request)
                            return form_error_response(message)
                        username = str(getattr(instance, "username", current_admin.verbose_name))
                    await current_admin.delete_model(session, instance)
                if user_admin is not None:
                    assert username is not None
                    return admin_modal_success_response(
                        gettext("User deleted", request=request),
                        table_target=f"#admin-{current_admin.model_path}-table",
                        notification={
                            "title": gettext("User deleted", request=request),
                            "description": gettext(
                                "%(username)s was removed from dashboard access.",
                                request=request,
                                username=username,
                            ),
                            "tone": "danger",
                            "icon": "ri-delete-bin-line",
                            "href": f"{prefix}/{current_admin.model_path}",
                            "time": gettext("Just now", request=request),
                        },
                    )
                return redirect_response(f"{prefix}/{current_admin.model_path}")

            @add_csrf_token()
            async def password_modal(
                request: Request,
                object_id: str,
                current_admin: AdminUserModelAdmin = cast(AdminUserModelAdmin, admin),
            ):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_read_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        return modal_not_found_response(
                            gettext("Change Password", request=request),
                            gettext("User not found.", request=request),
                        )
                    form = current_admin.build_password_form(request, session=session)
                    modal_html = await render_fragment(
                        request,
                        "oldman/auth/partials/password_form.html",
                        action=current_admin.get_object_url(instance, admin_prefix=prefix, action="password"),
                        form=form,
                        user=instance,
                    )
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                    return modal_response(f"{gettext('Change Password', request=request)} · {escape(username)}", html=modal_html)

            @csrf_protect()
            @add_csrf_token()
            async def password_submit(
                request: Request,
                object_id: str,
                current_admin: AdminUserModelAdmin = cast(AdminUserModelAdmin, admin),
            ):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        return form_error_response(
                            gettext("User not found", request=request),
                            status=404,
                        )
                    form = current_admin.build_password_form(request, session=session)
                    if not await form.validate():
                        return json_response(form.to_api_response().to_dict())
                    current_admin.change_password(instance, str(form.cleaned_data["password"]))
                    await current_admin.save_model(session, instance)
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                    target_user_id = user_identity(instance)
                # The same rule as every other password path: the sessions opened under the old
                # password end with it. An operator who changed their own row ends their own.
                signed_self_out = await revoke_user_sessions(request, target_user_id)
                if signed_self_out:
                    return form_response(
                        gettext("Password changed", request=request),
                        actions=[
                            FeedbackAction(
                                title=gettext("Password changed", request=request),
                                text=gettext("Your password was updated. Please sign in again.", request=request),
                                icon="success",
                            ),
                            RedirectAction(url=login_path, delay_ms=SIGN_IN_AGAIN_DELAY_MS),
                        ],
                    )
                return admin_modal_success_response(
                    gettext("Password changed", request=request),
                    table_target=f"#admin-{current_admin.model_path}-table",
                    notification={
                        "title": gettext("Password changed", request=request),
                        "description": gettext(
                            "%(username)s was signed out and needs the new password.",
                            request=request,
                            username=username,
                        ),
                        "tone": "success",
                        "icon": "ri-lock-password-line",
                        "href": f"{prefix}/{current_admin.model_path}",
                        "time": gettext("Just now", request=request),
                    },
                )

            @add_csrf_token()
            async def status_modal(
                request: Request,
                object_id: str,
                current_admin: AdminUserModelAdmin = cast(AdminUserModelAdmin, admin),
            ):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_read_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                return await user_status_modal_response(
                    request,
                    instance,
                    action=current_admin.get_object_url(instance, admin_prefix=prefix, action="status") if instance is not None else "",
                )

            @csrf_protect()
            @add_csrf_token()
            async def status_submit(
                request: Request,
                object_id: str,
                current_admin: AdminUserModelAdmin = cast(AdminUserModelAdmin, admin),
            ):
                if not current_admin.has_change_permission(request):
                    return await admin_access_denied_response(request, login_path)
                async with manager.get_session() as session:
                    instance = await load_admin_object(current_admin, session, object_id)
                    if instance is None:
                        return form_error_response(
                            gettext("User not found", request=request),
                            status=404,
                        )
                    target_active = form_value(request, "is_active").strip().lower() in {"1", "true", "yes", "on"}
                    try:
                        current_admin.set_active(instance, target_active, current_user_id=request_user_id(request))
                    except UserManagementError as exc:
                        message = gettext(str(exc), request=request)
                        return form_error_response(message)
                    await current_admin.save_model(session, instance)
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                return admin_modal_success_response(
                    gettext("User status updated", request=request),
                    table_target=f"#admin-{current_admin.model_path}-table",
                    notification={
                        "title": gettext("User status updated", request=request),
                        "description": gettext(
                            "%(username)s is now %(status)s.",
                            request=request,
                            username=username,
                            status=(gettext("active", request=request) if target_active else gettext("disabled", request=request)),
                        ),
                        "tone": "warning",
                        "icon": "ri-toggle-line",
                        "href": f"{prefix}/{current_admin.model_path}",
                        "time": gettext("Just now", request=request),
                    },
                )

            app.add_route(cast(Any, list_view), model_prefix, methods=["GET"], name=f"{self.name}_{admin.model_path}_list")
            app.add_route(cast(Any, table_view), f"{model_prefix}/table", methods=["GET"], name=f"{self.name}_{admin.model_path}_table")
            app.add_route(cast(Any, create_form), f"{model_prefix}/new", methods=["GET"], name=f"{self.name}_{admin.model_path}_new")
            app.add_route(cast(Any, create_submit), f"{model_prefix}/new", methods=["POST"], name=f"{self.name}_{admin.model_path}_create")
            app.add_route(cast(Any, edit_form), f"{model_prefix}/<object_id>/edit", methods=["GET"], name=f"{self.name}_{admin.model_path}_edit")
            app.add_route(cast(Any, edit_submit), f"{model_prefix}/<object_id>/edit", methods=["POST"], name=f"{self.name}_{admin.model_path}_update")
            if not isinstance(admin, AdminUserModelAdmin):
                app.add_route(
                    cast(Any, delete_form),
                    f"{model_prefix}/<object_id>/delete",
                    methods=["GET"],
                    name=f"{self.name}_{admin.model_path}_delete",
                )
            app.add_route(
                cast(Any, delete_submit), f"{model_prefix}/<object_id>/delete", methods=["POST"], name=f"{self.name}_{admin.model_path}_delete_submit"
            )
            if isinstance(admin, AdminUserModelAdmin):
                app.add_route(
                    cast(Any, delete_modal),
                    f"{model_prefix}/<object_id>/delete-modal",
                    methods=["GET"],
                    name=f"{self.name}_{admin.model_path}_delete_modal",
                )
                app.add_route(
                    cast(Any, password_submit),
                    f"{model_prefix}/<object_id>/password",
                    methods=["POST"],
                    name=f"{self.name}_{admin.model_path}_password_submit",
                )
                app.add_route(
                    cast(Any, password_modal),
                    f"{model_prefix}/<object_id>/password-modal",
                    methods=["GET"],
                    name=f"{self.name}_{admin.model_path}_password_modal",
                )
                app.add_route(
                    cast(Any, status_submit),
                    f"{model_prefix}/<object_id>/status",
                    methods=["POST"],
                    name=f"{self.name}_{admin.model_path}_status_submit",
                )
                app.add_route(
                    cast(Any, status_modal),
                    f"{model_prefix}/<object_id>/status-modal",
                    methods=["GET"],
                    name=f"{self.name}_{admin.model_path}_status_modal",
                )

        app.add_route(cast(Any, login_page), login_path, methods=["GET"], name=f"{self.name}_login")
        app.add_route(cast(Any, login_submit), login_path, methods=["POST"], name=f"{self.name}_login_submit")
        app.add_route(cast(Any, sign_out), f"{prefix}/sign-out", methods=["GET"], name=f"{self.name}_sign_out")
        reset_flow.register_routes(app, render=render_password_reset, is_authenticated=has_admin_permission, name_prefix=f"{self.name}_")
        app.add_route(
            cast(Any, user_session_page),
            f"{prefix}/user-session",
            methods=["GET"],
            name=f"{self.name}_user_session",
        )
        app.add_route(
            cast(Any, user_session_password_modal),
            f"{prefix}/user-session/password-modal",
            methods=["GET"],
            name=f"{self.name}_user_session_password_modal",
        )
        app.add_route(
            cast(Any, user_session_password_submit),
            f"{prefix}/user-session/password",
            methods=["POST"],
            name=f"{self.name}_user_session_password_submit",
        )
        app.add_route(
            cast(Any, language_catalog),
            f"{prefix}/i18n/<language:ext=json>",
            methods=["GET"],
            name=f"{self.name}_language_catalog",
        )
        app.add_route(
            cast(Any, language_preference),
            f"{prefix}/preferences/language",
            methods=["POST"],
            name=f"{self.name}_language_preference",
        )
        app.add_route(
            cast(Any, language_preference),
            f"{prefix}/user-session/language",
            methods=["POST"],
            name=f"{self.name}_user_session_language",
        )

        if notifications_enabled:

            @permission_required(login_url=login_path, user_keyword="user_id")
            async def user_notifications(request: Request, *, user_id: int):
                content = await render_center_content(request, user_id=user_id)
                return await render_admin_template(
                    "admin/user_notifications.html",
                    request,
                    admin_prefix=prefix,
                    site=self,
                    menu_items=self.menu_items(prefix),
                    notification_center_content=content,
                )

            app.add_route(
                cast(Any, user_notifications),
                f"{prefix}/user-notifications",
                methods=["GET"],
                name=f"{self.name}_user_notifications",
            )

        if not sse_enabled:
            return None

        @permission_required(login_url=login_path, user_keyword="user_id")
        @sse.streaming(session_guard=True, login_url=login_path)
        async def user_events(
            request: Request,
            stream: SSEStream,
            *,
            user_id: int,
        ) -> None:
            del request
            await stream.subscribe_user(user_id)

        user_events_url = f"{prefix}/user-events"
        app.add_route(
            cast(Any, user_events),
            user_events_url,
            methods=["GET"],
            name=f"{self.name}_user_events",
        )
        return user_events_url


async def render_admin_template(template_name: str, request: Request, **context: Any):
    """Render Admin template with common neutral context."""
    is_authenticated = has_admin_permission(request)
    context.setdefault("admin_bundle_name", "oldman:admin")
    context.setdefault("admin_is_authenticated", is_authenticated)
    context.setdefault("admin_prefix", "/admin")
    site = context.get("site")
    if isinstance(site, AdminSite):
        context.setdefault(
            "menu_groups",
            site.menu_groups(str(context["admin_prefix"])),
        )
    context.setdefault(
        "admin_extension_bundle_name",
        getattr(request.app.ctx, "oldman_admin_extension_bundle_name", None),
    )
    context.setdefault("dashboard_body_classes", "" if is_authenticated else " oldman-auth-page")
    i18n_bootstrap = admin_i18n_bootstrap(request, str(context["admin_prefix"]))
    context.setdefault("admin_i18n", i18n_bootstrap)
    context.setdefault("locale", i18n_bootstrap["currentLanguage"])
    context.setdefault("page_entry", "admin")
    context.setdefault("request", request)
    notification_routes = getattr(
        request.app.ctx,
        "oldman_admin_notification_routes",
        None,
    )
    context.setdefault(
        "admin_user_notification_urls",
        (
            {
                "center": notification_routes.center_url,
                "topbar": notification_routes.topbar_url,
            }
            if notification_routes is not None
            else None
        ),
    )
    context.setdefault(
        "admin_user_events_url",
        getattr(request.app.ctx, "oldman_admin_user_events_url", None),
    )
    return await render_template(template_name, context=context)


async def load_admin_object(model_admin: ModelAdmin, session: Any, object_id: Any) -> Any | None:
    """Load a routed object and convert malformed typed keys into route-level 404s."""
    try:
        return await model_admin.get_object(session, object_id)
    except InvalidAdminObjectId:
        raise NotFound(f"{model_admin.verbose_name} {object_id} was not found") from None


def admin_form_success_response(success: dict[str, Any]):
    """Redirect after a user save, with the Admin activity entry ahead of it."""
    return form_saved_response(
        str(success["message"]),
        url=str(success["url"]),
        delay_ms=1200,
        actions=[DashboardActivityAction(**success["notification"])],
    )


def admin_modal_success_response(message: str, *, table_target: str, notification: dict[str, str]):
    """Close-and-reload after a row-action modal, with the Admin activity entry."""
    return modal_success_response(
        message,
        table_target=table_target,
        text=str(notification.get("description", "")) or None,
        actions=[DashboardActivityAction(**notification)],
    )


def safe_next_url(raw_next_url: object, prefix: str) -> str:
    """Return a safe same-site redirect target, the Admin prefix when the value is not one."""
    return safe_same_site_url(raw_next_url, prefix)


def admin_login_url(login_path: str, request: Request) -> str:
    """Build an Admin login URL preserving the current request path."""
    next_url = safe_next_url(f"{request.path}?{request.query_string}" if request.query_string else request.path, login_path.rsplit("/", 1)[0])
    return f"{login_path}?{urlencode({'next': next_url})}"


async def admin_access_denied_response(request: Request, login_path: str):
    """Return the Admin-owned authentication or permission response."""
    response_mode = resolve_response_mode(request)
    if is_authenticated(request):
        return await permission_denied_response(request, response_mode)

    headers = getattr(request, "headers", {}) or {}
    is_oldman_request = str(headers.get("x-requested-with", "")).lower() == "xmlhttprequest"
    if response_mode == "json" or is_oldman_request:
        payload = DefaultApiResponse(
            error_code=ApiErrorCode.AUTHENTICATION_REQUIRED,
            message=gettext("Authentication required", request=request),
            data={"login_url": login_path},
        )
        return json_response(payload.to_dict(), status=401)
    return redirect_response(admin_login_url(login_path, request), status=302)


def admin_i18n_bootstrap(request: Request, prefix: str) -> dict[str, Any]:
    """Build settings-driven language metadata for the packaged Admin runtime."""
    normalized_prefix = prefix.rstrip("/") or "/admin"
    registry = language_registry(request)
    default_language = registry.resolve(conf.settings.i18n.default_language) or registry.codes[0]
    current = current_language(request)
    languages = language_menu_items(request)
    for definition in languages:
        definition["catalogPath"] = f"{normalized_prefix}/i18n/{quote(str(definition['code']), safe='')}.json"
    current_definition = next(item for item in languages if item["code"] == current)
    catalog = admin_translation_catalog(request, str(current_definition["code"]), current)
    return {
        "catalog": frontend_catalog_payload(catalog, str(current_definition["locale"])),
        "currentLanguage": current,
        "defaultLanguage": default_language,
        "languages": languages,
        "preferencePath": f"{normalized_prefix}/preferences/language",
    }


def admin_translation_catalog(
    request: Request,
    language_code: str,
    current_language: str,
) -> Any:
    """Resolve the current request catalog or a canonical catalog for another language."""
    if language_code == current_language:
        catalog = getattr(request.ctx, "translations", None)
        if catalog is not None:
            return catalog

    from oldman.web.i18n.translation import translation

    if not translation.is_initialized:
        return Translations()
    return translation.get_translations(language_code)


site = AdminSite()
