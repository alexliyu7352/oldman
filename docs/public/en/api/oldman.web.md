# `oldman.web`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Lightweight public Web primitives for Oldman applications.

Import with `from oldman.web import <name>`.

## `api_response`

function · defined in `oldman.web.response`

```python
def api_response(payload: DefaultApiResponse, *, status: int=200) -> Response
```

Return a native JSON response for an Oldman API payload.

## `autodiscover`

function · defined in `oldman.web.routing`

```python
def autodiscover(app: WebApp, *module_names: str | ModuleType, recursive: bool=False) -> None
```

Discover and register blueprints from one or more modules.

## `BadRequest`

re-export · defined in `sanic.exceptions`

```python
from sanic.exceptions import BadRequest
```

Re-exported unchanged from `sanic.exceptions`; see that library's documentation.

## `empty_response`

function · defined in `oldman.web.response`

```python
def empty_response(status: int=204, headers: Mapping[str, str] | None=None) -> Response
```

Create a Sanic empty response under the stable Oldman name.

## `Forbidden`

re-export · defined in `sanic.exceptions`

```python
from sanic.exceptions import Forbidden
```

Re-exported unchanged from `sanic.exceptions`; see that library's documentation.

## `get_arg`

function · defined in `oldman.web.request`

```python
def get_arg(args: object, key: str, default: object=None) -> object
```

Read a single value from request args or a plain mapping.

## `get_current_request`

value · defined in `oldman.web.request`

```python
get_current_request = Request.get_current
```

## `html_response`

function · defined in `oldman.web.response`

```python
def html_response(body: Any, status: int=200, headers: Mapping[str, str] | None=None) -> Response
```

Create a Sanic HTML response under the stable Oldman name.

## `HTTPMethodView`

class · defined in `oldman.web.http`

```python
class HTTPMethodView(SanicHTTPMethodView)
```

Sanic 的 HTTPMethodView 加上 Oldman 的登录协议与权限钩子。

Members:

- `response_mode: ResponseMode = 'auto'`
- `async def dispatch_request(request: Any, *args: object, **kwargs: object)` — 执行认证/权限检查后按 Sanic HTTPMethodView 规则分派 method。
- `def is_authenticated(request: Any) -> bool` — 判断请求是否来自已登录用户,不论它凭什么认证。
- `async def check_permission(request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]` — endpoint 级权限 hook,默认允许;返回 (是否允许, 拒绝时的提示)。
- `async def resolve_hook_response(response: Any) -> Any` — 兼容同步和异步权限响应 hook。
- `def on_authentication_required(request: Any, response_mode: Literal['html', 'json'], *, method_name: str) -> Any` — 未登录响应 hook;可以返回响应,也可以返回待 await 的响应(分派时两种都接受)。
- `async def on_permission_denied(request: Any, response_mode: Literal['html', 'json'], *, message: str, method_name: str)` — 无权限响应 hook。

## `import_app_modules`

function · defined in `oldman.web.routing`

```python
def import_app_modules(package_name: str, suffixes: tuple[str, ...]=('models', 'views')) -> None
```

Import conventional modules from an application package.

## `json_response`

function · defined in `oldman.web.response`

```python
def json_response(body: Any, status: int=200, headers: Mapping[str, str] | None=None, content_type: str='application/json', dumps: Callable[..., Any] | None=None, **kwargs: Any) -> Response
```

Create a Sanic JSON response under the stable Oldman name.

## `NotFound`

re-export · defined in `sanic.exceptions`

```python
from sanic.exceptions import NotFound
```

Re-exported unchanged from `sanic.exceptions`; see that library's documentation.

## `raw_response`

function · defined in `oldman.web.response`

```python
def raw_response(body: str | bytes | None, status: int=200, headers: Mapping[str, str] | None=None, content_type: str='application/octet-stream') -> Response
```

Create a Sanic raw response under the stable Oldman name.

## `redirect_response`

function · defined in `oldman.web.response`

```python
def redirect_response(to: str, headers: Mapping[str, str] | None=None, status: int=302, content_type: str='text/html; charset=utf-8') -> Response
```

