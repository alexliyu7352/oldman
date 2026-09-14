"""Admin site registry."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from babel.support import Translations
from markupsafe import Markup, escape

import oldman.conf as conf
from oldman.apps.admin.forms import AdminLoginForm
from oldman.apps.admin.model_admin import (
    AdminUserModelAdmin,
    InvalidAdminObjectId,
    ModelAdmin,
    request_user_id,
)
from oldman.apps.admin.permissions import has_admin_permission, is_authenticated
from oldman.apps.admin.settings import AdminSettings
from oldman.apps.admin.table import AdminModelTable, _AdminUserModelTable
from oldman.apps.admin.users import AdminUserManagementError
from oldman.auth import (
    AuthSettings,
    authenticate_user,
    has_staff_access,
    touch_last_login,
    user_identity,
)
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n import LanguageRegistry, LazyTranslation
from oldman.i18n.frontend import frontend_catalog_payload
from oldman.i18n.translations import gettext
from oldman.web.api import (
    ApiErrorCode,
    CloseModalAction,
    DefaultApiFormResponse,
    DefaultApiResponse,
    FeedbackAction,
    RedirectAction,
    ReloadTableAction,
)
from oldman.web.auth import (
    render_session_password_modal,
    save_language_preference,
    session_data_for_user,
    session_profile,
    staff_required,
    superuser_required,
    update_session_password,
)
from oldman.web.exceptions import NotFound
from oldman.web.http import permission_denied_response, resolve_response_mode
from oldman.web.i18n.assets import direct_flag_url
from oldman.web.messages.actions import DashboardActivityAction
from oldman.web.messages.notifications import render_center_content
from oldman.web.request import Request
from oldman.web.response import html_response, json_response, redirect_response
from oldman.web.routing import WebApp
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.session import Session, SessionData
from oldman.web.sse import SSEStream, sse
from oldman.web.template import render_template

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
            app_config = (
                self._app_registry.get_by_label(metadata.app_label)
                if self._app_registry is not None and metadata is not None
                else None
            )
            items.append({
                "label": registered.admin.verbose_name_plural,
                "path": registered.admin.model_path,
                "url": f"{resolved_prefix}/{registered.admin.model_path}",
                "app_label": metadata.app_label if metadata is not None else "",
                "app_display_name": app_config.display_name if app_config is not None else "",
                "icon": app_config.icon if app_config is not None else "ri-database-2-line",
            })
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
        permission_required = (
            superuser_required
            if admin_settings.require_superuser
            else staff_required
        )

        @add_csrf_token()
        async def login_page(request: Request):
            next_url = safe_next_url(request.args.get("next"), prefix)
            if has_admin_permission(request):
                return redirect_response(next_url)
            return await render_admin_template(
                "admin/login.html",
                request,
                admin_prefix=prefix,
                site=self,
                menu_items=self.menu_items(prefix),
                login_form=AdminLoginForm(request=request),
                login_error=login_error_message(request.args.get("error")),
                next_url=next_url,
            )

        @csrf_protect()
        async def login_submit(request: Request):
            next_url = safe_next_url(form_value(request, "next", str(request.args.get("next", "") or "")), prefix)
            user = await authenticate_user(
                form_value(request, "username").strip(),
                form_value(request, "password"),
                auth_settings=auth_settings,
                db_manager=manager,
            )
            if user is None or not has_staff_access(
                user,
                require_superuser=admin_settings.require_superuser,
            ):
                return redirect_response(login_error_url(login_path, next_url, "invalid_credentials"), status=303)

            session_manager: Session = request.app.ctx.session
            expiry = conf.settings.web.session.expiry
            user_id = user_identity(user)
            request_session = getattr(request.ctx, "session", None)
            if not isinstance(request_session, SessionData):
                raise RuntimeError("Oldman Admin login requires Session middleware")
            session_data = session_data_for_user(
                type(request_session),
                user,
                expiry=expiry,
                login_ip=str(request.ip or request.client_ip or ""),
            )
            new_session_id = await session_manager.exclusive_login(session_data)
            await touch_last_login(user_id, auth_settings=auth_settings, db_manager=manager)
            response = redirect_response(next_url)
            session_manager.update_session_id_to_cookie(response, new_session_id, session_data)
            return response

        async def sign_out(request: Request):
            await Session.logout_session(request)
            return redirect_response(login_path)

        async def language_catalog(request: Request, language: str, ext: str):
            del ext
            bootstrap = admin_i18n_bootstrap(request, prefix)
            resolved_language = admin_language_registry(request).resolve(language)
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
                registry=admin_language_registry(request),
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
            message = gettext("Session password changed", request=request)
            description = gettext(
                "%(username)s password was updated.",
                request=request,
                username=request_session.username,
            )
            return await update_session_password(
                request,
                success_actions=(
                    DashboardActivityAction(
                        title=message,
                        description=description,
                        tone="success",
                        icon="ri-lock-password-line",
                        href=f"{prefix}/user-session",
                        time=gettext("Just now", request=request),
                    ),
                ),
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
                        if (
                            resolve_response_mode(request) == "json"
                            if user_admin is not None
                            else accepts_json_form_response(request)
                        ):
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
                return admin_generic_form_success_response(request, f"{prefix}/{current_admin.model_path}")

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
                            return admin_form_error_response(
                                gettext("User not found", request=request),
                                status=404,
                            )
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                    form = current_admin.build_form(request, instance=instance, session=session)
                    if not await form.validate():
                        if (
                            resolve_response_mode(request) == "json"
                            if user_admin is not None
                            else accepts_json_form_response(request)
                        ):
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
                return admin_generic_form_success_response(request, f"{prefix}/{current_admin.model_path}")

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
                    if instance is None:
                        return json_response(
                            {
                                "title": gettext("Delete User", request=request),
                                "html": (
                                    '<p class="text-default-500 mb-0">'
                                    f'{escape(gettext("User not found.", request=request))}</p>'
                                ),
                            },
                            status=404,
                        )
                    modal_html = await render_admin_fragment(
                        "admin/model/delete_modal_form.html",
                        request,
                        action=current_admin.get_object_url(instance, admin_prefix=prefix, action="delete"),
                        object=instance,
                    )
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                    return json_response(
                        {
                            "title": f'{gettext("Delete User", request=request)} · {escape(username)}',
                            "html": str(modal_html),
                        }
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
                            return admin_form_error_response(
                                gettext("User not found", request=request),
                                status=404,
                            )
                        raise NotFound(f"{current_admin.verbose_name} {object_id} was not found")
                    if user_admin is not None:
                        try:
                            user_admin.validate_delete(instance, current_user_id=request_user_id(request))
                        except AdminUserManagementError as exc:
                            message = gettext(str(exc), request=request)
                            return admin_form_error_response(message)
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
                        return json_response(
                            {
                                "title": gettext("Change Password", request=request),
                                "html": (
                                    '<p class="text-default-500 mb-0">'
                                    f'{escape(gettext("User not found.", request=request))}</p>'
                                ),
                            },
                            status=404,
                        )
                    form = current_admin.build_password_form(request, session=session)
                    modal_html = await render_admin_fragment(
                        "oldman/auth/partials/password_form.html",
                        request,
                        action=current_admin.get_object_url(instance, admin_prefix=prefix, action="password"),
                        form=form,
                        user=instance,
                    )
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                    return json_response(
                        {
                            "title": f'{gettext("Change Password", request=request)} · {escape(username)}',
                            "html": str(modal_html),
                        }
                    )

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
                        return admin_form_error_response(
                            gettext("User not found", request=request),
                            status=404,
                        )
                    form = current_admin.build_password_form(request, session=session)
                    if not await form.validate():
                        return json_response(form.to_api_response().to_dict())
                    current_admin.change_password(instance, str(form.cleaned_data["password"]))
                    await current_admin.save_model(session, instance)
                    username = str(getattr(instance, "username", current_admin.verbose_name))
                return admin_modal_success_response(
                    gettext("Password changed", request=request),
                    table_target=f"#admin-{current_admin.model_path}-table",
                    notification={
                        "title": gettext("Password changed", request=request),
                        "description": gettext(
                            "%(username)s password was updated.",
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
                    if instance is None:
                        return json_response(
                            {
                                "title": gettext("Change Status", request=request),
                                "html": (
                                    '<p class="text-default-500 mb-0">'
                                    f'{escape(gettext("User not found.", request=request))}</p>'
                                ),
                            },
                            status=404,
                        )
                target_active = not bool(getattr(instance, "is_active", False))
                modal_html = await render_admin_fragment(
                    "admin/model/status_modal_form.html",
                    request,
                    action=current_admin.get_object_url(instance, admin_prefix=prefix, action="status"),
                    csrf_token=request.ctx.csrf_token,
                    target_active=target_active,
                    user=instance,
                )
                action_label = gettext("Enable", request=request) if target_active else gettext("Disable", request=request)
                username = str(getattr(instance, "username", current_admin.verbose_name))
                return json_response(
                    {
                        "title": gettext(
                            "%(action)s User · %(username)s",
                            request=request,
                            action=action_label,
                            username=escape(username),
                        ),
                        "html": str(modal_html),
                    }
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
                        return admin_form_error_response(
                            gettext("User not found", request=request),
                            status=404,
                        )
                    target_active = form_value(request, "is_active").strip().lower() in {"1", "true", "yes", "on"}
                    try:
                        current_admin.set_active(instance, target_active, current_user_id=request_user_id(request))
                    except AdminUserManagementError as exc:
                        message = gettext(str(exc), request=request)
                        return admin_form_error_response(message)
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
                            status=(
                                gettext("active", request=request)
                                if target_active
                                else gettext("disabled", request=request)
                            ),
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
    context.setdefault("admin_csrf_token", admin_csrf_token(request))
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


async def render_admin_fragment(template_name: str, request: Request, **context: Any) -> Markup:
    """Render an Admin-owned HTML fragment through the installed app environment."""
    context.setdefault("request", request)
    environment = request.app.ext.environment
    template = environment.get_template(template_name)
    if getattr(environment, "is_async", False):
        return Markup(await template.render_async(**context))
    return Markup(template.render(**context))


async def load_admin_object(model_admin: ModelAdmin, session: Any, object_id: Any) -> Any | None:
    """Load a routed object and convert malformed typed keys into route-level 404s."""
    try:
        return await model_admin.get_object(session, object_id)
    except InvalidAdminObjectId:
        raise NotFound(f"{model_admin.verbose_name} {object_id} was not found") from None


def accepts_json_form_response(request: Any) -> bool:
    """Return whether a form submission explicitly requests the JSON protocol."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "application/json" in accept


