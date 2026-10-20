# MCP 服务端

`oldman.mcp` 把已安装 App 的工具（tool）、resource 和 prompt 通过 [Model Context Protocol](https://modelcontextprotocol.io/) 提供给 AI agent（Claude Code、Claude Desktop、Cursor 等 MCP 客户端）。MCP 是 Web 服务里的一个路由：服务器仍是 Sanic，请求照常经过认证流水线、中间件、日志和 `client_ip` 的代理设置，多 worker 照常工作。协议的数据模型来自 `mcp-types`；官方的 `mcp` SDK 不在运行依赖里，框架也不导入它。

## 装上

在 Web 服务的 `init()` 里、`super().init()` 之后调用，和 `install_admin(app)` 一样是显式接线：

```python
from oldman.mcp import install_mcp
from oldman.runtime import WebApplication


class WebService(WebApplication):
    def init(self) -> None:
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Sanic app was not initialized")
        install_mcp(app)
```

`web.mcp.enabled` 默认为 false，这时 `install_mcp` 什么都不做、返回 `None`，记一条 INFO：代码可以先装上，由各环境的设置决定开不开，没有配置调用方的项目照常启动。打开后，`install_mcp` 加载每个已安装 App 的 `mcp` 模块（`AppConfig.mcp_module`，默认 `"mcp"`），建出这个服务提供的目录，检查设置，再注册 `POST <web.mcp.path>`（默认 `/mcp`）。每个工具、resource、prompt 的定义按每个支持的协议版本各检查一次能否列出。设置有问题、两个 App 声明了同名的工具、签名里的类型解析不了或生成不了 schema、某个定义有协议版本列不出来，都在这里报错并指出是哪一个，服务起不来，不会等到第一个请求。没有调用 `install_mcp` 或没有打开的服务不加载任何 App 的 `mcp` 模块。

## 在 App 里声明

`./run.sh startapp <name>` 选 `mcp` 模板，生成只有 `apps.py`、`permissions.py`、`mcp.py` 的 App。`mcp.py` 里有两个示例工具（一个对所有放行的调用方开放，一个只给持有本 App 权限的用户——API key 没有权限，只看得到前者）、一个 resource 和一个 prompt。已有的 App 直接加一个 `mcp.py`：

```python
from oldman.db import db_manager
from oldman.mcp import mcp
from oldman.web import Request

from apps.reports.permissions import ReportPermissions


@mcp.tool(permission=ReportPermissions.view)
async def count_reports(request: Request, status: str) -> int:
    """Count reports in one status."""
    async with db_manager.get_read_session() as session:
        ...


@mcp.resource("reports://{report_id}", mime_type="application/json", permission=ReportPermissions.view)
async def report(report_id: int) -> dict | None:
    """One report, or None when it does not exist."""
    ...


@mcp.prompt()
async def weekly_summary(week: str) -> str:
    """Ask for a summary of one week's reports."""
    return f"Summarise the reports of week {week}."
```

三种声明共同的规则：

- 只收 `async def`；同步函数在声明时报 `TypeError`（它会堵住 worker 的事件循环）。
- 第一个参数注解为 `oldman.web.Request` 时，框架传入当前请求，它不进 schema；`request.ctx.user`、`request.ctx.auth` 与视图里含义相同。
- 签名在 `install_mcp` 时用 `typing.get_type_hints` 解析，所以同一模块后面才定义的类型也能用；但签名里的类型必须**运行时**可导入，只写在 `if TYPE_CHECKING:` 里的类型会让 `install_mcp` 报错并指出函数和名字。
- 名字默认取函数名，说明默认取 docstring（模型读的就是它，写清楚这个工具做什么、什么时候用）。
- `permission=` 收声明过的 `Permission`：列表里只给持有它的用户看，调用时同样检查；看不到的按"不存在"回答，调用方分不出是没有还是没权限。函数里仍可以自己 `require_perm`。
- 只提供已安装 App 包里声明的东西；别的模块导入了未安装 App 的 `mcp.py` 时，那些声明不提供，启动时记一条 WARNING。

### 工具

- 参数及其注解生成输入 schema，有默认值的可选，多余的参数一律拒绝；参数由 pydantic 校验，校验不过回工具错误（`isError`），模型能据此改正。
- 名字限 1–128 个 `A-Z a-z 0-9 _ - .`（规范的建议），不符合在声明时报错。
- 返回值照官方 SDK 的规则：有返回注解时生成输出 schema，结果里同时有 `structuredContent` 和同一内容的 JSON 文本；`str`、`int`、`list[...]` 这类包成 `{"result": ...}`，pydantic 模型、TypedDict、dataclass、msgspec Struct、`dict[str, ...]` 直接作为对象；没有返回注解、或返回协议的内容块（`TextContent` 等）时只有内容块。返回值在发出前按返回注解校验（与 SDK 相同：匹配的 dict 也会按模型或 Struct 转换）；不匹配时记一条带调用栈的 ERROR，调用方得到 "The tool failed"，不会把不符合 schema 的结果当成功发出去。返回类型里任何位置有 msgspec Struct（`Struct | None`、`list[Struct]`、`dict[str, Struct]`）时，整个返回类型由 msgspec 生成 schema 并校验，包裹规则相同；同一个返回类型里不能混用 pydantic 模型和 Struct，参数也只收 pydantic 认识的类型（不收 Struct），这些在 `install_mcp` 时报错并指出工具。
- `oldman.mcp.ToolError("…")` 的消息原样给调用方；视图会抛的 Web 异常（`Forbidden`、`NotFound`、存储不可用的 503）回它们的消息；其他异常记一条带调用栈的 ERROR，调用方只看到 "The tool failed"，内部信息不外泄。
- `annotations=ToolAnnotations(read_only_hint=True)` 之类的提示从 `oldman.mcp` 导入。

### Resource

- URI 不含变量是一个固定 resource（`resources/list`），含 `{name}` 变量是模板（`resources/templates/list`）。只支持 RFC 6570 的简单变量；`{+path}`、`{?q}` 这类运算符和重复的变量在声明时报错。
- 每个变量必须正好是函数的一个参数。读取时先百分号解码，再按参数注解转换；一个变量匹配一段路径（不含 `/`）。转换失败按"不存在"回答。
- 固定的 URI 排在模板前面：`pages://about` 和 `pages://{slug}` 同时匹配时用前者。两个只差变量名的模板、两个相同的固定 URI 在 `install_mcp` 时报错。
- 返回 `str` 是文本（默认 `text/plain`），`bytes` 是二进制（base64，默认 `application/octet-stream`），模型、dict 等序列化为 JSON（默认 `application/json`）；`mime_type=` 覆盖默认值。
- 返回 `None`，或者函数抛 `NotFound`、`Forbidden`，都回 `-32602 Resource not found` 并带 `data.uri`（规范：不存在时不能回空的 contents）。其他 Web 异常回 `-32603` 带其消息，意外异常记 ERROR、只回 "Internal error"。

### Prompt

- 参数都必须是 `str`（协议以字符串传参），有默认值的可选；`Annotated[str, Field(description="…")]` 的说明出现在参数列表里。
- 返回 `str` 是一条 user 消息；多轮时返回 `PromptMessage` 列表（`PromptMessage`、`TextContent` 从 `oldman.mcp` 导入）。
- 未知的、看不到的 prompt，缺必填参数或带了多余参数，都回 `-32602`；函数出错回 `-32603`。

## 谁能调用

认证照常由 `web.auth.authenticators` 的流水线完成，MCP 路由再按认出的方式决定：

| 请求被认出的方式 | 结果 |
| --- | --- |
| `jwt` 访问令牌（或项目自己的、不是浏览器自动带上的令牌）认出的用户 | 放行；带 `permission=` 的按权限给 |
| `api_key`，名字在 `web.mcp.callers` 里 | 放行；只能用不带 `permission=` 的（API key 认出的是调用方，不是用户，没有角色） |
| `api_key`，名字不在 `web.mcp.callers` 里 | 403 |
| session、HTTP Basic、IP 白名单这类浏览器或网段自动带上的凭据（`Authentication.ambient`） | 403，不论 `allow_anonymous` 怎么设：伪造的跨站请求或 DNS rebinding 页面会带着它们 |
| 什么都没认出 | 默认 401（带 `WWW-Authenticate: Bearer`）；`web.mcp.allow_anonymous: true` 时放行为匿名，只能用不带 `permission=` 的 |

所以路由不校验 CSRF（已标 `csrf_exempt`）：能进来的只有调用方主动附加的凭据和真正的匿名。全局 CSRF 强制打开时也不受影响。

请求带 `Origin` 头（浏览器里的 MCP 客户端会带）时必须在 `web.mcp.allowed_origins` 里，否则 403；命令行与桌面客户端不发这个头。`Accept` 要接受 JSON（`application/json`、`application/*` 或 `*/*`），否则 406；请求体超过 `web.mcp.max_request_body_size`（默认 4 MiB）得到 413，读到超出就停，不会先读完。

设置项及默认值见[配置](configuration.md)的"MCP 端点（web.mcp）"一节。打开后，`install_mcp` 在启动时检查：谁都连不上（没有 `jwt`、`callers` 为空、没开 `allow_anonymous`）、`callers` 非空却没列 `api_key` 认证方式、`callers` 里有 `web.auth.api_keys` 没定义的名字，都报错。

## 限流

规范要求服务端限制工具调用的频率。`tools/call` 按调用方计数——用户按 id、API key 按名字、匿名按 `client_ip`——默认每 60 秒 60 次（`web.mcp.rate_limit`），计数器在 Redis（默认 `web.session.redis_alias`，与登录限流相同）。超出时工具返回错误并写明几秒后可以重试，模型读得到；Redis 出错时拒绝调用并记 ERROR，不会因为计不了数就放行。只限工具调用，列表、resource、prompt 不限。

## 连接客户端

客户端连 `https://<服务地址><web.mcp.path>`，用户带 `Authorization: Bearer <访问令牌>`（令牌由 `TokenFlow` 签发，见 [Web](web.md)），程序带 `X-API-Key: <key>`。例如 Claude Code：

```sh
claude mcp add --transport http reports https://reports.example.com/mcp --header "X-API-Key: <key>"
```

## 协议版本与已知限制

服务端同时支持 MCP 2026-07-28（无状态，每个请求自带协议版本与客户端能力，`server/discover` 取代握手）和握手代的 2024-11-05、2025-03-26、2025-06-18、2025-11-25（`initialize` 之后的普通请求）。版本只认框架自己的列表，`mcp-types` 升级多认识一个版本时，服务端不会跟着宣称支持。

- 只回 JSON，不回 SSE 流：没有进度通知、日志消息、订阅（`subscriptions/listen`）、参数补全（`completion/complete`）。
- 不保存会话：不发 `Mcp-Session-Id`；握手代客户端的 GET 流与 DELETE 得到 405。
- 取消：客户端断开连接时 Sanic 取消处理任务，正在跑的工具收到 `CancelledError`，两代都一样（2026-07-28 的客户端本来就靠关闭回应流取消）。2025-11-25 的传输规范说断开 SHOULD NOT 当作取消，那是为了客户端能续传拿回结果；这里不保存会话、没有续传，断开后结果送不到，所以照样取消。握手代客户端 POST 的 `notifications/cancelled` 回 202 不处理：连接还开着时，正在跑的工具会跑完。
- 不接受 JSON-RPC 批量（2025-06-18 起已从规范删除；2025-03-26 的客户端若发批量会被拒）。
- 没有 OAuth：网页版的 MCP 连接器通常只支持 OAuth，接它们需要另外的认证方式。
- 请求超时沿用 `web.response_timeout`（默认 120 秒），更久的工具会被断开。

## 测试

工具、resource、prompt 是普通的 async 函数，单元测试直接调用它们，`request` 参数传一个带 `ctx.user` 的对象即可。框架自己的测试用官方 SDK 的客户端（只在开发依赖里）连真实的 Sanic 服务，覆盖两代协议；协议层的每条校验另有手工构造请求的反向测试，见 `tests/test_oldman_mcp_*.py`。
