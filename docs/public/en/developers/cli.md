# CLI reference

`oldman` is the command entry point supplied by the Python package. Its first two levels distinguish **project operations** from **operations on a selected service**, rather than putting every capability in one service.

The EPG demo's [run.sh](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/run.sh) only enters its project directory, executes that project's `.venv/bin/oldman`, and forwards arguments unchanged. Service examples below use its actual `web` service; `oldman` in the same environment behaves identically. See [Run EPG Dashboard Demo](../users/getting-started.md) for installation, data, and asset preparation. Invoking `run.sh` does not chain these steps automatically.

## Project-level commands

| Command | Purpose |
| --- | --- |
| `oldman --version` | Show the installed oldman version; no project directory required |
| `oldman startproject <directory>` | Create a project; interactively select type, database, and optional built-in Admin integration |
| `./run.sh startapp <name>` | Create a business App; interactively select its template and display name |
| `./run.sh startservice <name>` | Add a service; interactively select simple, web, taskiq_worker, or taskiq_scheduler |
| `./run.sh language list/show/set <language>` | List, show, or set CLI language; only set takes a language argument |
| `./run.sh i18n extract/init/update/compile` | Manage project translations; init requires a locale |
| `./run.sh db makemigrations/migrate/status/history/downgrade/retire` | Project database schema management; choose one subcommand per invocation |

Read command-specific help:

```sh
./run.sh --help
./run.sh db --help
./run.sh i18n init --help
```

`startproject` project types:

