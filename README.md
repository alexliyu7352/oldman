# Oldman

English | [简体中文](https://github.com/alexliyu7352/oldman/blob/main/README.zh-CN.md)

**The whole back end of a business application, in one Python framework.** Dashboards, the admin site, APIs, background jobs, service-to-service messaging, terminal ops tools and an MCP endpoint for AI agents share one set of settings, permissions and UI. Oldman runs on Sanic; measured on the same machine, it serves about 1.8 times as many requests per second as FastAPI.

![The channel list in the EPG dashboard demo: a table with search, column and export menus and pagination, in the dashboard shell with its sidebar](https://raw.githubusercontent.com/alexliyu7352/oldman/main/website/static/img/epg-channels-light.webp)

**For coding agents:** start with the [Agent Guide](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md), read the documentation of the installed version's tag, and look up every `oldman` import in the [API index](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/api/README.md). A project not created by `oldman startproject` has no `AGENTS.md`; paste [this section](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md#existing-projects-a-section-for-your-own-instruction-file) into the project's own `AGENTS.md` or `CLAUDE.md`.

## Why Oldman

### One framework for the whole back end

A project can run several services. Each reads its own YAML and installs the Apps it needs, while all of them share one typed settings model, the same models, permissions and lifecycle:

- **Web**: business dashboards and the built-in Admin, rendered on the server with Sanic and Jinja.
- **APIs**: one authentication pipeline for sessions, JWT, API keys, HTTP Basic and IP allowlists.
- **Background work**: in-process coroutines, subprocesses and long-lived workers; durable Taskiq tasks on NATS JetStream with results, broadcasts and schedules.
- **Service-to-service messaging**: NATS events and RPC.
- **Terminal ops tools**: numbered menus, forms, an unattended mode with preset answers, remote scripts and systemd operations.
- **MCP server**: hand your Apps' data to AI agents, described below.

The [EPG demo](https://github.com/alexliyu7352/oldman-epg-dashboard) is one such project: `./run.sh web start`, `./run.sh task_worker start`, `./run.sh task_scheduler start` and `./run.sh nats_a start` start the web pages, the task workers, the schedule sender and a NATS receiver, all on the same settings type and the same models.

### A complete back office out of the box

- **`oldman startproject` with the dashboard type** generates sign-in and sign-out, a profile page (password change, language switch), a notification center, user management, and role and permission management, with the frontend build and the shared UI already wired. Password reset and token endpoints are one ready-made flow each.
- **The built-in Admin** works like Django admin: register a model and you get its list, search, sorting, create, edit, delete and CSV export. It needs no frontend build; its browser assets ship in the Python package.

```python
class DemoProjectAdmin(ModelAdmin):
    list_display = ("id", "name", "owner", "status", "is_active", "created_at")
    search_fields = ("name", "owner", "status")
    ordering = ("name",)
```

### Interactive pages with little frontend code

Tables, forms, modals, charts and live updates are declared in Python. The browser components come from `oldman-web`, which mounts and cleans them up as pages change, so you write TypeScript only where a page really needs it. The channel table in the screenshot above (search, sorting, pagination, row selection, column choice and CSV export) comes from this one class (excerpt):

```python
class ChannelsEpgTable(SQLAlchemyTableView):
    route_path = "/channels-epg/table"
    model = ChannelsEpg
    page_size = 10
    selectable = True
    export_formats = ("csv",)
    search_fields = ["name", "src_url", "country"]
    columns = [
        (_("ID"), "id"),
        (_("Name"), "name"),
        (_("Source URL"), "src_url", "get_column_src_url_data"),
        (_("Country"), "country"),
        (_("Hits"), "hits"),
        (_("Last Date"), "last_date"),
        (_("Action"), None, "get_column_action_data"),
    ]
```

The built-in Admin and your dashboards use the same components, styles and response protocol, so there is one frontend to maintain.

### Built for the AI era

- **A built-in MCP server.** Apps declare tools, resources and prompts with decorators, and the Web service offers them to AI agents such as Claude Code and Cursor behind the same authentication, permissions and rate limits. It is a route in your Web service: no second server and no dependency on the official SDK.
- **Material written for coding agents.** A project created by `oldman startproject` has an `AGENTS.md`; an existing project pastes a ready-made section into its own `AGENTS.md` or `CLAUDE.md`. The framework has English agent guides and an API index generated from the source, so an agent can wire new features correctly.

```python
@mcp.tool(permission=ReportPermissions.view)
async def count_reports(request: Request, status: str) -> int:
    """Count reports in one status."""
    async with db_manager.get_read_session() as session:
        ...
```

### Fast

Oldman runs on Sanic, and its authentication and middleware add next to no overhead:

| One worker, returning the same JSON | Requests per second | p99 latency |
| --- | ---: | ---: |
| **Oldman 0.8.0** (every request goes through the authentication pipeline) | **about 20,300** | **6.1 ms** |
| Sanic 25.12 (used directly) | about 17,900 | 6.8 ms |
| FastAPI 0.159 + uvicorn (responses encoded with orjson) | about 13,000 | 9.2 ms |
| FastAPI 0.159 + uvicorn (default style) | about 11,100 | 10.7 ms |

Setup: one AMD Ryzen 7 3800X, Python 3.13.11; each service ran one worker pinned to the same CPU; oha with 64 connections ran three 15-second rounds and the median is shown; uvicorn used uvloop and httptools. Oldman was the API project `startproject` generates, unchanged. This micro-benchmark measures framework overhead only; in real applications the database and outside calls usually dominate.

### The details production needs are done

- Typed settings: one root Settings type per project and typed settings per App; `settings sync` fills in missing fields by type and keeps existing values and comments.
- Security: CSRF, rate limits on sign-in and MCP, password-reset tokens, and every session and token revoked after a password change or deactivation.
- Processes: Web services, workers and schedulers hold a PID lock and stop as a whole process group, forced and confirmed after a timeout.
- Simplified and Traditional Chinese translations built in; a project's own text goes through the same extract, translate and compile pipeline.
- Built on proven libraries: Sanic, SQLAlchemy, Alembic, Jinja, WTForms, Taskiq and NATS, not a second set of foundations.

## Compared with the usual stack

| You need | The usual way | Oldman |
| --- | --- | --- |
| An admin site | Django's built-in admin; with FastAPI, a third-party library such as SQLAdmin | The built-in Admin, sharing one UI with your own pages |
| A business back office with accounts and permissions | Build the pages yourself or adapt a frontend template | `startproject` generates sign-in, user, role and permission management |
| Interactive pages | A separate React or Vue frontend, or wiring htmx yourself | Tables, forms and modals declared in Python, on shared components |
| Durable tasks | Add a task queue such as Celery | Taskiq on NATS JetStream, built in |
| Events and RPC between services | Pick a messaging library and wire it yourself | NATS events and RPC, built in |
| Terminal ops tools | Separate Click or Typer scripts | The same App commands, with terminal menus and forms |
| An interface for AI agents | Install the MCP SDK and wire authentication yourself | A built-in MCP server on your existing authentication and permissions |

## Quick start

Install [uv](https://docs.astral.sh/uv/), which manages Python environments and dependencies and installs the `oldman` command:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --python 3.13 oldman
oldman startproject my_site
```

On its first run, `startproject` asks for the command line's display language, then for the project type and the database. Choose `api` and `none` for a minimal API project:

```sh
cd my_site
uv sync
./run.sh api settings sync
./run.sh api start
```

The service has three endpoints: `/` is a health check that needs no credentials, while `/api/caller` and `/api/ops` show API key and HTTP Basic authentication; the generated project's README says where the credentials are and how to try them. For complete business pages, start by [running the EPG dashboard demo](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/getting-started.md), then follow its tutorials on [real data](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/tutorial-tasks.md) and [tables and Modal forms](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/tutorial-dashboard.md).

## Complete examples

- [EPG dashboard](https://github.com/alexliyu7352/oldman-epg-dashboard): a complete business back office on the dashboard skeleton, with accounts, notifications, user and role management, and UI and feature examples.
- [Built-in Admin](https://github.com/alexliyu7352/oldman-admin-demo): the built-in admin site as an application of its own.
- [Ops tool](https://github.com/alexliyu7352/oldman-ops-demo): a server maintenance tool in the terminal that edits sshd, sysctl and nginx sites and restarts services.

Each example is a Git repository of its own, with its settings, virtual environment, frontend dependencies and database; follow its README to run it.

## Documentation

- [Documentation site](https://alexliyu7352.github.io/oldman/): English, Simplified Chinese and Traditional Chinese, with local search.
- [User Guide](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/users/README.md): install, create a project and put it to use.
- [Developer Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/README.md): exact interfaces, load order and extension points.
- [Agent Guide](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/agents/README.md): for coding agents, which files to change for a task, how to wire them and how to verify.

## Requirements and limits

- Linux; Python `>=3.12,<3.15`, with 3.13 recommended.
- Two packages: `oldman` (PyPI) is the framework, and a plain API needs only that; `oldman-web` (npm) is the dashboard's browser side, so dashboard projects and the demos also need Node.js 20 or later and pnpm (`corepack enable` is enough). The built-in Admin's browser assets ship in the Python package.
- The SQLite driver is installed with the package; declare MySQL or PostgreSQL drivers as your project needs them. Redis entries in the settings do not connect at startup; Redis is needed only when a feature that uses it is enabled or called.
- Known issue: with `core.debug` on (asyncio debug mode), uvloop may raise or crash while collecting async generators that were never closed ([uvloop#699](https://github.com/MagicStack/uvloop/issues/699), [uvloop#715](https://github.com/MagicStack/uvloop/issues/715)). Production runs with debug off, the default, are not affected; see the [configuration reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/en/developers/configuration.md#web-defaults-and-switches).

## Source layout

```text
oldman/                       Python framework and packaged resources
frontend/packages/oldman-web/  browser package
frontend/apps/admin/          built-in Admin frontend source
examples/snippets/            partial usage snippets, not complete applications
tests/                        Python tests
scripts/                      maintenance and verification tools
docs/                         user, developer, and agent documentation
website/                      documentation site
```

See [PRODUCT.md](https://github.com/alexliyu7352/oldman/blob/main/PRODUCT.md) for product trade-offs.
