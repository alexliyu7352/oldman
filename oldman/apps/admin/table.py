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
from oldman.web.auth.tables import USER_FILTER_FIELDS, UserTableFilters
from oldman.web.components.tables import Column, SQLAlchemyTableView, TailwindTableRenderer
from oldman.web.components.tables.cells import normalize_raw_value
from oldman.web.components.tables.views import TableInvalidRequest


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
            Column(name="action", label=gettext("Action"), field_path=None, callback="get_column_action_data", exportable=False, hideable=False),
        )
        self.search_fields = tuple(model_admin.get_search_fields())
        self.ordering = tuple(model_admin.get_ordering())
        self.unsortable_columns = ("action",)
        self.page_size = model_admin.page_size
        self.selectable = model_admin.table_selectable
        # getattr: duck-typed ModelAdmin stand-ins may predate the toolbar options.
        self.toolbar = tuple(getattr(model_admin, "table_toolbar", ModelAdmin.table_toolbar))
        self.export_formats = tuple(getattr(model_admin, "export_formats", ModelAdmin.export_formats))
        # ModelAdmin owns this value: built-ins use gettext_lazy, while a
        # consumer-supplied plain string must stay literal.
        self.empty_message = str(model_admin.empty_message)
        self.database_manager = db_manager
        self._permission_denied_response = permission_denied_response

    async def check_auth(self, request: Any) -> bool:
        """Use the registered ModelAdmin permission contract for table requests."""
        return self.model_admin.has_view_permission(request)

    def export_filename(self, export_format: str) -> str:
        """Name downloads after the model path instead of the internal route name."""
        return f"{self.model_admin.model_path}-{dt.date.today().isoformat()}.{export_format}"

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


class _AdminUserModelTable(UserTableFilters, AdminModelTable):
    """The user ModelAdmin table: the shared User filters on top of the generic adapter."""

    _filter_fields = USER_FILTER_FIELDS


__all__ = ["AdminModelTable"]
