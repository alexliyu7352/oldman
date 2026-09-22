"""Table pieces for the configured User model: cell renderers, row actions, filters and a ready-made table view.

The built-in Admin and project login sites list the same users with the same columns, badges and row menu;
only the URLs differ, so a site provides those through `UserTable.object_url()` (or passes them to the
functions directly when it drives its own table).
"""

from __future__ import annotations

from typing import Any, cast

from markupsafe import Markup
from sqlalchemy import select

from oldman.auth import get_user_model
from oldman.i18n import gettext, gettext_lazy
from oldman.web.components.tables import (
    Column,
    RowAction,
    SQLAlchemyTableView,
    TailwindTableRenderer,
    badge,
    date_cell,
    link,
    parse_boolean_filter,
    parse_filter_datetime,
    row_actions,
)

USER_FILTER_FIELDS = ("is_active", "is_staff", "is_superuser", "last_login_from", "last_login_to")
USER_MODAL_TARGETS = {"password-modal": "#user-password-modal", "status-modal": "#user-status-modal", "delete-modal": "#user-delete-modal"}


def user_cell_value(user: Any, field_name: str, *, edit_url: str | None = None) -> Any:
    """Display value for the standard User columns; None for any other field so the caller can fall back.

    The username links to `edit_url`, the three flags render as badges and the last login as a date cell
    whose empty state reads "Never".
    """
    value = getattr(user, field_name, None)
    if field_name == "username":
        return link(edit_url, value or "") if edit_url else (value or "")
    if field_name == "is_active":
        return badge(gettext("Active") if value else gettext("Disabled"), "success" if value else "danger")
    if field_name == "is_staff":
        return badge(gettext("Staff") if value else gettext("No Staff"), "info" if value else "secondary")
    if field_name == "is_superuser":
        return badge(gettext("Superuser") if value else gettext("User"), "warning" if value else "secondary")
    if field_name == "last_login_at":
        return date_cell(value, empty=gettext("Never"))
    return None


def user_row_actions(
    user: Any,
    *,
    edit_url: str,
    password_modal_url: str,
    status_modal_url: str,
    delete_modal_url: str,
    label: object | None = None,
) -> Markup:
    """The user row menu: edit, change password, enable/disable and delete (the last three open modals)."""
    status_label = gettext("Disable") if bool(getattr(user, "is_active", False)) else gettext("Enable")
    return row_actions(
        [
            RowAction(gettext("Edit"), href=edit_url, icon="ri-pencil-fill"),
            RowAction(
                gettext("Change Password"),
                modal_target=USER_MODAL_TARGETS["password-modal"],
                modal_url=password_modal_url,
                icon="ri-lock-password-line",
            ),
            RowAction(status_label, modal_target=USER_MODAL_TARGETS["status-modal"], modal_url=status_modal_url, icon="ri-toggle-line"),
            RowAction(
                gettext("Delete"), modal_target=USER_MODAL_TARGETS["delete-modal"], modal_url=delete_modal_url, icon="ri-delete-bin-line", danger=True
            ),
        ],
        label=label if label is not None else gettext("User actions"),
    )


class UserTableFilters:
    """The standard User filters (`filter_<name>` hooks) for any table view whose `model` is the User model."""

    model: type[Any] | None

    async def filter_is_active(self, query: Any, value: object, table_request: Any):
        del table_request
        return query.where(cast(Any, self.model).is_active.is_(parse_boolean_filter(value)))

    async def filter_is_staff(self, query: Any, value: object, table_request: Any):
        del table_request
        return query.where(cast(Any, self.model).is_staff.is_(parse_boolean_filter(value)))

    async def filter_is_superuser(self, query: Any, value: object, table_request: Any):
        del table_request
        return query.where(cast(Any, self.model).is_superuser.is_(parse_boolean_filter(value)))

    async def filter_last_login_from(self, query: Any, value: object, table_request: Any):
        del table_request
        parsed = parse_filter_datetime(value)
        return query.where(cast(Any, self.model).last_login_at >= parsed) if parsed else query

    async def filter_last_login_to(self, query: Any, value: object, table_request: Any):
        del table_request
        parsed = parse_filter_datetime(value)
        return query.where(cast(Any, self.model).last_login_at <= parsed) if parsed else query


class UserTable(UserTableFilters, SQLAlchemyTableView):
    """The user list as a table data endpoint; a site sets `route_name`, `route_path` and `object_url()`."""

    renderer_class = TailwindTableRenderer
    page_size = 10
    selectable = True
    export_formats = ("csv",)
    ordering = ["username"]
    search_fields = ["username", "email", "display_name"]
    unsortable_columns = ["action"]
    empty_message = cast(str, gettext_lazy("No users found."))
    columns = [
        (gettext_lazy("Username"), "username", "get_column_username_data"),
        (gettext_lazy("Email"), "email"),
        (gettext_lazy("Display Name"), "display_name"),
        (gettext_lazy("Status"), "is_active", "get_column_is_active_data"),
        (gettext_lazy("Staff"), "is_staff", "get_column_is_staff_data"),
        (gettext_lazy("Superuser"), "is_superuser", "get_column_is_superuser_data"),
        (gettext_lazy("Last Login"), "last_login_at", "get_column_last_login_at_data"),
        Column(
            name="action",
            label=cast(str, gettext_lazy("Action")),
            field_path=None,
            callback="get_column_action_data",
            exportable=False,
            hideable=False,
        ),
    ]

    def __init__(self, request: Any = None, **options: Any) -> None:
        super().__init__(request, **options)
        if self.model is None:
            self.model = get_user_model()

    def object_url(self, row: Any, action: str) -> str:
        """Map "edit", "password-modal", "status-modal" and "delete-modal" to this site's routes for `row`."""
        raise NotImplementedError("UserTable subclasses must implement object_url(row, action)")

    async def get_queryset(self):
        return select(cast(Any, self.model))

    def get_column_username_data(self, row: Any, **_: object):
        return user_cell_value(row, "username", edit_url=self.object_url(row, "edit")), row.username

    def get_column_is_active_data(self, row: Any, **_: object):
        return user_cell_value(row, "is_active"), bool(row.is_active)

    def get_column_is_staff_data(self, row: Any, **_: object):
        return user_cell_value(row, "is_staff"), bool(row.is_staff)

    def get_column_is_superuser_data(self, row: Any, **_: object):
        return user_cell_value(row, "is_superuser"), bool(row.is_superuser)

    def get_column_last_login_at_data(self, row: Any, **_: object):
        return user_cell_value(row, "last_login_at")

    def get_column_action_data(self, row: Any, **_: object):
        return user_row_actions(
            row,
            edit_url=self.object_url(row, "edit"),
            password_modal_url=self.object_url(row, "password-modal"),
            status_modal_url=self.object_url(row, "status-modal"),
            delete_modal_url=self.object_url(row, "delete-modal"),
        ), ""


__all__ = ["USER_FILTER_FIELDS", "USER_MODAL_TARGETS", "UserTable", "UserTableFilters", "user_cell_value", "user_row_actions"]
