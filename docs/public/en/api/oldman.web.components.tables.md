# `oldman.web.components.tables`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Oldman 后端 Table 组件入口。

Import with `from oldman.web.components.tables import <name>`.

## `badge`

function · defined in `oldman.web.components.tables.cells`

```python
def badge(label: object, tone: str='secondary') -> Markup
```

One `om-badge`; an unknown tone falls back to the neutral badge.

## `BaseTableView`

class · defined in `oldman.web.components.tables.views`

```python
class BaseTableView(DataEndpointMixin, HTTPMethodView)
```

支持结构化数据源的无主题 Table 基类。

Constructor:

```python
BaseTableView(request: Any | None=None, *, initial_filters: dict[str, object] | None=None, initial_sort: str | None=None, initial_query: str | None=None, initial_page: int | None=None, initial_page_size: int | None=None) -> None
```

Members:

- `route_name: str = ''`
- `route_path: str = ''`
- `columns: list[object] | tuple[object, ...] = ()`
- `search_fields: list[str] | tuple[str, ...] = ()`
- `ordering: list[str] | tuple[str, ...] = ()`
- `unsortable_columns: list[str] | tuple[str, ...] = ()`
- `page_size: int = 20`
- `page_size_options: list[int] | tuple[int, ...] = (10, 20, 50, 100)`
- `max_page_size: int = 100`
- `selectable: bool = False`
- `toolbar: Sequence[str] = ('columns', 'density', 'export')`
- `export_formats: Sequence[str] = ()`
- `max_export_rows: int = 10000`
- `row_id_field: str | None = 'id'`
- `empty_message: str = cast(str, gettext_lazy('No records found.'))`
- `empty_description: str = ''`
- `empty_filtered_message: str = cast(str, gettext_lazy('No matching records'))`
- `empty_filtered_description: str = cast(str, gettext_lazy('Adjust or reset the filters to see more records.'))`
- `def get_columns() -> list[Column]` — 返回标准化后的列定义。
- `def get_renderer() -> TableRenderer` — 返回当前表格 renderer 实例。
- `async def render_shell(*, html_id: str | None=None, show_search: bool=True, data_format: Literal['html', 'json']='html', bulk_actions_html: Markup | str | None=None, **route_kwargs: object) -> Markup` — 异步渲染表格外壳和前端挂载属性；bulk_actions_html 放进工具条，只在有选中行时显示。
- `def build_table_request(request: Any, *, route_kwargs: dict[str, object]) -> TableRequest` — 从 HTTP 请求构建标准 TableRequest。
- `async def get(request: Any, **route_kwargs: object)` — 处理表格 data endpoint 请求。
- `async def check_auth(table_request: TableRequest) -> bool` — 要看请求参数或查库才能决定的整体拒绝,默认允许;拒绝时 403。
- `async def get_object_list() -> Sequence[object]` — 返回结构化数据源。
- `async def query_result(table_request: TableRequest) -> TableResult` — 执行结构化数据源查询生命周期。
- `async def query_export(table_request: TableRequest) -> TableResult` — Run the filter, search and sort lifecycle without paging; the row count stops at max_export_rows.
- `async def apply_base_filters(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — 应用服务端固定限制;第一个参数只按位置传,SQLAlchemy 表格的子类可以把它叫 ``query``。
- `async def apply_filters(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — 按 filter_xxx 方法应用请求筛选。
- `async def apply_search(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — 按 search_fields 对结构化数据做大小写不敏感搜索。
- `def resolve_sort_field(table_request: TableRequest) -> tuple[str, bool] | None` — Resolve the ordering to apply, refusing a sort the client may not ask for.
- `async def apply_ordering(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — 按 sort 参数对结构化数据排序。
- `async def paginate(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — 按页码和分页大小返回当前页数据。
- `async def preload_record_data(row: object) -> dict[str, object]` — 预加载当前行多个列共享的派生数据。
- `async def build_row_contexts(rows: Sequence[object]) -> list[Mapping[str, object]]` — Render context for every row of a page or an export; override to load extra data for all rows in one query.
- `async def render_html_fragment(table_request: TableRequest, result: TableResult) -> Markup` — 渲染 HTML Table 局部片段。
- `def render_html_head() -> str` — 渲染带列 metadata 的表头。
- `async def render_error_fragment(message: str) -> str` — 渲染表格错误局部片段。
- `async def render_request_error_response(request: Any, message: str, *, status: int)` — 按请求头把表格请求错误转换为局部 HTML 或 JSON。
- `async def render_permission_denied_response(request: Any, message: str | None=None)` — 按请求头把表格权限错误转换为局部 HTML 或 JSON;没给消息时用通用的「没有权限」。
- `async def on_permission_denied(request: Any, response_mode: str, *, message: str, method_name: str)` — endpoint 级权限失败复用表格局部错误协议,并带上 check_permission 给的消息(与图表、HTTPMethodView 一致)。
- `def render_html_row(row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> str` — 渲染 HTML Table 单行。
- `def render_html_summary(result: TableResult) -> str` — 渲染表格总数摘要。
- `def render_html_pagination(result: TableResult) -> str` — 渲染服务端分页按钮。
- `def pagination_window(current_page: int, page_count: int) -> list[int]` — 返回分页窗口页码，避免大结果集输出过多按钮撑开页面。
- `def render_html_cell(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> str` — 渲染 HTML Table 单元格。
- `def render_json_payload(table_request: TableRequest, result: TableResult[Any]) -> TableJsonPayload` — 渲染 JSON Table 协议 payload。
- `def resolve_export_format(request: Any) -> str` — Return the requested export format (`?export=csv`), lowercase, or an empty string.
- `def supported_export_formats() -> set[str]` — Return the declared export formats as lowercase names.
- `def export_filename(export_format: str) -> str` — Return the download name: route name (or `table`) plus today's date.
- `def render_export_response(export_format: str, table_request: TableRequest, result: TableResult[Any])` — Dispatch a declared export format to its renderer.
- `def render_csv_response(table_request: TableRequest, result: TableResult[Any])` — Write the exportable columns as UTF-8 CSV with a BOM so spreadsheets open it correctly.
- `def export_cell_value(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> str` — Numbers and booleans export their raw value; everything else exports the text the user sees.
- `def get_row_data(row: object) -> dict[str, object]` — 返回安全的行级前端元数据。
- `def get_row_id(row: object) -> object` — Return the configured stable identity for one structured row.
- `def get_cell_values(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue]` — 读取单元格显示值和 raw 值。
- `def resolve_cell_values(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue, bool]` — Like get_cell_values, plus whether the callback supplied the raw value itself (a `(display, raw)` tuple).
- `def call_column_callback(row: object, column: Column, context: Mapping[str, object], default_value: object, *, row_index: int, column_index: int, request: Any) -> CellReturnValue` — 调用列回调或返回默认字段值。
- `def resolve_response_type(request: Any) -> str` — 根据 response_mode 参数优先、Accept 兜底判断响应类型。

## `CellDisplayValue`

value · defined in `oldman.web.components.tables.columns`

```python
CellDisplayValue = str | int | float | Decimal | bool | None | Markup
```

## `CellRawValue`

value · defined in `oldman.web.components.tables.columns`

```python
CellRawValue = str | int | float | bool | None
```

## `CellReturnValue`

value · defined in `oldman.web.components.tables.columns`

```python
CellReturnValue = CellDisplayValue | tuple[CellDisplayValue, CellRawValue]
```

## `Column`

class · defined in `oldman.web.components.tables.columns`

```python
class Column
```

标准化后的表格列定义。

Members:

- `name: str`
- `label: str | None = None`
- `field_path: str | None | object = DEFAULT_FIELD_PATH`
- `type: str = 'string'`
- `callback: str | None = None`
- `sortable: bool = field(default=False, init=False)`
- `searchable: bool = field(default=False, init=False)`
- `exportable: bool = True`
- `visible: bool = True`
- `hideable: bool = True`
- `header_attrs: dict[str, object] = field(default_factory=dict)`
- `cell_attrs: dict[str, object] = field(default_factory=dict)`
- `def normalized(*, search_fields: set[str], unsortable_columns: set[str]) -> Column` — 返回补齐 field_path、label、排序和搜索能力后的列对象。
- `def with_metadata(*, sortable: bool, searchable: bool) -> Column` — 返回带内部排序和搜索 metadata 的列对象。

## `date_cell`

function · defined in `oldman.web.components.tables.cells`

```python
def date_cell(value: object, *, date_format: str=DEFAULT_DATE_FORMAT, empty: object='') -> tuple[Markup | str, str]
```

`(display, raw)` for a date or datetime: readable text plus the ISO value for sorting and export.

## `link`

function · defined in `oldman.web.components.tables.cells`

```python
def link(url: str, label: object, *, class_name: str='link-primary font-medium') -> Markup
```

An in-table link, by default the primary identity link of a row.

## `muted`

function · defined in `oldman.web.components.tables.cells`

```python
def muted(text: object) -> Markup
```

Secondary text, for placeholders such as "Never" or "-".

## `normalize_columns`

function · defined in `oldman.web.components.tables.columns`

```python
def normalize_columns(column_defs: list[object] | tuple[object, ...], *, search_fields: set[str], unsortable_columns: set[str]) -> list[Column]
```

把字符串、tuple 和 Column 声明标准化为 Column 列表。

## `parse_boolean_filter`

function · defined in `oldman.web.components.tables.filters`

```python
def parse_boolean_filter(value: object) -> bool
```

Accept 1/0, true/false, yes/no and on/off in any case.

## `parse_filter_datetime`

function · defined in `oldman.web.components.tables.filters`

```python
def parse_filter_datetime(value: object) -> dt.datetime | None
```

Parse an ISO date or datetime; blank means "no bound".

## `parse_int_filter`

function · defined in `oldman.web.components.tables.filters`

```python
def parse_int_filter(value: object, *, label: str, minimum: int | None=None, maximum: int | None=None) -> int
```

Parse an integer filter (an id, a score) and check it against the optional bounds.

## `resolve_field_path`

function · defined in `oldman.web.components.tables.columns`

```python
def resolve_field_path(row: object, path: str | None) -> object
```

按点号路径读取 dict、dataclass 或普通对象字段。

## `row_actions`

function · defined in `oldman.web.components.tables.cells`

```python
def row_actions(actions: Sequence[RowAction], *, label: object | None=None) -> Markup
```

The row-action menu: a ghost icon toggle and one `om-dropdown-item` per action, aligned to the end.

## `RowAction`

class · defined in `oldman.web.components.tables.cells`

```python
class RowAction
```

One entry of a row-action menu: a link, or a button that opens a (remote) modal.

Members:

- `label: object`
- `href: str | None = None`
- `modal_target: str | None = None`
- `modal_url: str | None = None`
- `icon: str | None = None`
- `danger: bool = False`
- `attrs: Mapping[str, object] | None = None`
- `def render() -> Markup`

## `SQLAlchemyTableView`

class · defined in `oldman.web.components.tables.views`

```python
class SQLAlchemyTableView(BaseTableView)
```

SQLAlchemy Table adapter 的占位基类。

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `model: type[Any] | None = None`
- `row_id_field: str | None = None`
- `loader_options: list[object] | tuple[object, ...] = ()`
- `db_session: AsyncSession | None = None`
- `async def get_queryset()` — 返回基础 SQLAlchemy 查询。
- `async def get(request: Any, **route_kwargs: object)` — 在同一个只读数据库 session 内完成表格查询和响应渲染。
- `async def query_result(table_request: TableRequest) -> TableResult` — 使用当前请求 session 完成 SQLAlchemy 表格查询生命周期。
- `async def query_export(table_request: TableRequest) -> TableResult` — Same lifecycle as query_result without OFFSET; LIMIT is max_export_rows.
- `def apply_loader_options(query: Any) -> Any` — 统一应用关系预加载配置，避免业务 get_queryset 重复手写 options。
- `async def apply_search(query: Any, /, table_request: TableRequest) -> Any` — 把 search_fields 转换为 SQL LIKE 条件。
- `async def apply_ordering(query: Any, /, table_request: TableRequest) -> Any` — 把 sort 或默认 ordering 转换为 SQL ORDER BY。
- `async def paginate(query: Any, /, table_request: TableRequest) -> list[object]` — 执行分页查询。
- `async def get_total_count(query: Any) -> int` — 执行去掉排序和分页的 count 查询。
- `def resolve_sql_field(query: Any, field_path: str, *, terminal_relationship_local_key: bool=False, isouter: bool=True) -> tuple[Any, Any]` — 解析字段路径，并为关系字段补齐显式 JOIN。
- `def require_db_session() -> AsyncSession` — Return the request-scoped SQLAlchemy session.
- `def get_row_id(row: object) -> object` — Use an explicit field or the model's single mapped primary key.

## `TableInvalidRequest`

class · defined in `oldman.web.components.tables.views`

```python
class TableInvalidRequest(Exception)
```

表格请求参数非法。

## `TableRenderer`

class · defined in `oldman.web.components.tables.renderers`

```python
class TableRenderer
```

无主题 Table renderer，负责把表格状态转换为模板上下文。

Constructor:

```python
TableRenderer(table: Any) -> None
```

Members:

- `def template_name(name: str) -> str` — 返回当前 renderer 使用的模板路径。
- `async def render_shell(*, route_kwargs: dict[str, object], html_id: str | None=None, show_search: bool=True, data_format: Literal['html', 'json']='html', bulk_actions_html: Markup | str | None=None) -> Markup` — 渲染表格外壳。
- `def render_empty_state(*, filtered: bool) -> Markup` — Empty-state block for the table body: plain when there is nothing, with a reset when filters hide everything.
- `def render_empty_templates() -> Markup` — Both empty-state variants as <template> elements for the JSON mode, which builds rows in the browser.
- `def render_toolbar(*, show_search: bool=True, bulk_actions_html: Markup | str | None=None) -> Markup` — Render the table toolbar; empty output when nothing would appear in it.
- `def toolbar_tools() -> list[str]` — Return the enabled toolbar tools in declared order.
- `def export_formats() -> list[str]` — Return the declared export formats as lowercase names.
- `staticmethod def column_is_hideable(column: Column) -> bool` — The row-action column is never hideable; other columns follow their own flag.
- `def shell_attrs(route_kwargs: dict[str, object], *, html_id: str | None, data_format: Literal['html', 'json']='html') -> dict[str, object]` — 生成表格外层容器属性。
- `def render_initial_fragment(*, data_format: Literal['html', 'json']='html') -> Markup` — 渲染远程表格首屏占位片段，避免数据到达前出现空白区域。
- `async def render_html_fragment(table_request: TableRequest, result: TableResult) -> Markup` — 渲染 HTML Table 局部片段。
- `def resolve_page_size_options(*, current_page_size: int | None=None) -> list[str]` — Return stable page-size choices even if the request view instance shadows defaults.
- `def render_html_head() -> Markup` — 渲染带列 metadata 的表头。
- `def render_error_fragment(message: str) -> Markup` — 渲染表格错误局部片段。
- `def render_html_row(row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> Markup` — 渲染 HTML Table 单行。
- `def render_html_summary(result: TableResult) -> Markup` — 渲染表格总数摘要。
- `def render_html_pagination(result: TableResult) -> Markup` — 渲染服务端分页按钮。
- `def render_html_cell(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> Markup` — 渲染 HTML Table 单元格。

## `TableRequest`

class · defined in `oldman.web.components.tables.request`

```python
class TableRequest
```

标准化后的表格请求。

Members:

- `request: Any`
- `q: str`
- `page: int`
- `page_size: int`
- `sort: str`
- `filters: dict[str, object]`
- `route_kwargs: dict[str, object]`

## `TableResult`

class · defined in `oldman.web.components.tables.results`

```python
class TableResult
```

表格查询结果，不是 HTTP 响应 DTO。

Members:

- `rows: Sequence[T_co]`
- `row_contexts: Sequence[Mapping[str, object]] = field(default_factory=list)`
- `total: int = 0`
- `filtered_total: int = 0`
- `page: int = 1`
- `page_size: int = 20`

## `TableValidationError`

class · defined in `oldman.web.components.tables.views`

```python
class TableValidationError(Exception)
```

表格筛选值校验失败。

## `TailwindTableRenderer`

class · defined in `oldman.web.components.tables.renderers`

```python
class TailwindTableRenderer(TableRenderer)
```

Tailwind/Oldman Table renderer。

## `truncated`

function · defined in `oldman.web.components.tables.cells`

```python
def truncated(text: object | None, *, max_width: int, placeholder: str='-') -> Markup
```

Muted text clipped to `max_width` pixels; empty values show `placeholder`.

## Module `oldman.web.components.tables.cells`

Cell primitives for column callbacks: badges, muted or truncated text, dates and row-action menus.

Import with `from oldman.web.components.tables.cells import <name>`.

### `BADGE_TONES`

value · defined in `oldman.web.components.tables.cells`

```python
BADGE_TONES = frozenset({'primary', 'secondary', 'success', 'info', 'warning', 'danger'})
```

### `DEFAULT_DATE_FORMAT`

value · defined in `oldman.web.components.tables.cells`

```python
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M'
```
