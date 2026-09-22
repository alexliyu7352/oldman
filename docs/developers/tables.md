# 静态、HTML 与 JSON Table

三种方式服务不同场景，不需要三个后端业务实现。

| 方式 | 适用场景 | 数据在哪里处理 |
| --- | --- | --- |
| 静态 HTML table | 已经知道的小列表或说明表 | 业务视图/模板一次渲染，不自动分页 |
| HTML Table | 服务端渲染的动态表格 | SQL 查询分页；前端替换 Table 片段 |
| JSON Table | 同一后端数据以 JSON 驱动前端表格 | SQL 查询分页；前端使用 TanStack Table Core 组织行列 |

JSON 模式不是把全部记录送到浏览器，也不要求项目直接依赖 TanStack。`oldman-web` 已声明依赖并封装在共享 Table 组件中。

本章直接对照 EPG Demo：`/examples/tables/static`、`/examples/tables/html`、`/examples/tables/json`。先完成[Demo 初始化](../users/getting-started.md)，加载 fixture 并登录 staff 账号。动态两页使用同一个 ExampleProjectTable、数据接口、筛选表单和 CRUD Modal；区别只在 Table 的响应与渲染格式。

## 后端定义

[apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py) 中 ExampleProjectTable 继承 `oldman.web.components.tables.SQLAlchemyTableView`。以下是类内配置的原样节选，列回调仍需保留原文件中的方法，不能把节选当成完整类：

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

Column、TailwindTableRenderer 从同一框架包导入，`_` 为 `oldman.i18n.gettext_lazy`，ExampleProject 来自该 App 的 models.py。类内的真实查询方法同时预加载 team，供两种显示模式复用：

```python
    async def get_queryset(self):
        """Return projects with the team needed by both render paths."""
        return select(ExampleProject).options(selectinload(ExampleProject.team))
```

select 来自 SQLAlchemy，selectinload 来自 sqlalchemy.orm。在 [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py) 注册数据接口：

```python
app = get_app()
app.add_route(ExampleProjectTable.as_view(), ExampleProjectTable.route_path, name=ExampleProjectTable.route_name)
```

get_app 来自 `oldman.web.routing`，在当前 App 的视图加载阶段使用。`as_view()` 保留基类 dispatch 的权限检查；Table 默认 `require_authenticated=True`、`require_staff=True`，Demo 的 check_auth 另外检查登录 Session，并不取消基类 staff 检查。Demo 是 staff 共用数据；需要租户/用户隔离的业务，固定查询范围放在 get_queryset/apply_base_filters，不能依赖用户可修改的 filter 参数。

同一个 views/tables.py 用以下辅助函数创建请求级 Table，FILTER_NAMES 是该文件列出的 team_id、status、priority、is_active：

```python
def _project_table(request: Request) -> ExampleProjectTable:
    """Build the shared dynamic Table state from visible page query values."""
    return ExampleProjectTable(
        request=request,
        initial_filters={name: request.args.get(name, "").strip() for name in FILTER_NAMES},
        initial_query=request.args.get("q", "").strip(),
    )
```

完整页视图在只读 Session 内创建 ExampleProjectFilterForm.from_query，并在退出 Session 前渲染 [dynamic.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/dynamic.html)，确保异步数据库选项仍能读取。下面是模板内连续的节选，table_format 由视图根据 html/json 页面传入：

```jinja
      {{ filter_form.render(method="get", submit_label=_("Filter"), table_target="#example-projects-table") }}
      <div data-om-component="feedback"></div>
      {{ table.render_shell(
        html_id="example-projects-table",
        show_search=false,
        data_format=table_format,
      ) }}
```

