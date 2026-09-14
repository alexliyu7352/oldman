"""Admin adapter for the shared Oldman table component."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, cast

from markupsafe import Markup
from sqlalchemy import select

from oldman.apps.admin.model_admin import ModelAdmin
from oldman.db import DatabaseManager
from oldman.i18n import gettext
from oldman.web.components.tables import Column, SQLAlchemyTableView, TailwindTableRenderer
from oldman.web.components.tables.views import (
    TableInvalidRequest,
    TableValidationError,
    normalize_raw_value,
)


class AdminModelTable(SQLAlchemyTableView):
    """Expose a ModelAdmin through the framework Table renderer and protocol."""

    renderer_class = TailwindTableRenderer
    route_name = ""
    route_path = ""
    selectable = False
    sync_page_url = True
    _filter_fields: tuple[str, ...] = ()

    def __init__(
        self,
        request: Any,
        *,
        model_admin: ModelAdmin,
        db_manager: DatabaseManager,
        admin_prefix: str,
        permission_denied_response: Callable[[Any], Any] | None = None,
    ) -> None:
        query = str((getattr(request, "args", {}) or {}).get("q", "") or "").strip()
        args = getattr(request, "args", {}) or {}
        initial_filters: dict[str, object] = {
            name: str(args.get(name, "") or "").strip()
            for name in self._filter_fields
            if str(args.get(name, "") or "").strip()
        }
        super().__init__(
            request,
            initial_filters=initial_filters,
            initial_query=query,
            initial_page_size=None,
        )
        self.model_admin = model_admin
        self.model = model_admin.model
        self.admin_prefix = admin_prefix.rstrip("/") or "/admin"
        self.route_path = f"{self.admin_prefix}/{model_admin.model_path}/table"
        self.columns = tuple(model_admin.get_table_columns()) + (
            Column(name="action", label=gettext("Action"), field_path=None, callback="get_column_action_data"),
        )
        self.search_fields = tuple(model_admin.get_search_fields())
        self.ordering = tuple(model_admin.get_ordering())
        self.unsortable_columns = ("action",)
        self.page_size = model_admin.page_size
        self.selectable = model_admin.table_selectable
        # ModelAdmin owns this value: built-ins use gettext_lazy, while a
        # consumer-supplied plain string must stay literal.
        self.empty_message = str(model_admin.empty_message)
        self.database_manager = db_manager
        self._permission_denied_response = permission_denied_response

    async def check_auth(self, request: Any) -> bool:
        """Use the registered ModelAdmin permission contract for table requests."""
        return self.model_admin.has_view_permission(request)

    async def render_permission_denied_response(self, request: Any):
        """Preserve the Admin site's authentication and permission response."""
        if self._permission_denied_response is not None:
            return await self.resolve_hook_response(self._permission_denied_response(request))
        return await super().render_permission_denied_response(request)

    async def get_queryset(self):
        """Return the registered model query consumed by SQLAlchemyTableView."""
        return select(cast(Any, self.model))

    async def apply_filters(self, query: Any, table_request: Any):
        """Reject filters outside this Table adapter's private allowlist."""
        allowed = set(self._filter_fields)
        for name in table_request.filters:
            if name not in allowed:
                raise TableInvalidRequest(f"Unknown table filter: {name}")
        return await super().apply_filters(query, table_request)

    def get_cell_values(
        self,
        row: object,
        column: Column,
        context: dict[str, object],
        *,
        row_index: int,
        column_index: int,
        request: Any,
    ):
        """Keep ModelAdmin display formatting while sharing the table renderer."""
        display_value, raw_value = super().get_cell_values(
            row,
            column,
            context,
            row_index=row_index,
            column_index=column_index,
            request=request,
        )
        if column.field_path:
            value = self.model_admin.table_cell_value(row, str(column.field_path), admin_prefix=self.admin_prefix)
            if isinstance(value, tuple):
                display_value, raw_value = value
                raw_value = normalize_raw_value(raw_value)
            else:
                display_value = value
        return display_value, raw_value

    def get_column_action_data(self, row: object, **_: object) -> Markup:
        """Render ModelAdmin row actions through the shared Table callback."""
        return self.model_admin.table_action_html(row, admin_prefix=self.admin_prefix)

    def get_row_id(self, row: object) -> object:
        """Use the registered model primary key, including non-id user keys."""
        return normalize_raw_value(self.model_admin.object_pk(row))


class _AdminUserModelTable(AdminModelTable):
    """User-only Table adapter preserving the source filter contract."""

    _filter_fields = ("is_active", "is_staff", "is_superuser", "last_login_from", "last_login_to")

    async def filter_is_active(self, query: Any, value: object, table_request: Any):
        """Filter configured Admin users by active state."""
        del table_request
        model = cast(Any, self.model)
        return query.where(model.is_active.is_(parse_boolean_filter(value)))

    async def filter_is_staff(self, query: Any, value: object, table_request: Any):
        """Filter configured Admin users by staff state."""
        del table_request
        model = cast(Any, self.model)
        return query.where(model.is_staff.is_(parse_boolean_filter(value)))

    async def filter_is_superuser(self, query: Any, value: object, table_request: Any):
        """Filter configured Admin users by superuser state."""
        del table_request
        model = cast(Any, self.model)
        return query.where(model.is_superuser.is_(parse_boolean_filter(value)))

    async def filter_last_login_from(self, query: Any, value: object, table_request: Any):
        """Filter configured Admin users by the start of last-login range."""
        del table_request
        parsed = parse_filter_datetime(value)
        model = cast(Any, self.model)
        return query.where(model.last_login_at >= parsed) if parsed else query

    async def filter_last_login_to(self, query: Any, value: object, table_request: Any):
        """Filter configured Admin users by the end of last-login range."""
        del table_request
        parsed = parse_filter_datetime(value)
        model = cast(Any, self.model)
        return query.where(model.last_login_at <= parsed) if parsed else query


def parse_boolean_filter(value: object) -> bool:
    """Parse source-compatible boolean filter values."""
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise TableValidationError("Invalid boolean filter")


def parse_filter_datetime(value: object) -> dt.datetime | None:
    """Parse source-compatible date-time filter values."""
    if value in {"", None}:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        raise TableValidationError("Invalid datetime filter") from None


__all__ = ["AdminModelTable"]
