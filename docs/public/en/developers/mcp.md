# MCP server

`oldman.mcp` exposes tools, resources, and prompts from installed Apps to AI agents through the [Model Context Protocol](https://modelcontextprotocol.io/). Clients include Claude Code, Claude Desktop, and Cursor. MCP is a route within a Web service: Sanic remains the server, and requests still pass through authentication, middleware, logging, and proxy settings for `client_ip`. Multiple workers continue to work normally. Protocol data models come from `mcp-types`. The official `mcp` SDK is not a runtime dependency, and the framework does not import it.

## Installation

Call this in the Web service's `init()`, after `super().init()`. Like `install_admin(app)`, it requires explicit wiring:

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

`web.mcp.enabled` defaults to false. When disabled, `install_mcp` does nothing, returns `None`, and logs an INFO message. The code can therefore be wired in advance while environment settings decide whether to enable it, and projects without configured callers still start normally. When enabled, `install_mcp` loads each installed App's `mcp` module, controlled by `AppConfig.mcp_module` with default `"mcp"`. It builds the service catalog, checks settings, and registers `POST <web.mcp.path>`, defaulting to `/mcp`. Every tool, resource, and prompt definition is checked for listing under every supported protocol version. Invalid settings, duplicate tool names across Apps, unresolved signature types, failed schema generation, and definitions that cannot be listed under a supported version all fail here with the specific entry identified. Startup fails rather than waiting for the first request. Services that do not call `install_mcp`, or leave it disabled, load no App `mcp` modules.

## App declarations

Select the `mcp` template in `./run.sh startapp <name>` to generate an App containing only `apps.py`, `permissions.py`, and `mcp.py`. Its `mcp.py` has two example tools, one available to all admitted callers and another restricted to users holding this App's permission. API keys have no permissions and see only the former. It also includes one resource and one prompt. `startapp` does not change the service's App list. Add `apps.<name>` to `apps` in the service settings, `data/<service>_settings.yaml`; otherwise `install_mcp` will not load it, and startup's tool count will exclude it. For an existing App, add `mcp.py` directly:

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

All three declaration types follow these rules:

- Only `async def` functions are accepted. Synchronous functions raise `TypeError` at declaration because they would block the worker's event loop.
- When the first parameter is annotated `oldman.web.Request`, the framework supplies the current request and excludes it from the schema. `request.ctx.user` and `request.ctx.auth` have the same meanings as in views.
- `install_mcp` resolves signatures through `typing.get_type_hints`, so types defined later in the same module work. Types must nevertheless be importable **at runtime**. A type defined only under `if TYPE_CHECKING:` makes `install_mcp` fail with the function and type name identified.
- Names default to function names, and descriptions default to docstrings. These are what models read, so explain what the tool does and when to use it.
- Pydantic validates arguments. Parameter names must not begin with an underscore, equal `model_config`, or shadow BaseModel methods such as `model_dump`. Pydantic does not treat the first two as fields, which would silently remove arguments; it rejects the last case directly. `install_mcp` reports the tool or prompt and the invalid parameter. If pydantic cannot convert a resource's URI-variable type, it likewise fails and identifies the URI.
- `permission=` accepts a declared `Permission`. Only users holding it can see the entry in lists, and the same check applies on invocation. Invisible entries are reported as nonexistent, so callers cannot distinguish missing entries from denied access. Functions may still call `require_perm` themselves.
- Only declarations belonging to installed App packages are exposed. If another module imports an uninstalled App's `mcp.py`, those declarations remain unavailable and startup logs a WARNING. An entry is included if either the declaration module, where `mcp.tool()` or a similar decorator is called, or the function's defining module belongs to an installed App. Thus an App's `mcp.py` can expose an imported async function as a tool, and a helper outside the App can declare the App's own function.

### Tools

- Parameters and their annotations generate the input schema. Defaults make arguments optional; extra arguments are always rejected. Pydantic validation failures return a tool error with `isError`, allowing the model to correct its input.
- Names must contain 1–128 characters from `A-Z a-z 0-9 _ - .`, following the specification's recommendation. Invalid names fail at declaration.
- Return values follow the official SDK's rules. A return annotation generates an output schema; results include both `structuredContent` and JSON text containing the same data. Types such as `str`, `int`, and `list[...]` are wrapped in `{"result": ...}`. Pydantic models, TypedDict, dataclass, msgspec Struct, and `dict[str, ...]` remain objects. Without a return annotation, or when returning protocol content blocks such as `TextContent`, only content blocks are returned. Values are checked against the return annotation before delivery, including converting matching dictionaries to models or Structs, as the SDK does. A mismatch logs an ERROR with a traceback and gives the caller "The tool failed"; invalid output is never reported as success. If msgspec Struct appears anywhere in the return type, such as `Struct | None`, `list[Struct]`, or `dict[str, Struct]`, msgspec generates and validates the entire schema with the same wrapping rules. A single return type must not mix pydantic models with Structs. Parameters accept only types recognized by pydantic, excluding Struct. `install_mcp` detects these errors and identifies the tool.
- Messages from `oldman.mcp.ToolError("…")` are passed unchanged to callers. Web exceptions used by views, including `Forbidden`, `NotFound`, and 503 for unavailable storage, return their messages. Other exceptions log an ERROR with a traceback, while callers see only "The tool failed" to avoid disclosing internal details.
- Import hints such as `annotations=ToolAnnotations(read_only_hint=True)` from `oldman.mcp`.

### Resource

- A URI without variables defines a fixed resource in `resources/list`. A URI containing `{name}` defines a template in `resources/templates/list`. Only RFC 6570 simple variables are supported. Operators such as `{+path}` and `{?q}`, and repeated variables, fail at declaration.
- Each variable must correspond exactly to one function parameter. Reads first percent-decode it, then convert it through its annotation. A variable matches one path segment without `/`. Conversion failure is reported as nonexistent.
- Fixed URIs take precedence over templates. If both `pages://about` and `pages://{slug}` match, the former wins. Two templates differing only in variable names, or duplicate fixed URIs, fail during `install_mcp`.
- A returned `str` is text with default `text/plain`. A returned `bytes` value is base64 binary with default `application/octet-stream`. Models, dictionaries, and similar values serialize as JSON with default `application/json`. `mime_type=` overrides these defaults.
- A return value of `None`, or a `NotFound` or `Forbidden` exception, produces `-32602 Resource not found` with `data.uri`. The specification disallows empty contents for nonexistent resources. Other Web exceptions return `-32603` with their messages. Unexpected exceptions log ERROR and expose only "Internal error".

### Prompt

- All parameters must be `str` because the protocol passes strings. Defaults make them optional. Descriptions from `Annotated[str, Field(description="…")]` appear in the argument list.
- A returned `str` becomes one user message. For multiple turns, return a list of `PromptMessage`. Import `PromptMessage` and `TextContent` from `oldman.mcp`.
- Unknown or invisible prompts, missing required arguments, and extra arguments return `-32602`. Function failures return `-32603`.

## Who can call

The `web.auth.authenticators` pipeline authenticates requests normally. The MCP route then decides based on the recognized method:

| Recognized authentication | Result |
| --- | --- |
| A user identified by a `jwt` access token or a project token that browsers do not attach automatically | Access is allowed. Entries with `permission=` require the corresponding permission. |
| An `api_key` whose name appears in `web.mcp.callers` | Access is allowed only to entries without `permission=`. API keys identify callers rather than users and have no roles. |
| An `api_key` whose name is absent from `web.mcp.callers` | The response is 403. |
| Credentials attached automatically by browsers or network context, such as sessions, HTTP Basic, or IP allowlists (`Authentication.ambient`) | The response is 403 regardless of `allow_anonymous`. Forged cross-site requests and DNS-rebinding pages would carry these credentials. |
| No recognized identity | The default response is 401 with `WWW-Authenticate: Bearer`. `web.mcp.allow_anonymous: true` admits anonymous callers to entries without `permission=` only. |

The route therefore skips CSRF validation through `csrf_exempt`: admitted requests use explicitly supplied credentials or are genuinely anonymous. Globally enforced CSRF does not change this behavior.

If a request carries an `Origin` header, as browser MCP clients do, it must appear in `web.mcp.allowed_origins` or the response is 403. Command-line and desktop clients do not send this header. `Accept` must allow JSON through `application/json`, `application/*`, or `*/*`; otherwise the response is 406. A body exceeding `web.mcp.max_request_body_size`, default 4 MiB, receives 413. Reading stops at the limit rather than buffering the whole body first.

See the "MCP endpoint (web.mcp)" section in [Configuration reference](configuration.md) for settings and defaults. When enabled, `install_mcp` checks at startup for configurations that admit nobody: no `jwt`, empty `callers`, and disabled `allow_anonymous`. It also rejects nonempty `callers` without `api_key` authentication and names in `callers` that are absent from `web.auth.api_keys`.

## Rate limiting

The specification requires servers to limit tool-call frequency. `tools/call` counts per caller: by user ID, API-key name, or `client_ip` for anonymous requests. The default `web.mcp.rate_limit` allows 60 calls per 60 seconds. Counters live in Redis, defaulting to `web.session.redis_alias`, as sign-in limits do. An exceeded limit returns a tool error stating how many seconds to wait before retrying, which the model can read. If Redis fails, the call is rejected and an ERROR is logged; unavailable counters do not grant access. Only tool calls are limited, not lists, resources, or prompts.

## Connecting clients

Clients connect to `https://<service-address><web.mcp.path>`. Users send `Authorization: Bearer <access-token>`, with tokens issued by `TokenFlow`; see [Web requests, templates, and permissions](web.md). Programs send `X-API-Key: <key>`. For example, Claude Code:

```sh
claude mcp add --transport http reports https://reports.example.com/mcp --header "X-API-Key: <key>"
```

## Protocol versions and known limits

The server supports both MCP 2026-07-28 and the handshake generations 2024-11-05, 2025-03-26, 2025-06-18, and 2025-11-25. The former is stateless: each request carries its protocol version and client capabilities, and `server/discover` replaces the handshake. Handshake generations send ordinary requests after `initialize`. Supported versions come only from the framework's own list. An upgrade making `mcp-types` recognize another version does not make the server claim support automatically.

- Responses use JSON, not SSE streams. There are no progress notifications, log messages, subscriptions through `subscriptions/listen`, or argument completion through `completion/complete`.
- Sessions are not stored, and no `Mcp-Session-Id` is issued. Handshake clients receive 405 for GET streams and DELETE.
- When a client disconnects, Sanic cancels the handler and running tools receive `CancelledError` in both generations. Clients using 2026-07-28 already cancel by closing the response stream. The 2025-11-25 transport specification says disconnection SHOULD NOT imply cancellation so clients can resume and retrieve results. This server stores no sessions and supports no resumption, so disconnected results cannot be delivered and tools are still cancelled. A handshake client's POST of `notifications/cancelled` returns 202 without processing it; a running tool finishes if its connection remains open.
- JSON-RPC batches are not accepted. The specification removed them in 2025-06-18; batches from 2025-03-26 clients are rejected too.
- OAuth is not supported. Browser-based MCP connectors often support only OAuth, so connecting them requires another authentication approach.
- Requests use `web.response_timeout`, default 120 seconds. Longer-running tools are disconnected.

## Testing

Tools, resources, and prompts are ordinary async functions that unit tests can call directly. Supply an object with `ctx.user` as the `request` argument. The framework's own tests use official SDK clients, available only in development dependencies, against real Sanic services for both protocol generations. Handcrafted negative requests additionally cover every protocol validation. See `tests/test_oldman_mcp_*.py`.

<!-- source: zh/developers/mcp.md @ ca60929c -->
