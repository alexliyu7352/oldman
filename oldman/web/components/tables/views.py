"""Table 视图基类和响应渲染。"""

from __future__ import annotations

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
from oldman.web.http import OldmanHTTPMethodView, resolve_response_mode
from oldman.web.response import html_response, json_response

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


class BaseTableView(OldmanHTTPMethodView):
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
    row_id_field: str | None = "id"
    empty_message: str = cast(str, gettext_lazy("No records found."))
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
        **route_kwargs: object,
    ) -> Markup:
        """异步渲染表格外壳和前端挂载属性。"""
        return await self.get_renderer().render_shell(route_kwargs=route_kwargs, html_id=html_id, show_search=show_search, data_format=data_format)

    def build_data_url(self, route_kwargs: dict[str, object]) -> str:
        """通过 Sanic url_for 生成 data endpoint 地址。"""
        if self.request is not None and getattr(self.request, "app", None) is not None and self.route_name:
            try:
                return self.request.app.url_for(self.route_name, **route_kwargs)
            except Exception:
                return self.request.app.url_for(f"{self.request.app.name}.{self.route_name}", **route_kwargs)
        return self.route_path

    def build_table_request(self, request: Any, *, route_kwargs: dict[str, object]) -> TableRequest:
        """从 HTTP 请求构建标准 TableRequest。"""
        args = getattr(request, "args", {}) or {}
        try:
            page_size = parse_positive_int(get_arg(args, "page_size", self.initial_page_size or self.page_size), self.page_size, maximum=self.max_page_size)
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
        try:
            result = await self.query_result(table_request)
        except TableInvalidRequest as exc:
            return await self.render_request_error_response(request, str(exc), status=400)
        except TableValidationError as exc:
            return await self.render_request_error_response(request, str(exc), status=422)
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
        rows = list(await self.get_object_list())
        total = len(rows)
        rows = list(await self.apply_base_filters(rows, table_request))
        rows = list(await self.apply_filters(rows, table_request))
        rows = list(await self.apply_search(rows, table_request))
        filtered_total = len(rows)
        rows = list(await self.apply_ordering(rows, table_request))
        rows = list(await self.paginate(rows, table_request))
        row_contexts = [await self.preload_record_data(row) for row in rows]
        return TableResult(rows=rows, row_contexts=row_contexts, total=total, filtered_total=filtered_total, page=table_request.page, page_size=table_request.page_size)

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

    async def apply_ordering(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按 sort 参数对结构化数据排序。"""
        sort = table_request.sort or first_ordering(self.ordering)
        if not sort:
            return rows
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        columns = {column.name: column for column in self.get_columns()}
        column = columns.get(field)
        if column is not None:
            if not column.sortable:
                return rows
            field = str(column.field_path)
        return sorted(rows, key=lambda row: sort_key(resolve_field_path(row, field)), reverse=descending)

    async def paginate(self, rows: Sequence[object], table_request: TableRequest) -> Sequence[object]:
        """按页码和分页大小返回当前页数据。"""
        start = (table_request.page - 1) * table_request.page_size
        end = start + table_request.page_size
        return rows[start:end]

    async def preload_record_data(self, row: object) -> dict[str, object]:
        """预加载当前行多个列共享的派生数据。"""
        return {}

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
                display_value, raw_value = self.get_cell_values(row, column, context, row_index=row_index, column_index=column_index, request=table_request.request)
                cells[column.name] = None if display_value is None else str(render_display_value(display_value))
                raw_values[column.name] = "" if raw_value is None else raw_value
            rows.append({"cells": cells, "raw_values": raw_values, "data": self.get_row_data(row)})
        return {
            "columns": [
                {"name": column.name, "label": str(column.label or column.name), "type": column.type, "sortable": bool(column.sortable), "searchable": bool(column.searchable)}
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

    def get_cell_values(self, row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue]:
        """读取单元格显示值和 raw 值。"""
        default_value = resolve_field_path(row, str(column.field_path)) if column.field_path else None
        value = self.call_column_callback(row, column, context, default_value, row_index=row_index, column_index=column_index, request=request)
        if isinstance(value, tuple):
            display_value, raw_value = value
            return display_value, normalize_raw_value(raw_value)
        return value, normalize_raw_value(default_value if column.field_path else None)

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
        row_contexts = [await self.preload_record_data(row) for row in rows]
        return TableResult(rows=rows, row_contexts=row_contexts, total=total, filtered_total=filtered_total, page=table_request.page, page_size=table_request.page_size)

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
        sort = table_request.sort or first_ordering(self.ordering)
        if not sort:
            return query
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        columns = {column.name: column for column in self.get_columns()}
        column = columns.get(field)
        if column is not None:
            if not column.sortable:
                return query
            field = str(column.field_path)
        joined_query, sql_field = self.resolve_sql_field(
            query,
            field,
            terminal_relationship_local_key=True,
        )
        return joined_query.order_by(sql_field.desc() if descending else sql_field.asc())

    async def paginate(self, query: Any, table_request: TableRequest) -> list[object]:
        """执行分页查询。"""
        result = await self.require_db_session().execute(query.limit(table_request.page_size).offset((table_request.page - 1) * table_request.page_size))
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
    ) -> tuple[Any, Any]:
        """解析字段路径，并为关系字段补齐显式 JOIN。"""
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
                        raise ValueError(
                            f"SQLAlchemy relationship ordering requires an explicit scalar field path: {field_path}"
                        )
                    return query, local_columns[0]
                query = query.join(descriptor)
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


def callback_name_for_column(column: Column) -> str:
    """返回字段列默认回调方法名。"""
    if not column.field_path:
        return ""
    safe_name = safe_method_name(str(column.field_path))
    return f"get_column_{safe_name}_data"


def safe_method_name(value: str) -> str:
    """把字段路径转换为 Python 方法名片段。"""
    return value.replace(".", "_").replace("-", "_")


def to_kebab_case(value: str) -> str:
    """把筛选字段名转换为 HTML data 属性后缀。"""
    return value.replace("_", "-").replace(".", "-")


def get_arg(args: object, key: str, default: object = None) -> object:
    """从 request.args 读取单值参数。"""
    getter = getattr(args, "get", None)
    if getter is None:
        return default
    return first_arg_value(getter(key, default))


def iter_args(args: object) -> list[tuple[str, object]]:
    """遍历 request.args 中的单值参数。"""
    if hasattr(args, "items"):
        return [(key, first_arg_value(value)) for key, value in cast(Any, args).items()]
    return []


def first_arg_value(value: object) -> object:
    """把 Sanic 多值查询参数规范为首个值。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


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


def normalize_raw_value(value: object) -> CellRawValue:
    """把字段值规范为 raw value。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def render_display_value(value: CellDisplayValue) -> Markup:
    """把显示值转换为安全 HTML。"""
    if isinstance(value, Markup):
        return value
    if value is None:
        return Markup("")
    return Markup(escape(value))


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
