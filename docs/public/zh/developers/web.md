# Web 请求、模板与权限

本章面向使用 `WebApplication` 的服务。配置和 App 加载先读[应用生命周期](applications.md)；完整接线见[Demo 项目管理教程](../users/tutorial-dashboard.md)。下文业务节选来自 EPG Demo 的 services/web.py、apps/auth/views.py 和 session.py，不另外建立 tasks App。

## 路由和请求对象

内部直接使用 Sanic。常用公开入口：

```python
from oldman.web import (
    Request, Response, WebApp, router,
    api_response, html_response, json_response, redirect_response,
    render_template, replace_html_response,
)
```

在已安装 App 的 `views.py` 中 `from oldman.web import router`，再使用 `@router.get()`、`@router.post()` 等装饰器。Registry 在 Web 运行时存在后加载这些视图；不要在 `apps.py`、模型或配置模块中导入视图，也不要创建第二个 Sanic 实例。

导入视图模块不会因为还没有 Web 服务器而失败。本进程的 Web 服务已经建好应用时，登记立即生效；还没有时——Shell、只调用了 `bootstrap_service()` 的脚本、App 命令，以及在服务构造之前就被导入的模块——登记先记下，Web 服务建好应用后、加载视图之前一次补上。没有 Web 服务的进程里，这些登记不会生效。路由名重复这类错误因此在建应用时报出，仍在启动阶段。

`request.args` 是查询参数，`request.form` 是表单数据，`request.files` 是上传文件；它们不是同一种输入。`TailwindForm.from_request()` 读取表单及文件，不把任意 JSON 请求体自动转换成表单字段。JSON API 可用 `msgspec.json.decode(request.body, type=...)` 验证专用输入模型。

## 客户端地址与代理

