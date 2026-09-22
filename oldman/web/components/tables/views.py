"""Table 视图基类和响应渲染。"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal, TypedDict, cast

from markupsafe import Markup, escape
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, RelationshipDirection, RelationshipProperty

from oldman.db import DatabaseManager
from oldman.db import db_manager as default_db_manager
from oldman.i18n import gettext_lazy
from oldman.web.api import ApiErrorCode, DefaultApiResponse
from oldman.web.components.data_endpoint import DataEndpointMixin
from oldman.web.http import OldmanHTTPMethodView, resolve_response_mode
from oldman.web.request import get_arg, iter_args
from oldman.web.response import html_response, json_response, raw_response

from .cells import normalize_raw_value, render_display_value
from .columns import (
    CellDisplayValue,
    CellRawValue,
    CellReturnValue,
    Column,
    normalize_columns,
    resolve_field_path,
)
from .renderers import TableRenderer
from .request import TableRequest, parse_positive_int
from .results import TableResult


class TableColumnPayload(TypedDict):
    name: str
    label: str
    type: str
    sortable: bool
    searchable: bool


class TableRowPayload(TypedDict):
    cells: dict[str, object]
    raw_values: dict[str, object]
    data: dict[str, object]


class TablePaginationPayload(TypedDict):
    page: int
    page_size: int
    total: int
    filtered_total: int
    has_next: bool


class TableJsonPayload(TypedDict):
    columns: list[TableColumnPayload]
    rows: list[TableRowPayload]
    pagination: TablePaginationPayload
    sort: str


class TableInvalidRequest(Exception):
    """表格请求参数非法。"""


class TableValidationError(Exception):
    """表格筛选值校验失败。"""


class BaseTableView(DataEndpointMixin, OldmanHTTPMethodView):
    """支持结构化数据源的无主题 Table 基类。"""

    require_authenticated = True
    require_staff = True
    route_name: str = ""
    route_path: str = ""
    columns: list[object] | tuple[object, ...] = ()
    search_fields: list[str] | tuple[str, ...] = ()
    ordering: list[str] | tuple[str, ...] = ()
    unsortable_columns: list[str] | tuple[str, ...] = ()
    page_size: int = 20
    page_size_options: list[int] | tuple[int, ...] = (10, 20, 50, 100)
    max_page_size: int = 100
    sync_page_url = False
    selectable: bool = False
    # Toolbar tools in display order; "export" only renders once export_formats is non-empty.
    toolbar: Sequence[str] = ("columns", "density", "export")
    # Declaring a format (only "csv" is built in) enables `?export=<format>` on the data endpoint.
    export_formats: Sequence[str] = ()
    max_export_rows: int = 10_000
    row_id_field: str | None = "id"
    empty_message: str = cast(str, gettext_lazy("No records found."))
    empty_description: str = ""
    # Shown instead when records exist but none match the search or filters; offers a reset.
    empty_filtered_message: str = cast(str, gettext_lazy("No matching records"))
    empty_filtered_description: str = cast(str, gettext_lazy("Adjust or reset the filters to see more records."))
    renderer_class = TableRenderer

    def __init__(
        self,
        request: Any | None = None,
        *,
        initial_filters: dict[str, object] | None = None,
        initial_sort: str | None = None,
        initial_query: str | None = None,
        initial_page: int | None = None,
        initial_page_size: int | None = None,
    ) -> None:
        """初始化表格 shell 或请求实例。"""
        self.request = request
        self.initial_filters = initial_filters or {}
        args = getattr(request, "args", {}) or {} if request is not None else {}
        self.initial_sort = initial_sort if initial_sort is not None else optional_text(get_arg(args, "sort", None))
        self.initial_query = initial_query if initial_query is not None else optional_text(get_arg(args, "q", None))
        self.initial_page = initial_page
        if self.initial_page is None:
            try:
                self.initial_page = parse_positive_int(get_arg(args, "page", 1), 1)
            except ValueError:
                self.initial_page = 1
        self.initial_page_size = initial_page_size
        if self.initial_page_size is None:
            raw_page_size = get_arg(args, "page_size", None)
            if raw_page_size not in {"", None}:
                try:
                    self.initial_page_size = parse_positive_int(raw_page_size, self.page_size, maximum=self.max_page_size)
                except ValueError:
                    self.initial_page_size = None

    def get_columns(self) -> list[Column]:
        """返回标准化后的列定义。"""
        return normalize_columns(list(self.columns), search_fields=set(self.search_fields), unsortable_columns=set(self.unsortable_columns))

    def get_renderer(self) -> TableRenderer:
        """返回当前表格 renderer 实例。"""
        return self.renderer_class(self)

    async def render_shell(
        self,
        *,
        html_id: str | None = None,
        show_search: bool = True,
        data_format: Literal["html", "json"] = "html",
        bulk_actions_html: Markup | str | None = None,
        **route_kwargs: object,
    ) -> Markup:
        """异步渲染表格外壳和前端挂载属性；bulk_actions_html 放进工具条，只在有选中行时显示。"""
        # Only forward the slot when a page fills it, so renderers with the older signature keep working.
        extra: dict[str, Markup | str] = {"bulk_actions_html": bulk_actions_html} if bulk_actions_html else {}
        return await self.get_renderer().render_shell(
            route_kwargs=route_kwargs,
            html_id=html_id,
            show_search=show_search,
            data_format=data_format,
            **extra,
        )

    def build_table_request(self, request: Any, *, route_kwargs: dict[str, object]) -> TableRequest:
        """从 HTTP 请求构建标准 TableRequest。"""
        args = getattr(request, "args", {}) or {}
        try:
            page_size = parse_positive_int(
                get_arg(args, "page_size", self.initial_page_size or self.page_size), self.page_size, maximum=self.max_page_size
            )
            page = parse_positive_int(get_arg(args, "page", 1), 1)
        except ValueError as exc:
            raise TableInvalidRequest("Invalid table pagination parameter") from exc
        filters = {key.removeprefix("filter."): value for key, value in iter_args(args) if key.startswith("filter.") and value not in {"", None}}
        return TableRequest(
            request=request,
            q=str(get_arg(args, "q", "") or ""),
            page=page,
            page_size=page_size,
            sort=str(get_arg(args, "sort", self.initial_sort or first_ordering(self.ordering)) or ""),
            filters=filters,
            route_kwargs=dict(route_kwargs),
        )

    async def get(self, request: Any, **route_kwargs: object):
        """处理表格 data endpoint 请求。"""
        self.request = request
        try:
            table_request = self.build_table_request(request, route_kwargs=route_kwargs)
        except TableInvalidRequest as exc:
            return await self.render_request_error_response(request, str(exc), status=400)
        if not await self.check_auth(table_request.request):
            return await self.render_permission_denied_response(request)
        export_format = self.resolve_export_format(request)
        if export_format and export_format not in self.supported_export_formats():
            return await self.render_request_error_response(request, "Unsupported table export format", status=400)
        try:
            result = await (self.query_export(table_request) if export_format else self.query_result(table_request))
        except TableInvalidRequest as exc:
            return await self.render_request_error_response(request, str(exc), status=400)
        except TableValidationError as exc:
            return await self.render_request_error_response(request, str(exc), status=422)
        if export_format:
            return self.render_export_response(export_format, table_request, result)
        if self.resolve_response_type(request) == "json":
            return json_response(self.render_json_payload(table_request, result))
        return html_response(await self.render_html_fragment(table_request, result))

    async def check_auth(self, request: Any) -> bool:
        """检查当前请求是否允许访问表格数据。"""
        return True

    async def get_object_list(self) -> Sequence[object]:
        """返回结构化数据源。"""
        return []

    async def query_result(self, table_request: TableRequest) -> TableResult:
        """执行结构化数据源查询生命周期。"""
        rows = list(await self.apply_base_filters(list(await self.get_object_list()), table_request))
        total = len(rows)  # like the SQL lifecycle: base filters shape the data, user filters narrow it
        rows = list(await self.apply_filters(rows, table_request))
        rows = list(await self.apply_search(rows, table_request))
        filtered_total = len(rows)
        rows = list(await self.apply_ordering(rows, table_request))
        rows = list(await self.paginate(rows, table_request))
        row_contexts = await self.build_row_contexts(rows)
        return TableResult(
            rows=rows,
            row_contexts=row_contexts,
            total=total,
            filtered_total=filtered_total,
            page=table_request.page,
            page_size=table_request.page_size,
        )

    async def query_export(self, table_request: TableRequest) -> TableResult:
        """Run the filter, search and sort lifecycle without paging; the row count stops at max_export_rows."""
        rows = list(await self.apply_base_filters(list(await self.get_object_list()), table_request))
        total = len(rows)
        rows = list(await self.apply_filters(rows, table_request))
        rows = list(await self.apply_search(rows, table_request))
        filtered_total = len(rows)
        rows = list(await self.apply_ordering(rows, table_request))[: self.max_export_rows]
        row_contexts = await self.build_row_contexts(rows)
        return TableResult(rows=rows, row_contexts=row_contexts, total=total, filtered_total=filtered_total, page=1, page_size=max(1, len(rows)))

    async def apply_base_filters(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """应用服务端固定限制。"""
        return rows

    async def apply_filters(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按 filter_xxx 方法应用请求筛选。"""
        current: Sequence[object] = rows
        for name, value in table_request.filters.items():
            method = getattr(self, f"filter_{safe_method_name(name)}", None)
            if method is None:
                raise TableInvalidRequest(f"Unknown table filter: {name}")
            current = await method(current, value, table_request)
        return current

    async def apply_search(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按 search_fields 对结构化数据做大小写不敏感搜索。"""
        term = table_request.q.strip().lower()
        if not term:
            return rows
        fields = tuple(self.search_fields)
        if not fields:
            return rows
        return [row for row in rows if any(term in stringify(resolve_field_path(row, field)).lower() for field in fields)]

    def resolve_sort_field(self, table_request: TableRequest) -> tuple[str, bool] | None:
        """Resolve the ordering to apply, refusing a sort the client may not ask for.

        Client-supplied `sort` and the developer's `ordering` are not the same kind of
        value and must not share one code path. `ordering` is code: it may legitimately
        name something that is not a visible column, such as `-updated_at`.
        `table_request.sort` is request input, so it has to name a column this table
        declares as sortable — the way `apply_filters` requires a declared `filter_<name>`
        method rather than accepting any name it is handed.

        The old check asked `if column is not None` before consulting `sortable`, so a
        column that was *declared and excluded* was refused while one that was *never
        declared at all* went straight through to ORDER BY. `?sort=password_hash` worked
        on the framework's own user table, which puts that column in `exclude`, and an
        undeclared dotted path could emit a JOIN nobody asked for.

        Returns the field path and direction, or None when there is nothing to order by.
        """
        columns = {column.name: column for column in self.get_columns()}

        requested = table_request.sort
        if requested:
            descending = requested.startswith("-")
            name = requested[1:] if descending else requested
            column = columns.get(name)
            if column is None:
                raise TableInvalidRequest(f"Unknown table sort: {name}")
            if not column.sortable:
                raise TableInvalidRequest(f"Table column is not sortable: {name}")
            return str(column.field_path), descending

        fallback = first_ordering(self.ordering)
        if not fallback:
            return None
        descending = fallback.startswith("-")
        name = fallback[1:] if descending else fallback
        column = columns.get(name)
        if column is None:
            return name, descending
        if not column.sortable:
            return None
        return str(column.field_path), descending

    async def apply_ordering(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按 sort 参数对结构化数据排序。"""
        resolved = self.resolve_sort_field(table_request)
        if resolved is None:
            return rows
        field, descending = resolved
        return sorted(rows, key=lambda row: sort_key(resolve_field_path(row, field)), reverse=descending)

    async def paginate(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按页码和分页大小返回当前页数据。"""
        start = (table_request.page - 1) * table_request.page_size
        end = start + table_request.page_size
        return rows[start:end]

    async def preload_record_data(self, row: object) -> dict[str, object]:
        """预加载当前行多个列共享的派生数据。"""
        return {}

    async def build_row_contexts(self, rows: Sequence[object]) -> list[Mapping[str, object]]:
        """Render context for every row of a page or an export; override to load extra data for all rows in one query.

        The default calls `preload_record_data(row)` per row. Both `query_result()` and `query_export()` go
        through here, so a subclass never has to duplicate the query lifecycle to enrich its rows.
        """
        return [await self.preload_record_data(row) for row in rows]

    async def render_html_fragment(self, table_request: TableRequest, result: TableResult) -> Markup:
        """渲染 HTML Table 局部片段。"""
        return await self.get_renderer().render_html_fragment(table_request, result)

    def render_html_head(self) -> str:
        """渲染带列 metadata 的表头。"""
        return str(self.get_renderer().render_html_head())

    async def render_error_fragment(self, message: str) -> str:
        """渲染表格错误局部片段。"""
        return str(self.get_renderer().render_error_fragment(message))

    async def render_request_error_response(self, request: Any, message: str, *, status: int):
        """按请求头把表格请求错误转换为局部 HTML 或 JSON。"""
        if self.resolve_response_type(request) == "json":
            response = DefaultApiResponse(
                error_code=ApiErrorCode.INVALID_REQUEST,
                message=message,
                data={"errors": {"table": message}},
            )
            return json_response(response.to_dict(), status=status)
        return html_response(await self.render_error_fragment(message), status=status)

    async def render_permission_denied_response(self, request: Any):
        """按请求头把表格权限错误转换为局部 HTML 或 JSON。"""
        message = "Permission denied"
        if self.resolve_response_type(request) == "json":
            response = DefaultApiResponse(
                error_code=ApiErrorCode.PERMISSION_DENIED,
                message=message,
                data={"errors": {"table": message}},
            )
            return json_response(response.to_dict(), status=403)
        return html_response(await self.render_error_fragment(message), status=403)

    async def on_permission_denied(self, request: Any, response_mode: str, *, message: str, method_name: str):
        """endpoint 级权限失败复用表格局部错误协议。"""
        del response_mode, message, method_name
        return await self.render_permission_denied_response(request)

    def render_html_row(self, row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> str:
        """渲染 HTML Table 单行。"""
        return str(self.get_renderer().render_html_row(row, context, row_index=row_index, request=request))

    def render_html_summary(self, result: TableResult) -> str:
        """渲染表格总数摘要。"""
        return str(self.get_renderer().render_html_summary(result))

    def render_html_pagination(self, result: TableResult) -> str:
        """渲染服务端分页按钮。"""
        return str(self.get_renderer().render_html_pagination(result))

    def pagination_window(self, current_page: int, page_count: int) -> list[int]:
        """返回分页窗口页码，避免大结果集输出过多按钮撑开页面。"""
        if page_count <= 9:
            return list(range(1, page_count + 1))

        pages = {1, page_count}
        for page in range(max(1, current_page - 2), min(page_count, current_page + 2) + 1):
            pages.add(page)
        # 当前在首尾附近时补齐相邻页码，避免首页只能看到极少操作项。
        if current_page <= 4:
            pages.update(range(1, min(page_count, 6) + 1))
        if current_page >= page_count - 3:
            pages.update(range(max(1, page_count - 5), page_count + 1))
        return sorted(pages)

    def render_html_cell(self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> str:
        """渲染 HTML Table 单元格。"""
        return str(self.get_renderer().render_html_cell(row, column, context, row_index=row_index, column_index=column_index, request=request))

    def render_json_payload(self, table_request: TableRequest, result: TableResult[Any]) -> TableJsonPayload:
        """渲染 JSON Table 协议 payload。"""
        columns = self.get_columns()
        rows: list[TableRowPayload] = []
        for row_index, (row, context) in enumerate(zip(result.rows, result.row_contexts, strict=True)):
            cells: dict[str, object] = {}
            raw_values: dict[str, object] = {}
            for column_index, column in enumerate(columns):
                display_value, raw_value = self.get_cell_values(
                    row, column, context, row_index=row_index, column_index=column_index, request=table_request.request
                )
                cells[column.name] = None if display_value is None else str(render_display_value(display_value))
                raw_values[column.name] = "" if raw_value is None else raw_value
            rows.append({"cells": cells, "raw_values": raw_values, "data": self.get_row_data(row)})
        return {
            "columns": [
                {
                    "name": column.name,
                    "label": str(column.label or column.name),
                    "type": column.type,
                    "sortable": bool(column.sortable),
                    "searchable": bool(column.searchable),
                }
                for column in columns
            ],
            "rows": rows,
            "pagination": {
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "filtered_total": result.filtered_total,
                "has_next": result.page * result.page_size < result.filtered_total,
            },
            "sort": table_request.sort,
        }

    def resolve_export_format(self, request: Any) -> str:
        """Return the requested export format (`?export=csv`), lowercase, or an empty string."""
        return str(get_arg(getattr(request, "args", {}) or {}, "export", "") or "").strip().lower()

    def supported_export_formats(self) -> set[str]:
        """Return the declared export formats as lowercase names."""
        return {str(name).lower() for name in self.export_formats}

    def export_filename(self, export_format: str) -> str:
        """Return the download name: route name (or `table`) plus today's date."""
        return f"{self.route_name or 'table'}-{dt.date.today().isoformat()}.{export_format}"

    def render_export_response(self, export_format: str, table_request: TableRequest, result: TableResult[Any]):
        """Dispatch a declared export format to its renderer."""
        if export_format == "csv":
            return self.render_csv_response(table_request, result)
        raise ValueError(f"No renderer for table export format {export_format!r}")

    def render_csv_response(self, table_request: TableRequest, result: TableResult[Any]):
        """Write the exportable columns as UTF-8 CSV with a BOM so spreadsheets open it correctly."""
        columns = [(index, column) for index, column in enumerate(self.get_columns()) if column_is_exportable(column)]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([str(column.label or column.name) for _index, column in columns])
        for row_index, (row, context) in enumerate(zip(result.rows, result.row_contexts, strict=True)):
            writer.writerow(
                [
                    csv_safe_text(
                        self.export_cell_value(row, column, context, row_index=row_index, column_index=index, request=table_request.request)
                    )
                    for index, column in columns
                ]
            )
        body = ("\ufeff" + buffer.getvalue()).encode("utf-8")
        return raw_response(
            body,
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{self.export_filename("csv")}"'},
        )

    def export_cell_value(
        self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any
    ) -> str:
        """Numbers and booleans export their raw value; everything else exports the text the user sees.

        A Markup cell whose callback also returned a raw text (`(markup, raw)`) exports that raw text: the
        markup is presentation (a link, a title plus description) and the raw value is the data behind it.
        """
        display_value, raw_value, explicit_raw = self.resolve_cell_values(
            row, column, context, row_index=row_index, column_index=column_index, request=request
        )
        if isinstance(raw_value, bool):
            return "true" if raw_value else "false"
        if isinstance(raw_value, (int, float)):
            return str(raw_value)
        if isinstance(display_value, Markup):
            if explicit_raw and isinstance(raw_value, str) and raw_value.strip():
                return raw_value
            text = markup_text(display_value)
        else:
            text = "" if display_value is None else str(display_value)
        if text.strip():
            return "true" if display_value is True else "false" if display_value is False else text
        return "" if raw_value is None else str(raw_value)

    def get_row_data(self, row: object) -> dict[str, object]:
        """返回安全的行级前端元数据。"""
        row_id = self.get_row_id(row)
        return {"id": row_id} if row_id is not None else {}

    def get_row_id(self, row: object) -> object:
        """Return the configured stable identity for one structured row."""
        if self.row_id_field is None:
            raise ValueError("BaseTableView.row_id_field must be set")
        row_id = resolve_field_path(row, self.row_id_field)
        if row_id is None:
            raise ValueError(f"Table row identity field {self.row_id_field!r} is missing")
        return normalize_raw_value(row_id)

    def get_cell_values(
        self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any
    ) -> tuple[CellDisplayValue, CellRawValue]:
        """读取单元格显示值和 raw 值。"""
        display_value, raw_value, _explicit = self.resolve_cell_values(
            row, column, context, row_index=row_index, column_index=column_index, request=request
        )
        return display_value, raw_value

    def resolve_cell_values(
        self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any
    ) -> tuple[CellDisplayValue, CellRawValue, bool]:
        """Like get_cell_values, plus whether the callback supplied the raw value itself (a `(display, raw)` tuple)."""
        default_value = resolve_field_path(row, str(column.field_path)) if column.field_path else None
        value = self.call_column_callback(row, column, context, default_value, row_index=row_index, column_index=column_index, request=request)
        if isinstance(value, tuple):
            display_value, raw_value = value
            return display_value, normalize_raw_value(raw_value), True
        return value, normalize_raw_value(default_value if column.field_path else None), False

    def call_column_callback(
        self,
        row: object,
        column: Column,
        context: Mapping[str, object],
        default_value: object,
        *,
        row_index: int,
        column_index: int,
        request: Any,
    ) -> CellReturnValue:
        """调用列回调或返回默认字段值。"""
        callback = column.callback or callback_name_for_column(column) or f"get_column_{column_index}_data"
        method = getattr(self, callback, None) if callback else None
        if method is not None:
            return method(
                row,
                column=column,
                field_path=column.field_path,
                default_value=default_value,
                row_context=context,
                row_index=row_index,
                column_index=column_index,
                table=self,
                request=request,
            )
        return normalize_display_value(default_value)

    def resolve_response_type(self, request: Any) -> str:
        """根据 response_mode 参数优先、Accept 兜底判断响应类型。"""
        return resolve_response_mode(request)


class SQLAlchemyTableView(BaseTableView):
    """SQLAlchemy Table adapter 的占位基类。"""

    # 多数据库业务通过子类覆盖该属性；默认对象仍由 DB 模块惰性初始化。
    database_manager: DatabaseManager = default_db_manager
    model: type[Any] | None = None
    row_id_field: str | None = None
    loader_options: list[object] | tuple[object, ...] = ()
    db_session: AsyncSession | None = None

    async def get_queryset(self):
        """返回基础 SQLAlchemy 查询。"""
        raise NotImplementedError("SQLAlchemyTableView.get_queryset() must be implemented by subclasses")

    async def get(self, request: Any, **route_kwargs: object):
        """在同一个只读数据库 session 内完成表格查询和响应渲染。"""
        try:
            self.build_table_request(request, route_kwargs=route_kwargs)
        except TableInvalidRequest as exc:
            return await self.render_request_error_response(request, str(exc), status=400)
        async with self.database_manager.get_read_session() as session:
            self.db_session = session
            try:
                return await super().get(request, **route_kwargs)
            finally:
                self.db_session = None

    async def query_result(self, table_request: TableRequest) -> TableResult:
        """使用当前请求 session 完成 SQLAlchemy 表格查询生命周期。"""
        query = await self.get_queryset()
        query = self.apply_loader_options(query)
        query = await self.apply_base_filters(query, table_request)
        total = await self.get_total_count(query)
        filtered_query = await self.apply_filters(query, table_request)
        filtered_query = await self.apply_search(filtered_query, table_request)
        filtered_total = await self.get_total_count(filtered_query)
        ordered_query = await self.apply_ordering(filtered_query, table_request)
        rows = await self.paginate(ordered_query, table_request)
        row_contexts = await self.build_row_contexts(rows)
        return TableResult(
            rows=rows,
            row_contexts=row_contexts,
            total=total,
            filtered_total=filtered_total,
            page=table_request.page,
            page_size=table_request.page_size,
        )

    async def query_export(self, table_request: TableRequest) -> TableResult:
        """Same lifecycle as query_result without OFFSET; LIMIT is max_export_rows."""
        query = await self.get_queryset()
        query = self.apply_loader_options(query)
        query = await self.apply_base_filters(query, table_request)
        total = await self.get_total_count(query)
        filtered_query = await self.apply_filters(query, table_request)
        filtered_query = await self.apply_search(filtered_query, table_request)
        filtered_total = await self.get_total_count(filtered_query)
        ordered_query = await self.apply_ordering(filtered_query, table_request)
        executed = await self.require_db_session().execute(ordered_query.limit(self.max_export_rows))
        rows = list(executed.scalars().all())
        row_contexts = await self.build_row_contexts(rows)
        return TableResult(rows=rows, row_contexts=row_contexts, total=total, filtered_total=filtered_total, page=1, page_size=max(1, len(rows)))

    def apply_loader_options(self, query: Any) -> Any:
        """统一应用关系预加载配置，避免业务 get_queryset 重复手写 options。"""
        if not self.loader_options:
            return query
        return query.options(*self.loader_options)

    async def apply_search(self, query: Any, table_request: TableRequest) -> Any:
        """把 search_fields 转换为 SQL LIKE 条件。"""
        term = table_request.q.strip()
        if not term or not self.search_fields:
            return query
        like = f"%{term}%"
        expressions = []
        current_query = query
        for field in self.search_fields:
            current_query, sql_field = self.resolve_sql_field(current_query, field)
            expressions.append(sql_field.like(like))
        return current_query.where(or_(*expressions))

    async def apply_ordering(self, query: Any, table_request: TableRequest) -> Any:
        """把 sort 或默认 ordering 转换为 SQL ORDER BY。"""
        resolved = self.resolve_sort_field(table_request)
        if resolved is None:
            return query
        field, descending = resolved
        joined_query, sql_field = self.resolve_sql_field(
            query,
            field,
            terminal_relationship_local_key=True,
        )
        return joined_query.order_by(sql_field.desc() if descending else sql_field.asc())

    async def paginate(self, query: Any, table_request: TableRequest) -> list[object]:
        """执行分页查询。"""
        result = await self.require_db_session().execute(
            query.limit(table_request.page_size).offset((table_request.page - 1) * table_request.page_size)
        )
        return list(result.scalars().all())

    async def get_total_count(self, query: Any) -> int:
        """执行去掉排序和分页的 count 查询。"""
        count_query = select(func.count()).select_from(query.order_by(None).subquery())
        return int((await self.require_db_session().execute(count_query)).scalar_one() or 0)

    def resolve_sql_field(
        self,
        query: Any,
        field_path: str,
        *,
        terminal_relationship_local_key: bool = False,
        isouter: bool = True,
    ) -> tuple[Any, Any]:
        """解析字段路径，并为关系字段补齐显式 JOIN。

        JOIN 在这里只为读到关联表的某一列，所以默认是 LEFT OUTER JOIN：没有关联记录的行仍然留在
        列表里（搜索时它们匹配不到这一列，排序时排在一端）。想用 JOIN 顺带过滤掉这些行时传
        `isouter=False`。同一个关系被多个字段路径用到时 SQLAlchemy 只会拼一次 JOIN——注意条件是"同一个
        关系"：两个不同关系指向同一张表（`created_by` 和 `updated_by` 都指向用户表）会拼出两个不带别名的
        JOIN，WHERE 里的列名随即有歧义，数据库直接报错。那种表需要调用方自己用 `aliased()`。
        """
        if self.model is None:
            raise ValueError("SQLAlchemyTableView.model must be set")
        mapper: Mapper[Any] = inspect(self.model)
        current_model = self.model
        current_mapper = mapper
        current_attr: Any = None
        parts = field_path.split(".")
        for index, part in enumerate(parts):
            descriptor = getattr(current_model, part, None)
            if descriptor is None:
                raise ValueError(f"Unknown SQLAlchemy field path: {field_path}")
            current_attr = descriptor
            property_ = current_mapper.attrs.get(part)
            if isinstance(property_, RelationshipProperty):
                if terminal_relationship_local_key and index == len(parts) - 1:
                    local_columns = tuple(property_.local_columns)
                    if property_.direction is not RelationshipDirection.MANYTOONE or len(local_columns) != 1:
                        raise ValueError(f"SQLAlchemy relationship ordering requires an explicit scalar field path: {field_path}")
                    return query, local_columns[0]
                query = query.join(descriptor, isouter=isouter)
                current_model = property_.mapper.class_
                current_mapper = inspect(current_model)
        return query, current_attr

    def require_db_session(self) -> AsyncSession:
        """Return the request-scoped SQLAlchemy session."""
        if self.db_session is None:
            raise RuntimeError("SQLAlchemyTableView requires an active database session")
        return self.db_session

    def get_row_id(self, row: object) -> object:
        """Use an explicit field or the model's single mapped primary key."""
        if self.model is None:
            raise ValueError("SQLAlchemyTableView.model must be set")
        if self.row_id_field is not None:
            return BaseTableView.get_row_id(self, row)
        primary_key = list(inspect(self.model).primary_key)
        if len(primary_key) != 1:
            raise ValueError("SQLAlchemy Table rows require exactly one primary key column")
        row_id = getattr(row, primary_key[0].key, None)
        if row_id is None:
            raise ValueError("SQLAlchemy Table row primary key value is missing")
        return normalize_raw_value(row_id)


CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
NUMERIC_TEXT = re.compile(r"[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?")


BLOCK_TAG_BOUNDARY = re.compile(
    r"<(?:/?(?:p|div|li|tr|td|th|h[1-6]|section|article|ul|ol|table|blockquote|dd|dt|pre)\b[^>]*|br\s*/?)>", re.IGNORECASE
)


def markup_text(value: Markup) -> str:
    """Visible text of a fragment; block boundaries become spaces so `<a>Title</a><div>Desc</div>` reads "Title Desc"."""
    return Markup(BLOCK_TAG_BOUNDARY.sub(" ", str(value))).striptags()


def csv_safe_text(text: str) -> str:
    """Neutralise spreadsheet formula triggers (OWASP CSV injection) without touching plain numbers.

    A cell such as `=HYPERLINK(...)` or `-2+3+cmd|' /C calc'!A0` would run when the export is opened in
    Excel or LibreOffice; a leading apostrophe makes the application show it as text.
    """
    if not text or text[0] not in CSV_FORMULA_PREFIXES or NUMERIC_TEXT.fullmatch(text):
        return text
    return f"'{text}"


def column_is_exportable(column: Column) -> bool:
    """The row-action column (named `action`, like the CSS and toolbar conventions) never exports."""
    return bool(column.exportable) and column.name != "action"


def callback_name_for_column(column: Column) -> str:
    """返回字段列默认回调方法名。"""
    if not column.field_path:
        return ""
    safe_name = safe_method_name(str(column.field_path))
    return f"get_column_{safe_name}_data"


def safe_method_name(value: str) -> str:
    """把字段路径转换为 Python 方法名片段。"""
    return value.replace(".", "_").replace("-", "_")


def first_ordering(ordering: list[str] | tuple[str, ...]) -> str:
    """返回默认排序字段。"""
    return str(ordering[0]) if ordering else ""


def optional_text(value: object) -> str | None:
    """Normalize optional request text without turning a missing value into ``"None"``."""
    if value in {"", None}:
        return None
    return str(value)


def stringify(value: object) -> str:
    """把搜索值转换为字符串。"""
    return "" if value is None else str(value)


def sort_key(value: object) -> tuple[int, object]:
    """生成结构化数据排序 key。"""
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.lower())
    return (0, value)


def normalize_display_value(value: object) -> CellDisplayValue:
    """把字段值规范为可显示值。"""
    if isinstance(value, (str, int, float, bool, Decimal, Markup)) or value is None:
        return value
    return str(value)


def render_attrs(attrs: dict[str, object]) -> str:
    """渲染 HTML 属性字符串。"""
    rendered = []
    for key, value in attrs.items():
        if value is None:
            continue
        if value == "":
            rendered.append(f" {key}")
        else:
            rendered.append(f' {key}="{escape(value)}"')
    return "".join(rendered)
