# Agent guide: offer tools to AI agents over MCP

Use this guide when the project should let MCP clients (Claude Code, Claude Desktop, Cursor and other agents) call its
code: tools, readable resources, or prompt templates. The full reference is `docs/public/zh/developers/mcp.md`; paths
are relative to the framework repository (your `.oldman-docs/` clone). Look up every `oldman` import in the
[API index](../api/README.md).

The MCP endpoint is a route of an existing Web service. Do not add another server, do not install or import the `mcp`
SDK, and do not write a JSON-RPC handler yourself: `oldman.mcp` implements the protocol.

## 1. Create the App and install it

```sh
OLDMAN_ANSWER_STARTAPP_TEMPLATE=mcp ./run.sh startapp <name>
```

This writes `apps/<name>/` with `apps.py`, `permissions.py` and `mcp.py`: two example tools (one every admitted
caller sees, one only for users holding the App's permission), a resource and a prompt. Add
`apps.<name>` to `apps` in `data/<service>_settings.yaml` and run `./run.sh <service> settings sync`. To give an existing
App tools instead, add an `mcp.py` to it.

## 2. Turn the endpoint on in the Web service

In `services/<service>.py`, in `init()`, after `super().init()` and the other `install_*` calls:

```python
from oldman.mcp import install_mcp

...
    def init(self) -> None:
        super().init()
        app = self.runtime_app
        if app is None:
            raise RuntimeError("Sanic app was not initialized")
        install_mcp(app)
```

## 3. Decide who may call, in the settings

In `data/<service>_settings.yaml` under `web:`. Set `web.mcp.enabled: true`: while it is false (the default)
`install_mcp` does nothing and logs `MCP endpoint is off`. Once enabled, `install_mcp` refuses to start when nobody
could call.

- Signed-in users: list `jwt` in `web.auth.authenticators` and set `web.auth.jwt.secret`. Clients send
  `Authorization: Bearer <access token>`; tokens come from a `TokenFlow` route (`docs/public/zh/developers/web.md`).
- Programs: list `api_key` in `web.auth.authenticators`, define the key under `web.auth.api_keys`, and put its name in
  `web.mcp.callers`. Clients send `X-API-Key: <key>`. A key not named in `web.mcp.callers` gets 403.
- Session cookies, HTTP Basic and IP allowlists are always refused on this route (a browser sends them by itself).
- `web.mcp.rate_limit` (on by default: 60 tool calls per caller per 60 seconds) counts in Redis on
  `web.session.redis_alias`; that alias must exist in `redis`.

Do not set `web.mcp.allow_anonymous: true` unless the user asked for an open endpoint.

## 4. Write tools, resources and prompts

```python
from oldman.mcp import ToolError, mcp
from oldman.web import Request

from apps.reports.permissions import ReportPermissions


@mcp.tool(permission=ReportPermissions.view)
async def count_reports(request: Request, status: str) -> int:
    """Count the reports in one status: draft, sent or archived."""
    if status not in ("draft", "sent", "archived"):
        raise ToolError("status must be draft, sent or archived")
    ...


@mcp.resource("reports://{report_id}")
async def report(report_id: int) -> dict | None:
    """One report as JSON."""
    ...  # return None when it does not exist


@mcp.prompt()
async def weekly_summary(week: str) -> str:
    """Ask for a summary of one ISO week's reports, e.g. 2026-W43."""
    return f"Summarise the reports of week {week}."
```

- `async def` only. The docstring is what the model reads: say what the tool does and when to use it.
- Annotate every parameter and the return type; the annotations become the JSON schemas. Import those types at run
  time, not under `if TYPE_CHECKING:`, or `install_mcp` stops with an error naming the type.
- Take `request: Request` as the first parameter only when the code needs the caller (`request.ctx.user`).
- Raise `ToolError("…")` for a failure the model should read; anything else is logged and the model only sees
  "The tool failed".
- Return plain data (a model, a dict, a number): structured output is generated from the return annotation. A
  container of msgspec Structs (`list[Struct]`) has no schema and stops `install_mcp`; return a Struct that holds the
  list instead.
- `permission=` hides the item from, and refuses it to, users without that permission. API-key callers and anonymous
  callers have no permissions: give them only items without `permission=`. Declare permissions in `permissions.py`
  (`docs/public/zh/developers/permissions.md`).
- Tool names: up to 128 of `A-Z a-z 0-9 _ - .`; names, resource URIs and prompt names must be unique across all Apps.
- Prompt parameters must be `str`. Resource URI variables are simple `{name}` placeholders, one per function parameter.

## 5. Verify

- Unit-test the functions directly: they are plain async functions (pass a `request` whose `ctx.user` you built).
- Start the service and call the endpoint, here with an API key named in `web.mcp.callers`:

```sh
curl -s http://127.0.0.1:<port>/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H 'MCP-Protocol-Version: 2025-11-25' -H 'X-API-Key: <key>' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

  The answer lists the tools this caller may see. `{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params":
  {"name": "<tool>", "arguments": {...}}}` calls one. A 404 means the endpoint is off (`web.mcp.enabled`), a 401 that
  no credential was recognised, a 403 a credential this route refuses (or an API key missing from `web.mcp.callers`).
- To add the server to Claude Code: `claude mcp add --transport http <name> http://127.0.0.1:<port>/mcp --header "X-API-Key: <key>"`.

The endpoint answers in JSON only: no progress notifications, no subscriptions, no sessions. A tool that needs more
than `web.response_timeout` (default 120 s) is cut off; for long work, start it in the background
(`en/agents/background-work.md`) and give the model a tool that reports its status.
