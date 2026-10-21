# Static, HTML, and JSON Tables

The three approaches serve different situations without requiring three backend business implementations.

| Approach | Suitable use | Where data is processed |
| --- | --- | --- |
| Static HTML table | Known small lists or explanatory tables | Business views/templates render once, without automatic pagination |
| HTML Table | Server-rendered dynamic tables | SQL pagination; browser replaces Table fragments |
| JSON Table | JSON-driven browser tables using the same backend data | SQL pagination; browser organizes rows/columns with TanStack Table Core |

JSON mode does not send every record to the browser or require a direct project dependency on TanStack. `oldman-web` declares the dependency and wraps it in its shared Table component.

This chapter follows the EPG demo's `/examples/tables/static`, `/examples/tables/html`, and `/examples/tables/json`. Complete [demo initialization](../users/getting-started.md), load fixtures, and sign in first. Both dynamic pages use the same ExampleProjectTable, data endpoint, filter form, and CRUD Modal. Only Table response/rendering formats differ.

## Backend definition

ExampleProjectTable in [apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py) inherits `oldman.web.components.tables.SQLAlchemyTableView`. This is an unchanged excerpt of class configuration. Retain column callback methods from the original file; the excerpt is not a complete class:

```python
    renderer_class = TailwindTableRenderer
    route_name = "example_projects_table"
    route_path = "/examples/tables/projects/table"
    model = ExampleProject
    page_size = 10
    selectable = True
    ordering = ("-updated_at",)
    search_fields = ("name", "slug", "description", "team.name")
    unsortable_columns = ("action",)
    empty_message = _("No example projects match these filters.")
    columns = (
        Column("id", _("ID")),
        Column("name", _("Project"), callback="get_column_name_data"),
        Column("team", _("Team"), field_path="team.name", callback="get_column_team_data"),
        Column("status", _("Status"), callback="get_column_status_data"),
        Column("priority", _("Priority"), callback="get_column_priority_data"),
        Column("progress", _("Progress"), callback="get_column_progress_data", type="number"),
        Column("budget", _("Budget"), callback="get_column_budget_data", type="number"),
        Column("updated_at", _("Updated"), callback="get_column_updated_at_data", type="date"),
        Column("action", _("Actions"), field_path=None, callback="get_column_action_data", exportable=False),
    )
```

Column and TailwindTableRenderer come from the same framework package. `_` is `oldman.i18n.gettext_lazy`, and ExampleProject comes from this App's models.py. Its actual query method preloads team for reuse by both display modes:

```python
    async def get_queryset(self):
        """Return projects with the team needed by both render paths."""
        return select(ExampleProject).options(selectinload(ExampleProject.team))
```

select comes from SQLAlchemy and selectinload from sqlalchemy.orm. Register the data endpoint in [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py):

```python
router.add_route(ExampleProjectTable.as_view(), ExampleProjectTable.route_path, name=ExampleProjectTable.route_name)
```

`router` comes from `oldman.web` and is used during this App's view loading. `as_view()` preserves base dispatch permission checks. Tables default to `require_authenticated=True`; the framework baseline is sign-in. Override `check_permission()` for checks requiring no data query (staff/role permissions), `check_auth(table_request)` for checks needing request parameters/database reads, and `apply_base_filters()` for visible-row scope; see [permission layers in data components](permissions.md#permission-layers-in-data-components). The demo's business tables require sign-in and share data among signed-in users. The example project table additionally requires role permission `examples.view_projects` in `check_permission` to demonstrate that layer. For tenant/user isolation, put fixed scope in get_queryset/apply_base_filters rather than user-editable filter parameters.

The same views/tables.py creates a request-scoped Table with this helper. FILTER_NAMES lists team_id, status, priority, and is_active in that file:

