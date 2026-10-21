# MCP server

`oldman.mcp` exposes installed Apps' tools, resources, and prompts to AI agents (Claude Code, Claude Desktop, Cursor, and other MCP clients) through [Model Context Protocol](https://modelcontextprotocol.io/). MCP is a Web-service route: Sanic remains the server, with ordinary authentication, middleware, logging, client_ip proxy settings, and multiple workers. Protocol models come from mcp-types. The official mcp SDK is not a runtime dependency and is not imported by the framework.

## Installation

Call this in Web-service init(), after super().init(), as explicit wiring like install_admin(app):

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

web.mcp.enabled defaults to false. Disabled install_mcp does nothing, returns None, and logs INFO: code can be wired in advance while environment settings choose whether to enable it, and projects without callers still start. When enabled, it loads installed Apps' mcp modules (AppConfig.mcp_module, default "mcp"), builds the service catalog, validates settings, and registers POST <web.mcp.path> (default /mcp). Every tool/resource/prompt is checked for listing under every supported protocol version. Bad settings, duplicate names, unresolved signature types, schema-generation failures, or definitions unlistable in any version fail here with specific identification, preventing startup rather than waiting for requests. Services without install_mcp or with MCP disabled load no App mcp modules.

## App declarations

Choose the mcp template in ./run.sh startapp <name> to generate an App containing only apps.py, permissions.py, and mcp.py. mcp.py has two example tools (one for all admitted callers, one requiring this App's user permission; API keys have no permissions and see only the former), one resource, and one prompt. startapp does not edit service App lists. Add apps.<name> to apps in data/<service>_settings.yaml or install_mcp will not load it and startup tool counts will exclude it. Existing Apps can directly add mcp.py:

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

Shared declaration rules:

- Only async def is accepted. Synchronous functions raise TypeError at declaration because they would block worker event loops.
- If the first parameter is annotated oldman.web.Request, the framework injects the current request and excludes it from schemas. request.ctx.user/request.ctx.auth mean the same as in views.
- install_mcp resolves signatures with typing.get_type_hints, allowing types defined later in the same module. Types must be importable **at runtime**; definitions present only under if TYPE_CHECKING cause an error naming the function/type.
- Names default to function names and descriptions to docstrings. Models read these, so clearly describe purpose and when to use the tool.
- Pydantic validates arguments. Parameter names must not begin with underscores, equal model_config, or shadow BaseModel methods such as model_dump. The first two are not fields and would silently disappear; the latter is rejected directly. install_mcp identifies offending tool/prompt parameters. Unconvertible resource URI-variable types likewise fail with the URI identified.
- permission= accepts a declared Permission. Only users holding it see/call the entry; invisible entries appear nonexistent so callers cannot distinguish absence from denial. Functions may still call require_perm themselves.
- Only installed-App declarations are exposed. Importing an uninstalled App's mcp.py elsewhere does not expose its entries and logs WARNING at startup. An entry qualifies if either its declaration module (where mcp.tool() is called) or function-definition module belongs to an installed App. Thus App mcp.py can declare imported async functions, and external helpers can declare an App's own functions.

### Tools

- Parameters/annotations generate input schemas; defaults make parameters optional. Extra arguments are rejected. Pydantic failures return isError tool results that models can correct.
- Names allow 1–128 characters from A-Z, a-z, 0-9, _, -, and ., following specification recommendations. Invalid names fail at declaration.
- Returns follow official SDK rules. Return annotations generate output schemas, with structuredContent plus equivalent JSON text. str/int/list[...] are wrapped as {"result": ...}; pydantic models, TypedDict, dataclass, msgspec Struct, and dict[str, ...] remain objects. Without return annotations, or when returning protocol blocks such as TextContent, only content blocks appear. Values are validated against annotations before sending, including converting matching dicts to models/Structs like the SDK. Mismatches log ERROR with tracebacks and return "The tool failed", never successful schema-invalid output. If any return-type position contains msgspec Struct (Struct | None, list[Struct], dict[str, Struct]), msgspec handles the entire schema/validation with the same wrappers. One return type must not mix pydantic models and Structs; arguments accept only pydantic-recognized types, excluding Struct. install_mcp identifies such errors by tool.
- oldman.mcp.ToolError messages pass unchanged to callers. Web exceptions (Forbidden, NotFound, unavailable-store 503) return their messages. Other exceptions log ERROR with tracebacks while exposing only "The tool failed".
- Import hints such as annotations=ToolAnnotations(read_only_hint=True) from oldman.mcp.

### Resource

- URIs without variables are fixed resources (resources/list); {name} variables make templates (resources/templates/list). Only RFC 6570 simple variables are supported. Operators such as {+path}/{?q} and duplicate variables fail at declaration.
- Each variable must exactly match a function parameter. Reads percent-decode then convert through annotations. One variable matches one slash-free path segment. Conversion failures appear nonexistent.
- Fixed URIs precede templates: pages://about wins over pages://{slug} when both match. Duplicate fixed URIs and templates differing only in variable names fail install_mcp.
- str returns text (default text/plain), bytes returns base64 binary (application/octet-stream), and models/dicts/etc. serialize as JSON (application/json). mime_type= overrides defaults.
- None returns and NotFound/Forbidden exceptions produce -32602 Resource not found with data.uri; the specification disallows empty contents for nonexistent resources. Other Web exceptions return -32603 with their messages. Unexpected exceptions log ERROR and expose only "Internal error".

### Prompt

- All parameters must be str because the protocol transmits strings. Defaults make them optional; Annotated[str, Field(description="…")] descriptions appear in argument lists.
- str returns one user message; multi-turn prompts return a PromptMessage list. Import PromptMessage/TextContent from oldman.mcp.
- Unknown/invisible prompts, missing required arguments, and extra arguments return -32602. Function failures return -32603.

## Who can call

The ordinary web.auth.authenticators pipeline authenticates requests; the MCP route then decides by the recognized method:

| Recognized authentication | Result |
| --- | --- |
| User recognized by jwt access token or another explicitly attached non-browser-ambient project token | Admitted; permission= entries require their permissions |
| api_key named in web.mcp.callers | Admitted, but only entries without permission=; API keys identify callers rather than users and have no roles |
| api_key absent from web.mcp.callers | 403 |
| Browser/network-ambient credentials such as session, HTTP Basic, or IP allowlists (Authentication.ambient) | 403 regardless of allow_anonymous; forged cross-site/DNS-rebinding pages would carry them |
| No recognized identity | Default 401 with WWW-Authenticate: Bearer; web.mcp.allow_anonymous: true admits anonymously to entries without permission= |

Accordingly, the route is csrf_exempt: admitted credentials are explicitly attached by callers or genuinely anonymous. Even globally enforced CSRF does not affect it.

Requests carrying Origin, as browser MCP clients do, require it in web.mcp.allowed_origins or receive 403; CLI/desktop clients omit it. Accept must allow JSON (application/json, application/*, or */*) or receives 406. Bodies exceeding web.mcp.max_request_body_size (default 4 MiB) receive 413, stopping reading at the limit rather than buffering everything first.

See the "MCP endpoint (web.mcp)" section in [Configuration reference](configuration.md) for defaults. Enabled install_mcp fails startup when nobody could connect (no jwt, empty callers, anonymous disabled), callers are configured without api_key authentication, or caller names are missing from web.auth.api_keys.

## Rate limiting

The specification requires tool-call rate limits. tools/call counts by caller: user ID, API-key name, or anonymous client_ip. Default web.mcp.rate_limit is 60 calls per 60 seconds. Redis holds counters, defaulting to web.session.redis_alias like sign-in limits. Exceeded calls return tool errors with retry-after seconds visible to models. Redis failure rejects/logs ERROR rather than allowing uncounted calls. Only tool calls are limited, not lists/resources/prompts.

## Connecting clients

Clients connect to https://<service-address><web.mcp.path>. Users send Authorization: Bearer <access-token> issued by TokenFlow (see [Web requests, templates, and permissions](web.md)); programs send X-API-Key: <key>. For example, Claude Code:

```sh
claude mcp add --transport http reports https://reports.example.com/mcp --header "X-API-Key: <key>"
```

## Protocol versions and known limits

The server supports MCP 2026-07-28 (stateless requests carrying version/client capabilities, with server/discover replacing handshake) and handshake-generation 2024-11-05, 2025-03-26, 2025-06-18, and 2025-11-25 (ordinary requests after initialize). Only the framework's explicit version list applies; new mcp-types versions do not automatically expand claimed support.

- JSON responses only, without SSE, progress notifications, logging messages, subscriptions/listen, or completion/complete.
- No stored sessions or Mcp-Session-Id; handshake clients' GET streams/DELETE receive 405.
- Cancellation: Sanic cancels handlers on disconnect, delivering CancelledError to active tools in both generations (2026-07-28 clients already cancel by closing response streams). The 2025-11-25 transport says disconnection SHOULD NOT cancel so clients can resume results. Here there are no sessions/resumption, so disconnected results cannot be delivered and execution is cancelled. Handshake POST notifications/cancelled returns 202 without processing: while the connection stays open, active tools finish.
- No JSON-RPC batches, removed from the specification in 2025-06-18; batches from 2025-03-26 clients are rejected too.
- No OAuth. Web MCP connectors often support OAuth only and need another authentication approach to connect.
- Requests use web.response_timeout (default 120 seconds); longer tools disconnect.

## Testing

Tools/resources/prompts are ordinary async functions and can be called directly in unit tests, passing request objects with ctx.user. Framework tests connect official SDK clients (development dependencies only) to real Sanic services, covering both protocol generations. Handcrafted negative requests separately cover protocol validations; see tests/test_oldman_mcp_*.py.

<!-- source: zh/developers/mcp.md @ ca60929c -->
