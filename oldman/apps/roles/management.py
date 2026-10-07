"""Managing roles: the steps every role page takes, and a dashboard's role pages.

Permission checks read a role's permissions from its Redis key (``oldman.apps.roles.store``), and
the key never expires, so a page that saves or deletes a role keeps it in step:

- once the save has committed, write the key (`publish_saved_role`);
- inside the delete's transaction, drop the key before the row (`delete_role`), and drop it once
  more after the delete has committed (`forget_deleted_role`).

The built-in Admin's role page calls these; a dashboard installs `RoleManagementFlow`, which
calls them too. Importing this module declares no ``roles.*`` permission: they are imported
where they are checked, so only a service that installs the roles App has them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from markupsafe import Markup, escape
from redis.exceptions import RedisError
from sanic import Sanic
from sanic.exceptions import ServiceUnavailable
from sqlalchemy import select

from oldman.apps.roles import store
from oldman.apps.roles.forms import RoleForm
from oldman.apps.roles.models import Role
from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n import gettext, gettext_lazy
from oldman.logging import get_logger
from oldman.web.api import (
    ApiErrorCode,
    CloseModalAction,
    FeedbackAction,
    RedirectAction,
    ReloadTableAction,
    form_error_response,
    form_response,
    modal_not_found_response,
    modal_response,
)
from oldman.web.auth.flows import PageRenderer, resolve_page_renderer
from oldman.web.auth.permissions import has_perm, roles_installed
from oldman.web.components.tables import Column, RowAction, SQLAlchemyTableView, TailwindTableRenderer, link, row_actions
from oldman.web.http import access_denied_response
from oldman.web.messages.actions import recent_activity
from oldman.web.response import json_response, redirect_response
from oldman.web.routing import Router, router
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.template import render_fragment

logger = get_logger(__name__)

ROLE_DELETE_MODAL = "#role-delete-modal"


async def publish_saved_role(role: Role) -> None:
    """Write the saved permissions to the role's cache key; call it once the save has committed.

    The role is saved by then. If Redis refuses, this raises a 503 saying the permission store
    is unavailable, and saving the role again once Redis is back repairs the key.
    """
    try:
        await store.publish_role(role)
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc


async def delete_role(session: Any, role: Role) -> None:
    """Drop the role's cache key, then delete its row, inside the caller's transaction.

    If Redis refuses, the 503 raised rolls the transaction back and nothing is deleted. The other
    order would leave a key nothing can remove: the role would be gone, and the next delete
    would find no role.
    """
    try:
        await store.forget_role(role.id)
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The permission store is unavailable")) from exc
    await session.delete(role)
    await session.flush()


async def forget_deleted_role(role_id: int) -> None:
    """Drop the key once more after the delete has committed.

    A request that read the role just before the delete may have written the key back in
    between. The delete already stands, so a refusal here is logged, not reported.
    """
    try:
        await store.forget_role(role_id)
    except RedisError:
        logger.warning("Could not drop the cache key of deleted role %s", role_id, exc_info=True)


class RoleTable(SQLAlchemyTableView):
    """The role list as a table data endpoint; a site sets `route_name`, `route_path` and `object_url()`.

    It asks for `roles.view` itself (a superuser holds it): a dashboard admits every active
    user, and being signed in is not enough.
    """

    renderer_class = TailwindTableRenderer
    model = Role
    page_size = 10
    ordering = ["name"]
    search_fields = ["name", "description"]
    unsortable_columns = ["action"]
    empty_message = cast(str, gettext_lazy("No roles found."))
    columns = [
        (gettext_lazy("Name"), "name", "get_column_name_data"),
        (gettext_lazy("Description"), "description"),
        Column(
            name="action",
            label=cast(str, gettext_lazy("Action")),
            field_path=None,
            callback="get_column_action_data",
            exportable=False,
            hideable=False,
        ),
    ]

    async def check_permission(self, request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]:
        """`roles.view`, checked before the query runs."""
        del method_name, route_kwargs
        # Imported here: importing this module must declare no roles.* permission.
        from oldman.apps.roles.permissions import VIEW_ROLES

        return await has_perm(request, VIEW_ROLES), None

    def object_url(self, row: Any, action: str) -> str:
        """Map "edit" and "delete-modal" to this site's routes for `row`."""
        raise NotImplementedError("RoleTable subclasses must implement object_url(row, action)")

    async def get_queryset(self):
        return select(Role)

    def get_column_name_data(self, row: Any, **_: object):
        return link(self.object_url(row, "edit"), row.name), row.name

    def get_column_action_data(self, row: Any, **_: object) -> tuple[Markup, str]:
        return row_actions(
            [
                RowAction(gettext("Edit"), href=self.object_url(row, "edit"), icon="ri-pencil-fill"),
                RowAction(
                    gettext("Delete"),
                    modal_target=ROLE_DELETE_MODAL,
                    modal_url=self.object_url(row, "delete-modal"),
                    icon="ri-delete-bin-line",
                    danger=True,
                ),
            ],
            label=gettext("Role actions"),
        ), ""