```python
def _project_table(request: Request) -> ExampleProjectTable:
    """Build the shared dynamic Table state from visible page query values."""
    return ExampleProjectTable(
        request=request,
        initial_filters={name: request.args.get(name, "").strip() for name in FILTER_NAMES},
        initial_query=request.args.get("q", "").strip(),
    )
```

Whole-page views create ExampleProjectFilterForm.from_query inside a read Session and render [dynamic.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/dynamic.html) before exiting, so asynchronous database choices remain readable. The following is a continuous template excerpt. The view supplies table_format according to the html/json page:

```jinja
      {{ filter_form.render(method="get", submit_label=_("Filter"), table_target="#example-projects-table") }}
      <div data-om-component="feedback"></div>
      {{ table.render_shell(
        html_id="example-projects-table",
        show_search=false,
        data_format=table_format,
      ) }}
```

Jinja enables asynchronous rendering, so templates do not write await explicitly. Both modes need the browser `table` loader, supplied through the application BasePage's Dashboard loaders in the demo; see [the frontend entry point](frontend.md#demo-dashboard-page-entry-point). The shell includes the data endpoint, pagination, and initial parameters. Only afterwards does the browser request actual data. An initial HTML shell does not prove database data has loaded.

## Query parameters and lifecycle

Parameters include `q`, `page`, `page_size`, `sort`, and `filter.<name>`. sort uses column names, prefixed with `-` for descending order. Response format prioritizes the `response_mode` query parameter, then Accept. Default page size is 20, with options 10/20/50/100 and a maximum of 100. Invalid pagination returns 400.

SQLAlchemyTableView queries and renders in one read Session, in this order:

1. `get_queryset()` and `loader_options`.
2. `apply_base_filters(query, table_request)`, then calculate the base total.
3. `filter_<name>(query, value, table_request)` and search, then calculate filtered_total.
4. Ordering and database limit/offset.
5. `build_row_contexts(rows)` prepares rendering context for the whole page (calling `preload_record_data(row)` per row by default; override it to fetch additional page-wide data in one query; pages and exports share this hook), then columns render.

Use `self.require_db_session()` for this request's Session. Do not store it globally across requests. Load relationships through `loader_options`, such as SQLAlchemy selectinload, rather than lazy-loading or repeating queries in every cell.

Alternatively, explicitly use `.options(...)` in get_queryset as the demo does above. The complete ExampleProjectTable.filter_status method follows. PROJECT_STATUSES is the original file's status allowlist. TableValidationError comes from `oldman.web.components.tables`; import `TableInvalidRequest` through that package entry point too:

```python
    async def filter_status(self, query, value: object, table_request):
        """Filter by a known project status."""
        status = str(value)
        if status not in PROJECT_STATUSES:
            raise TableValidationError("Invalid project status filter")
        return query.where(ExampleProject.status == status)
```

Page filter fields have ordinary names; Table data requests send parameters such as `filter.status`. The Table returns 422 for this filtering exception, unlike JSON Form's HTTP-200 business-error protocol. Invalid priority, team_id, and is_active also have explicit demo failure branches. Do not accept arbitrary expressions merely to demonstrate filtering.

Constructor parameters `initial_filters`, `initial_sort`, `initial_query`, `initial_page`, and `initial_page_size` set initial values. `sync_page_url=True` synchronizes pagination/filter state into the current page URL; it defaults to false.

`BaseTableView` suits existing small structured lists by overriding `get_object_list()`. It filters and paginates in Python memory rather than replacing database queries for large datasets.

## Column names, field paths, and display values

The demo columns above include ordinary fields, relationships, formatted fields, and virtual action columns. Simple columns can also be declared as field names directly.

- name is the stable browser column identifier; label is translatable display text only.
- An omitted field_path uses name. Explicit None creates a virtual column, without sorting/searching by default.
- callback names an ordinary or `async def` method. Otherwise, field columns look for `get_column_<field_path>_data`, replacing dots with underscores.
- `unsortable_columns` disables column sorting; `search_fields` explicitly lists searchable database fields.
- Callbacks receive row plus keyword arguments including column, field_path, default_value, row_context, row/column indexes, table, and request. Accept unused arguments through `**kwargs`.

