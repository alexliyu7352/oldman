# `oldman.web.components.charts`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

后端 Chart 组件封装入口。

Import with `from oldman.web.components.charts import <name>`.

## `BaseChartView`

class · defined in `oldman.web.components.charts.views`

```python
class BaseChartView(DataEndpointMixin, HTTPMethodView)
```

支持独立 endpoint 的无主题 Chart 基类。

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
- `def build_chart_request(request: Any, *, route_kwargs: dict[str, object]) -> ChartRequest` — 从 HTTP 请求构建标准 ChartRequest。
- `async def get(request: Any, **route_kwargs: object)` — 处理图表 data endpoint 请求。
- `async def check_auth(request: Any) -> bool` — 检查当前请求是否允许访问图表数据。
- `async def validate_filters(chart_request: ChartRequest) -> None` — 验证请求中的 filter 参数都由业务图表显式支持。
- `def validate_allowed_parameter(name: str, value: str, allowed: tuple[str, ...], *, default: str) -> None` — 按业务图表声明的白名单校验单个请求参数。
- `def render_error_response(message: str, *, status: int, error_code: ApiErrorCode=ApiErrorCode.INVALID_REQUEST)` — 把图表请求错误转换为统一 JSON 响应。
- `async def on_permission_denied(request: Any, response_mode: Literal['html', 'json'], *, message: str, method_name: str)` — endpoint 级权限失败复用 Chart JSON 错误协议。
- `def render_json_result(result: ChartResult)` — 渲染 ChartResult JSON 响应。
- `def get_renderer() -> ChartRenderer` — 返回当前图表 renderer 实例。
- `async def render_shell(*, html_id: str | None=None, **route_kwargs: object) -> Markup` — 异步渲染图表外壳和前端挂载属性。
- `async def get_result(chart_request: ChartRequest) -> ChartResult` — 返回当前图表结果，业务子类应重写。

## `ChartConfig`

class · defined in `oldman.web.components.charts.config`

```python
class ChartConfig
```

Chart 类属性和字段配置的标准对象。

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

图表可聚合字段声明。

Members:

- `key: str`
- `label: str`
- `expression: Any | None = None`

## `ChartInvalidRequest`

class · defined in `oldman.web.components.charts.exceptions`

```python
class ChartInvalidRequest(Exception)
```

图表请求参数非法。

## `ChartRenderer`

class · defined in `oldman.web.components.charts.renderers`

```python
class ChartRenderer
```

无主题 Chart renderer，负责把图表状态转换为模板上下文。

Constructor:

```python
ChartRenderer(chart: Any) -> None
```

Members:

- `def template_name(name: str) -> str` — 返回当前 renderer 使用的模板路径。
- `async def render_shell(*, route_kwargs: dict[str, object], html_id: str | None=None) -> Markup` — 渲染图表外壳和前端挂载属性。
- `def shell_attrs(route_kwargs: dict[str, object], *, html_id: str | None) -> dict[str, object]` — 生成图表外层容器属性。

## `ChartRequest`

class · defined in `oldman.web.components.charts.request`

```python
class ChartRequest
```

标准化后的图表请求状态。

Members:

- `request: Any`
- `range_key: str`
- `group_by: str`
- `chart_type: str`
- `metric: str`
- `filters: dict[str, object]`
- `route_kwargs: dict[str, object]`
- `def range_days() -> int` — `7d`、`30d` 这类 range key 对应的天数。
- `def range_start(*, end: dt.datetime | None=None) -> dt.datetime` — 当前窗口的起点，含今天：`end`（默认无时区 UTC 现在）往前 `range_days() - 1` 天的零点。

## `ChartResult`

class · defined in `oldman.web.components.charts.results`

```python
class ChartResult
```

图表查询结果，不是 HTTP 响应对象。

Members:

- `series: Sequence[ChartSeries] | Sequence[int | float]`
- `labels: Sequence[object] = field(default_factory=list)`
- `summary: Sequence[ChartSummary] = field(default_factory=list)`
- `meta: dict[str, object] = field(default_factory=dict)`
- `chart: dict[str, object] = field(default_factory=dict)`
- `options: dict[str, object] = field(default_factory=dict)`
- `def to_apex_options() -> dict[str, object]` — 转换为前端 ApexChart 组件可消费的 JSON 配置。

## `ChartSeries`

class · defined in `oldman.web.components.charts.results`

```python
class ChartSeries
```

ApexCharts series 数据。

Members:

- `name: str`
- `data: Sequence[object]`

## `ChartSummary`

class · defined in `oldman.web.components.charts.results`

```python
class ChartSummary
```

图表旁边的摘要项。

Members:

- `label: str`
- `value: object`
- `tone: str = 'secondary'`

## `SQLAlchemyChartView`

class · defined in `oldman.web.components.charts.sqlalchemy`

```python
class SQLAlchemyChartView(BaseChartView)
```

在同一个只读数据库 session 内完成图表查询的 adapter。

Members:

- `database_manager: DatabaseManager = default_db_manager`
- `db_session: AsyncSession | None = None`
- `async def get(request: Any, **route_kwargs: object)` — 在只读 session 生命周期内处理图表 data endpoint 请求。
- `def require_db_session() -> AsyncSession` — Return the request-scoped SQLAlchemy session.

## `TailwindChartRenderer`

class · defined in `oldman.web.components.charts.renderers`

```python
class TailwindChartRenderer(ChartRenderer)
```

Tailwind/Oldman 图表 renderer。
