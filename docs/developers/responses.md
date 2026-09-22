# 浏览器响应与有序动作

本协议服务于已经启动 Oldman Page 的浏览器，不要求纯数据 API 执行 UI 动作。页面与对象来源见[前端运行时](frontend.md)。

可运行示例位于 EPG Demo 的 `/examples/modals/actions` 和 `/examples/modals/workflows`，项目保存链在 `/examples/tables/html`、`/examples/tables/json`。先按[入门步骤](../users/getting-started.md)准备数据和登录；不要只复制下面的函数，而漏掉 Demo 的 App、Page、组件和权限接线。

## 后端类型

公开响应模型、Action 子类，以及 ApiErrorCode、ApiResponseAction、FeedbackMode、HtmlSwap 均从 `oldman.web.api` 导入。响应辅助函数可从 `oldman.web` 或 `oldman.web.response` 导入；Demo 的视图使用后者。

`DefaultApiResponse` 有 `error_code`、`message`、`data`、`actions`。默认业务码为 0，文本为空，字典和动作列表独立初始化。`DefaultApiFormResponse` 只增加 `errors: dict[str, str | LazyTranslation]`，每个真实字段输出第一条错误，不含 `__all__`。

Action 是扁平、带 msgspec tag 的强类型对象。下面是 Demo [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py) 中的完整辅助函数；创建、编辑、删除视图均在数据库事务成功退出后调用它：

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

LazyTranslation 来自 `oldman.i18n`，json_response 来自 `oldman.web.response`。这是请求内翻译并输出响应的时点；不是把 lazy 对象直接塞给任意 JSON 库。`api_response(payload)` 封装了同样的 `payload.to_dict()` 加 JSON 输出，下一节的 Demo 路由使用该简写。

`oldman.web.api` 还提供按 Accept 协商的 Form 响应助手，Admin 和演示站都用它们而不再各自拼 `DefaultApiFormResponse`：`accepts_json_form_response(request)` / `accepts_html_form_response(request)` 读取客户端要求；`form_response(message, actions=, errors=, error_code=, status=)` 是基础载荷；`form_error_response(message, errors=)` 是 HTTP 200 的业务错误（默认 `FORM_INVALID`，可换 `INVALID_REQUEST`）；`await form_invalid_response(request, form, fragment=, page=)` 在 JSON、422 片段和整页之间选择；`form_success_response(request, url)` 保存后给 JSON 客户端 `RedirectAction`、给浏览器 303；`feedback_response`、`form_saved_response(message, url=, delay_ms=, actions=)`、`modal_success_response(message, table_target=, text=, actions=)` 分别对应“留在本页”“跳转”“关闭 modal 并刷新表格”三种成功，附加动作插在 Feedback 之后。

响应不提供单个 `action`、顶层 `html` 或多区域 `fragments` 字段。无动作就是 `actions=[]`。框架动作名称由 `ApiResponseAction` 管理；调用具体子类不需要手填名称。延迟翻译继承已有 `TranslatableMsgspecModel` 能力，在 HTTP 输出时解析；无需自己写递归 JSON 转换器。

## 五个内置动作

| 类型 | 参数和行为 |
| --- | --- |
| `FeedbackAction` | 必填 `title`；`mode` 默认 toast，也可 alert；可传 `text`、`icon`、`target`。标题和正文是文本 |
| `ReplaceHtmlAction` | 必填 `html`；可传 `target`、`swap`，只支持 inner/outer |
| `CloseModalAction` | 可指定 `target`；省略时寻找请求来源所在的最近 Modal |
| `ReloadTableAction` | 必须指定已挂载 Table 的 `target`，等待其 reload 完成 |
| `RedirectAction` | 必填 `url`；可传非负 `delay_ms`，默认 0；跳转后结束动作循环 |

基类共享可选 `target` 和 `data`，子类直接加自己的字段，不再嵌套一层 ActionData。