Display callbacks can return an ordinary value or `(display_value, raw_value)`. Ordinary strings are HTML-escaped. Return Markup for trusted HTML, escaping user input first. Callbacks change display without automatically changing SQL ordering.

Use `async def` for callbacks that query the database or render fragments. SQLAlchemy tables query/render in the same read session, available through `self.require_db_session()`. Cells are calculated sequentially by row/column rather than concurrently, so sharing that session is safe. Below, `select`/`func` come from sqlalchemy and `badge` from `oldman.web.components.tables`:

```python
    async def get_column_programmes_data(self, row: Channel, **kwargs: object):
        count_query = select(func.count()).select_from(Programme).where(Programme.channel_id == row.id)
        count = (await self.require_db_session().execute(count_query)).scalar_one()
        return badge(str(count), tone="primary"), count
```

One query per cell means 50 queries for 50 rows. Fetch data needed by every row in `build_row_contexts()` once, then read `row_context` in callbacks. Callback queries suit small, on-demand cases. To include a Modal in a cell, likewise call `await render_modal(request, ...)` in an asynchronous callback; request is among its keyword arguments. See [the frontend Modal section](frontend.md#modal-is-only-a-container).

ExampleProjectTable's name column demonstrates this boundary. Markup and escape both come from markupsafe:

```python
    def get_column_name_data(self, row: ExampleProject, **kwargs: object):
        """Render the project name and stable slug."""
        return (
            Markup(
                f'<div class="font-medium text-default-900">{escape(row.name)}</div>'
                f'<code class="text-xs text-default-500">{escape(row.slug)}</code>'
            ),
            row.name,
        )
```

Relationship sorting needs particular care. For a single-column many-to-one `team` relationship without a more specific field_path, sorting uses the local foreign-key column, such as team_id. Only `field_path="team.name"` joins and sorts by team name. Composite or collection relationships require explicit scalar paths; the framework does not guess a sort value.

When search/sorting uses a relationship path such as `team.name`, `resolve_sql_field()` automatically adds a LEFT OUTER JOIN. It joins only to read that column; rows without related records remain listed (they cannot match that column and sort at one end). To also exclude them, call `resolve_sql_field(query, path, isouter=False)` in your `apply_search`/`apply_ordering`. There is no need to rewrite all search logic for an outer join.

## Cell primitives and filter parsing

Column callbacks return `(display, raw)`. Build display with primitives from `oldman.web.components.tables` rather than rewriting HTML in every project:

- `badge(label, tone="secondary")`: `om-badge`, with primary/secondary/success/info/warning/danger tones; other values fall back to neutral.
- `link(url, label)`: inline primary link; `muted(text)`: secondary text; `truncated(text, max_width=)`: truncated secondary text.
- `date_cell(value, date_format=, empty=)`: returns `(readable_text, ISO_raw_value)`. Empty values display `empty` (such as "Never") with an empty raw value; strings pass through unchanged.
- `row_actions([RowAction(label, href=… | modal_target=…, modal_url=…, icon=…, danger=…)], label=)`: row-action dropdown using shared markup for links and modal-opening buttons.

Filter parsing is shared too: `parse_boolean_filter(value)`, `parse_filter_datetime(value)` (converts aware input to naive UTC before comparison), and `parse_int_filter(value, label=, minimum=, maximum=)`. Invalid input raises `TableValidationError`, producing the Table's 422 validation response. Both built-in Admin user tables and demo business tables use these functions.

## Stable row and column DOM

Both HTML and JSON Tables emit `tr[data-om-table-row][data-om-table-row-id]`. Cells use `data-om-column`, `data-om-column-label`, and `data-raw-value`. Dynamic project-table IDs come from ExampleProject primary keys, and column names from Column.name above. Do not invent DOM numbers unrelated to backend records.

SQLAlchemyTableView defaults to the model's unique primary key; its name need not be id. Set `row_id_field="external_id"` for an existing field or override `get_row_id(row)`. Missing IDs and unhandled composite keys raise errors. Row numbers must not stand in for stable record identity. BaseTableView defaults to `row_id_field="id"`.

Column DOM uses Column.name rather than translated headings. For SSE partial updates, the business Page locates nodes by row ID/column name and updates dynamic values, without a new Table message bus. There is currently no public `updateCell()` API. Direct DOM edits change only current display, not JSON Table internal data; a new query rerenders server data. Persist changes to the database, and use [Table reload](frontend.md#table-operations) when the whole table needs synchronization.

The demo's `/examples/tables/realtime` combines handwritten HTML tables with a page-private RealtimeTable component, not a TanStack real-time plugin. [realtime.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/realtime.html) uses this unchanged row structure inside `for server, metric in metric_rows`:

```jinja
          <tr data-om-table-row data-om-table-row-id="{{ server.id }}">
            <td data-om-column="name"><strong>{{ server.name }}</strong><div class="text-xs text-default-500">{{ server.host }}</div></td>
            <td data-om-column="region">{{ server.region }}</td>
            <td data-om-column="sampled_at">{{ metric.sampled_at.strftime("%Y-%m-%d %H:%M:%S") }}</td>
            <td data-om-column="cpu_percent">{{ "{:.2f}%".format(metric.cpu_percent) }}</td>
            <td data-om-column="memory_percent">{{ "{:.2f}%".format(metric.memory_percent) }}</td>
            <td data-om-column="upload_mbps">{{ "{:.2f} Mbps".format(metric.upload_mbps) }}</td>
            <td data-om-column="download_mbps">{{ "{:.2f} Mbps".format(metric.download_mbps) }}</td>
          </tr>
```

server.id is used instead of metric.id because each row represents a server; successive samples change that row's values. Initial values and SSE batches come from the database. Connections replay existing batches without continuously adding records on every browser open. See [Real-time delivery guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md) for complete backend/browser wiring.

## Toolbar

The table shell renders an `om-table-toolbar` above the data area; inside `om-table-card`, it sits below the card header. Left to right are search (when `render_shell(show_search=True)`), selected-count text (when `selectable=True`), and bulk-action slots; tools sit on the right. On narrow screens, right-hand tools wrap to the next line while search retains its width. The table class declares tools through `toolbar`, defaulting to `("columns", "density", "export")`:

| Tool | Purpose | Notes |
| --- | --- | --- |
| `columns` | Dropdown checkboxes choose visible columns | Excludes `Column(hideable=False)` and the row-action column named `action` |
| `density` | Comfortable (44px rows) / compact (36px rows) | Stored on the root's `data-om-density`, retained through fragment refresh |
| `export` | Exports all matches with current search/filter/order | Appears only with declared `export_formats`; built-in `csv` |

Column visibility and density are stored locally by table `html_id` (`oldman:table:<id>`) and retained on the next visit. With `toolbar = ()` and no search, selection, or bulk actions, no toolbar is emitted. ModelAdmin forwards the same settings as `table_toolbar` and `export_formats`.

Export uses the same data endpoint. With `export_formats = ("csv",)`, the browser removes pagination parameters, adds `export=csv`, and starts a download. Backend `query_export()` applies the same filters, search, and order without pagination, capped by `max_export_rows` (default 10000). It writes only `Column(exportable=True)` columns. Numbers/booleans use raw values (booleans as `true`/`false`); other columns use displayed text, stripping tags and adding spaces between block tags. Columns returning raw text as `(markup, raw)` write raw directly. Empty display values fall back to raw. Text starting with `=`, `+`, `-`, `@`, Tab, or carriage return gets a leading apostrophe against spreadsheet-formula execution; purely numeric values such as negative numbers are unaffected. `export_filename(format)` chooses the filename (route name plus date by default). UTF-8 with BOM opens correctly in Excel. Permissions/scope retain `check_permission()`, `check_auth()`, and `get_queryset()`/`apply_base_filters()`. ModelAdmin enables CSV by default; disable it per model with `export_formats = ()`.

There are two empty states. With no records, the table shows `empty_message` and optional `empty_description`. With records all excluded by search/filters, it shows `empty_filtered_message` and `empty_filtered_description` plus a reset-filters button. The button clears the table's own search/initial filters and resets same-page filter forms targeting it through `data-om-table-target`; without a filter form, it reloads directly. JSON mode emits both states as `<template>` elements with the shell, selecting by `filtered_total < total` in the browser.

Pages provide their own bulk actions. `render_shell(bulk_actions_html=...)` places HTML in `data-om-table-bulk-actions`, visible only when rows are selected. Browser Table instances expose `selectedIds()` and `clearSelection()` and dispatch `om:table:selection` with `detail.ids` when selection changes. The framework has no built-in bulk deletion. Action submissions still need project endpoints and permission checks.

```jinja
{% set bulk_actions %}
  <button type="button" class="om-button om-button-secondary om-button-sm" data-archive-selected>{{ _("Archive") }}</button>
{% endset %}
{{ table.render_shell(html_id="projects-table", show_search=False, bulk_actions_html=bulk_actions) }}
```

## JSON data format

Successful responses have top-level columns, rows, pagination, and sort, without a DefaultApiResponse wrapper. In a signed-in browser, inspect `/examples/tables/projects/table?response_mode=json&page=1&page_size=10&sort=team` or the JSON page's Network panel for current real database results, rather than a fabricated fixed record.

| Field | Framework output and demo example |
| --- | --- |
| `columns[]` | name, label, type, sortable, searchable; names include id, name, team, etc. |
| `rows[].cells` | Display HTML keyed by column name; empty display may be null; name contains the name/slug HTML above |
| `rows[].raw_values` | Values without display-HTML wrappers; name is the project name, progress numeric, budget a decimal string in the demo |
| `rows[].data` | Stable id by default; ExampleProjectTable uses project primary keys |
| `pagination` | page, page_size, total, filtered_total, has_next; total is within fixed permission scope, filtered_total is after filtering |
| `sort` | Current sort value; `team` / `-team` sort by configured team.name ascending/descending |

cells contains display-renderer HTML. Do not infer raw_values from display content. Let the Table endpoint generate the complete structure rather than handcrafting an incomplete summary for the browser. Endpoint errors can still use non-2xx structured responses handled by Table itself; this differs from Form's HTTP-200 business-failure protocol.

## Operations and scope

Ordinary Forms and Modals handle creation/editing. Demo success emits feedback, closes the Modal, then runs `ReloadTableAction(target="#example-projects-table")`. Both Table modes share an ID, so save endpoints need not guess the page mode. Multiple Tables on one page need different IDs and explicit action targets. HTML Table format does not imply HTML Form responses inside Modals; CRUD Forms use JSON on both demo pages.

`selectable=True` only adds selection controls and toolbar counts. It neither implements bulk deletion nor authorizes arbitrary-ID operations; see [the toolbar](#toolbar) for bulk actions. Pagination/search/sorting do not replace backend access scope. The demo's `/examples/tables/advanced` explicitly displays missing features and does not establish implemented frozen columns or bulk actions.

Actually verify search, ascending/descending sorting, pagination, refresh after editing, empty data, and request failure in both HTML/JSON modes. Checking only initial shells or rows arrays is insufficient. Complete runnable wiring is in [Demo HTML/JSON tables and Modal forms](../users/tutorial-dashboard.md). These are developer verification steps, not a claim that this documentation change reran browser acceptance tests.

<!-- source: zh/developers/tables.md @ ee7652fb -->
