"""Managing other users' accounts: the rules every site applies, and a dashboard's user pages.

The built-in Admin manages users through its ModelAdmin pages; a dashboard installs
`UserManagementFlow`. Both apply the same rules from here: who may change which account
(`can_manage_user`, in `oldman.web.auth.permissions` so the user form can use it too), whose logins end after a change (`finish_user_change`) and what the
answer says (`user_change_text`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from markupsafe import escape
from sanic import Sanic

from oldman.auth import (
    UserManagementError,
    get_user_model,
    set_user_active,
    user_access_flags,
    user_identity,
    validate_user_delete,
)
from oldman.auth.settings import AuthSettings
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n import gettext
from oldman.web.api import (
    CloseModalAction,
    FeedbackAction,
    RedirectAction,
    ReloadTableAction,
    ResponseAction,
    form_error_response,
    form_response,
    modal_not_found_response,
    modal_response,
)
from oldman.web.auth.flows import PageRenderer, resolve_page_renderer
from oldman.web.auth.forms import UserFilterForm, UserPasswordForm, user_create_form_class, user_edit_form_class
from oldman.web.auth.login import form_value
from oldman.web.auth.modals import user_delete_modal_response, user_status_modal_response
from oldman.web.auth.permissions import can_manage_user, has_perm
from oldman.web.auth.session import revoke_user_logins
from oldman.web.auth.tables import USER_FILTER_FIELDS, UserTable
from oldman.web.auth.user_session import SIGN_IN_AGAIN_DELAY_MS
from oldman.web.authentication import request_user
from oldman.web.http import access_denied_response
from oldman.web.messages.actions import DashboardActivityAction
from oldman.web.response import Response, json_response, redirect_response
from oldman.web.routing import Router, router
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.template import render_fragment

UserChange = Literal["created", "saved", "password", "enabled", "disabled", "deleted"]


async def finish_user_change(request: Any, user_id: int, *, login_url: str) -> Response | None:
    """End the account's logins after a change to what it may do; the answer when that was the operator's own.

    Sessions and access tokens carry the flags and roles they were opened with, so a new
    password, disabling, deleting, or changed flags or roles end them. When the account is
    the operator's, this browser is signed out too: the answer returned says so and sends
    it to `login_url`. Otherwise None, and the caller answers as usual.
    """
    if not await revoke_user_logins(request, user_id):
        return None
    message = gettext("Password changed", request=request)
    return form_response(
        message,
        actions=[
            FeedbackAction(
                title=message,
                text=gettext("Your password was updated. Please sign in again.", request=request),
                icon="success",
            ),
            RedirectAction(url=login_url, delay_ms=SIGN_IN_AGAIN_DELAY_MS),
        ],
    )


def user_change_text(change: UserChange, *, username: str, request: Any = None) -> str:
    """The sentence the Admin and a dashboard both show after changing an account."""
    if change == "created":
        return gettext("%(username)s was created.", request=request, username=username)
    if change == "saved":
        return gettext("%(username)s profile was updated.", request=request, username=username)
    if change == "password":
        return gettext("%(username)s was signed out and needs the new password.", request=request, username=username)
    if change == "enabled":
        return gettext("%(username)s is now active.", request=request, username=username)
    if change == "disabled":
        return gettext("%(username)s is now disabled.", request=request, username=username)
    return gettext("%(username)s was deleted.", request=request, username=username)


@dataclass
class UserManagementFlow:
    """A dashboard's user pages: list with filters, create, edit, password, enable or disable, delete.

    Each action needs its declared permission, which superusers hold: `auth.users.view` for
    the list and its table data, `add`, `change` (edit, password, status) and `delete`. The
    rules of `can_manage_user` apply on top, and the roles the operator may hand on are
    checked by the user form. The pages sit at `base_path` (a dashboard's
    `settings.web.account.users_url`); `user_model` is the configured User model by default.
    """

    base_path: str
    login_path: str
    user_model: type[Any] | None = None
    auth_settings: AuthSettings | None = None
    db_manager: DatabaseManager | None = None

    def model(self) -> type[Any]:
        """The User model the pages manage."""
        return self.user_model if self.user_model is not None else get_user_model(self.auth_settings)

    def database(self) -> DatabaseManager:
        """Where the users live, the process's database by default."""
        return self.db_manager if self.db_manager is not None else default_db_manager

    def object_url(self, user: Any, action: str) -> str:
        """`edit`, `password`, `password-modal`, `status`, `status-modal`, `delete` or `delete-modal` for one user."""
        return f"{self.base_path}/{user_identity(user)}/{action}"

    def table_class(self, name_prefix: str = "") -> type[UserTable]:
        """The user table data endpoint at `<base_path>/table`; `UserTable` itself asks for `auth.users.view`."""
        flow = self

        class ManagedUserTable(UserTable):
            route_name = f"{name_prefix}users_table"
            route_path = f"{flow.base_path}/table"
            model = flow.model()
            database_manager = flow.database()

            def object_url(self, row: Any, action: str) -> str:
                return flow.object_url(row, action)

        return ManagedUserTable

    def activity(self, request: Any, title: str, description: str, *, tone: str, icon: str) -> DashboardActivityAction:
        """The topbar's activity entry for one change."""
        return DashboardActivityAction(
            title=title,
            description=description,
            tone=tone,
            icon=icon,
            href=self.base_path,
            time=gettext("Just now", request=request),
        )

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        name_prefix: str = "",
    ) -> None:
        """Install the pages, the table data endpoint, the modals and their submits under `base_path`.

        Pages render through `render(request, page, **context)` or `<template_prefix>/<page>.html`:
        `users/index` with `table`, `filter_form`, `users_url` and `new_url`; `users/form` with
        `form`, `user` (None when creating), `action` and `users_url`. Route names are
        `<name_prefix>users`, `..._users_table`, `..._users_new`, `..._users_create`,
        `..._users_edit`, `..._users_update`, `..._users_password_modal`,
        `..._users_password_submit`, `..._users_status_modal`, `..._users_status_submit`,
        `..._users_delete_modal` and `..._users_delete_submit`.
        """
        # Imported here, not with the module: importing oldman.web.auth must declare no auth.*
        # permission; a service that installs this flow has the auth App, which declares them.
        from oldman.auth.user_permissions import ADD_USERS, CHANGE_USERS, DELETE_USERS, VIEW_USERS

        render_view = resolve_page_renderer(render, template_prefix)
        table_class = self.table_class(name_prefix)
        target = app if app is not None else router
        base = self.base_path

        async def refuse(request: Any):
            return await access_denied_response(request, login_url=self.login_path)

        @add_csrf_token()
        async def users(request: Any):
            if not await has_perm(request, VIEW_USERS):
                return await refuse(request)
            table = table_class(
                request=request,
                initial_filters={name: str(request.args.get(name, "") or "").strip() for name in USER_FILTER_FIELDS},
                initial_query=str(request.args.get("q", "") or "").strip(),
            )
            return await render_view(
                request,
                "users/index",
                table=table,
                filter_form=UserFilterForm.from_query(request),
                users_url=base,
                new_url=f"{base}/new",
            )

        @add_csrf_token()
        async def users_new(request: Any):
            if not await has_perm(request, ADD_USERS):
                return await refuse(request)
            # The form lists the roles to give from the database.
            async with self.database().get_read_session() as session:
                form = user_create_form_class(self.model(), session=session)(request=request, session=session)
                return await render_view(request, "users/form", form=form, user=None, action=f"{base}/new", users_url=base)

        @csrf_protect()
        async def users_create(request: Any):
            if not await has_perm(request, ADD_USERS):
                return await refuse(request)
            async with self.database().get_session() as session:
                form = user_create_form_class(self.model(), session=session).from_request(request, session=session)
                if not await form.validate():
                    return json_response(form.to_api_response().to_dict())
                user = await form.save(commit=True, session=session)
                # The new user has an id only now; the checked roles are written with it.
                await form.save_roles(session, user)
                username = str(user.username)
                user_id = user_identity(user)
            title = gettext("User created", request=request)
            text = user_change_text("created", username=username, request=request)
            return form_response(
                title,
                actions=[
                    FeedbackAction(target="#users-form-feedback", title=title, text=text, icon="success"),
                    self.activity(request, title, text, tone="success", icon="ri-user-add-line"),
                    RedirectAction(url=f"{base}/{user_id}/edit", delay_ms=1200),
                ],
            )

        @add_csrf_token()
        async def users_edit(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                user = await session.get(self.model(), user_id)
                if user is None:
                    return redirect_response(base)
                form = user_edit_form_class(self.model())(request=request, instance=user, session=session)
                return await render_view(request, "users/form", form=form, user=user, action=self.object_url(user, "edit"), users_url=base)

        @csrf_protect()
        async def users_update(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            async with self.database().get_session() as session:
                user = await session.get(self.model(), user_id)
                if user is None:
                    return form_error_response(gettext("User not found", request=request), status=404)
                form = user_edit_form_class(self.model()).from_request(request, instance=user, session=session)
                form.current_user_id = request_user(request).id
                if not await form.validate():
                    return json_response(form.to_api_response().to_dict())
                access_before = user_access_flags(user)
                await form.save(commit=True, session=session)
                roles_changed = await form.save_roles(session, user)
                access_changed = user_access_flags(user) != access_before or roles_changed
                username = str(user.username)
            # The form never lets operators take their own access away; giving themselves more
            # ends their own session, and the answer then sends them to sign in again.
            if access_changed:
                signed_out = await finish_user_change(request, user_id, login_url=self.login_path)
                if signed_out is not None:
                    return signed_out
            title = gettext("User saved", request=request)
            text = user_change_text("saved", username=username, request=request)
            return form_response(
                title,
                actions=[
                    FeedbackAction(target="#users-form-feedback", title=title, text=text, icon="success"),
                    self.activity(request, title, text, tone="primary", icon="ri-settings-3-line"),
                    RedirectAction(url=f"{base}/{user_id}/edit", delay_ms=1200),
                ],
            )

        @add_csrf_token()
        async def password_modal(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                user = await session.get(self.model(), user_id)
            if user is None:
                return modal_not_found_response(gettext("Change Password", request=request), gettext("User not found.", request=request))
            form = UserPasswordForm(request=request)
            html = await render_fragment(
                request, "oldman/auth/partials/password_form.html", action=self.object_url(user, "password"), user=user, form=form
            )
            return modal_response(f"{gettext('Change Password', request=request)} · {escape(str(user.username))}", html=html)

        @csrf_protect()
        async def password_submit(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            async with self.database().get_session() as session:
                user = await session.get(self.model(), user_id)
                if user is None:
                    return form_error_response(gettext("User not found", request=request), status=404)
                if not can_manage_user(request, user):
                    return form_error_response(gettext("Permission denied", request=request))
                form = UserPasswordForm.from_request(request, session=session)
                if not await form.validate():
                    return json_response(form.to_api_response().to_dict())
                user.set_password(str(form.cleaned_data["password"]))
                session.add(user)
                username = str(user.username)
            signed_out = await finish_user_change(request, user_id, login_url=self.login_path)
            if signed_out is not None:
                return signed_out
            return list_change_response(request, "password", username, tone="success", icon="ri-lock-password-line")

        def list_change_response(request: Any, change: UserChange, username: str, *, tone: str, icon: str):
            titles = {
                "password": gettext("Password changed", request=request),
                "enabled": gettext("User status updated", request=request),
                "disabled": gettext("User status updated", request=request),
                "deleted": gettext("User deleted", request=request),
            }
            title = titles[change]
            text = user_change_text(change, username=username, request=request)
            actions: list[ResponseAction] = [
                FeedbackAction(target="#users-feedback", title=title, text=text, icon="warning" if change in {"enabled", "disabled"} else "success"),
                self.activity(request, title, text, tone=tone, icon=icon),
                CloseModalAction(),
                ReloadTableAction(target="#users-table"),
            ]
            return form_response(title, actions=actions)

        @add_csrf_token()
        async def status_modal(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                user = await session.get(self.model(), user_id)
            return await user_status_modal_response(request, user, action=f"{base}/{user_id}/status")

        @csrf_protect()
        async def status_submit(request: Any, user_id: int):
            if not await has_perm(request, CHANGE_USERS):
                return await refuse(request)
            target_active = form_value(request, "is_active").strip().lower() in {"1", "true", "yes", "on"}
            async with self.database().get_session() as session:
                user = await session.get(self.model(), user_id)
                if user is None:
                    return form_error_response(gettext("User not found", request=request), status=404)
                if not can_manage_user(request, user):
                    return form_error_response(gettext("Permission denied", request=request))
                try:
                    set_user_active(user, target_active, current_user_id=request_user(request).id)
                except UserManagementError as exc:
                    return form_error_response(gettext(str(exc), request=request))
                session.add(user)
                username = str(user.username)
            # Every disable ends the logins, not only a change of state: one disabled earlier may still hold some.
            if not target_active:
                await finish_user_change(request, user_id, login_url=self.login_path)
            return list_change_response(request, "enabled" if target_active else "disabled", username, tone="warning", icon="ri-toggle-line")

        @add_csrf_token()
        async def delete_modal(request: Any, user_id: int):
            if not await has_perm(request, DELETE_USERS):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                user = await session.get(self.model(), user_id)
            return await user_delete_modal_response(request, user, action=f"{base}/{user_id}/delete")

        @csrf_protect()
        async def delete_submit(request: Any, user_id: int):
            if not await has_perm(request, DELETE_USERS):
                return await refuse(request)
            async with self.database().get_session() as session:
                user = await session.get(self.model(), user_id)
                if user is None:
                    return form_error_response(gettext("User not found", request=request), status=404)
                if not can_manage_user(request, user):
                    return form_error_response(gettext("Permission denied", request=request))
                try:
                    validate_user_delete(user, current_user_id=request_user(request).id)
                except UserManagementError as exc:
                    return form_error_response(gettext(str(exc), request=request))
                username = str(user.username)
                await session.delete(user)
            await finish_user_change(request, user_id, login_url=self.login_path)
            return list_change_response(request, "deleted", username, tone="danger", icon="ri-delete-bin-line")

        one = f"{base}/<user_id:int>"
        routes: tuple[tuple[Any, str, str, str], ...] = (
            (users, base, "GET", "users"),
            (users_new, f"{base}/new", "GET", "users_new"),
            (users_create, f"{base}/new", "POST", "users_create"),
            (users_edit, f"{one}/edit", "GET", "users_edit"),
            (users_update, f"{one}/edit", "POST", "users_update"),
            (password_modal, f"{one}/password-modal", "GET", "users_password_modal"),
            (password_submit, f"{one}/password", "POST", "users_password_submit"),
            (status_modal, f"{one}/status-modal", "GET", "users_status_modal"),
            (status_submit, f"{one}/status", "POST", "users_status_submit"),
            (delete_modal, f"{one}/delete-modal", "GET", "users_delete_modal"),
            (delete_submit, f"{one}/delete", "POST", "users_delete_submit"),
        )
        for handler, path, method, name in routes:
            target.add_route(cast(Any, handler), path, methods=[method], name=f"{name_prefix}{name}")
        target.add_route(cast(Any, table_class.as_view()), table_class.route_path, methods=["GET"], name=table_class.route_name)


__all__ = ["UserChange", "UserManagementFlow", "finish_user_change", "user_change_text"]
