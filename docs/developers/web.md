# Web 请求、模板与权限

本章面向使用 `WebApplication` 的服务。配置和 App 加载先读[应用生命周期](applications.md)；完整接线见[Demo 项目管理教程](../users/tutorial-dashboard.md)。下文业务节选来自 EPG Demo 的 services/web.py、apps/auth/views.py 和 session.py，不另外建立 tasks App。

## 路由和请求对象

内部直接使用 Sanic。常用公开入口：

```python
from oldman.web import (
    Request, Response, WebApp, get_app,
    api_response, html_response, json_response, redirect_response,
    render_template, replace_html_response,
)
```

在已安装 App 的 `views.py` 中调用 `app = get_app()`，再使用 `@app.get()`、`@app.post()` 等 Sanic 装饰器。Registry 在 Web 运行时存在后加载这些视图；不要在 `apps.py`、模型或配置模块中导入视图，也不要创建第二个 Sanic 实例。

`request.args` 是查询参数，`request.form` 是表单数据，`request.files` 是上传文件；它们不是同一种输入。`TailwindForm.from_request()` 读取表单及文件，不把任意 JSON 请求体自动转换成表单字段。JSON API 可用 `msgspec.json.decode(request.body, type=...)` 验证专用输入模型。

## 客户端地址与代理

`request.ip` 是 TCP 对端地址；`request.client_ip` 是 Sanic 按代理配置解析出的客户端地址，没有可信代理头时等于 `request.ip`。auth 装饰器的本机回环判断同时要求 `request.ip` 和 `request.client_ip` 都是回环地址；Admin 登录记录取 `request.ip`，为空时才用 `request.client_ip`。安全相关判断只应使用这两个属性。

Sanic 只信任你声明过的代理拓扑，三项配置都来自 `settings.web`，由 WebApplication 在 `init()` 中写入 Sanic config：

| 字段 | Sanic 行为 |
| --- | --- |
| `real_ip_header`（默认 `X-Real-IP`） | 直接采用该头的值。反向代理必须覆盖而不是透传客户端发来的同名头 |
| `proxies_count` | 取 `X-Forwarded-For` 从右数第 N 段，即最后 N 个可信代理追加的部分。未设置时忽略该头 |
| `forwarded_secret` | 只接受 `by=`/`secret=` 与之匹配的 RFC 7239 `Forwarded` 头 |

`X-Forwarded-For` 最左一段由客户端控制，可以伪造；这三项都不做"过滤内网、保留公网"的猜测。

`oldman.utils.http.first_public_ip(request)` 提供这种猜测：按 `FORWARDED_CLIENT_IP_HEADERS` 的顺序读取代理头，返回第一个全球可路由地址（`ipaddress.is_global`，同时支持 IPv4 和 IPv6），头里没有时返回公网的对端地址，否则 `None`。它适合日志、统计等接受误差的用途，不能用于鉴权或访问控制，也不会覆盖 `request.client_ip`。

## 自定义中间件

内部直接使用 Sanic 中间件，没有另一套注册接口。请求中间件签名为 `async def fn(request)`：返回 `None` 继续，返回响应则跳过视图直接回复。响应中间件签名为 `async def fn(request, response)`：可以修改或替换响应，请求被短路时同样会执行。下面两个函数已在 Sanic 25.12 中实际请求验证：

```python
from oldman.web import Request, Response, json_response


async def block_legacy_api(request: Request) -> Response | None:
    """请求中间件：返回响应即短路，视图不再执行。"""
    if request.path.startswith("/legacy/"):
        return json_response({"error": "gone"}, status=410)
    return None


async def add_no_store(request: Request, response: Response) -> None:
    """响应中间件：请求被短路时也会执行。"""
    response.headers.setdefault("Cache-Control", "no-store")
```

