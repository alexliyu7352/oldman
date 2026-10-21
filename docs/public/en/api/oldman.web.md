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

Sanic HTTPMethodView with Oldman sign-in protocols and permission hooks.

Members:

- `response_mode: ResponseMode = 'auto'`
- `async def dispatch_request(request: Any, *args: object, **kwargs: object)` — Check authentication/permissions, then dispatch by Sanic HTTPMethodView rules.
- `def is_authenticated(request: Any) -> bool` — Check whether a user is signed in, regardless of authentication method.
- `async def check_permission(request: Any, *, method_name: str, route_kwargs: dict[str, object]) -> tuple[bool, str | None]` — Check endpoint permissions, allowing by default and returning an allowed flag and denial message.
- `async def resolve_hook_response(response: Any) -> Any` — Support synchronous and asynchronous permission-response hooks.
- `def on_authentication_required(request: Any, response_mode: Literal['html', 'json'], *, method_name: str) -> Any` — Return an unauthenticated response directly or as an awaitable, both supported by dispatch.
- `async def on_permission_denied(request: Any, response_mode: Literal['html', 'json'], *, message: str, method_name: str)` — Return a permission-denied response.

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

Route-registration entry point used in views.py without accessing the underlying server instance.

Members:

- `def add_route(handler: _Handler, uri: str, *, name: str | None=None, **kwargs: object) -> _Handler` — Register a handler, usually the result of a class view's as_view().
- `def route(uri: str, methods: Iterable[str], *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a set of methods, preferring same-named shortcuts for single methods.
- `def websocket(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a WebSocket route.
- `def get(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a GET route.
- `def post(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a POST route.
- `def put(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a PUT route.
- `def patch(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a PATCH route.
- `def delete(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a DELETE route.
- `def head(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register a HEAD route.
- `def options(uri: str, *, name: str | None=None, **kwargs: object) -> Callable[[_Handler], _Handler]` — Register an OPTIONS route.

## `router`

value · defined in `oldman.web.routing`

```python
router = Router()
```

Process-wide route registration through ``from oldman.web import router``.

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

Base HTTP view for Oldman backend components.

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

Return an unauthenticated response, defaulting login_url to site web.account.login_url.

### `build_login_url`

function · defined in `oldman.web.http`

```python
def build_login_url(request: Any, login_url: str | None=None) -> str
```

Build a sign-in redirect preserving path/query, defaulting login_url to site web.account.login_url.

### `permission_denied_response`

function · defined in `oldman.web.http`

```python
async def permission_denied_response(request: Any, response_mode: Literal['html', 'json'], *, message: str | None=None)
```

Return JSON 403 or project-overridable HTML 403, defaulting to translated Permission denied.

### `resolve_response_mode`

function · defined in `oldman.web.http`

```python
def resolve_response_mode(request: Any, default: ResponseMode='auto') -> Literal['html', 'json']
```

Resolve response mode from response_mode first, falling back to Accept.

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

Shortcut for fetching an object or returning 404.

Import with `from oldman.web.shortcuts import <name>`.

### `get_object_or_404`

function · defined in `oldman.web.shortcuts`

```python
async def get_object_or_404(session: Any, model: type[TModel], object_id: Any, *, message: str | None=None) -> TModel
```

Read an object by primary key in the caller's transaction, raising NotFound when absent.
