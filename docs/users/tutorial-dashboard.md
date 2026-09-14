# Demo 的 HTML/JSON 表格与 Modal 表单

先完成[运行 Demo](getting-started.md)和[真实数据准备](tutorial-tasks.md)。本章不再创建服务或替换源码，而是操作 EPG Demo 已存在的项目管理示例，并沿着实际文件理解整个链路。

打开：

- [HTML Data Table](http://127.0.0.1:17998/examples/tables/html)
- [JSON Data Table](http://127.0.0.1:17998/examples/tables/json)

两页都使用 `ExampleProject`、`ExampleProjectTable`、`ExampleProjectForm` 和同一组增删改接口。只有 Table 数据的传输与渲染格式不同；JSON Table 不是另一份数据库数据。

## 1. 先找到所有接线位置

以下路径都相对于 EPG Demo 根目录。源码节选保持真实类名、路由和 DOM ID；节选不是可脱离这些文件运行的独立程序。

| 职责 | 实际源码 |
| --- | --- |
| Session、CSRF、模板、通知和静态 bundle 初始化 | [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) |
| 登录、会话和页面访问限制 | [apps/auth/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/views.py)、[decorators.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/decorators.py) |
| 数据模型 | [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) |
| 筛选表单和编辑表单 | [apps/examples/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) |
| 两种格式共用的 Table | [apps/examples/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tables.py) |
| 页面、数据路由及 Modal CRUD | [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py) |
| 两页共用的 Jinja 模板 | [templates/pages/examples/tables/dynamic.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/tables/dynamic.html) |
| 全局浏览器启动和按需加载 Page | [frontend/src/main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) |
| 共享业务 Page 和示例 Page | [base-page.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/base-page.ts)、[examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) |

## 2. 登录和初始化不是表格自动提供的

配置模板已安装 `oldman.auth`、`oldman.apps.admin`、通知 App 和 Demo 业务 Apps，并启用 Session。Auth 的具体 User 是 `apps.auth.models.OldmanUser`。首次运行通过 `./run.sh web createsuperuser` 创建自己的账户。

这里的 Admin App 提供账户命令，**EPG 的管理界面不是通过 install_admin() 自动生成的站点**。`/users`、`/login` 等是 Demo 的业务视图；内置 Admin 站点另见[Admin 指南](admin.md)。

WebService 先执行框架初始化，再安装 StatelessCSRFManager、通知路由和模板帮助函数。Jinja 的 `_`、`gettext` 直接使用 `oldman.i18n.gettext`，不是只接受一个字符串的自制包装，因此表格摘要带参数、关闭翻译时也能正常渲染。

页面、Modal 和写接口使用 Demo 的 `@admin_required()`，检查已登录且为 staff；Table 数据通过 `ExampleProjectTable.as_view()` 进入框架的认证和权限分派。不能只保护展示页面而把数据接口裸露出去。

项目列表是 Demo 中 staff 共用的数据，不按当前用户或租户筛选。将代码用于私有业务数据时，必须同时限定列表查询及编辑/删除对象范围。

## 3. 一份 Table，两个渲染格式

`ExampleProjectTable` 的数据路由是 `/examples/tables/projects/table`。视图模块显式注册：

```python
app = get_app()
app.add_route(ExampleProjectTable.as_view(), ExampleProjectTable.route_path, name=ExampleProjectTable.route_name)
```

同一模块的 `_project_table(request)` 将页面查询中的 `q`、`team_id`、`status`、`priority`、`is_active` 作为初始状态传入。不要在前端再写一套独立筛选查询。

Table 的实际配置包括：

- 默认每页 10 条，默认排序 `("-updated_at",)`。
- 搜索 `name`、`slug`、`description`、`team.name`。
- 使用 `select(ExampleProject).options(selectinload(ExampleProject.team))` 取得数据。
- Team 列明确声明 `field_path="team.name"`，因此点击它按团队名称排序，不是按显示 HTML 或 relationship 对象排序。
- 操作列不可排序，负责输出打开编辑和删除 Modal 的按钮。

Team 列声明原文：

```python
        Column("team", _("Team"), field_path="team.name", callback="get_column_team_data"),
```

`callback` 决定显示值，`field_path` 决定数据库字段映射，两者不是同一个功能。想改排序规则就在 Table 声明中改，不从前端文本猜 SQL 字段。

动态模板中，筛选器和表格实际这样连接：

```jinja
      {{ filter_form.render(method="get", submit_label=_("Filter"), table_target="#example-projects-table") }}
      <div data-om-component="feedback"></div>
      {{ table.render_shell(
        html_id="example-projects-table",
        show_search=false,
        data_format=table_format,
      ) }}
```

视图根据 `/html` 或 `/json` 传入 `table_format`；`show_search=false` 是因为已有外部筛选表单，不再显示第二个搜索框。这个 Table 的稳定 DOM ID 是 `example-projects-table`，后面的 reload_table 动作使用同一目标。

## 4. Modal 只负责装入内容

动态模板从 `oldman/dashboard/components/modal.html` 导入共享 `modal` 宏。实际容器如下：

```jinja
  {% call modal(
    "example-project-modal",
    _("Example project"),
    component="modal",
    close_label=_("Close"),
    dialog_scrollable=true,
    inline_hidden_style=true,
    remote_content=true
  ) %}
    <p class="text-default-500 mb-0">{{ _("Choose create, edit or delete to load the real database Form.") }}</p>
  {% endcall %}
```

“New project”按钮的目标为 `#example-project-modal`，远程地址为 `/examples/tables/projects/new-modal`。行内编辑和删除按钮指向同一个容器，只改变远程 URL。

新建 Modal 的完整视图函数原文如下；其导入和 `app` 定义位于本章源码表所指的 views/tables.py，不需要另建请求客户端：

```python
@app.get("/examples/tables/projects/new-modal", name="example_project_create_modal")
@add_csrf_token()
@admin_required()
async def example_project_create_modal(request: Request):
    """Load a create Form into the shared remote Modal."""
    async with db_manager.get_read_session() as session:
        form = ExampleProjectForm(request=request, session=session)
        html = await form.render(
            action="/examples/tables/projects/create",
            form_mode="json",
            submit_label=_("Create project"),
            validate=True,
        )
    return json_response({"title": str(_("Create example project")), "html": str(html)})
```

这里有三个关键边界：

1. GET 生成 CSRF 令牌，并在活跃只读 Session 中渲染需要数据库团队选项的 Form。
2. 首次 Modal 请求返回 `title/html` JSON，由共享 Dashboard Modal 装入；这不是表单提交的 actions 响应。
3. 装入的表单仍是普通 Form 组件。Modal 不自己解析字段错误或实现第二套提交；新内容通过共享组件生命周期挂载。

编辑入口先用 `_project_or_404()` 读取真实记录，再通过 `instance=project` 构建相同的 Form。不存在的记录应返回 404，不偷偷变成新建表单。

## 5. 校验后再保存

新建的完整处理函数：

```python
@app.post("/examples/tables/projects/create", name="example_project_create")
@csrf_protect()
@admin_required()
async def example_project_create(request: Request):
    """Create one Project and reload the mounted HTML or JSON Table."""
    async with db_manager.get_session() as session:
        form = ExampleProjectForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return _project_saved_response(_("Project created."))
```

`ExampleProjectForm.Meta.fields` 是允许修改的字段白名单；请求不能借此任意更新模型字段。Form 沿用 WTForms 的字段和同步验证，并增加实际业务清理：

- `clean_slug()` 用当前 Session 检查重复 slug；编辑时排除当前实例。
- `clean()` 检查结束日期不能早于开始日期。此错误不是单个字段错误，显示在表单顶部 message 区域。
- Budget 和 Progress 分别有非负、0–100 的限制。
- Team 选项从数据库读取，不能把浏览器传来的文本当成任意合法外键。

JSON 校验失败是 HTTP 200 加业务错误码，不执行 save；字段错误由 Form 放在字段旁，整体错误放在专用 message 区域。数据库约束、连接失败等系统异常不能被包装成假成功。

`save(commit=True)` 在当前事务中 add/flush；退出上下文提交成功后，才执行下一段的成功响应构建。不要把浏览器收到 toast 当成数据库提交机制。

## 6. 成功后按顺序执行界面动作

实际的 `_project_saved_response()`：

```python
def _project_saved_response(message: str | LazyTranslation):
    """Close the Modal and refresh whichever render mode is mounted."""
    payload = DefaultApiFormResponse(
        error_code=ApiErrorCode.OK,
        message=message,
        actions=[
            FeedbackAction(title=message, icon="success"),
            CloseModalAction(),
            ReloadTableAction(target="#example-projects-table"),
        ],
    )
    return json_response(payload.to_dict())
```

这段代码在 views/tables.py 中从 `oldman.web.api` 导入这些动作和响应模型，从 `oldman.i18n` 导入 LazyTranslation。调用方传入当前请求的翻译文案，不是通知中心消息。

执行顺序就是列表顺序：提示成功、关闭发起请求的 Modal、刷新指定 Table。Form 先处理 message/errors，再交给当前 Page 的 Runner 执行动作；不要再监听提交成功事件做第二次刷新。

其中某个动作失败，后续动作停止；已经提交的数据库事务不会因为 UI 动作失败而撤销。用户离开页面，旧 Page 的请求和剩余 UI 工作放弃，不把它们搬到新页面继续执行。

编辑和删除成功也调用此函数，所以 HTML/JSON 两页采用相同的 UI 行为。删除前的普通确认 Form 位于 [delete_project.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/partials/examples/tables/delete_project.html)，包含 CSRF、message 和 status 区域。取消 Modal 不发出删除请求；确认后才通过 POST 删除数据库记录。

## 7. 不要混淆 HTML Table 与 HTML Form

本章两个 Table 页里的 Modal 都提交 JSON Form。**HTML Table 不代表其中的 Form 也必须使用 HTML 响应**。

要比较表单自身的两种返回方式，打开 [/examples/forms/basics](http://127.0.0.1:17998/examples/forms/basics)，分别操作 HTML response 和 JSON response actions 两张表单。其实际代码是 [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py)、[forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) 和 [forms/page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/page.html)。validation 页用于另外展示校验规则，当前只挂载 JSON 表单，不要在那里寻找第二张 HTML 表单。

`_form_error_response()` 根据客户端 Accept 返回 JSON 业务错误，或 HTTP 422 的错误表单 HTML。JSON Form 的响应和 HTML Form 的响应在前端适配到共同处理流程，不等于后端只剩 JSON。

| 场景 | 响应消费者 |
| --- | --- |
| 完整页面、登录页 | 浏览器/Turbo 页面导航 |
| Modal 首次 title/html JSON | Dashboard Modal |
| 表格数据 HTML 或 Table 专用 JSON | Table |
| JSON Form 的 message/errors/actions | Form 与 Page Runner |
| HTML Form 的 2xx/422 片段 | Form 的 HTML 响应适配 |
| 401、403、5xx 或网络失败 | 公共认证、权限和请求错误链路，不是业务成功 |

普通字段展示页只做校验和呈现，不都写数据库。真正的模型保存示例使用本章 CRUD、multi-step、JSON List 或上传页面；不要把“提交成功”文字解释为已经新增模型。

## 8. 页面脚本如何被加载和销毁

后端 `_page_context()` 传入 `page_entry="examples"`。模板继承链为：

`tables/dynamic.html → pages/examples/base.html → base.html → oldman/dashboard/base.html`。

项目 base.html 使用共享 `dashboard_main_frame()`；页面入口同时写入 body 和主 Frame。frontend/src/main.ts 的 `pageLoader` 根据这个名字导入 `pages/examples.ts`，该文件执行 `setupPage("examples", ExamplesPage)`。

ExamplesPage 继承项目 BasePage，BasePage 继承框架 DashboardPage，已经接入共享 Form、Modal、Table 和 Feedback loaders。实时表格等私有 loader 只在 ExamplesPage 声明，不放到全局。示例没有额外的 FormModal。

通过侧栏切页时，统一生命周期卸载旧 Page，替换主 Frame，再创建目标 Page。两个示例 URL 都用 ExamplesPage，也仍然是不同实例。只在当前页面装入 Modal 或替换表单片段，则只更新受影响的组件，不销毁整个 Page。

具体的取消、清理、主 Frame 和 Feedback 规则见[前端参考](../developers/frontend.md)。不能用“把所有组件注册到全局”解决某一页的入口没有加载。

## 9. 按真实操作验证

以下操作会修改 Demo 数据，只在自己的测试数据库执行。用自己创建的临时项目，不删除团队或预设业务记录。

1. 未登录直接打开 HTML/JSON 表格，应进入登录页。错误密码应有明确登录错误，正确密码进入页面。
2. 两页分别搜索项目名、筛选 Team/Status，翻页，再点击 Team 正反排序。Network 中数据格式不同，但数据来源相同。
3. 打开新建 Modal，填写一个唯一 slug；先让结束日期早于开始日期，提交应在顶部显示错误，不新增记录。再改正日期保存，应关闭 Modal、出现成功提示、刷新列表。
4. 编辑刚创建的项目，使用另一个已存在项目的 slug，提交应显示字段错误且保留原记录。改成合法值保存，重新打开检查数据。
5. 点删除先取消，记录应保留；再确认删除，两个表格重新查询后都不应再出现该行。
6. 从非示例页经侧栏进入，再在 HTML/JSON 示例间切换，重复打开和提交 Modal。直接刷新正常不能代替 Turbo 导航验证。
7. 在浏览器检查 Form 请求：JSON 校验失败应为 HTTP 200 的业务错误，而不是 422；在 basics 页的 HTML 表单另测 HTML 422。浏览器原生校验可能先拦截输入；需要查后端响应时使用开发工具观察实际请求，不能把未发请求误认作后端返回。
8. 在自己的独立服务上模拟请求失败，确认页面导航结束遮罩并显示错误，旧页面可继续使用；不要为验证而关闭别人正在使用的 Demo。
9. 刷新、重启自己的服务后再次查询；持久化以数据库和新查询结果为准，不以 toast 为准。

客户端必填校验可能在请求发送前阻止提交。要验证后端业务校验，可用重复 slug 或日期倒置，不必关闭浏览器安全设置。分页需有超过 10 条符合筛选的数据；过滤到一条结果时无法声称已验证多页。

下一步从 [Demo 示例索引](demo-examples.md)选择文件、实时数据、动态输入或 UI 页面。高级表格的明确缺口不能因页面存在就当成已实现。