Runner 顺序等待动作；某个动作抛错，后续停止，已执行动作不回滚。toast 发出后不等它自然消失；alert 等用户关闭后继续。普通 Feedback Action 不返回用户的业务选择，确认框或复杂交互应写 Page 私有动作。

## HTML 目标和组件生命周期

目标优先级：`action.target` → 发起元素的 `data-om-target` → 发起元素自身。swap 优先级：`action.swap` → `data-om-swap` → inner。

Demo [templates/pages/examples/modals/actions.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/modals/actions.html) 有下面这个真实按钮；同模板内还声明了目标节点。以下为两个分别摘出的片段：

```jinja
      <button type="button" class="om-button om-button-secondary" data-example-action="replace_html" data-om-action="get" data-om-url="/examples/modals/actions/replace-html" data-om-target="#replace-action-result">{{ _("Replace HTML") }}</button>
```

```jinja
      <p id="replace-action-result" class="mb-2 text-default-600">{{ _("Replace HTML target") }}</p>
```

对应 [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py) 的完整路由如下。app 来自该文件的 `get_app()`，admin_required 来自 Demo，Request、响应类型及翻译函数按原文件导入：

```python
@app.get("/examples/modals/actions/replace-html", name="example_action_replace_html")
@admin_required()
async def example_action_replace_html(request: Request):
    """Let the trigger choose where a target-less Replace HTML Action renders."""
    del request
    return api_response(DefaultApiResponse(actions=[ReplaceHtmlAction(html=str(_("HTML replaced by an ordered Action.")))]))
```

后端未指定 target，浏览器才使用按钮上的 `data-om-target`。同一接口可以在其他页面指定不同目标，不需要服务器猜页面容器 ID。框架另有 `replace_html_response()` 简写；以下只是公开签名说明，Demo 上述路由实际使用完整模型，并没有调用这个辅助函数：

```python
def replace_html_response(
    html: str | Markup, *, target: str | None = None,
    swap: HtmlSwap | None = None, status: int = 200,
) -> Response: ...
```

它只生成一个 replace_html 动作，要求 2xx。`Markup` 来自 `markupsafe`，`Response` 来自 `oldman.web`。复杂响应直接创建完整模型，不向辅助函数塞额外反馈或其他动作参数。真实 HTML HTTP 响应仍用 `html_response()`。

CSS selector 只在当前 Page 根节点内查找，不操作缓存中的别的页面。inner 卸载目标内部组件、写入 HTML、挂载新增组件；outer 连目标本身一起卸载和替换。替换后才执行下一个动作。不要自行 `innerHTML = ...` 绕过管理器处理包含组件的内容。

Form 的特殊处理：inner 替换请求来源 Form 自身时，如果返回片段的第一个元素就是 `<form>`，框架同步表单属性并替换其内部，不嵌套第二个 `<form>`。不是在任意外层包装里找到一个 Form 都会做这一处理。需要整块页面重绘时显式指定外层容器或 outer。

## 三种请求消费方式

| 请求方 | 接受的业务响应 | HTTP 错误 |
| --- | --- | --- |
| JSON Form | 2xx `DefaultApiFormResponse`；业务失败使用非零 error_code | 非 2xx 进入公共 HTTP 错误链路 |
| HTML Form | 2xx HTML；校验失败允许 422 HTML | 其余非 2xx 进入公共 HTTP 错误链路 |
| 远程 `data-om-action` | 2xx `DefaultApiResponse` | 非 2xx 不执行响应动作 |

JSON Form 指的是**响应**格式，不表示请求体变成 JSON；Form 仍提交正常表单及文件。

HTML Form 的后端仍只返回 HTML。前端在接收边界把它转成一个内部响应：2xx 对应业务成功，422 对应表单无效，HTML 放入单个 replace_html 动作。转换后复用同一个 Runner；这没有废除 HTML HTTP 接口，也不要求后端包装 JSON。

