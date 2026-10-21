# `oldman.web.components.tables`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Backend Oldman Table component entry point.

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

Unthemed Table base supporting structured data sources.

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
- `def get_columns() -> list[Column]` — Return normalized column definitions.
- `def get_renderer() -> TableRenderer` — Return the current table renderer instance.
- `async def render_shell(*, html_id: str | None=None, show_search: bool=True, data_format: Literal['html', 'json']='html', bulk_actions_html: Markup | str | None=None, **route_kwargs: object) -> Markup` — Render the shell and mounting attributes asynchronously, showing toolbar bulk_actions_html only when rows are selected.
- `def build_table_request(request: Any, *, route_kwargs: dict[str, object]) -> TableRequest` — Build a standard TableRequest from an HTTP request.
- `async def get(request: Any, **route_kwargs: object)` — Handle a table data-endpoint request.
- `async def check_auth(table_request: TableRequest) -> bool` — Check request- or database-dependent access, allowing by default and returning 403 on denial.
- `async def get_object_list() -> Sequence[object]` — Return the structured data source.
- `async def query_result(table_request: TableRequest) -> TableResult` — Run the structured-source query lifecycle.
- `async def query_export(table_request: TableRequest) -> TableResult` — Run the filter, search and sort lifecycle without paging; the row count stops at max_export_rows.
- `async def apply_base_filters(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — Apply fixed server-side restrictions using a positional-only first argument that SQLAlchemy subclasses may name query.
- `async def apply_filters(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — Apply requested filters through filter_xxx methods.
- `async def apply_search(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — Search structured data case-insensitively using search_fields.
- `def resolve_sort_field(table_request: TableRequest) -> tuple[str, bool] | None` — Resolve the ordering to apply, refusing a sort the client may not ask for.
- `async def apply_ordering(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — Sort structured data according to the sort parameter.
- `async def paginate(rows: Sequence[object], /, table_request: TableRequest) -> Sequence[object]` — Return current-page data by page number and page size.
- `async def preload_record_data(row: object) -> dict[str, object]` — Preload derived data shared by several columns in the current row.
- `async def build_row_contexts(rows: Sequence[object]) -> list[Mapping[str, object]]` — Render context for every row of a page or an export; override to load extra data for all rows in one query.
- `async def render_html_fragment(table_request: TableRequest, result: TableResult) -> Markup` — Render an HTML Table fragment.
- `async def render_html_head() -> str` — Render table headings with column metadata.
- `async def render_error_fragment(message: str) -> str` — Render a table-error fragment.
- `async def render_request_error_response(request: Any, message: str, *, status: int)` — Convert table request errors to partial HTML or JSON according to request headers.
- `async def render_permission_denied_response(request: Any, message: str | None=None)` — Return partial HTML or JSON permission errors according to headers, defaulting to translated Permission denied.
- `async def on_permission_denied(request: Any, response_mode: str, *, message: str, method_name: str)` — Use table-fragment errors for endpoint permission denial, preserving check_permission messages like charts and HTTPMethodView.
- `async def render_html_row(row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> str` — Render one HTML Table row.
- `async def render_html_summary(result: TableResult) -> str` — Render the table-count summary.
- `async def render_html_pagination(result: TableResult) -> str` — Render server-side pagination buttons.
- `def pagination_window(current_page: int, page_count: int) -> list[int]` — Return a page-number window to avoid excessive pagination buttons for large results.
- `async def render_html_cell(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> str` — Render an HTML Table cell.
- `async def render_json_payload(table_request: TableRequest, result: TableResult[Any]) -> TableJsonPayload` — Render the JSON Table protocol payload.
- `def resolve_export_format(request: Any) -> str` — Return the requested export format (`?export=csv`), lowercase, or an empty string.
- `def supported_export_formats() -> set[str]` — Return the declared export formats as lowercase names.
- `def export_filename(export_format: str) -> str` — Return the download name: route name (or `table`) plus today's date.
- `async def render_export_response(export_format: str, table_request: TableRequest, result: TableResult[Any])` — Dispatch a declared export format to its renderer.
- `async def render_csv_response(table_request: TableRequest, result: TableResult[Any])` — Write the exportable columns as UTF-8 CSV with a BOM so spreadsheets open it correctly.
- `async def export_cell_value(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> str` — Numbers and booleans export their raw value; everything else exports the text the user sees.
- `def get_row_data(row: object) -> dict[str, object]` — Return safe row-level browser metadata.
- `def get_row_id(row: object) -> object` — Return the configured stable identity for one structured row.
- `async def get_cell_values(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue]` — Read cell display and raw values.
- `async def resolve_cell_values(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> tuple[CellDisplayValue, CellRawValue, bool]` — Like get_cell_values, plus whether the callback supplied the raw value itself (a `(display, raw)` tuple).
- `async def call_column_callback(row: object, column: Column, context: Mapping[str, object], default_value: object, *, row_index: int, column_index: int, request: Any) -> CellReturnValue` — Call the column's callback, or return the field value when it has none.
- `def resolve_response_type(request: Any) -> str` — Choose response type from response_mode first, falling back to Accept.

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

Normalized table-column definition.

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
- `def normalized(*, search_fields: set[str], unsortable_columns: set[str]) -> Column` — Return a column with resolved field_path, label, sorting, and search capabilities.
- `def with_metadata(*, sortable: bool, searchable: bool) -> Column` — Return a column with internal sorting and search metadata.

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

Normalize strings, tuples, and Column declarations to a Column list.

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

Read dict, dataclass, or ordinary-object fields through dotted paths.

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

Placeholder base class for SQLAlchemy Table adapters.

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `model: type[Any] | None = None`
- `row_id_field: str | None = None`
- `loader_options: list[object] | tuple[object, ...] = ()`
- `db_session: AsyncSession | None = None`
- `async def get_queryset()` — Return the base SQLAlchemy query.
- `async def get(request: Any, **route_kwargs: object)` — Query and render table responses within one read-only database session.
- `async def query_result(table_request: TableRequest) -> TableResult` — Run SQLAlchemy table queries using the current request session.
- `async def query_export(table_request: TableRequest) -> TableResult` — Same lifecycle as query_result without OFFSET; LIMIT is max_export_rows.
- `def apply_loader_options(query: Any) -> Any` — Apply relationship-preloading configuration centrally without repeated options in business get_queryset methods.
- `async def apply_search(query: Any, /, table_request: TableRequest) -> Any` — Convert search_fields to SQL LIKE conditions.
- `async def apply_ordering(query: Any, /, table_request: TableRequest) -> Any` — Convert sort or default ordering to SQL ORDER BY.
- `async def paginate(query: Any, /, table_request: TableRequest) -> list[object]` — Execute a paginated query.
- `async def get_total_count(query: Any) -> int` — Execute a count query without ordering or pagination.
- `def resolve_sql_field(query: Any, field_path: str, *, terminal_relationship_local_key: bool=False, isouter: bool=True) -> tuple[Any, Any]` — Resolve field paths and add explicit JOINs for relationship fields.
- `def require_db_session() -> AsyncSession` — Return the request-scoped SQLAlchemy session.
- `def get_row_id(row: object) -> object` — Use an explicit field or the model's single mapped primary key.

## `TableInvalidRequest`

class · defined in `oldman.web.components.tables.views`

```python
class TableInvalidRequest(Exception)
```

Invalid table request parameters.

## `TableRenderer`

class · defined in `oldman.web.components.tables.renderers`

```python
class TableRenderer
```

Unthemed Table renderer converting table state into template context.

Constructor:

```python
TableRenderer(table: Any) -> None
```

Members:

- `def template_name(name: str) -> str` — Return the current renderer's template path.
- `async def render_shell(*, route_kwargs: dict[str, object], html_id: str | None=None, show_search: bool=True, data_format: Literal['html', 'json']='html', bulk_actions_html: Markup | str | None=None) -> Markup` — Render the table shell.
- `async def render_empty_state(*, filtered: bool) -> Markup` — Empty-state block for the table body: plain when there is nothing, with a reset when filters hide everything.
- `async def render_empty_templates() -> Markup` — Both empty-state variants as &lt;template&gt; elements for the JSON mode, which builds rows in the browser.
- `async def render_toolbar(*, show_search: bool=True, bulk_actions_html: Markup | str | None=None) -> Markup` — Render the table toolbar; empty output when nothing would appear in it.
- `def toolbar_tools() -> list[str]` — Return the enabled toolbar tools in declared order.
- `def export_formats() -> list[str]` — Return the declared export formats as lowercase names.
- `staticmethod def column_is_hideable(column: Column) -> bool` — The row-action column is never hideable; other columns follow their own flag.
- `def shell_attrs(route_kwargs: dict[str, object], *, html_id: str | None, data_format: Literal['html', 'json']='html') -> dict[str, object]` — Build outer table-container attributes.
- `async def render_initial_fragment(*, data_format: Literal['html', 'json']='html') -> Markup` — Render an initial remote-table placeholder to avoid blank space before data arrives.
- `async def render_html_fragment(table_request: TableRequest, result: TableResult) -> Markup` — Render an HTML Table fragment.
- `def resolve_page_size_options(*, current_page_size: int | None=None) -> list[str]` — Return stable page-size choices even if the request view instance shadows defaults.
- `async def render_html_head() -> Markup` — Render table headings with column metadata.
- `async def render_error_fragment(message: str) -> Markup` — Render a table-error fragment.
- `async def render_html_row(row: object, context: Mapping[str, object], *, row_index: int, request: Any) -> Markup` — Render one HTML Table row.
- `async def render_html_summary(result: TableResult) -> Markup` — Render the table-count summary.
- `async def render_html_pagination(result: TableResult) -> Markup` — Render server-side pagination buttons.
- `async def render_html_cell(row: object, column: Column, context: Mapping[str, object], *, row_index: int, column_index: int, request: Any) -> Markup` — Render an HTML Table cell.

## `TableRequest`

class · defined in `oldman.web.components.tables.request`

```python
class TableRequest
```

Normalized table request.

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

Table query results, not an HTTP response DTO.

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

Table-filter value validation failure.

## `TailwindTableRenderer`

class · defined in `oldman.web.components.tables.renderers`

```python
class TailwindTableRenderer(TableRenderer)
```

Tailwind/Oldman Table renderer.

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
