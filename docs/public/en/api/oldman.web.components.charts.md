# `oldman.web.components.charts`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Backend Chart component entry point.

Import with `from oldman.web.components.charts import <name>`.

## `BaseChartView`

class · defined in `oldman.web.components.charts.views`

```python
class BaseChartView(DataEndpointMixin, HTTPMethodView)
```

Unthemed Chart base supporting a standalone endpoint.

Constructor:

```python
BaseChartView(request: Any | None=None) -> None
```

Members:

- `route_name: str = ''`
- `route_path: str = ''`
- `chart_type: str = 'line'`
- `default_range: str = '30d'`
- `default_group_by: str = ''`
- `default_metric: str = ''`
- `allowed_ranges: tuple[str, ...] = ()`
- `allowed_group_by: tuple[str, ...] = ()`
- `allowed_metrics: tuple[str, ...] = ()`
- `allowed_chart_types: tuple[str, ...] = ()`
- `def build_chart_request(request: Any, *, route_kwargs: dict[str, object]) -> ChartRequest` — Build a standard ChartRequest from an HTTP request.
- `async def get(request: Any, **route_kwargs: object)` — Handle a chart data-endpoint request.
- `async def check_auth(chart_request: ChartRequest) -> bool` — Check request- or database-dependent access, allowing by default and returning 403 on denial.
- `async def validate_filters(chart_request: ChartRequest) -> None` — Validate that the business chart explicitly supports every requested filter.
- `def validate_allowed_parameter(name: str, value: str, allowed: tuple[str, ...], *, default: str) -> None` — Validate one request parameter against the business chart's allowlist.
- `def render_error_response(message: str, *, status: int, error_code: ApiErrorCode=ApiErrorCode.INVALID_REQUEST)` — Convert chart request errors to common JSON responses.
- `async def on_permission_denied(request: Any, response_mode: Literal['html', 'json'], *, message: str, method_name: str)` — Use the Chart JSON error protocol for endpoint-level permission denial.
- `def render_json_result(result: ChartResult)` — Render a ChartResult JSON response.
- `def get_renderer() -> ChartRenderer` — Return the current chart renderer instance.
- `async def render_shell(*, html_id: str | None=None, **route_kwargs: object) -> Markup` — Render the chart shell and browser mounting attributes asynchronously.
- `async def get_result(chart_request: ChartRequest) -> ChartResult` — Return the current chart result, to be overridden by business subclasses.

## `ChartConfig`

class · defined in `oldman.web.components.charts.config`

```python
class ChartConfig
```

Standard chart class-attribute and field configuration.

Members:

- `chart_type: str = 'line'`
- `default_range: str = '30d'`
- `default_group_by: str = ''`
- `default_metric: str = ''`
- `fields: tuple[ChartField, ...] = field(default_factory=tuple)`

## `ChartField`

class · defined in `oldman.web.components.charts.config`

```python
class ChartField
```

Declaration of an aggregatable chart field.

Members:

- `key: str`
- `label: str`
- `expression: Any | None = None`

## `ChartInvalidRequest`

class · defined in `oldman.web.components.charts.exceptions`

```python
class ChartInvalidRequest(Exception)
```

Invalid chart request parameters.

## `ChartRenderer`

class · defined in `oldman.web.components.charts.renderers`

```python
class ChartRenderer
```

Unthemed Chart renderer converting chart state into template context.

Constructor:

```python
ChartRenderer(chart: Any) -> None
```

Members:

- `def template_name(name: str) -> str` — Return the current renderer's template path.
- `async def render_shell(*, route_kwargs: dict[str, object], html_id: str | None=None) -> Markup` — Render the chart shell and browser mounting attributes.
- `def shell_attrs(route_kwargs: dict[str, object], *, html_id: str | None) -> dict[str, object]` — Build outer chart-container attributes.

## `ChartRequest`

class · defined in `oldman.web.components.charts.request`

```python
class ChartRequest
```

Normalized chart request state.

Members:

- `request: Any`
- `range_key: str`
- `group_by: str`
- `chart_type: str`
- `metric: str`
- `filters: dict[str, object]`
- `route_kwargs: dict[str, object]`
- `def range_days() -> int` — Return the day count represented by range keys such as 7d or 30d.
- `def range_start(*, end: dt.datetime | None=None) -> dt.datetime` — Return midnight at the start of a window including today, range_days() - 1 days before end (default naive UTC now).

## `ChartResult`

class · defined in `oldman.web.components.charts.results`

```python
class ChartResult
```

Chart query results, not an HTTP response.

Members:

- `series: Sequence[ChartSeries] | Sequence[int | float]`
- `labels: Sequence[object] = field(default_factory=list)`
- `summary: Sequence[ChartSummary] = field(default_factory=list)`
- `meta: dict[str, object] = field(default_factory=dict)`
- `chart: dict[str, object] = field(default_factory=dict)`
- `options: dict[str, object] = field(default_factory=dict)`
- `def to_apex_options() -> dict[str, object]` — Convert to JSON options consumed by the browser ApexChart component.

## `ChartSeries`

class · defined in `oldman.web.components.charts.results`

```python
class ChartSeries
```

ApexCharts series data.

Members:

- `name: str`
- `data: Sequence[object]`

## `ChartSummary`

class · defined in `oldman.web.components.charts.results`

```python
class ChartSummary
```

A summary item beside the chart.

Members:

- `label: str`
- `value: object`
- `tone: str = 'secondary'`

## `SQLAlchemyChartView`

class · defined in `oldman.web.components.charts.sqlalchemy`

```python
class SQLAlchemyChartView(BaseChartView)
```

Adapter running chart queries within one read-only database session.

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `db_session: AsyncSession | None = None`
- `async def get(request: Any, **route_kwargs: object)` — Handle chart data-endpoint requests within a read-only session lifecycle.
- `def require_db_session() -> AsyncSession` — Return the request-scoped SQLAlchemy session.

## `TailwindChartRenderer`

class · defined in `oldman.web.components.charts.renderers`

```python
class TailwindChartRenderer(ChartRenderer)
```

Tailwind/Oldman chart renderer.