Jinja 环境开启异步渲染，所以模板不手写 await。两种模式都需要前端 `table` loader，Demo 通过应用 BasePage 的 Dashboard loaders 获得它，见[前端入口](frontend.md#demo-的-dashboard-页面入口)。shell 带 data endpoint、分页和初始参数；浏览器随后才请求实际数据。HTML 初始骨架不能当作数据库已加载的证明。

## 查询参数和生命周期

参数包括 `q`、`page`、`page_size`、`sort`、`filter.<name>`。sort 用列名，降序前缀 `-`；响应模式由 `response_mode` 查询参数优先，再看 Accept。分页默认 20，选项 10/20/50/100，最大 100；非法分页返回 400。

SQLAlchemyTableView 在一个只读 Session 内查询和渲染，顺序为：

1. `get_queryset()` 和 `loader_options`。
2. `apply_base_filters(query, table_request)`，然后计算基础 total。
3. `filter_<name>(query, value, table_request)` 及搜索，计算 filtered_total。
4. 排序和数据库 limit/offset。
5. `build_row_contexts(rows)` 为整页行准备渲染上下文（默认逐行调用 `preload_record_data(row)`；要一次查询补齐整页数据就重写它，页面和导出共用同一个钩子），再渲染各列。

使用 `self.require_db_session()` 取得该请求的 Session；不能把它放成跨请求全局变量。需要关联显示时用 `loader_options`，例如 SQLAlchemy selectinload，避免在每个单元格里惰性加载关系或重复查询。

也可以像上面的 Demo 一样在 get_queryset 中显式 `.options(...)`。ExampleProjectTable.filter_status 的完整方法如下；PROJECT_STATUSES 是原文件的状态白名单，TableValidationError 来自 `oldman.web.components.tables`（`TableInvalidRequest` 同样从包入口导入）：

```python
    async def filter_status(self, query, value: object, table_request):
        """Filter by a known project status."""
        status = str(value)
        if status not in PROJECT_STATUSES:
            raise TableValidationError("Invalid project status filter")
        return query.where(ExampleProject.status == status)
```

页面筛选字段用普通名称，Table 数据请求发送 `filter.status` 等参数。这个筛选异常由 Table 返回 422；它不是 JSON Form 的 HTTP 200 业务错误协议。Demo 的非法 priority、team_id、is_active 也有明确失败分支，不能为了演示过滤直接接受任意表达式。

初值可通过构造参数 `initial_filters`、`initial_sort`、`initial_query`、`initial_page`、`initial_page_size` 设置。`sync_page_url=True` 让 Table 把分页、筛选等状态同步到当前页面 URL，默认关闭。

`BaseTableView` 则适合已有结构化小列表，覆盖 `get_object_list()`；它在 Python 内存执行筛选和分页，不是大数据集的数据库替代品。

## 列名、字段路径和显示值

上面的 Demo columns 已同时包含普通字段、关联字段、格式化字段和虚拟操作列。简单列也可直接写字段名。

- name 是稳定的前端列名；label 只负责展示，可翻译。
- 未指定 field_path 时使用 name；指定 None 表示虚拟列，默认不排序/搜索。
- callback 可指定同步方法；否则字段列查找 `get_column_<字段路径>_data`，点号变下划线。
- `unsortable_columns` 关闭列排序；`search_fields` 是明确的数据库字段搜索清单。
- 回调会收到 row 以及 column、field_path、default_value、row_context、行列序号、table、request 等关键字参数；不需要的参数可用 `**kwargs` 接受。

显示回调可以返回普通值，或 `(显示值, raw_value)`。普通字符串会 HTML 转义；可信 HTML 返回 Markup，用户输入先转义。回调只改显示，不自动改变 SQL 排序规则。

ExampleProjectTable 中的名称列正好展示了这个边界。Markup、escape 均来自 markupsafe：

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

关系排序尤其需要区分：若 `team` 是单列 many-to-one 关系且没设置更具体的 field_path，按其本地外键列（如 team_id）排序；只有 `field_path="team.name"` 才 join 后按团队名称排序。多列或集合关系需要显式标量路径，不能猜一个值替用户排序。

搜索或排序用到 `team.name` 这种跨关系路径时，`resolve_sql_field()` 自动补的是 LEFT OUTER JOIN：JOIN 只为读那一列，没有关联记录的行仍然留在列表里（它匹配不到这一列，排序时排在一端）。想让 JOIN 顺带过滤掉这些行，在自己的 `apply_search`/`apply_ordering` 里调用 `resolve_sql_field(query, path, isouter=False)`；不需要为了外连接重写整段搜索。

## 单元格原语与筛选解析

列回调返回 `(display, raw)`；display 半边用 `oldman.web.components.tables` 里的原语拼，不在每个项目里重写 HTML：

- `badge(label, tone="secondary")`：`om-badge`，tone 取 primary/secondary/success/info/warning/danger，其它值回退为中性色。
- `link(url, label)`：行内主链接；`muted(text)`：次要文字；`truncated(text, max_width=)`：截断的次要文字。
- `date_cell(value, date_format=, empty=)`：返回 `(可读文本, ISO 原值)`，空值显示 `empty`（如 "Never"）并给空 raw；字符串原样透传。
- `row_actions([RowAction(label, href=… | modal_target=…, modal_url=…, icon=…, danger=…)], label=)`：行操作下拉，链接项和打开 modal 的按钮项共用一套标记。

筛选值解析同样共享：`parse_boolean_filter(value)`、`parse_filter_datetime(value)`（带时区的输入先转成 naive UTC 再比较）、`parse_int_filter(value, label=, minimum=, maximum=)`，非法输入统一抛 `TableValidationError`，进入表格的 422 校验错误。内置 Admin 的用户表与 Demo 的业务表格都用这些函数。

## 稳定行与列 DOM

HTML 和 JSON Table 模式都输出 `tr[data-om-table-row][data-om-table-row-id]`，单元格使用 `data-om-column`、`data-om-column-label` 和 `data-raw-value`。动态项目表格的 ID 来自 ExampleProject 的主键，列名来自前面的 Column.name；不要另造与后端记录无关的 DOM 编号。

SQLAlchemyTableView 默认取模型唯一主键；不是必须叫 id。可用 `row_id_field="external_id"` 指定已有字段，或覆盖 `get_row_id(row)`。缺失 ID、复合主键未明确处理时会报错，不能用行号充当稳定记录身份。BaseTableView 默认 `row_id_field="id"`。

列 DOM 使用 Column.name，而不是翻译后的表头。用于 SSE 局部更新时，业务 Page 依据行 ID 和列名找到节点，只更新动态值；不必为此创造一套 Table 消息总线。当前没有公开的 `updateCell()` API。直接修改 DOM 只改变当前显示，不修改 JSON Table 的内部数据；重新查询会以服务端数据重新渲染。需要持续保存的变化写数据库，需要整表同步时使用[Table 的 reload](frontend.md#table-操作)。

Demo `/examples/tables/realtime` 是手写 HTML table 配合页面私有 RealtimeTable 组件，不是 TanStack 实时插件。[realtime.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/realtime.html) 在 `for server, metric in metric_rows` 循环内使用以下原样行结构：

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

这里用 server.id 而不是 metric.id，是因为一行代表一台服务器，连续采样只更改这一行的数值。初值和 SSE 批次来自数据库，连接只回放已有批次，不因每次打开浏览器持续增加记录。完整后端、前端接线见[实时界面示例](../agents/realtime.md)。

## 工具条

表格外壳在数据区上方输出一条工具条（`om-table-toolbar`），放在 `om-table-card` 里时贴在卡片头下面。左侧依次是搜索框（`render_shell(show_search=True)` 时）、"已选 N 项"计数（`selectable=True` 时）和批量动作槽；右侧是工具按钮。工具由表格类的 `toolbar` 声明，默认 `("columns", "density", "export")`：

| 工具 | 作用 | 备注 |
| --- | --- | --- |
| `columns` | 下拉菜单勾选显示哪些列 | `Column(hideable=False)` 的列和名为 `action` 的行操作列不进菜单 |
| `density` | 舒适（44px 行）/ 紧凑（36px 行）切换 | 写在组件根的 `data-om-density` 上，刷新片段不丢 |
| `export` | 按当前搜索、筛选和排序导出全部匹配行 | 只有声明了 `export_formats` 才出现；内置 `csv` |

列显隐和密度按表格的 `html_id` 记在浏览器本地（`oldman:table:<id>`），同一张表下次打开保持。`toolbar = ()` 且没有搜索、选择和批量动作时不输出工具条。ModelAdmin 通过同名的 `table_toolbar` 和 `export_formats` 透传。

导出走同一个数据接口：`export_formats = ("csv",)` 后，前端把当前请求参数去掉分页、加上 `export=csv` 发起下载，后端 `query_export()` 跑同一套筛选、搜索、排序但不分页，行数上限 `max_export_rows`（默认 10000），只写 `Column(exportable=True)` 的列：数字和布尔写 raw value（布尔为 `true`/`false`），其余列写用户看到的文本（去掉标签，块级标签之间补空格；回调以 `(markup, raw)` 形式给出 raw 文本的列直接写 raw），显示为空时才回退到 raw value；以 `=`、`+`、`-`、`@`、Tab 或回车开头的文本前面会加一个单引号，防止 Excel 把用户输入当公式执行（负数等纯数字不受影响）。文件名由 `export_filename(format)` 决定（默认路由名加日期），UTF-8 带 BOM，Excel 直接打开不乱码。权限与数据范围沿用 `check_auth()` 和 `get_queryset()`/`apply_base_filters()`；ModelAdmin 默认开启 CSV，不需要的模型设 `export_formats = ()`。

表内空状态有两种：没有任何记录时显示 `empty_message`（可加 `empty_description`），有记录但被搜索或筛选全部挡掉时显示 `empty_filtered_message` 和 `empty_filtered_description`，并带一个“重置筛选”按钮，它清掉表格自己的搜索和初始筛选，再触发同一页面里 `data-om-table-target` 指向本表的筛选表单的重置（没有筛选表单时直接重新加载）。JSON 模式的两种空状态随外壳以 `<template>` 输出，浏览器端按 `filtered_total < total` 选用。

批量动作由页面自己提供：`render_shell(bulk_actions_html=...)` 接收一段 HTML，放进 `data-om-table-bulk-actions` 容器，只在有选中行时显示。前端 Table 实例提供 `selectedIds()` 和 `clearSelection()`，并在选中集合变化时派发 `om:table:selection` 事件（`detail.ids`）。框架不内置批量删除，动作提交仍要走项目自己的接口和权限检查。

```jinja
{% set bulk_actions %}
  <button type="button" class="om-button om-button-secondary om-button-sm" data-archive-selected>{{ _("Archive") }}</button>
{% endset %}
{{ table.render_shell(html_id="projects-table", show_search=False, bulk_actions_html=bulk_actions) }}
```

## JSON 数据格式

成功返回值顶层是 columns、rows、pagination、sort，不套 DefaultApiResponse。在已登录的浏览器里查看 `/examples/tables/projects/table?response_mode=json&page=1&page_size=10&sort=team`，或打开 JSON 页的 Network 面板，即可看到当前真实数据库结果；不是文档编造的固定一条记录。

| 字段 | 框架输出内容与 Demo 对照 |
| --- | --- |
| `columns[]` | name、label、type、sortable、searchable；name 包含 id、name、team 等 |
| `rows[].cells` | 按列名保存显示 HTML，空显示值可为 null；name 列为上面的名称和 slug HTML |
| `rows[].raw_values` | 未包裹显示 HTML 的值；name 是项目名，progress 是数值，budget 在 Demo 中是十进制字符串 |
| `rows[].data` | 默认含稳定 id；ExampleProjectTable 使用项目主键 |
| `pagination` | page、page_size、total、filtered_total、has_next；total 为固定权限范围内总数，filtered_total 为筛选后总数 |
| `sort` | 当前排序值；`team` 与 `-team` 分别按配置的 team.name 正反排序 |

cells 是经显示渲染器编码的 HTML；raw_values 不应从显示内容反推。让 Table endpoint 生成完整结构，不手工拼一个省略字段的摘要供前端使用。接口错误仍可使用非 2xx 的结构化错误，Table 自己处理；不要把它混同于表单 HTTP 200 业务失败协议。

## 操作与范围

创建/编辑由普通 Form 和 Modal 处理，Demo 成功后依次反馈、关闭 Modal、`ReloadTableAction(target="#example-projects-table")`。两种 Table 共享相同 ID，因此不需要让保存接口猜页面使用哪种模式；同页放两张 Table 时应使用不同 ID，并明确动作目标。Table 格式为 HTML 不表示 Modal 中的 Form 也用 HTML 响应，本 Demo 两页的 CRUD Form 都用 JSON。

`selectable=True` 只增加选择控件和工具条上的选中计数，不自动实现批量删除，也不授权任意 ID 操作；批量动作见[工具条](#工具条)。分页、搜索、排序不能代替后端访问范围。Demo 的 `/examples/tables/advanced` 是明确缺口的展示页，不能当作已实现固定列或批量动作。

HTML 和 JSON 两种模式都应实际验证搜索、正反排序、分页、编辑后刷新、空数据和请求失败；只检查 initial shell 或 rows 数组不够。完整可运行接线在[项目 Table 教程](../users/tutorial-dashboard.md)。这些是开发者复核步骤，不代表本次文档修改重新运行了浏览器验收。