@dataclass
class RoleManagementFlow:
    """A dashboard's role pages: list, create, edit and delete.

    Each action needs its declared permission, which superusers hold: `roles.view` for the
    list and its table data, `roles.add`, `roles.change` and `roles.delete`. The role form
    adds its own rule: someone who is not a superuser adds only permissions they hold. Saving
    and deleting keep the role's cache key in step, as the Admin does. Deleting a role ends
    nobody's logins; those still carrying its id get nothing from it. The pages sit at
    `base_path` (a dashboard's `settings.web.account.roles_url`).
    """

    base_path: str
    login_path: str
    db_manager: DatabaseManager | None = None

    def database(self) -> DatabaseManager:
        """Where the roles live, the process's database by default."""
        return self.db_manager if self.db_manager is not None else default_db_manager

    def object_url(self, role: Any, action: str) -> str:
        """`edit`, `delete-modal` or `delete` for one role."""
        return f"{self.base_path}/{role.id}/{action}"

    def table_class(self, name_prefix: str = "") -> type[RoleTable]:
        """The role table data endpoint at `<base_path>/table`; `RoleTable` itself asks for `roles.view`."""
        flow = self

        class ManagedRoleTable(RoleTable):
            route_name = f"{name_prefix}roles_table"
            route_path = f"{flow.base_path}/table"
            database_manager = flow.database()

            def object_url(self, row: Any, action: str) -> str:
                return flow.object_url(row, action)

        return ManagedRoleTable

    def register_routes(
        self,
        app: Sanic | Router | None = None,
        *,
        render: PageRenderer | None = None,
        template_prefix: str | None = None,
        name_prefix: str = "",
    ) -> None:
        """Install the pages, the table data endpoint, the delete modal and its submit under `base_path`.

        Pages render through `render(request, page, **context)` or `<template_prefix>/<page>.html`:
        `roles/index` with `table`, `roles_url` and `new_url`; `roles/form` with `form`, `role`
        (None when creating), `action` and `roles_url`. Route names are `<name_prefix>roles`,
        `..._roles_table`, `..._roles_new`, `..._roles_create`, `..._roles_edit`,
        `..._roles_update`, `..._roles_delete_modal` and `..._roles_delete_submit`. Given the
        service's app, it refuses one that does not install the roles App.
        """
        if isinstance(app, Sanic) and not roles_installed(app):
            raise RuntimeError("RoleManagementFlow needs the oldman.apps.roles App: add it to the service's apps and run migrate")
        # Imported here, not with the module: importing it must declare no roles.* permission;
        # a service that installs this flow has the roles App, which declares them.
        from oldman.apps.roles.permissions import ADD_ROLES, CHANGE_ROLES, DELETE_ROLES, VIEW_ROLES

        render_view = resolve_page_renderer(render, template_prefix)
        table_class = self.table_class(name_prefix)
        target = app if app is not None else router
        base = self.base_path

        async def refuse(request: Any):
            return await access_denied_response(request, login_url=self.login_path)

        def unavailable(exc: ServiceUnavailable):
            # Raised, the 503 would reach the browser as Sanic's own error body, without the
            # error_code the form needs to show the translated message.
            return form_error_response(str(exc), error_code=ApiErrorCode.SERVICE_UNAVAILABLE, status=503)

        def saved_response(request: Any, role: Role, *, created: bool):
            title = gettext("Role created", request=request) if created else gettext("Role saved", request=request)
            name = str(role.name)
            text = (
                gettext("%(name)s was created.", request=request, name=name)
                if created
                else gettext("%(name)s was updated.", request=request, name=name)
            )
            return form_response(
                title,
                actions=[
                    FeedbackAction(target="#roles-form-feedback", title=title, text=text, icon="success"),
                    recent_activity(request, title, text, tone="success" if created else "primary", icon="ri-shield-user-line", href=base),
                    RedirectAction(url=self.object_url(role, "edit"), delay_ms=1200),
                ],
            )

        @add_csrf_token()
        async def roles(request: Any):
            if not await has_perm(request, VIEW_ROLES):
                return await refuse(request)
            table = table_class(request=request, initial_query=str(request.args.get("q", "") or "").strip())
            return await render_view(request, "roles/index", table=table, roles_url=base, new_url=f"{base}/new")

        @add_csrf_token()
        async def roles_new(request: Any):
            if not await has_perm(request, ADD_ROLES):
                return await refuse(request)
            form = RoleForm(request=request)
            return await render_view(request, "roles/form", form=form, role=None, action=f"{base}/new", roles_url=base)

        @csrf_protect()
        async def roles_create(request: Any):
            if not await has_perm(request, ADD_ROLES):
                return await refuse(request)
            async with self.database().get_session() as session:
                form = RoleForm.from_request(request, session=session)
                if not await form.validate():
                    return json_response(form.to_api_response().to_dict())
                role = await form.save(commit=True, session=session)
            try:
                await publish_saved_role(role)
            except ServiceUnavailable as exc:
                return unavailable(exc)
            return saved_response(request, role, created=True)

        @add_csrf_token()
        async def roles_edit(request: Any, role_id: int):
            if not await has_perm(request, CHANGE_ROLES):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                role = await session.get(Role, role_id)
            if role is None:
                return redirect_response(base)
            form = RoleForm(request=request, instance=role)
            return await render_view(request, "roles/form", form=form, role=role, action=self.object_url(role, "edit"), roles_url=base)

        @csrf_protect()
        async def roles_update(request: Any, role_id: int):
            if not await has_perm(request, CHANGE_ROLES):
                return await refuse(request)
            async with self.database().get_session() as session:
                role = await session.get(Role, role_id)
                if role is None:
                    return form_error_response(gettext("Role not found", request=request), status=404)
                form = RoleForm.from_request(request, instance=role, session=session)
                if not await form.validate():
                    return json_response(form.to_api_response().to_dict())
                await form.save(commit=True, session=session)
            try:
                await publish_saved_role(role)
            except ServiceUnavailable as exc:
                return unavailable(exc)
            return saved_response(request, role, created=False)

        @add_csrf_token()
        async def delete_modal(request: Any, role_id: int):
            if not await has_perm(request, DELETE_ROLES):
                return await refuse(request)
            async with self.database().get_read_session() as session:
                role = await session.get(Role, role_id)
            title = gettext("Delete Role", request=request)
            if role is None:
                return modal_not_found_response(title, gettext("Role not found.", request=request))
            html = await render_fragment(
                request, "oldman/dashboard/account/roles/delete_form.html", action=self.object_url(role, "delete"), role=role
            )
            return modal_response(f"{title} · {escape(str(role.name))}", html=html)

        @csrf_protect()
        async def delete_submit(request: Any, role_id: int):
            if not await has_perm(request, DELETE_ROLES):
                return await refuse(request)
            try:
                async with self.database().get_session() as session:
                    role = await session.get(Role, role_id)
                    if role is None:
                        return form_error_response(gettext("Role not found", request=request), status=404)
                    name = str(role.name)
                    await delete_role(session, role)
            except ServiceUnavailable as exc:
                # Raised inside the transaction, so it rolled back: the role and its key are both still there.
                return unavailable(exc)
            await forget_deleted_role(role_id)
            title = gettext("Role deleted", request=request)
            text = gettext("%(name)s was deleted.", request=request, name=name)
            return form_response(
                title,
                actions=[
                    FeedbackAction(target="#roles-feedback", title=title, text=text, icon="success"),
                    recent_activity(request, title, text, tone="danger", icon="ri-delete-bin-line", href=base),
                    CloseModalAction(),
                    ReloadTableAction(target="#roles-table"),
                ],
            )

        one = f"{base}/<role_id:int>"
        routes: tuple[tuple[Any, str, str, str], ...] = (
            (roles, base, "GET", "roles"),
            (roles_new, f"{base}/new", "GET", "roles_new"),
            (roles_create, f"{base}/new", "POST", "roles_create"),
            (roles_edit, f"{one}/edit", "GET", "roles_edit"),
            (roles_update, f"{one}/edit", "POST", "roles_update"),
            (delete_modal, f"{one}/delete-modal", "GET", "roles_delete_modal"),
            (delete_submit, f"{one}/delete", "POST", "roles_delete_submit"),
        )
        for handler, path, method, name in routes:
            target.add_route(cast(Any, handler), path, methods=[method], name=f"{name_prefix}{name}")
        target.add_route(cast(Any, table_class.as_view()), table_class.route_path, methods=["GET"], name=table_class.route_name)


__all__ = ["RoleManagementFlow", "RoleTable", "delete_role", "forget_deleted_role", "publish_saved_role"]
