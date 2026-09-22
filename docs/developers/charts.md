# Chart

Chart 组件由两半组成：一个返回 ApexCharts 配置的 **data endpoint**，和页面上一个只带挂载属性的 **外壳**。
后端不渲染图形，前端不写查询。

| 部分 | 谁负责 | 产出 |
| --- | --- | --- |
| data endpoint | `BaseChartView` 子类的 `get_result()` | `ChartResult` → `to_apex_options()` 的 JSON |
| 外壳 | `render_shell()` | 一个带 `data-om-component="apex-chart"` 和 `data-om-chart-src` 的容器 |
| 画图 | 浏览器里的 ApexCharts | 按 `data-om-chart-src` 取一次 JSON |

本章对照 EPG Demo 的 [apps/dashboard/chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/dashboard/chart_views.py)。

## 定义一个图表

```python
class DashboardProgrammeTrendChart(SQLAlchemyChartView):
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
        start_at = chart_request.range_start()
        ...
        return ChartResult(series=[ChartSeries(name="Programmes", data=data)], labels=labels)
```

路由自己注册，框架不扫描：

```python
app.add_route(DashboardProgrammeTrendChart.as_view(), DashboardProgrammeTrendChart.route_path, name=DashboardProgrammeTrendChart.route_name)
```

页面上把实例放进模板上下文，再在模板里 `await chart.render_shell()`；`build_data_url()` 用 `route_name` 走
`url_for`，拿不到 app 时回落到 `route_path`。

## 请求参数只认白名单

`build_chart_request()` 从 query 里读 `range`、`group_by`、`metric`、`chart_type`，以及所有 `filter.<名字>`；
`validate_filters()` 逐个对照类上的 `allowed_*`。**白名单为空表示"只允许对应的 default_*"**，不是"什么都允许"。
不在白名单里、或者没有对应 `filter_<名字>` 方法的筛选，抛 `ChartInvalidRequest`，由 `get()` 转成 400。
错误信息里只有参数名，不回显用户传进来的值。

`ChartRequest` 是这次请求的只读状态：

| 成员 | 含义 |
| --- | --- |
| `range_key` / `group_by` / `metric` / `chart_type` | 已经过白名单校验的请求参数 |
| `filters` | `filter.` 前缀去掉后的筛选值 |
| `route_kwargs` | 路由里的动态段 |
| `range_days()` | `7d`、`30d` 这类写法对应的天数；不是 `<天数>d` 就是接线错误，按非法请求处理 |
| `range_start(end=None)` | 含今天的窗口起点，**取整到零点** |

`range_start()` 取整到零点是必须的：图表按天分桶（`group_by(func.date(...))`），起点带着当前时分秒的话，
最早那一天只统计"此刻之后"的记录，折线图第一个点永远偏低，而且随刷新时间漂移。时间一律是 naive UTC
（`oldman.utils.date.naive_utcnow`），和数据库里存的时间同一口径。

## 结果对象

`ChartResult` 不是 HTTP 响应，它只描述图：`series`（`ChartSeries` 或裸数值序列）、`labels`、`summary`
（图旁边的几个数字，`ChartSummary(label, value, tone)`）、`chart`（ApexCharts 的 chart 段）、`options`
（其余 ApexCharts 选项）、`meta`（前端不画但要回显的东西，例如当前 range）。`to_apex_options()` 负责合并，
视图不用自己拼 JSON。

## 数据库

`SQLAlchemyChartView` 在**一个只读 session** 里跑完整个请求：`get()` 打开 session，`get_result()` 里用
`require_db_session()` 取用，请求结束即关闭。它不提供聚合 DSL——`select(...)` 怎么写就怎么写，图表只是
把结果排成 series 和 labels。多数据库的服务覆盖 `database_manager`。

## 权限

`require_authenticated` 和 `require_staff` 默认都是 True，走的是和其他视图同一套 `OldmanHTTPMethodView`
权限；拒绝时返回 403 的 JSON 错误协议，不跳登录页。需要更细的规则就覆盖 `check_auth()`。

## 不做的事

- 不做自动聚合、不猜时间列：分桶和排序都写在业务的 `get_result()` 里。
- 不把整张表送给浏览器：外壳只带一个 URL，数据由 data endpoint 决定。
- 不在前端拼查询：所有参数都要在类上显式列进白名单，前端只能在这些值里选。