Create a Sanic redirect response under the stable Oldman name.

## `render_template`

re-export · defined in `sanic_ext`

```python
from sanic_ext import render
```

Re-exported unchanged from `sanic_ext`; see that library's documentation.

## `replace_html_response`

function · defined in `oldman.web.response`

```python
def replace_html_response(html: str | Markup, *, target: str | None=None, swap: HtmlSwap | None=None, status: int=200) -> Response
```

Return one JSON replace-html action for a successful request.

## `Request`

re-export · defined in `sanic`

```python
from sanic import Request
```

Re-exported unchanged from `sanic`; see that library's documentation.

## `request_accepts_json`

function · defined in `oldman.web.request`

```python
def request_accepts_json(request: Request) -> bool
```

Return whether the request Accept header includes JSON.

## `Response`

re-export · defined in `sanic.response`

```python
from sanic.response import BaseHTTPResponse
```

Re-exported unchanged from `sanic.response`; see that library's documentation.

## `Router`

class · defined in `oldman.web.routing`

```python
class Router
```

注册路由的入口。应用在 ``views.py`` 里用它,不接触底层服务器实例。

Members:

- `def add_route(handler: _Handler, uri: str, *, name: str | None=None, **kwargs: object) -> _Handler` — 注册一个处理器,通常是类视图的 ``as_view()`` 结果。
- `def route(uri: str, methods: Iterable[str], *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 按给定方法集注册。单一方法优先用下面的同名快捷方法。
- `def websocket(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 WebSocket 路由。
- `def get(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 GET 路由。
- `def post(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 POST 路由。
- `def put(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 PUT 路由。
- `def patch(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 PATCH 路由。
- `def delete(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 DELETE 路由。
- `def head(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 HEAD 路由。
- `def options(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — 注册 OPTIONS 路由。

## `router`

value · defined in `oldman.web.routing`

```python
router = Router()
```

进程级路由注册入口。``from oldman.web import router``

## `stream_response`

function · defined in `oldman.web.response`

```python
def stream_response(streaming_fn: Callable[[StreamWriter], Awaitable[None]], status: int=200, headers: Mapping[str, str] | None=None, content_type: str | None=None) -> StreamingResponse
```

Create a Sanic streaming response under the stable Oldman name.

## `StreamingResponse`

re-export · defined in `sanic.response`

```python
from sanic.response import ResponseStream
```

Re-exported unchanged from `sanic.response`; see that library's documentation.

## `StreamWriter`

value · defined in `oldman.web.response`

```python
StreamWriter = StreamingResponse
```

## `text_response`

function · defined in `oldman.web.response`

```python
def text_response(body: str, status: int=200, headers: Mapping[str, str] | None=None, content_type: str | None='text/plain; charset=utf-8') -> Response
```

Create a text response while allowing an omitted upstream content type.

## `TooManyRequests`

class · defined in `oldman.web.exceptions`

```python
class TooManyRequests(SanicException)
```

A request refused by a rate limit; carries Retry-After when the window is known.

## `Unauthorized`

re-export · defined in `sanic.exceptions`

```python
from sanic.exceptions import Unauthorized
```

Re-exported unchanged from `sanic.exceptions`; see that library's documentation.

## `WebApp`

re-export · defined in `sanic`

```python
from sanic import Sanic
```

Re-exported unchanged from `sanic`; see that library's documentation.

## Module `oldman.web.errors`

HTML fallback pages for Oldman Web applications.

Import with `from oldman.web.errors import <name>`.

### `ErrorPageHandler`

class · defined in `oldman.web.errors`

```python
class ErrorPageHandler(ErrorHandler)
```

Render project-overridable HTML pages without changing API errors.

Members:

- `async def default(request: Any, exception: Exception)` — Use project-overridable templates for production HTML errors.

### `render_html_error_response`

function · defined in `oldman.web.errors`

```python
async def render_html_error_response(request: Any, exception: Exception)
```

Render an explicitly selected HTML error, including project overrides.

## Module `oldman.web.exceptions`

Web exceptions the framework raises, named so handlers can match on them.

Import with `from oldman.web.exceptions import <name>`.

### `CSRFFailure`

class · defined in `oldman.web.exceptions`

```python
class CSRFFailure(Forbidden)
```

A state-changing request whose CSRF token or origin did not check out.

Constructor:

```python
CSRFFailure(message: str, *, page_description: str) -> None
```

## Module `oldman.web.http`

Oldman 后端组件 HTTP 视图基类。

Import with `from oldman.web.http import <name>`.

### `access_denied_response`

function · defined in `oldman.web.http`

```python
async def access_denied_response(request: Any, *, login_url: str | None=None, response_mode: ResponseMode='auto')
```

Turn away a request a page's own check refused: 403 when signed in, the login protocol otherwise.

### `authentication_required_response`

function · defined in `oldman.web.http`

```python
def authentication_required_response(request: Any, response_mode: Literal['html', 'json'], *, login_url: str | None=None)
```

返回未登录响应;`login_url` 省略时用站点的 `web.account.login_url`。

### `build_login_url`

function · defined in `oldman.web.http`

```python
def build_login_url(request: Any, login_url: str | None=None) -> str
```

构造包含原始 path/query 的登录跳转地址;`login_url` 省略时用站点的 `web.account.login_url`。

### `permission_denied_response`

function · defined in `oldman.web.http`

```python
async def permission_denied_response(request: Any, response_mode: Literal['html', 'json'], *, message: str | None=None)
```

返回 JSON 403 或项目可覆盖的 HTML 403 页面;没给 message 时用翻译后的"没有权限"。

### `resolve_response_mode`

function · defined in `oldman.web.http`

```python
def resolve_response_mode(request: Any, default: ResponseMode='auto') -> Literal['html', 'json']
```

按 response_mode 参数优先、Accept 兜底解析响应模式。

## Module `oldman.web.package_data`

Package data helpers.

Import with `from oldman.web.package_data import <name>`.

### `package_root`

function · defined in `oldman.web.package_data`

```python
def package_root() -> Path
```

Return oldman.web package root on the local filesystem.

### `package_template_dir`

function · defined in `oldman.web.package_data`

```python
def package_template_dir() -> Path
```

Return bundled template directory.

## Module `oldman.web.request`

Oldman request aliases and helpers.

Import with `from oldman.web.request import <name>`.

### `basic_credentials`

function · defined in `oldman.web.request`

```python
def basic_credentials(request: Any) -> tuple[str, str] | None
```

The username and password of an ``Authorization: Basic`` header, or None.

### `bearer_credential`

function · defined in `oldman.web.request`

```python
def bearer_credential(request: Any) -> str | None
```

The token of an ``Authorization: Bearer`` header, or None.

### `client_ip`

function · defined in `oldman.web.request`

```python
def client_ip(request: Any) -> str
```

The address a request came from: Sanic's `client_ip` honours the configured proxy headers, `ip` is the socket peer.

### `first_arg_value`

function · defined in `oldman.web.request`

```python
def first_arg_value(value: object, default: object=None) -> object
```

Reduce a Sanic multi-value parameter to its first value.

### `iter_args`

function · defined in `oldman.web.request`

```python
def iter_args(args: object) -> list[tuple[str, object]]
```

Walk request args as single-valued pairs.

### `request_sends_json`

function · defined in `oldman.web.request`

```python
def request_sends_json(request: Any) -> bool
```

Whether the request body is JSON, by its Content-Type: ``application/json`` or a ``+json`` type.

## Module `oldman.web.shortcuts`

读取一个对象或者返回 404 的快捷函数。

Import with `from oldman.web.shortcuts import <name>`.

### `get_object_or_404`

function · defined in `oldman.web.shortcuts`

```python
async def get_object_or_404(session: Any, model: type[TModel], object_id: Any, *, message: str | None=None) -> TModel
```

在调用方的事务里按主键读一个对象，读不到就抛 `NotFound`。