Table 和 Modal 的初次远程加载有自己的数据格式，不因为也用 JSON 就变成 `DefaultApiResponse`。Modal 的载荷用 `oldman.web.api` 的 `modal_response(title, html=)` / `modal_response(title, body=, footer=)` / `modal_not_found_response(title, message)` 生成，不各自拼 dict。见 [Table](tables.md) 和 [Modal](frontend.md#modal-只是容器)。

## Form 的执行顺序

1. 前端字段校验通过才提交；开始 loading，避免同表单重复提交。
2. 收到合法响应后清除上次 message 和字段错误，再显示本次内容。
3. 不论 `error_code` 是否为零，都执行非空 actions。
4. 动作抛错则停止，通过 Page Feedback 显示异常，不伪造字段错误。
5. 动作完成且原 Form 仍挂在页面中，才设置 success/error 状态并派发事件。

业务成功的条件是 `error_code == 0` 且 `errors` 为空。`om:form:success` / `om:form:error` 是生命周期通知，本身不关闭 Modal、不刷新 Table、不跳转。界面操作由 actions 或业务监听方明确完成，避免重复执行。

字段错误进入 `[data-om-error-for="字段提交名"]`；顶部 message 进入 `[data-om-form-message]`。`[data-om-form-status]` 只放“正在提交”等瞬时状态。网络失败不再额外生成一条业务 message。

Form 请求失败时先结束 loading、派发一次 `om:form:error`，再复用普通 `data-om-action` 已使用的 `showResponseActionFailure`，通过当前 Page 的 Feedback 显示“请求失败”。这是共享组件的职责，Demo 页面不需要自行补 `onError` 弹窗。HTTP Client 继续保留原始 rejection；默认不另装全局弹窗回调，避免同一次错误在 HTTP 层和组件层各显示一次。应用自行提供 `onError` 时，也不要对这些已有 UI 消费者重复弹窗。

主动取消或页面切换引起的请求中止不显示这个错误。HTML 422 和 JSON 业务错误仍按表单内容处理；它们不是网络失败，不额外弹“请求失败”。请求异常不会伪造顶部 message 或字段 errors，用户已经填写的内容也不会因此被清空。

## 普通 API 的 message 和 Feedback

远程 `data-om-action` 没有 Form 顶部消息区。若 actions 已含 feedback，不重复显示 message；否则非空 message 作为默认 Feedback，然后按顺序执行动作。

声明在 `<form data-om-action="submit">` 上时，公共监听在提交捕获阶段用 `data-turbo="false"` 标明该表单由 Actions 接管，避免 Turbo Frame 提前截走 JSON 响应。真正的请求处理仍在冒泡阶段；表单自己的组件可以先阻止提交，例如 Demo 的 FeedbackWorkflow 先询问用户、确认后显式 `runAction()`。没有 `data-om-action` 的普通 Form/Turbo 表单不受影响，动态插入的 Actions 表单同样不需要业务手工补 Turbo 配置。

Feedback 按动作 target、来源 Form 上的 `data-om-feedback-target`、Page 默认 Feedback 寻找。非 Form 来源只查找其最近 Form 的这一属性；不是在任意按钮上写同名属性都有效。显式目标必须是 Page 内已挂载的 Feedback，写错目标不会静默改用别处的实例。

DashboardPage 已有壳上的默认实例；它就是当前 Dashboard Page 的默认反馈，不需要每个业务页面再创建一份，也不需要任意全局单例。Demo 的 ExamplesPage 继承应用 BasePage，再继承 DashboardPage，所以不用另建通知系统。自己直接继承底层 Page 时，应提供相应反馈能力。没有可用 Feedback 时，message 兜底仅记录日志；显式 feedback Action 无法取得实例则失败，不能把日志当成用户已经看到提示。

业务错误码不是网络重试条件；动作失败也不重试。通用表单 POST 不应自动重试写入。401 认证跳转、403 权限和 5xx 服务异常仍由公共 HTTP 链路处理。

## 页面离开和私有动作

请求及响应处理绑定发起时的 Page 和 Turbo Frame。离开页面、替换来源 Frame 或销毁 Page 时取消后续处理，不把旧响应动作应用到新页面。浏览器取消不代表服务器事务回滚，UI 不承担数据库回滚职责。

Runner 使用 Promise 的正常 return/throw，不返回第二套终止状态。redirect 结束循环；Form 被替换后用 DOM 连接状态避免更新已经离开的表单。

项目私有动作可定义自己的 tag。Demo views/modals.py 中实际声明如下，LazyTranslation 与 ResponseAction 分别来自 `oldman.i18n`、`oldman.web.api`：

```python
class _ExampleMarkAction(ResponseAction, tag="example_mark", kw_only=True):
    """Update one Demo-owned output through the Page extension hook."""

    text: str | LazyTranslation
```

同文件的完整发布路由：

```python
@app.get("/examples/modals/actions/private", name="example_action_private")
@admin_required()
async def example_action_private(request: Request):
    """Return one Demo-owned Action handled by ExamplesPage."""
    del request
    return api_response(
        DefaultApiResponse(actions=[_ExampleMarkAction(target="#private-action-result", text=_("Private Page Action completed."))])
    )
```

前端 [frontend/src/pages/examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) 的完整对应方法如下，仍位于 ExamplesPage 类中；ResponseAction、ResponseActionContext 从 `oldman-web/core` 导入：

```typescript
  override async handleResponseAction(
    action: ResponseAction,
    context: ResponseActionContext
  ): Promise<boolean> {
    if (action.action !== "example_mark") return super.handleResponseAction(action, context);
    if (typeof action.target !== "string" || typeof action.text !== "string") {
      throw new Error("Example mark Action requires a target and text");
    }
    const target = this.root.querySelector<HTMLElement>(action.target);
    if (!target) throw new Error(`Example mark Action target was not found: ${action.target}`);
    target.textContent = action.text;
    return true;
  }
```

Page 覆盖 `async handleResponseAction(action, context): Promise<boolean>`：处理则返回 true；不认识交给 `super.handleResponseAction()`。Runner 对最终 false 报错并停止。框架枚举只管理内置动作，第三方 App 无需修改框架枚举。

该 Demo 视图传 `page_entry="examples"`，main.ts 加载 examples.ts，文件末尾 `setupPage("examples", ExamplesPage)` 注册这一 Page 类。只有把私有处理方法写进实际挂载的 Page，才会接到私有动作；把方法写在一个从未加载的类里没有作用。完整入口关系见[前端运行时](frontend.md#demo-的-dashboard-页面入口)。

不要通过协议执行任意 JavaScript、把字符串当函数名调用，或在 HTML 属性中编写脚本。私有动作仍由明确的 Page 方法实现，并验证需要的输入字段。

## 在 Demo 验证成功与失败

以下操作来自现有页面，供开发者在改动后复核；本次文档对齐没有重跑浏览器验收。

- `/examples/modals/actions`：逐个点击反馈、HTML 替换、Reload Table、Redirect、Private Page Action；每个按钮都指向 views/modals.py 的真实路由。
- 点击 Missing target 或 Unknown Action，应显示动作失败，而不是一直等待。Fail in the middle 先更新 `#action-chain-result`，第二个动作找不到目标并失败，最后的 `later Action must not run` 不应写入页面；前一步结果不回滚。
- `/examples/modals/workflows`：首次 GET 返回 Modal 的 title/body/footer，不是 actions；第一步 Form 提交成功后返回 ReplaceHtmlAction 更新 Form，第二步成功反馈并关闭。两步只验证普通字段，没有写库；它不是跨请求数据库事务。
- `/examples/forms/basics`：分别比较 HTML 与 JSON 表单的校验失败；HTML 是 422 HTML，JSON 是 200 加业务错误码。前端字段约束可能先拦截提交，要查看后端响应时使用浏览器 Network 区分“尚未请求”和“后端校验失败”。
- `/examples/tables/json`：创建/编辑先完成真实事务，再执行本章首个函数的三项动作。网络失败、数据库失败和动作失败不能混称“保存失败”：例如 reload 出错，不代表前面的数据库事务被撤销。