def accepts_html_form_response(request: Any) -> bool:
    """Return whether a form submission explicitly requests an HTML fragment."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "text/html" in accept and not accepts_json_form_response(request)


def admin_generic_form_success_response(request: Any, redirect_url: str):
    """Return the generic ModelAdmin success response selected by Accept."""
    if accepts_json_form_response(request):
        payload = DefaultApiFormResponse(
            error_code=ApiErrorCode.OK,
            actions=[RedirectAction(url=redirect_url)],
        )
        return json_response(payload.to_dict(), status=200)
    return redirect_response(redirect_url, status=303)


def admin_form_error_response(
    message: str,
    *,
    status: int = 200,
    errors: dict[str, str] | None = None,
):
    """Return a JSON Form business error with concrete field errors only."""
    resolved_errors: dict[str, str | LazyTranslation] = dict(errors or {})
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.FORM_INVALID,
        message=message,
        errors=resolved_errors,
    )
    return json_response(payload.to_dict(), status=status)


def admin_form_success_response(success: dict[str, Any]):
    """Return the source-compatible redirect and notification Form payload."""
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.OK,
        message=str(success["message"]),
        actions=[
            FeedbackAction(title=str(success["message"]), icon="success"),
            DashboardActivityAction(**success["notification"]),
            RedirectAction(url=str(success["url"]), delay_ms=1200),
        ],
    )
    return json_response(payload.to_dict())


def admin_modal_success_response(message: str, *, table_target: str, notification: dict[str, str]):
    """Return the shared close-and-reload contract for Admin row-action modals."""
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.OK,
        message=message,
        actions=[
            FeedbackAction(
                title=message,
                text=str(notification.get("description", "")) or None,
                icon="success",
            ),
            DashboardActivityAction(**notification),
            CloseModalAction(),
            ReloadTableAction(target=table_target),
        ],
    )
    return json_response(payload.to_dict())


def form_value(request: Request, key: str, default: str = "") -> str:
    """Return a scalar form value."""
    return str(scalar_value((request.form or {}).get(key, default), default))


def safe_next_url(raw_next_url: object, prefix: str) -> str:
    """Return a safe same-site redirect target."""
    try:
        raw_next_url = scalar_value(raw_next_url)
        next_url = "" if raw_next_url is None else str(raw_next_url)
        next_url.encode("utf-8")
    except Exception:
        return prefix
    if not next_url.startswith("/") or next_url.startswith("//"):
        return prefix
    if any(character == "\\" or ord(character) < 0x20 or ord(character) == 0x7F for character in next_url):
        return prefix
    try:
        parsed = urlparse(next_url)
    except ValueError:
        return prefix
    if parsed.scheme or parsed.netloc:
        return prefix
    return next_url


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


def login_error_url(login_path: str, next_url: str, error_code: str) -> str:
    """Build Admin login URL with an error code."""
    return f"{login_path}?{urlencode({'next': next_url, 'error': error_code})}"


def login_error_message(error_code: object) -> str:
    """Map login error codes to safe messages."""
    return {"invalid_credentials": gettext("Invalid username or password.")}.get(str(scalar_value(error_code) or ""), "")


def admin_i18n_bootstrap(request: Request, prefix: str) -> dict[str, Any]:
    """Build settings-driven language metadata for the packaged Admin runtime."""
    i18n_config = conf.settings.i18n
    registry = admin_language_registry(request)
    normalized_prefix = prefix.rstrip("/") or "/admin"
    languages = [
        {
            "code": definition.code,
            "locale": definition.code,
            "aliases": list(definition.aliases),
            "flag": definition.flag,
            "catalogPath": f"{normalized_prefix}/i18n/{quote(definition.code, safe='')}.json",
            "name": definition.name,
        }
        for definition in registry
    ]

    configured_default = i18n_config.default_language
    request_locale = str(getattr(request.ctx, "locale", "") or "")
    cookies = getattr(request, "cookies", {}) or {}
    default_language = registry.resolve(configured_default) or registry.codes[0]
    current_language = ""
    for candidate in (
        request_locale,
        str(cookies.get("lang", "")),
        str(cookies.get("preferred_language", "")),
        default_language,
    ):
        current_language = registry.resolve(candidate)
        if current_language:
            break
    current_language = current_language or default_language
    for definition in languages:
        definition["flagUrl"] = admin_language_flag_url(
            request,
            str(definition["flag"]),
            language_code=str(definition["code"]),
        )
        definition["url"] = _admin_language_url(
            request,
            str(definition["code"]),
            default_language=default_language,
            use_i18n_path=i18n_config.use_i18n_path,
        )
    current_definition = next(item for item in languages if item["code"] == current_language)
    catalog = admin_translation_catalog(
        request,
        str(current_definition["code"]),
        current_language,
    )
    return {
        "catalog": frontend_catalog_payload(
            catalog,
            str(current_definition["locale"]),
        ),
        "currentLanguage": current_language,
        "defaultLanguage": default_language,
        "languages": languages,
        "preferencePath": f"{normalized_prefix}/preferences/language",
    }


def _admin_language_url(
    request: Request,
    language: str,
    *,
    default_language: str,
    use_i18n_path: bool,
) -> str:
    """Build one Admin language target without retaining an older query override."""
    request_context = getattr(request, "ctx", None)
    clean_path = str(getattr(request_context, "clean_path", "") or getattr(request, "path", "") or "/")
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"

    target_path = clean_path
    if use_i18n_path and language != default_language:
        target_path = f"/{quote(language, safe='')}{clean_path}"

    query_items = [
        (key, value)
        for key, value in parse_qsl(str(getattr(request, "query_string", "") or ""), keep_blank_values=True)
        if key != "lang"
    ]
    query = urlencode(query_items)
    return f"{target_path}?{query}" if query else target_path


def admin_language_registry(request: Request) -> LanguageRegistry:
    """Build the Admin view of the canonical project language registry."""
    i18n_config = conf.settings.i18n
    if i18n_config.use_i18n:
        registry = LanguageRegistry(i18n_config.languages)
        if registry:
            return registry

    fallback_code = str(
        getattr(getattr(request, "ctx", None), "locale", "")
        or i18n_config.default_language
        or "en"
    )
    return LanguageRegistry(
        {
            fallback_code: {
                "aliases": [],
                "name": fallback_code,
                "flag": "",
            }
        }
    )


def admin_language_flag_url(
    request: Request,
    asset_path: str,
    *,
    language_code: str,
) -> str:
    """Resolve an Admin flag through the application's collected static root."""
    static_url = conf.settings.web.static.url
    try:
        return direct_flag_url(asset_path, static_url=static_url)
    except ValueError as exc:
        raise RuntimeError(
            f"Admin language {language_code} flag {asset_path!r} cannot be "
            "resolved without settings.web.static.url"
        ) from exc


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


def admin_csrf_token(request: Request) -> str:
    """Generate a page-level token for shell-owned state-changing requests."""
    manager = getattr(request.app.ctx, "csrf", None)
    generate_token = getattr(manager, "generate_token", None)
    return str(generate_token(request)) if callable(generate_token) else ""


def scalar_value(value: object, default: object = "") -> object:
    """Return a scalar value from Sanic request mappings."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


site = AdminSite()
