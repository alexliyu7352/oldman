# Chart

The Chart component has two parts: a **data endpoint** returning ApexCharts options and a **shell** containing only mounting attributes.
The backend does not draw charts, and the browser does not build queries.

| Part | Owner | Output |
| --- | --- | --- |
| Data endpoint | `get_result()` on a `BaseChartView` subclass | `ChartResult` → JSON from `to_apex_options()` |
| Shell | `render_shell()` | A container with `data-om-component="apex-chart"` and `data-om-chart-src` |
| Drawing | ApexCharts in the browser | Fetches JSON once from `data-om-chart-src` |

This chapter follows the EPG demo's [apps/dashboard/chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/dashboard/chart_views.py).

## Defining a chart

```python
class DashboardProgrammeTrendChart(SQLAlchemyChartView):
    """Data endpoint for the home page's programme-count trend chart."""

    renderer_class = TailwindChartRenderer
    route_name = "dashboard_programme_trend_chart"
    route_path = "/dashboard/charts/programme-trend"
    chart_type = "line"
    default_range = "30d"
    default_metric = "programmes"
    allowed_ranges = ("7d", "30d", "90d")
    allowed_metrics = ("programmes",)
    allowed_chart_types = ("line",)

    async def get_result(self, chart_request):
        """Aggregate programme counts by date and return ApexCharts options."""
        start_at = chart_request.range_start()
        date_expr = func.date(EpgList.start_date)
        result = await self.require_db_session().execute(
            select(date_expr.label("day"), func.count(EpgList.id).label("total"))
            .where(EpgList.start_date >= start_at)
            .group_by(date_expr)
            .order_by(date_expr.asc())
        )
        rows = result.all()
        labels = [str(row.day) for row in rows]
        data = [int(row.total or 0) for row in rows]
        total = sum(data)
        return ChartResult(
            series=[ChartSeries(name=_("Programmes"), data=data)] if data else [],
            labels=labels,
            summary=[ChartSummary(label=_("Total Programmes"), value=total, tone="primary")],
            meta=chart_caption(chart_request, _("Programmes")),
            chart={"type": "line", "height": 320, "toolbar": {"show": False}},
        )
```

Register routes yourself; the framework does not scan for them (`router` comes from `oldman.web`):

```python
router.add_route(DashboardProgrammeTrendChart.as_view(), DashboardProgrammeTrendChart.route_path, name=DashboardProgrammeTrendChart.route_name)
```

Put the instance in the page's template context, then call `await chart.render_shell()` in the template. `build_data_url()` uses `route_name` with
`url_for`, falling back to `route_path` when no app is available.

## Request parameters use allowlists only

`build_chart_request()` reads `range`, `group_by`, `metric`, `chart_type`, and all `filter.<name>` parameters from the query.
`validate_filters()` checks each against class `allowed_*` values. **An empty allowlist permits only the corresponding `default_*` value**, rather than every value.
Values outside the allowlist, or filters without a corresponding `filter_<name>` method, raise `ChartInvalidRequest`, converted to 400 by `get()`.
Errors include parameter names only, without echoing submitted values.

`ChartRequest` is read-only state for this request:

| Member | Meaning |
| --- | --- |
| `range_key` / `group_by` / `metric` / `chart_type` | Request parameters already validated against allowlists |
| `filters` | Filter values with the `filter.` prefix removed |
| `route_kwargs` | Dynamic route segments |
| `range_days()` | Number of days represented by `7d`, `30d`, etc.; anything outside `<days>d` is a wiring error treated as an invalid request |
| `range_start(end=None)` | Window start including today, **rounded down to midnight** |

Rounding `range_start()` down to midnight is necessary because charts bucket by day (`group_by(func.date(...))`). Keeping the current time would
count only later records on the earliest day, making the first point consistently low and dependent on refresh time. All times use naive UTC
(`oldman.utils.date.naive_utcnow`), matching database storage.

## Result objects

`ChartResult` is not an HTTP response; it describes the chart through `series` (`ChartSeries` or raw numeric sequences), `labels`, `summary`
(adjacent numbers represented by `ChartSummary(label, value, tone)`), `chart` (ApexCharts chart settings), `options`
(other ApexCharts options), and `meta` (not plotted, but displayed unchanged below as key/value notes such as the current range; both keys and values are user-facing, so translate them rather than using identifiers such as `range`). `to_apex_options()` merges these;
views need not build JSON themselves.

## Database

`SQLAlchemyChartView` handles the complete request in **one read session**. `get()` opens it, `get_result()` accesses it with
`require_db_session()`, and request completion closes it. There is no aggregation DSL: write ordinary `select(...)` queries, and the chart
arranges results into series/labels. Multi-database services override `database_manager`.

## Permissions

`require_authenticated` defaults to True: the framework baseline is sign-in. Put rules needing no data query (staff/role permissions) in `check_permission()`, using the same `oldman.web.HTTPMethodView`
permission mechanism as other views. Rejection returns the JSON error protocol with 403 rather than redirecting to sign-in. Override `check_auth(chart_request)` for rules needing parameters/database reads; it runs after parameter validation. See [Permissions](permissions.md#permission-layers-in-data-components) for the division of responsibilities.

## What charts do not do

- No automatic aggregation or guessed time columns: business `get_result()` defines bucketing and ordering.
- No entire-table transfer to the browser: the shell carries only a URL, and the data endpoint chooses its output.
- No browser-built queries: class allowlists explicitly enumerate all parameters, and the browser selects only among them.

<!-- source: zh/developers/charts.md @ d2d7dd40 -->