`request.ip` 是 TCP 对端地址；`request.client_ip` 是 Sanic 按代理配置解析出的客户端地址，没有可信代理头时等于 `request.ip`。[IP 白名单](#ip-白名单)要求这两个地址落在同一个条目里；登录记录的 IP、登录与找回密码的限流取 `oldman.web.request.client_ip(request)`，即 `request.client_ip`，为空时才用 `request.ip`。安全相关判断只应使用这两个属性。

Sanic 只信任你声明过的代理拓扑，三项配置都来自 `settings.web`，由 WebApplication 在 `init()` 中写入 Sanic config：

| 字段 | Sanic 行为 |
| --- | --- |
| `real_ip_header`（默认 `X-Real-IP`） | 直接采用该头的值，不管是谁发来的。反向代理必须覆盖而不是透传客户端发来的同名头；服务端口能被直接访问时，任何客户端都能用它冒充地址 |
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

框架自己的中间件是这套机制的实际样例：Session 在 `oldman/web/session/__init__.py` 注册打开/保存两个中间件，Redis 失败时请求中间件直接返回 503；i18n 在 `WebApplication.init()` 里最先注册 `install_i18n` 和 `cleanup_i18n`，排在 Session、messages 和认证之前：这些中间件拒绝请求时（例如存储不可用的 503）用的就是请求的语言；语言只从路径、查询参数、cookie 和 Accept-Language 取，不依赖登录。按上面的倒序规则，`cleanup_i18n` 在响应中间件里最后执行，其他响应中间件运行时翻译仍然绑定着。它们由配置开关控制安装，不需要也不应该在服务类里再注册一次。

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
@router.get("/users/new", name="users_new")
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

会话中间件还替别的子系统按会话 cookie 的同一套策略写 cookie：`Session.get_session_manager(request).send_cookie(request, name, value, max_age=...)` 登记一个 cookie，响应阶段在保存会话之后写出（会话没有变化、跳过保存时照样写），Domain、Secure、SameSite 与会话 cookie 相同，并且是 HttpOnly。`opened_session_id(request)` 返回会话中间件为这个请求记下的 SID，没经过会话中间件（手搭的请求）时是 None；`send_cookie` 只能用在经过会话中间件的请求上。CSRF 给匿名访客的 cookie 就是这样写出的，见下文 CSRF 一节。

Demo 的 [apps/auth/session.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/auth/session.py) 在模块中从 oldman.web.session 导入 SessionData、get_session_data，从 oldman.web.request 导入 Request；其类与读取函数原文如下。WebService.SESSION_MODEL 指向这个子类：

```python
class DashboardSessionData(SessionData, kw_only=True):
    """Keep an application-specific Session type without duplicating base fields."""


def dashboard_session(request: Request) -> DashboardSessionData:
    """Return this application's concrete request Session model."""
    return get_session_data(request, DashboardSessionData)
```

`SessionData.user_id` 是 `int | None`，还包含用户名、显示名、登录 IP/时间、active/staff/superuser 快照。自定义字段通过子类及服务的 `SESSION_MODEL` 设置。读取 Session 不等于每次查用户数据库；修改用户权限后，业务应撤销相应 Session，使旧授权快照失效。框架接收用户 id 的入口（会话存储、令牌签发与撤销、`oldman.auth` 的用户服务）只收 `int` 本身，`bool` 和 `IntEnum` 这类 int 子类报 TypeError：用户 id 以文字写进 Redis 键和令牌声明，子类的写法可能和它代表的数字不同。这条规则由 `oldman.security.require_user_id()` 统一检查。

登录时核对凭据用 `oldman.web.auth.authenticate_credentials(request, username=..., password=...)`：它按 `web.auth.login_backends` 的顺序询问登录后端，第一个认出凭据的说了算。默认只有内置的 `users`，即 `oldman.auth.authenticate_user`，检查用户存在、active 和密码，不附加 staff 权限。项目自己的登录后端写类的导入路径：无参构造，提供 `name` 和 `async authenticate(request, **credentials)`，只取自己认得的关键字参数（例如设备令牌登录取 `token=`），认不出返回 `None`，认出时返回要登录的 User。

Demo 的 `authenticate_user(request, username, password)` 来自 apps.auth.services，在 `authenticate_credentials` 之上只加了 staff 检查；不要把它和框架的同名函数混淆。普通业务网站不必沿用 Admin 的 staff 限制。

登录表单、用户筛选表单和用户创建/编辑 ModelForm 都来自 `oldman.web.auth`（`LoginForm`、`UserFilterForm`、`user_create_form_class(User)`、`user_edit_form_class(User)`），用户列表表格来自 `oldman.web.auth.UserTable`（子类只提供 `model`、路由名和 `object_url(row, action)`；单元格与行菜单也可单独用 `user_cell_value`、`user_row_actions`），用户管理的自保护规则（`set_user_active`、`validate_user_delete`、`UserManagementError`）来自 `oldman.auth`；staff 和超级用户账号只归超级用户管理：用户表单按它绑定的请求判断操作者，非超级用户新建、编辑这类账号或勾选这两个标志时报「没有权限」，不经过表单的删除、启停、改密由视图在取到用户后用 `is_ordinary_user(user)` 同样判断（内置 Admin 已经这样做）；行菜单里的启停和删除弹窗来自 `oldman.web.auth.user_status_modal_response(request, user, action=...)` 和 `user_delete_modal_response(...)`，视图只负责按 id 取用户（取不到就传 `None`，助手会回 404 的 modal 文案）和给出表单要 POST 的地址；项目和内置 Admin 共用同一份，不各自定义。同一个 views.py 的完整登录入口如下。authenticate_user 来自 apps.auth.services（框架凭据检查加本站的 staff 策略）；form_value、remember_me_requested、login_error_url、login_user、logout_user 和 safe_next_url 都来自 `oldman.web.auth`（safe_next_url 只放行站内路径，拒绝外站、`//host`、反斜杠和控制字符）；redirect_response、CSRF 和 Request 来自框架。它是原生登录提交，不是 JSON Form：

```python
@router.post("/login", name="login_submit")
@csrf_protect()
async def login_submit(request: Request):
    """处理后台用户名密码登录。"""
    next_url = safe_next_url(form_value(request, "next") or request.args.get("next"))
    user = await authenticate_user(request, form_value(request, "username").strip(), form_value(request, "password"))
    if user is None:
        return redirect_response(login_error_url("/login", next_url, "invalid_credentials"), status=303)
    return await login_user(request, user, response=redirect_response(next_url), remember=remember_me_requested(request))
```

`user` 是刚通过认证的真实 User。`login_user()` 用 `session_data_for_user()` 按请求上挂的 Session 类型（这里是 DashboardSessionData）创建会话数据，传入“记住我”决定的有效期和代理感知的登录 IP，用 exclusive_login 创建排他登录并写 Cookie；需要同用户多个会话时自己调用公开方法 login()。当前请求退出用 `await logout_user(request, "/login")`（内部是 `Session.logout_session`，同时安排清除 Cookie）；强制退出某用户用 `await session_manager.force_logout_user(user_id)`。这些是服务端操作，不是在浏览器中删除一个标志就算注销。错误密码回到带错误说明的 GET 登录页，重新生成 CSRF；过期 CSRF 是下面的 403 错误页流程，不能当作密码错误绕过。

## 请求认证：request.ctx.user

每个请求进入视图之前都会经过一条认证流水线，结果放在两个固定位置，不论请求凭什么认证：

- `request.ctx.user`：已登录用户的快照（`id`、`username`、`display_name`、`is_staff`、`is_superuser`、`role_ids`，`is_authenticated` 为真），或匿名用户（`is_authenticated` 为假，所有权限标志都为假）。它是认证那一刻的快照，不是数据库行，读它不查库；需要完整的 User 时按 `id` 自己查。
- `request.ctx.auth`：认出这个请求的方式（`method`，例如 `"session"`），匿名时为 `None`。

```python
@router.get("/me", name="me")
@login_required(response_mode="json")
async def me(request: Request):
    return json_response({"id": request.ctx.user.id, "via": request.ctx.auth.method})
```

流水线按 `web.auth.authenticators` 的顺序逐个尝试，第一个认出凭据的说了算，都认不出就是匿名。不设置时，开启了 Session 就只用 `session`，否则什么都不用；列出 `session` 却没有开启 Session 会在启动时报错。项目自己的认证方式写类的导入路径，这个类无参构造，提供 `name` 和 `async authenticate(request)`，认出凭据时返回 `oldman.web.authentication.Authentication`，认不出返回 `None`（不要在这里回应请求，拒绝与否是权限层的事）。

```yaml
web:
  auth:
    authenticators: [session, apps.accounts.auth.DeviceTokenAuthentication]
```

`login_user()` 成功后，本次请求剩下的部分就是刚登录的用户；`logout_user()` 之后，凭 session 认证的请求变为匿名。关于「这个浏览器会话」的页面（会话资料、改自己的密码）只对已登录的 session 开放：用 `authenticated_session(request)` 取会话，其他方式认证的调用方得到 401。

## Bearer 访问令牌（JWT）

前后端分离的前端、移动端和其他服务，用 `Authorization: Bearer <令牌>` 请求头认证。启用方式是在认证方式里加上 `jwt`，并配置签名密钥：

```yaml
web:
  auth:
    authenticators: [session, jwt]
    jwt:
      secret: "至少 32 个字符的随机串"
```

令牌由 `oldman.web.authentication.issue_access_token(user, role_ids=...)` 签发，返回的 `AccessToken` 带有令牌、`expires_in` 和声明。令牌里是签发那一刻的用户快照（`sub` 为用户 id，另有用户名、显示名、staff、superuser，以及 `roles`：用户持有的角色 id，见[权限](permissions.md)），加上 `iat`、`exp`、`jti`；没有合法 `roles` 声明的令牌一律拒绝。读令牌不查库。只认 `Bearer`，大小写不限；`Token` 前缀和查询参数一律不认。

- 令牌缺失、格式不对、过期或密钥不符时，不在认证这一步拒绝，请求保持匿名，由权限层回 401。这样共享密钥的 Bearer 接口不会被误伤。
- 出示了 Bearer 令牌的请求，401/403 一律是 JSON，不跳转登录页。
- 令牌由客户端主动附加，浏览器不会自动带上，所以不校验 CSRF；同一请求若还带着已登录的 session，照常校验。
- SSE 只支持 session：浏览器的 EventSource 不能附加请求头。
- `session` 应排在 `jwt` 前面：两种凭据同时出现时由 session 决定身份。

**刷新令牌。** 访问令牌寿命短，客户端用刷新令牌换新的，不必重新登录。刷新令牌是随机串，Redis 里只存它的 SHA-256。每次登录开始一串：`issue_refresh_token(user_id)` 发出第一个，`rotate_refresh_token(token)` 每用一次换成同一串的下一个，旧的随即失效，新的从这一刻起活 `web.auth.jwt.refresh_token_ttl`。已经换掉的刷新令牌再被出示，说明有两方拿着同一串，分不清谁是原主，整串作废、都得重新登录；两个请求同时拿同一个令牌来换也按这条处理，只有一个成功。作废一串时，它已经换出去的访问令牌不收回，在访问令牌寿命内自然过期。`revoke_refresh_token(token)` 结束令牌所在的那一串，用于单个客户端注销。`refresh_token_user(token)` 只查令牌属于哪个用户、不用掉它：先查用户、做完检查再轮换，中途失败（比如数据库短暂故障）时客户端手上的令牌仍然有效，重试不会被当成重放。令牌路由就是这个顺序；登录后端返回停用账号时，取令牌同样回 401。

**取令牌、刷新与注销的接口。** 框架提供现成的三个接口，项目只决定「谁能拿令牌」：

```python
from oldman.auth import has_staff_access
from oldman.web.auth import TokenFlow

TokenFlow(accept_user=has_staff_access).register_routes(
    obtain_path="/api/token",
    refresh_path="/api/token/refresh",
    revoke_path="/api/token/revoke",
)
```

- `accept_user` 必填，没有默认值：登录页只放 staff 的站点，不能因为令牌接口忘了问就给所有账号发令牌。取令牌时问一次，每次刷新时按数据库里的最新用户再问一次；账号被停用、删除或不再符合时，下次刷新拿不到新令牌，那一串随之作废。
- 取令牌：请求体（JSON 对象或表单）里的 `username`、`password` 交给[登录后端](#session-和认证不是自动登录系统)核对。要核对别的字段时改 `credential_fields`；客户端多传的字段不会交给登录后端。失败次数与登录页共用同一套限流；成功后更新最后登录时间。
- 刷新：请求体带 `refresh_token`，返回新的一对，旧的刷新令牌随即作废。
- 注销：请求体带 `refresh_token`，结束那一串；请求头里若带着访问令牌，它也立即作废。刷新令牌已经无效时同样回答成功。
- 三个接口都不写 cookie，不需要 CSRF 令牌（已标记 `csrf_exempt`）：别的网站能让浏览器向它们提交，但读不到返回的令牌。响应一律带 `Cache-Control: no-store`。
- 省略 `app` 时经 `oldman.web.router` 注册，路由名为 `<name_prefix>token_obtain`、`..._refresh`、`..._revoke`。签发令牌的服务必须配置 `web.auth.jwt.secret`；注册时不检查它，因为视图模块在导入时就调用 `register_routes`，而在没有服务运行的地方导入视图模块不能报错，所以缺了密钥要到第一次请求才报错。接受令牌的服务在认证方式里列出 `jwt`，只签发不接受的服务可以不列。

响应沿用框架统一的 JSON 外壳：

```json
{"error_code": 0, "message": "", "data": {"access_token": "…", "token_type": "Bearer", "expires_in": 900, "refresh_token": "…", "refresh_expires_in": 604800}, "actions": []}
```

| 情况 | HTTP 状态 | `error_code` |
| --- | --- | --- |
| 缺字段，或字段不是字符串 | 400 | 1000 |
| 凭据不对，或账号不在 `accept_user` 之内（两者回答相同，不透露密码是否正确） | 401 | 1401 |
| 失败次数超过登录限流 | 429，带 `Retry-After` | 1429 |
| 令牌存储（Redis）不可用 | 503 | — |

**撤销。** 用户改密码，或被停用、删除、改变启用/staff/超级用户标志后，框架的入口调用 `revoke_user_logins(request, user_id)`（完整清单见[安全边界](security.md#凭据会话和可信-html)），同时结束该用户的全部 session，并作废此前签发的全部访问令牌和刷新令牌：在 Redis（与 session 同一个安全存储）里记下截止时间，`iat` 不晚于它的访问令牌、登录时间不晚于它的刷新令牌一律拒绝，同一秒的也不例外。令牌的签发时间按 JWT 惯例只精确到秒，分不清同一秒里的先后，所以撤销之后同一秒内签发的令牌也会被拒绝。框架自己没有「撤销后马上签发」的流程；项目自己的流程要在撤销后立即签发时，等到下一秒。截止时间保留到两种令牌中较长的寿命，此后更早的令牌本来也已过期。单个客户端注销时，`revoke_access_token(claims)` 按 `jti` 作废它出示的那一个访问令牌，记录保留到这个令牌本来过期为止。没有请求对象的地方（命令行、后台任务）用 `end_user_logins(user_id)`。没有配置 `web.auth.jwt.secret` 的服务不签发也不接受令牌，但照样写截止时间：只做 Admin 的后台停用账号或改密码后，API 服务签发的令牌也要失效。几个服务共用用户时，它们共用 `web.auth.jwt` 的两个有效期（截止时间按本服务的有效期保留）、同一个 Redis 和同一个 `core.namespace`，在任何一个服务上改密码都对所有服务生效；命名空间不同的服务看不到彼此的撤销记录。校验令牌时 Redis 不可用，请求得到 503，不按「未撤销」放行。

## 服务与内部工具：调用方认证

其他服务、脚本、内网机器调用的接口，要问的不是“谁登录了”，而是“是哪个调用方”。下面这些认证方式认出的都是**调用方**，
不是用户：`request.ctx.user` 仍是匿名，`request.ctx.auth.caller` 是配置里的名字；接口用 `authenticated_by` 放行。

### API key

```yaml
web:
  auth:
    authenticators: [session, api_key]
    api_keys:
      monitor:
        secret: "一个足够长的随机串"
      legacy_bot:
        secret: "……"
        query_param: admin_secrets   # 也从这个查询参数读
        authorization: true          # 也接受 Authorization: Bearer <key>
```

- 调用方默认在 `X-API-Key` 请求头里带 key。某个 key 配了 `query_param` 才从该查询参数读——它会出现在访问日志、浏览器历史和 Referer 里，
  只给改不了请求头的老调用方用；配了 `authorization: true` 才接受 `Authorization: Bearer <key>`。
- 比较用恒定时间。两个名字不能共用一个 key，key 不能为空，列了 `api_key` 却没有任何 key 会在启动时报错。
- key 由客户端主动附加，浏览器不会自动带上，所以这种请求不校验 CSRF；同一请求若还带着已登录的 session，照常校验。
- 与 `jwt` 同时启用时，一个不是合法令牌的 Bearer 值由 `jwt` 放过、再交给 `api_key` 核对，两者不冲突。

### HTTP Basic

```yaml
web:
  auth:
    authenticators: [session, http_basic]
    http_basic:
      realm: "Internal"
      accounts:
        ops: "一个足够长的密码"
```

- 固定账号，给会说 HTTP Basic 的工具和机器用（监控抓取、curl、老系统）；账号名即 `request.ctx.auth.caller`。
- 密码按写的原样存放（settings 文件仅属主可读写）。用户名不能含冒号，密码不能为空；列了 `http_basic` 却没有账号时启动报错。
- 每个账号的用户名和密码都用恒定时间比较，哪一部分错都花同样的时间。
- 浏览器会记住 Basic 凭据并自动带上，所以照常校验 CSRF：机器客户端用 Basic 调用 POST 等接口时，要么给接口加 `csrf_exempt`，
  要么改用 API key。
- 只接受 Basic（没有同时列 `session`）的接口，未通过时返回带 `WWW-Authenticate: Basic realm="…"` 的 401，浏览器会弹出登录框；
  同时列了 `session` 时按登录页流程走，不弹框。

### IP 白名单

```yaml
web:
  auth:
    authenticators: [session, api_key, ip_allowlist]   # ip_allowlist 必须排最后
    ip_allowlist:
      local: ["127.0.0.1/32", "::1/128"]
      office: ["10.0.0.0/8", "127.0.0.1"]   # 服务在本机 nginx 后面：代理自己的地址也要列上
```

- 按请求来自哪个网段认出调用方，条目名即 `request.ctx.auth.caller`。每个条目写单个地址或 CIDR 网段；网段带主机位（如 `10.0.0.1/8`）、
  写错的地址或空条目在加载配置时报错，不会被悄悄放宽；列了 `ip_allowlist` 却没有条目时启动报错。
- 同时检查两个地址，两个都落在**同一个条目**里才算：TCP 对端地址 `request.ip`，和按代理配置解析出的 `request.client_ip`。
  代理头任何客户端都能发，Sanic 对 `real_ip_header` 又不看是谁发的（见[客户端地址与代理](#客户端地址与代理)）；要求对端地址也在名单里，
  能直连服务端口的人伪造代理头也进不来。服务在反向代理后面时，条目里要把代理自己的地址和放行的客户端网段写在一起；这时对端地址总是代理，
  挡不挡得住伪造全看代理：它必须用真实地址覆盖 `real_ip_header`（或者配了 `proxies_count` 时只往 `X-Forwarded-For` 后面追加），
  不能把客户端发来的同名头原样转发，否则名单外的人写上一个名单内的地址就能进来。这是部署前提，框架检查不了。
- 必须排在 `web.auth.authenticators` 的最后，否则启动报错：排在前面时，一个从内网访问、带着登录会话的用户会被当成匿名的白名单调用方，
  登录态被遮住。
- 双栈监听（默认 `listen_host: "::"`）时 IPv4 调用方的地址是 `::ffff:a.b.c.d`，比对前先还原成 IPv4，所以条目里写 IPv4 形式。
  取不到 IP 地址的请求（UNIX socket、代理给的匿名标识）不会被认出。
- 浏览器每个请求都来自它所在的网段，所以照常校验 CSRF，与 HTTP Basic 相同。

### authenticated_by

```python
from oldman.web.auth import authenticated_by

@router.post("/internal/metrics", name="internal_metrics")
@authenticated_by("api_key", callers={"monitor"})
async def internal_metrics(request: Request):
    ...
```

- `authenticated_by(*methods, callers=None, login_url=None, response_mode=None)`：请求须是被列出的某种方式认出的。
- `callers` 限定调用方的名字（哪个 key），不限定用户：同时列出 `session` 或 `jwt` 时，已登录用户照常通过。
- 什么方式都没认出 → 401；被别的方式认出、或是没列出的调用方 → 403。列了 `session` 时，回答按页面的响应模式，与 `login_required` 相同
  （浏览器页面跳登录页）；否则一律 JSON，因为调用方是程序，列了 `http_basic` 时 401 带 `WWW-Authenticate` 质询。

## 权限入口

从 `oldman.web.auth` 导入，全部只读 `request.ctx.user`：

| 装饰器 | 检查 |
| --- | --- |
| `login_required(login_url=None, response_mode="auto")` | 已登录用户，不论凭什么认证 |
| `staff_required(login_url=None, response_mode="auto")` | 已认证且 staff |
| `superuser_required(login_url=None, response_mode="auto")` | 已认证、staff 且 superuser |
| `api_login_required()` | 已认证，使用 JSON 未登录响应 |
| `authenticated_by(*methods, callers=None)` | 由列出的某种方式认证；`callers` 限定调用方名字，见[调用方认证](#服务与内部工具调用方认证) |

`login_url` 省略时，未登录的浏览器被送到站点设置 `web.account.login_url`（默认 `/login`）；只有登录页不归站点设置管的宿主（例如挂在自己前缀下的内置 Admin）才需要显式传。

写在路由装饰器下面，例如 `@router.post(...)`、`@staff_required()`、`@csrf_protect()`、视图函数。权限需要覆盖数据、保存、删除和 Modal 内容接口，不只是页面入口。

未登录的浏览器 HTML 导航会 302 跳到登录页。JSON 或携带 `X-Requested-With: XMLHttpRequest` 的请求返回 HTTP 401，`data.login_url` 供公共 HTTP Client 处理。已登录但无权限返回 403。这些不是 HTTP 200 的业务校验错误。

对象级权限仍由业务查询保证。不能因为用户已登录，就信任 URL 中任何记录 ID。ExampleProject 教程采用所有 staff 共用项目数据，不暗示已实现个人或租户隔离；添加私有业务时，应在列表和保存/删除对象查询中同时限定访问范围，而不是只隐藏操作按钮。

`HTTPMethodView` 从 `oldman.web` 导入，是 Sanic 同名类的子类，加了登录与 staff 协议，两项都关闭时行为与 Sanic 原类相同；可使用 `as_view()` 注册；设置 `require_authenticated`、`require_staff`，或覆盖异步 `check_permission(request, *, method_name, route_kwargs)` 返回 `(allowed, message)`。Table 基类默认要求登录和 staff；直接调用实例 `get()` 不经过 `dispatch_request()` 的权限检查，因此应用应使用 `as_view()` 或自己明确保护包装视图。

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
- 缺少令牌、过期、绑定不符、来源不是本站均为 403，不取消验证来修复久置登录页。抛出的是 `oldman.web.exceptions.CSRFFailure`（`Forbidden` 的子类，原有按 `Forbidden` 处理的代码不变）；HTML 错误页显示"页面已过期，或无法确认请求来自本站，请刷新后重试"，而不是"没有权限"，JSON 响应不变。
- CSRF 默认有效期为 `settings.web.security.csrf.ttl`，当前为 3600 秒；密钥来自统一 Web security 配置。
- 令牌绑定到谁：已登录的请求绑定会话中间件记下的 SID，同一用户的另一个会话、退出后再登录都拿不到可用的旧令牌；匿名访客绑定一个只装随机 id 的 cookie（名字是 `web.security.csrf.cookie_name`，默认 `csrf_id`，和 Django 的 CSRF cookie 同理），别的访客的令牌对他无效，已登录用户的令牌拿到匿名请求上也不通过。
- 已登录时签发的令牌还同时记下浏览器的这个 cookie（和 Django 一样，CSRF cookie 比会话活得久）。表单一直开着、期间会话结束了（过期、在别处退出、被强制下线），提交时请求已是匿名，按 cookie 比对仍能认出是同一个浏览器，于是通过 CSRF，交给视图的登录检查，页面跳到登录页（接口回 401），而不是 CSRF 错误。已登录的请求只比对 SID，所以同一浏览器重新登录后，旧令牌照样失效；别的浏览器（cookie 不同）或不带 cookie 的请求不通过。代价是：不要求登录、但加了 CSRF 保护的接口，在会话结束后仍接受同一浏览器登录时打开的表单。
- 这个 cookie 只在请求生成过令牌（匿名或已登录）、而浏览器还没有有效 id 时发一次，由会话中间件在响应阶段按会话 cookie 的同一套策略写出（Domain、Secure、SameSite 相同，HttpOnly，Path `/`，有效期一年）；不生成令牌的请求（接口、静态文件、SSE）不发。服务端不存任何东西，匿名访客也不会因此落地 session。
- 没开 Session 的服务没有会话中间件，也就没有人写这个 cookie：匿名令牌不绑定，只靠 Origin 同源检查（这类服务没有能被伪造请求借用的浏览器登录态）。
- 登录后，登录前在别的标签页打开的表单令牌失效（改按 SID 比对），刷新即可。生成过令牌的页面 `cache_response` 不缓存：页面里的令牌只属于一个访客或一个会话。
- 校验只针对浏览器会自动带上的凭据：凭请求头里的令牌或 key 认证的请求（认证结果的 `ambient` 为假）不校验，跨站表单伪造不出这种请求；但只要同一个请求还带着已登录的 session，就照常校验。

`csrf_exempt` 只在 `web.security.csrf.enforce` 打开时有意义:那个开关会注册一个全局中间件,对每个状态改变请求校验 token,而被标注的 handler 跳过。开关关闭时保护是逐路由声明的(`@csrf_protect`),不加保护即等于豁免,这个装饰器不产生任何效果。

不要给普通业务表单加 `csrf_exempt`。外部 Webhook 等特殊接口需要明确的另一种请求认证，不属于教程默认路径。

### 可选:按请求解析时区

`oldman.web.middlewares.install_timezone(app)` 注册一个请求中间件,按 `X-Timezone` 头、
`timezone` cookie 的顺序解析调用方时区,写进 `request.ctx.timezone`;两者都没有时用
`core.time_zone`。**默认不注册**——多数服务不读这个值,不该为它在每个请求上花一次头查找和时区解析。
非法时区名回落到配置的默认值,不会抛异常。

## 错误页面和内容协商

URL 里的主键来自浏览器，查不到是正常情况：在自己的事务里用 `await get_object_or_404(session, Model, object_id)`（来自 `oldman.web.shortcuts`）读对象，它读不到就抛 `NotFound`，交给下面的错误处理，不用每个视图写一遍“is None 就 raise”。需要自定义提示时传 `message=`。

WebApplication 已安装 `ErrorPageHandler`，默认 `settings.web.fallback_error_format: auto`。HTML 异常页面按下面顺序选择：

1. `errors/<status>.html`，通常是项目提供的模板。
2. `oldman/errors/<status>.html`，框架提供 403、404、500。
3. `errors/default.html`。
4. `oldman/errors/default.html`。

框架自带的错误页只有一段内联 CSS，不加载任何前端产物，纯 API 服务和网站项目同样可用；取色和字体回退与共享设计 token 一致，并跟随系统明暗。要让错误页带 Dashboard 外壳，按上面的顺序放项目自己的模板。模板上下文只有必要的 `request`、`status_code` 和 `description`，不把异常堆栈或敏感详情交给生产页面：`description` 只在异常自己带了 `page_description`（目前只有 `CSRFFailure`，内容是已翻译的处理建议）时有值，其他异常的消息不会出现在页面上。框架的 403 模板有 `description` 时显示它，否则显示"没有权限"；项目自己的 403 模板要用同样的写法才会显示这句建议。项目可自行加 `templates/errors/401.html`。Dashboard 脚手架提供 `errors/403.html`、`404.html`、`500.html`、`default.html`，它们独立继承框架 Dashboard 错误模板，修改一个不会要求复制整套处理器。

项目 `errors/default.html` 不会覆盖已经匹配到的框架专用 403/404/500；要定制它们需各放一个专用模板。若要统一覆盖所有框架默认样式，也可覆盖对应的 `oldman/errors/...` 路径。

异常处理器与公共权限拒绝辅助函数共用上述模板流程。`await permission_denied_response(request, response_mode)` 按已解析的模式返回 HTML 403 页面或标准 JSON 403；明确指定的模式不会再次被 Accept 覆盖。HTTPMethodView、staff/superuser 装饰器与 Admin 已接入，调用方需等待异步模板渲染。

视图自己 `return text_response(..., status=403)` 仍不会被全局改写成错误页面。API 错误保持 JSON/其内容协商格式；debug 模式的 500 保留 Sanic 调试行为。模板环境缺失或错误模板自身失败时会记录异常并退回 Sanic HTML，不能据此声称任何情况下都必定显示自定义模板。

## HTML 的信任边界

Jinja 普通变量默认转义。Table 普通字符串转义，`Markup` 表示业务已经确认安全的 HTML。响应 `replace_html`、Modal 内容也是 HTML 接口，必须在服务器端转义不可信字段或清理允许的富文本。

Form 的 JSON `message` 和字段错误按文本显示；Feedback Action 的 `title/text` 也是文本。需要复杂业务 HTML，用模板和 `ReplaceHtmlAction`，不要把 HTML 塞入纯文本字段。Cookie flash、持久通知和响应 Feedback 是不同能力，不因名字像“消息”就共用一种显示约定。