| Type | Generated content |
| --- | --- |
| `cli` | Ordinary Python script and dependencies, without services or automatic configuration |
| `service` | SimpleApplication in `services/service.py`; example `main()` logs every 10 seconds until `stop` |
| `api` | WebApplication in `services/api.py`, without frontend installation. Project App `apps.home` provides `/` health, `/api/caller` accepting only API keys, and `/api/ops` accepting only HTTP Basic. Both credentials are generated randomly into service `web.auth` settings, without database or Session requirements |
| `web` | WebApplication in `services/web.py` with asynchronous templates. `/` is an editable/removable welcome page in project App `apps.home`; `<html lang>` in `templates/base.html` follows request language |
| `dashboard` | Sign-in-ready scaffold with sign-in, home, profile, notifications, user/role management, a project User model, and Vite/Tailwind frontend; see [Frontend assets, styles, icons, and translation](assets.md#dashboard-scaffold-scope) |

Every project includes `AGENTS.md` with coding-agent instructions: clone documentation for the installed version into `.oldman-docs/`, task-specific required guides, rules, and facts varying by project type/Admin integration. `CLAUDE.md` contains only `@AGENTS.md`; `.gitignore` excludes `.oldman-docs/`. These files are generated at project creation, not updated on framework upgrades. Generated `pyproject.toml` sets `[tool.ruff] line-length = 150`, matching framework code (ruff defaults to 88 otherwise). Generated code and `startapp` Apps pass `ruff format --check` and `ruff check` with that width. Change that setting for your team's preference.

Database choices are `none`, `sqlite`, `mysql`, and `postgres`. CLI scripts do not ask for a database; dashboards require one. MySQL/PostgreSQL scaffolds declare drivers, but you still supply actual URLs, create databases, and apply migrations.

Database-enabled `web` and `dashboard` projects next ask whether to integrate the built-in Admin (default no). Choosing it installs `oldman.auth`, `oldman.apps.roles`, and `oldman.apps.admin`, generates a project User in `apps/accounts` like dashboard (`app_settings.auth.user_model` selects it), enables Session, and calls `install_admin(app)` in service `init()`. Admin mounts at `app_settings.admin.prefix` (default `/admin`) and shares sign-in state. Web without a database does not ask, since Admin users require storage. You can add it later by installing those Apps, enabling Session, and calling `install_admin`. Dashboards install user and role Apps regardless of this choice.

These choices use questions, not `startproject --type` or `--db`. For unattended CI/scripts/agents, use environment [Terminal interaction](tui.md#preset-answers-for-unattended-use); configured questions are not asked again:

```sh
OLDMAN_ANSWER_STARTPROJECT_TYPE=web OLDMAN_ANSWER_STARTPROJECT_DATABASE=sqlite oldman startproject my_site
OLDMAN_ANSWER_STARTAPP_TEMPLATE=api ./run.sh startapp reports
OLDMAN_ANSWER_STARTSERVICE_TYPE=taskiq_worker ./run.sh startservice worker
```

| Command | Question | Variable | Choices |
| --- | --- | --- | --- |
| `startproject` | Project type | `OLDMAN_ANSWER_STARTPROJECT_TYPE` | `cli`, `service`, `api`, `web`, `dashboard` |
| `startproject` | Database (not asked for `cli`) | `OLDMAN_ANSWER_STARTPROJECT_DATABASE` | `none`, `sqlite`, `mysql`, `postgres`; `dashboard` requires a database |
| `startproject` | Built-in Admin integration (database-enabled `web` and `dashboard` only) | `OLDMAN_ANSWER_STARTPROJECT_ADMIN` | `yes`, `no` (also true/false, 1/0); unset outside a terminal defaults to `no` |
| `startapp` | App template | `OLDMAN_ANSWER_STARTAPP_TEMPLATE` | `service`, `api`, `web`, `dashboard`, `mcp` (MCP tools/resources/prompts only; see [MCP server](mcp.md)) |
| `startapp` | Display name | `OLDMAN_ANSWER_STARTAPP_DISPLAY_NAME` | Any text; defaults to a name-derived value |
| `startservice` | Service type | `OLDMAN_ANSWER_STARTSERVICE_TYPE` | `simple`, `web`, `taskiq_worker`, `taskiq_scheduler` |

Values may also be choice numbers in displayed order. Invalid preset answers fail with the variable name and write no files. Outside a terminal, missing required answers also fail and identify the variable to set. Answers are not read line by line from pipes: `printf 'web\nsqlite\n' | oldman startproject my_site` does not work.

`startproject` creates minimal YAML; use `settings sync` afterward. `startservice` creates service code only, requiring subsequent `settings init`. `startapp` does not update service App lists.

## Service-level commands

The EPG demo uses [services/web.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/web.py). These show available entry points, not a requirement to start and then stop/restart each service. Choose the command for your operation:

```sh
./run.sh web settings sync
./run.sh web settings check
./run.sh web --help
./run.sh web start
./run.sh web stop
./run.sh web restart
./run.sh web shell
```

`start` runs in the foreground. `stop` reads the service PID, signals shutdown, waits for the entire group to exit, and prints “Stopped web (main process …)”; when absent it prints “web is not running”. `restart` stops before starting. Running `run.sh` without arguments does not start every service.

The demo also has task_worker/task_scheduler with the same hierarchy, such as `./run.sh task_worker start` and `./run.sh task_scheduler stop`. Both stop commands wait, then force-stop the identity-verified group at the total deadline, without another kill command. See [Taskiq interfaces and runtime](distributed-tasks.md) for Worker supervision and the single-Scheduler rule. Creating entry points does not change App lists or start other services.

Web services also provide:

```sh
./run.sh web static collect
```

Static collection copies incrementally by default. `--clear` removes tracked output; check the directory/help first, and do not target business uploads. Startup does not build or collect static assets automatically.

```sh
./run.sh web templates copy
```

Copy framework templates into `web.template.dir` (default `templates/`) with original relative paths, then edit project copies. Sources are shared `oldman/web/templates` plus installed framework Apps' `templates` directories (Admin templates only when installed). Missing files copy directly; identical files are skipped. Different existing files are listed before one overwrite-all confirmation (default no; unattended variable `OLDMAN_ANSWER_TEMPLATES_COPY_OVERWRITE`). Copies do not follow future framework upgrades. For one or two pages, same-name overrides or `framework:` inheritance are simpler; see [Web requests, templates, and permissions](web.md#enable-templates).

The demo's `WebService.get_default_commands()` retains parent commands and adds `dev`. `dev()` selects Vite assets then calls `start()`; it does not start Vite. Demo [scripts/dev.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/scripts/dev.py) manages both development processes; see [Frontend assets, styles, icons, and translation](assets.md) for wiring. Frontend dashboard scaffolds also provide dev; ordinary API/Web and Simple services do not acquire it automatically.

See [Configuration reference](configuration.md#configuration-file-selection) for `--config` scope and path behavior. Do not assume it is a global option shared by all commands.

### Data fixtures and user management

Runtime services provide two JSON data tools. The demo's [README](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/README.md) uses actual Examples App/ExampleProject data. These examples choose local `data/` export paths; names are user-selected, not fixed framework directories:

```sh
./run.sh web dumpdata examples --output data/examples-export.json
./run.sh web dumpdata examples.ExampleProject --output data/projects-export.json
./run.sh web loaddata data/examples-export.json
```

These demonstrate import/export, not instructions to reload your database immediately. Inspect existing files before overwriting exports. Initial demo data comes from `./run.sh web loaddata demo`, reading [apps/examples/fixtures/demo.json](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/fixtures/demo.json). See [Real demo data, migrations, and queries](../users/tutorial-tasks.md#4-import-repeatable-real-data) for primary keys, relationships, and repeat-import rules.

`dumpdata` selectors choose Apps/models registered by the current service; without `--output`, JSON goes to stdout. `loaddata` writes database rows; it is neither backup restoration nor schema migration. Verify target databases and conflict rules first. Do not use production tables for tutorials.

All services installing Auth (`oldman.auth`) have these two account commands, whether Admin is installed or not:

```sh
./run.sh web createsuperuser
./run.sh web changepassword admin
```

Migrate before creating accounts. Replace admin in `changepassword admin` with an existing username. Missing users fail without creation; password changes end all existing sign-ins for that user. Duplicate `createsuperuser` names also fail without modifying accounts. Passwords use hidden input and confirmation, not plaintext command arguments. Database creation does not create a default administrator. Scripts provide passwords through environment variables: `createsuperuser --noinput --username … [--email …]` reads `OLDMAN_SUPERUSER_PASSWORD`; `changepassword` reads preset `OLDMAN_ANSWER_CHANGEPASSWORD_PASSWORD` ([Terminal interaction](tui.md#preset-answers-for-unattended-use)). Neither reads passwords from pipes. These commands need App registration and a database, not mounted/running `/admin` pages.

## Custom App commands

App commands extend `oldman.cli.Command` and are publicly exported from App `commands.py`. Registry discovers them when the App is in service `settings.apps`; no second registration decorator is needed.

The EPG demo's [apps/examples/commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) implements actual `project-stats`: it queries ExampleProject, groups counts by status, and optionally filters team IDs. This excerpt retains the class and all required imports, omitting imports for eight other examples and the final export list. It is not the entire current file:

```python
"""Read real Demo data through the installed App command lifecycle."""

from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import func, select

from oldman.cli import Command
from oldman.db import db_manager
from oldman.i18n import gettext
from oldman.i18n import gettext_lazy as _

from .models import ExampleProject, ExampleTeam


class ProjectStats(Command):
    """Count projects without changing fixtures, records or cache snapshots."""

    name = "project-stats"
    help = _("Count example projects, optionally filtered by team.")

    async def handle(
        self,
        team_id: Annotated[int | None, typer.Option(min=1)] = None,
    ) -> None:
        """Read a fresh grouped count; CLI validation restricts the optional ID."""
        try:
            async with db_manager.get_read_session() as session:
                statement = (
                    select(ExampleProject.status, func.count())
                    .group_by(ExampleProject.status)
                    .order_by(ExampleProject.status)
                )
                if team_id is not None:
                    if await session.get(ExampleTeam, team_id) is None:
                        raise ValueError(gettext("Team %(team_id)s does not exist.", team_id=team_id))
                    statement = statement.where(ExampleProject.team_id == team_id)
                # The result has keys() — its column names — so dict() would read it as a mapping; take the rows.
                counts = dict((await session.execute(statement)).all())
            # Plain output keeps database values from being interpreted as Rich markup.
            typer.echo(gettext("Total projects: %(count)s", count=sum(counts.values())))
            for status, count in counts.items():
                typer.echo(f"{status}: {count}")
        finally:
            # One-shot commands do not run the Web service's shutdown listeners.
            await db_manager.close()
```

`apps.examples` is already in service YAML `apps`. Inherited `commands_module = "commands"` lets Registry discover this exported class without AppConfig/WebService changes. Help groups commands by App display name. Invoke it as follows:

```sh
./run.sh web --help
./run.sh web project-stats --help
./run.sh web project-stats
./run.sh web project-stats --team-id 1
```

Prepare settings/database first; see [Demo page and source index](../users/demo-examples.md#custom-app-commands) for steps and results. Here `web` selects service settings without opening a Web port. Default demo NATS/Taskiq settings make the command lifecycle connect to infrastructure, without starting receivers, Workers, or Scheduler. Disable `nats_bus.enabled`/`taskiq.enabled` when not trying those features; the command itself uses neither them nor Redis cache.

Typer checks `--team-id` type/minimum, returning exit 2 for invalid arguments. A missing team raises ValueError, displayed with exit 1; an existing empty team prints zero and exits 0. Missing tables or inaccessible databases also exit 1 without creating tables/importing fixtures. Status groups use actual database values, sorted and displayed only when present. Every run queries anew, not the cache-page snapshot.

Read-session context managers close Sessions; `finally` also releases this command's database pool after query failure. One-off commands do not run Web stop listeners, so `WebService.before_server_stop()` cannot clean up for them. This is command resource ownership, not a statistics helper for concurrent requests. It prints ordinary text through `typer.echo()` and returns None, preventing Rich from interpreting database strings as markup. Questions use [Terminal interaction](tui.md) (`tui.ask`, `tui.confirm`, etc.); built-in [Admin commands](https://github.com/alexliyu7352/oldman/blob/main/oldman/apps/admin/commands.py) provide examples.

`name` matches `[a-z][a-z0-9-]*`; use hyphens for command names and underscores for Python parameters. `help` must be nonempty text or `LazyTranslation`. Classes must construct without arguments; `handle()` must be `async def`, returning a result for CLI printing or writing output itself and returning None.

Parameters follow Typer: no default usually means positional; a default usually means option. Set explicit constraints through `Annotated[..., typer.Option(...)]` or `typer.Argument(...)`. Ask through [Terminal interaction](tui.md) instead of custom input parsing. Give questions keys for unattended use.

App command names must be unique within a service and not conflict with existing service, settings/static/Shell, or fixture commands. App display names group help without adding command levels. Use `web changepassword`, not `web admin changepassword`.

Registry enumerates non-underscore public variables in command modules, selecting concrete Command subclasses, including imports. It does not use `__all__` as a registration inventory. Demo BackgroundStats and others enter through ordinary imports in commands.py. Changing `__all__` alone neither registers unimported classes nor hides publicly imported ones.

If `commands_module` is a package, import required Command classes explicitly in its `__init__.py`. Registry does not recurse through Python files; do not export one class under multiple public names. Use private import aliases for concrete internal helpers; abstract public bases are not instantiated.

### Command lifecycle

With models loaded, App commands follow this flow:

```text
Construct the selected service Application
→ Configure command logging
→ Initialize Storage in the same event loop
→ Open enabled Core NATS send connections
→ Open enabled Taskiq publication connections
→ await application.before_command(name, ...)
→ await command.handle(...)
→ await application.after_command(name, ...)
→ Taskiq shutdown (native hooks may still call Core)
→ Close Core NATS
→ Wait for model-cache invalidation writes
→ Close cache, Redis, and database engines
→ Close logging resources for this command
```

This does not run service `init()`, `prepare()`, `main()`, `prepare_server()`, or Web start/stop listeners, so executing commands does not bind HTTP ports. Override `before_command()` for service-level command initialization; close related resources in `after_command()`. Business `handle()` may also use context managers/finally for its own resources.

Core sends/RPC only: consume=true neither loads App events nor starts subscribers. Ordinary commands do not load all tasks automatically. Disabled capabilities create no corresponding connections. Initialization/handle/after_command failures still enter communication finally, retaining original errors and separately logging cleanup failures. DB/HTTP resources retain their ownership rules. Import bus directly in commands without another manual async with. Settings/help, database commands, and bootstrap/Shell do not run this async command chain; see [Redis and NATS providers](providers.md#shell-ide-and-independent-connections) for explicit Shell communication.

Command files under `logging.dir` are named by command and contain INFO and above. Terminals normally show warnings/errors only. Return results or use [Terminal interaction](tui.md) for user output, not `logger.info()`. DEBUG (`core.debug` or `logging.level: DEBUG`) shows all terminal logs. Service `start` is unaffected.

Do not connect databases, read requests, or start tasks in Command constructors. CLI displays errors and exits with failure. Do not swallow exceptions and return success text.

Two optional class attributes:

- `check_pid = True`: serialize same-name commands for one service using `<service>.<command>.pid` under `process.pid_dir`. Default false; this is not distributed or cross-machine locking.
- `raw_stdout = True`: send command logs to stderr for machine-readable stdout. Default false. Commands must also avoid explanatory text in data streams. With [Terminal interaction](tui.md), all explanatory output, tables, and waiting indicators except `echo` automatically use stderr.

## Database command scope

Migration commands collect default YAML from actual project services, merge App lists, and require database URLs to be **exactly identical strings** across database-enabled services. Auth-enabled services must also select the same concrete User.

Migrations neither publish one service's App Settings, start services, nor load views/App commands. Model declarations must not depend on service-specific `app.settings` and produce different structures for the same table across processes.

Apps store standard Alembic revisions; the framework supplies a common Alembic environment and directory wiring. Generation selects an App; execution follows revision dependencies, not menu/configuration order.

First use, state recovery, renaming, and deletion require interactive terminals; do not expect `echo yes | ...` to bypass decisions. Run `makemigrations` and `migrate` separately so generated files can be reviewed first.

`downgrade` runs reverse migrations and may delete data. `retire` stops managing an App's schema while retaining physical tables; it is not Python package removal. Choose explicit targets before either operation, rather than treating them as routine onboarding.

## CLI language

```sh
./run.sh language list
./run.sh language show
./run.sh language set zh-Hans
```

Built-in CLI languages are `en`, `zh-Hans`, and `zh-Hant`. Preferences live in `oldman/cli.json` in the user's XDG config directory without changing service YAML. `OLDMAN_CLI_LANGUAGE` overrides one command, independently of business Settings' YAML-only rule.

App command help uses `gettext_lazy()` and translates at runtime. Python, Jinja, and CLI share the `messages` catalog without a separate CLI domain.

Missing translations fall back to original text. After command-copy changes, extract, complete simplified/traditional Chinese translations, and compile. Framework CLI messages live in `oldman/locales`; see instructions at the start of [scripts/framework_i18n.py](https://github.com/alexliyu7352/oldman/blob/main/scripts/framework_i18n.py).

<!-- source: zh/developers/cli.md @ f65caa13 -->