注册位置是服务类覆盖的 `init()`：先调用 `super().init()`，再通过 `self.runtime_app` 取得 Sanic 实例。[应用生命周期](applications.md#模板和基础能力接线)中 Demo 安装 CSRF 和通知路由的 `init()` 覆盖就是这个位置：

```python
from oldman.runtime import WebApplication


class WebService(WebApplication):
    def init(self) -> None:
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Sanic app was not initialized")
        app.register_middleware(block_legacy_api, "request")
        app.register_middleware(add_no_store, "response")
```

`super().init()` 返回时，基类已按开关安装 messages、Session、Storage、SSE 和 i18n 中间件并加载完 views。之后注册的请求中间件排在它们后面，可以读取 `request.ctx.locale`、`request.ctx.translations` 和已打开的 Session。不要在 `apps.py`、models 或 views 的导入阶段注册：那时 Sanic 实例可能还不存在，views 也不该依赖导入顺序产生副作用。

同一位置有多个中间件时的顺序：`priority` 高的先执行；priority 相同，请求中间件按注册顺序执行，响应中间件按注册顺序倒序执行。基类安装的 Session、messages 和 i18n 中间件都使用默认 `priority=0`，所以你在 `init()` 里注册的请求中间件默认排在它们之后；需要在 Session 打开之前运行时，显式传更高的 `priority`。实测：注册 `first`、`second`、`high(priority=10)` 三个请求中间件的执行顺序是 `high, first, second`；响应中间件 `resp_a`、`resp_b` 的执行顺序是 `resp_b, resp_a`。

框架自己的中间件是这套机制的实际样例：Session 在 `oldman/web/session/__init__.py` 注册打开/保存两个中间件，Redis 失败时请求中间件直接返回 503；i18n 在 `WebApplication.init()` 末尾注册 `install_i18n` 和 `cleanup_i18n`。它们由配置开关控制安装，不需要也不应该在服务类里再注册一次。

## 启用模板

`WebApplication.get_ext_config()` 默认返回 `None`。Demo 的 [WebService](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py) 中完整方法如下，Any 来自 typing，settings 来自项目 config.settings：

```python
    def get_ext_config(self) -> dict[str, Any]:
        """返回 Sanic-Ext 配置。"""
        return {
            "oas": False,
            "oas_autodoc": False,
            "templating_path_to_templates": settings.web.template.dir,
            "templating_enable_async": True,
            "logging": False,
            "cors": True,
        }
```

服务 `init()` 中先 `super().init()`，再取得 `self.runtime_app`，检查实例存在，然后安装 CSRF、通知和 install_template_helpers。后者用 `install_template_loaders(app.ext.environment, settings.web.template.dir)` 接入共享模板，并绑定翻译、bundle 和页面帮助函数。完整服务文件在教程中，不需要自己实例化 Jinja Environment 或重新包装 Sanic-Ext。上面的 cors 是 Demo 自己启用的扩展项，不是使用模板必须打开跨域。

模板路径由 `settings.web.template.dir` 配置。普通项目使用一个项目模板目录；不是自动搜索每个已安装 App 的 `templates/`。Demo 在 templates/pages 和 templates/partials 下按业务分类。

查找次序是显式传入的项目目录、已有环境 loader、框架共享模板。用户可以在项目目录放同相对路径的文件覆盖共享模板，例如 `templates/oldman/forms/default/message.html`。组件渲染也复用请求关联的模板环境，不另维护一套主题。

完整 HTTP 响应与 HTML 内容不要混淆。下面是 Demo [apps/auth/views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/views.py) 的完整页面入口；app、Request、CSRF/权限装饰器、UserCreateForm 和 render_template 均由原模块导入或初始化：

```python
@app.get("/users/new", name="users_new")
@add_csrf_token()
@admin_required()
async def users_new(request: Request):
    """渲染后台用户创建页。"""
    form = UserCreateForm(request=request, csrf_token=request.ctx.csrf_token)
    return await render_template("pages/users/form.html", context={"active_section": "system", "active_page": "users", "form": form, "user": None})
```

与此不同，`oldman.web.template.render_component_template(owner, template_name, context)` 是返回 `Markup` 内容的公开接口；`owner.request` 用于取得当前环境。Form/Table renderer 使用它，业务也可用于自己的组件模板；不是一个自行发送 HTTP 的函数。在视图函数里渲染一个片段用 `await render_fragment(request, template_name, **context)`：它通过应用已安装的模板环境渲染并返回 `Markup`，`request` 自动进入上下文；Demo 的 Modal 初次加载就是用它渲染后组成 title/html JSON，具体代码见[Modal 教程](../users/tutorial-dashboard.md#4-modal-只负责装入内容)。视图不要直接使用 `request.app.ext.environment`。所有模板环境都带三个壳层全局：`current_language(request)`、`language_menu_items(request)`（`oldman.web.i18n`，语言菜单和 `<html lang>` 用）和 `csrf_token_for(request)`（`oldman.web.security.csrf`，`csrf-token` meta 用）；`oldman/dashboard/partials/language_switcher.html` 不传参数时就用它们，只有一种语言时不渲染。传入的上下文仍需明确提供模板需要的变量。异步 Jinja 模板中调用异步方法可写 `{{ form.render() }}`；Python 中则必须 `await form.render()`。

## Session 和认证不是自动登录系统

```yaml
web:
  session:
    enabled: true
    redis_alias: SESSION
```

Session 启用后，WebApplication 自动安装读写中间件。Redis 连接从当前服务的 `settings.redis` 取得；没有生产 Memory Session。Session Redis 读取或写入失败会返回 503，不应假装匿名成功继续运行。

Demo 的 [apps/auth/session.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/session.py) 在模块中从 oldman.web.session 导入 SessionData、get_session_data，从 oldman.web.request 导入 Request；其类与读取函数原文如下。WebService.SESSION_MODEL 指向这个子类：

```python
class DashboardSessionData(SessionData, kw_only=True):
    """Keep an application-specific Session type without duplicating base fields."""


def dashboard_session(request: Request) -> DashboardSessionData:
    """Return this application's concrete request Session model."""
    return get_session_data(request, DashboardSessionData)
```

`SessionData.user_id` 是 `int | None`，还包含用户名、显示名、登录 IP/时间、active/staff/superuser 快照。自定义字段通过子类及服务的 `SESSION_MODEL` 设置。读取 Session 不等于每次查用户数据库；修改用户权限后，业务应撤销相应 Session，使旧授权快照失效。

`oldman.auth` 提供 `authenticate_user(username, password)`，它检查用户存在、active 和密码，不附加 staff 权限。Demo 的同名函数来自 apps.auth.services，另外检查 staff 和 Admin 配置的 require_superuser；不要混淆这两个导入。普通业务网站不必沿用 Admin 的 staff 限制。

登录表单、用户筛选表单和用户创建/编辑 ModelForm 都来自 `oldman.web.auth`（`LoginForm`、`UserFilterForm`、`user_create_form_class(User)`、`user_edit_form_class(User)`），用户列表表格来自 `oldman.web.auth.UserTable`（子类只提供 `model`、路由名和 `object_url(row, action)`；单元格与行菜单也可单独用 `user_cell_value`、`user_row_actions`），用户管理的自保护规则（`set_user_active`、`validate_user_delete`、`UserManagementError`）来自 `oldman.auth`；行菜单里的启停和删除弹窗来自 `oldman.web.auth.user_status_modal_response(request, user, action=...)` 和 `user_delete_modal_response(...)`，视图只负责按 id 取用户（取不到就传 `None`，助手会回 404 的 modal 文案）和给出表单要 POST 的地址；项目和内置 Admin 共用同一份，不各自定义。同一个 views.py 的完整登录入口如下。authenticate_user 来自 apps.auth.services（框架凭据检查加本站的 staff 策略）；form_value、remember_me_requested、login_error_url、login_user、logout_user 和 safe_next_url 都来自 `oldman.web.auth`（safe_next_url 只放行站内路径，拒绝外站、`//host`、反斜杠和控制字符）；redirect_response、CSRF 和 Request 来自框架。它是原生登录提交，不是 JSON Form：

```python
@app.post("/login", name="login_submit")
@csrf_protect()
async def login_submit(request: Request):
    """处理后台用户名密码登录。"""
    next_url = safe_next_url(form_value(request, "next") or request.args.get("next"))
    user = await authenticate_user(form_value(request, "username").strip(), form_value(request, "password"))
    if user is None:
        return redirect_response(login_error_url("/login", next_url, "invalid_credentials"), status=303)
    return await login_user(request, user, response=redirect_response(next_url), remember=remember_me_requested(request))
```

`user` 是刚通过认证的真实 User。`login_user()` 用 `session_data_for_user()` 按请求上挂的 Session 类型（这里是 DashboardSessionData）创建会话数据，传入“记住我”决定的有效期和代理感知的登录 IP，用 exclusive_login 创建排他登录并写 Cookie；需要同用户多个会话时自己调用公开方法 login()。当前请求退出用 `await logout_user(request, "/login")`（内部是 `Session.logout_session`，同时安排清除 Cookie）；强制退出某用户用 `await session_manager.force_logout_user(user_id)`。这些是服务端操作，不是在浏览器中删除一个标志就算注销。错误密码回到带错误说明的 GET 登录页，重新生成 CSRF；过期 CSRF 是下面的 403 错误页流程，不能当作密码错误绕过。

## 权限入口

从 `oldman.web.auth` 导入：

| 装饰器 | 检查 |
| --- | --- |
| `login_required(login_url="/login", response_mode="auto")` | 已认证的 active Session |
| `staff_required(login_url="/login", response_mode="auto")` | 已认证且 staff |
| `superuser_required(login_url="/login", response_mode="auto")` | 已认证、staff 且 superuser |
| `api_login_required()` | 已认证，使用 JSON 未登录响应 |

写在 Sanic 路由装饰器下面，例如 `@app.post(...)`、`@staff_required()`、`@csrf_protect()`、视图函数。权限需要覆盖数据、保存、删除和 Modal 内容接口，不只是页面入口。

未登录的浏览器 HTML 导航会 302 跳到登录页。JSON 或携带 `X-Requested-With: XMLHttpRequest` 的请求返回 HTTP 401，`data.login_url` 供公共 HTTP Client 处理。已登录但无权限返回 403。这些不是 HTTP 200 的业务校验错误。

对象级权限仍由业务查询保证。不能因为用户已登录，就信任 URL 中任何记录 ID。ExampleProject 教程采用所有 staff 共用项目数据，不暗示已实现个人或租户隔离；添加私有业务时，应在列表和保存/删除对象查询中同时限定访问范围，而不是只隐藏操作按钮。

`OldmanHTTPMethodView` 位于 `oldman.web.http`，可使用 `as_view()` 注册；设置 `require_authenticated`、`require_staff`，或覆盖异步 `check_permission(request, *, method_name, route_kwargs)` 返回 `(allowed, message)`。Table 基类默认要求登录和 staff；直接调用实例 `get()` 不经过 `dispatch_request()` 的权限检查，因此应用应使用 `as_view()` 或自己明确保护包装视图。

## CSRF

配置密钥不会自动保护所有 POST。业务 Web 服务在 `init()` 中创建一次 `StatelessCSRFManager(app)`；Admin 安装函数已处理这一步。

```python
from oldman.web.security.csrf import (
    StatelessCSRFManager, add_csrf_token, csrf_protect,
)
```

- 显示表单的 GET 用 `@add_csrf_token()`，把令牌写入 `request.ctx.csrf_token`。
- 改数据的 POST 用 `@csrf_protect()`；重新渲染时还可加 `@add_csrf_token()`。
- Oldman Form 自动输出令牌隐藏字段。手写原生表单用 `{% csrf_token %}`。
- 缺少令牌、过期、绑定不符均为 403，不取消验证来修复久置登录页。
- CSRF 默认有效期为 `settings.web.security.csrf.ttl`，当前为 3600 秒；密钥来自统一 Web security 配置。

`csrf_exempt` 只在 `web.security.csrf.enforce` 打开时有意义:那个开关会注册一个全局中间件,对每个状态改变请求校验 token,而被标注的 handler 跳过。开关关闭时保护是逐路由声明的(`@csrf_protect`),不加保护即等于豁免,这个装饰器不产生任何效果。

不要给普通业务表单加 `csrf_exempt`。外部 Webhook 等特殊接口需要明确的另一种请求认证，不属于教程默认路径。

### 可选:按请求解析时区

`oldman.web.middlewares.install_timezone(app)` 注册一个请求中间件,按 `X-Timezone` 头、
`timezone` cookie 的顺序解析调用方时区,写进 `request.ctx.timezone`;两者都没有时用
`core.time_zone`。**默认不注册**——多数服务不读这个值,不该为它在每个请求上花一次头查找和时区解析。
非法时区名回落到配置的默认值,不会抛异常。

## 错误页面和内容协商

URL 里的主键来自浏览器，查不到是正常情况：在自己的事务里用 `await get_object_or_404(session, Model, object_id)`（来自 `oldman.web.shortcuts`）读对象，它读不到就抛 `NotFound`，交给下面的错误处理，不用每个视图写一遍“is None 就 raise”。需要自定义提示时传 `message=`。

WebApplication 已安装 `OldmanErrorHandler`，默认 `settings.web.fallback_error_format: auto`。HTML 异常页面按下面顺序选择：

1. `errors/<status>.html`，通常是项目提供的模板。
2. `oldman/errors/<status>.html`，框架提供 403、404、500。
3. `errors/default.html`。
4. `oldman/errors/default.html`。

框架自带的错误页只有一段内联 CSS，不加载任何前端产物，纯 API 服务和网站项目同样可用；取色和字体回退与共享设计 token 一致，并跟随系统明暗。要让错误页带 Dashboard 外壳，按上面的顺序放项目自己的模板。模板上下文只有必要的 `request`、`status_code`，不把异常堆栈或敏感详情交给生产页面。项目可自行加 `templates/errors/401.html`。Dashboard 脚手架提供 `errors/403.html`、`404.html`、`500.html`、`default.html`，它们独立继承框架 Dashboard 错误模板，修改一个不会要求复制整套处理器。

项目 `errors/default.html` 不会覆盖已经匹配到的框架专用 403/404/500；要定制它们需各放一个专用模板。若要统一覆盖所有框架默认样式，也可覆盖对应的 `oldman/errors/...` 路径。

异常处理器与公共权限拒绝辅助函数共用上述模板流程。`await permission_denied_response(request, response_mode)` 按已解析的模式返回 HTML 403 页面或标准 JSON 403；明确指定的模式不会再次被 Accept 覆盖。HTTPMethodView、staff/superuser 装饰器与 Admin 已接入，调用方需等待异步模板渲染。

视图自己 `return text_response(..., status=403)` 仍不会被全局改写成错误页面。API 错误保持 JSON/其内容协商格式；debug 模式的 500 保留 Sanic 调试行为。模板环境缺失或错误模板自身失败时会记录异常并退回 Sanic HTML，不能据此声称任何情况下都必定显示自定义模板。

## HTML 的信任边界

Jinja 普通变量默认转义。Table 普通字符串转义，`Markup` 表示业务已经确认安全的 HTML。响应 `replace_html`、Modal 内容也是 HTML 接口，必须在服务器端转义不可信字段或清理允许的富文本。

Form 的 JSON `message` 和字段错误按文本显示；Feedback Action 的 `title/text` 也是文本。需要复杂业务 HTML，用模板和 `ReplaceHtmlAction`，不要把 HTML 塞入纯文本字段。Cookie flash、持久通知和响应 Feedback 是不同能力，不因名字像“消息”就共用一种显示约定。
