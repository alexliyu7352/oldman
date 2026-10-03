"""The parts of a new project's AGENTS.md that depend on what was generated.

The text every project shares is `oldman/scaffolds/project/common/AGENTS.md.tpl`. Each line here
names the projects it is for, by project type and by whether the built-in Admin was included, so the
five types share one list and differ only by the lines they leave out.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

# Whether one line belongs in a project: (project type, built-in Admin included).
Applies = Callable[[str, bool], bool]

# Projects with run.sh and a service, and those whose service answers HTTP.
SERVICE_TYPES = frozenset({"service", "api", "web", "dashboard"})
HTTP_TYPES = frozenset({"api", "web", "dashboard"})


def types(*names: str) -> Applies:
    """For the listed project types."""
    return lambda project_type, admin: project_type in names


def services(project_type: str, admin: bool) -> bool:
    return project_type in SERVICE_TYPES


def http_services(project_type: str, admin: bool) -> bool:
    return project_type in HTTP_TYPES


def everyone(project_type: str, admin: bool) -> bool:
    return True


def with_admin(project_type: str, admin: bool) -> bool:
    return admin


def signs_users_in(project_type: str, admin: bool) -> bool:
    """A dashboard always has its users; a web project when it includes the Admin."""
    return project_type == "dashboard" or admin


# Required reading by task, under `.oldman-docs/docs/public/` of the installed version.
GUIDES: tuple[tuple[Applies, str], ...] = (
    (services, "| Add an App, a route or an API endpoint | `en/agents/create-service.md` |"),
    (services, "| Add or change a database model | `en/agents/data-and-files.md` |"),
    (services, "| Work that continues after the response is sent | `en/agents/background-work.md` |"),
    (services, "| Persistent queue, job results, schedules | `zh/agents/distributed-tasks.md` |"),
    (services, "| Cache, Redis, outbound HTTP, NATS | `zh/agents/cache-and-network.md` |"),
    (services, "| Server-sent events, notifications | `zh/agents/realtime.md` |"),
    (types("dashboard"), "| A dashboard page: table, form, create/edit/delete | `zh/agents/dashboard-crud.md` |"),
    (with_admin, "| Show a model in the built-in Admin, or change how it does | `zh/agents/admin.md` |"),
)

RULES: tuple[tuple[Applies, str], ...] = (
    (
        services,
        "- Create an App with `OLDMAN_ANSWER_STARTAPP_TEMPLATE={startapp_template} ./run.sh startapp <name>`, then add\n"
        "  `apps.<name>` to `apps` in `data/{service_name}_settings.yaml` and run\n"
        "  `./run.sh {service_name} settings sync`. Do not write App packages by hand.",
    ),
    (
        services,
        "- Change the database schema only through `./run.sh db makemigrations` and `./run.sh db migrate`.\n"
        "  They ask questions that need a real terminal (also the first `db migrate` of a new database).\n"
        "  If you have no terminal, stop and ask the user to run the command (in Claude Code: `! ./run.sh db migrate`).\n"
        "  Never create, alter or drop tables yourself: no `create_all`, no SQL DDL, no scripts that write\n"
        "  the migration state tables.",
    ),
    (
        services,
        "- Database access: models subclass `oldman.db.DatabaseModel` in the App's `models.py`. Write with\n"
        "  `async with db_manager.get_session() as session:` (commits when the block exits normally),\n"
        "  read with `async with db_manager.get_read_session() as session:`; `db_manager` comes from `oldman.db`.",
    ),
    (
        http_services,
        "- Work after the response: fire-and-forget inside a web handler uses `request.app.ctx.tasks.spawn(...)`.\n"
        "  Work whose status or result someone will query, or that must survive a restart, uses Taskiq\n"
        "  (`zh/agents/distributed-tasks.md`). Never call `asyncio.create_task` in a view, never keep job state\n"
        "  in a module-level dict.",
    ),
    (
        types("service"),
        "- Background work in this service uses its own `self.task_manager.spawn(...)` (a coroutine function and\n"
        "  its arguments). Work whose status or result someone will query, or that must survive a restart, uses\n"
        "  Taskiq (`zh/agents/distributed-tasks.md`). Never call `asyncio.create_task` yourself, never keep job\n"
        "  state in a module-level dict.",
    ),
    (
        types("dashboard"),
        "- Every active user who signs in can open the dashboard; `startapp` pages have `login_required()`.\n"
        "  A page or endpoint that needs more says so with `staff_required()` or `require_perm(...)` from\n"
        "  `oldman.web.auth`, or a check of its own.",
    ),
    (
        types("dashboard"),
        "- Every endpoint that writes checks its own permission (not only the page that links to it) and\n  requires CSRF.",
    ),
    (
        types("dashboard"),
        "- A new page's menu entry goes in `templates/partials/sidebar.html`, the only menu.",
    ),
    (
        types("dashboard"),
        "- The sign-in, account and user pages come from the framework. To change how one looks, put a\n"
        "  template of the same name under `templates/`; do not copy the framework's code into the project.",
    ),
    (
        types("dashboard"),
        "- The frontend is in `frontend/`: install and build it there with `pnpm install` and `pnpm build`.",
    ),
    (
        signs_users_in,
        "- `./run.sh {service_name} createsuperuser` asks for a password in a terminal; ask the user to run it.",
    ),
    (
        services,
        "- Commands that ask for passwords or migration decisions need a terminal; ask the user instead of\n  working around them.",
    ),
    (
        services,
        "- Stop a service with `./run.sh {service_name} stop`. Never use `killall`, `pkill`, or kill\n"
        "  processes by name or port: other services on this machine are not yours.",
    ),
    (
        everyone,
        "- Do not edit the installed `oldman` package or copy framework code into this project. If the\n  framework lacks something, say so.",
    ),
)

FACTS: tuple[tuple[Applies, str], ...] = (
    (
        http_services,
        "- Service `<name>` is `services/<name>.py`, configured by `data/<name>_settings.yaml`.\n"
        "  This project's service is `{service_name}`; it listens on 17998 unless `web.listen_port` says otherwise.",
    ),
    (
        types("service"),
        "- Service `<name>` is `services/<name>.py`, configured by `data/<name>_settings.yaml`.\n  This project's service is `{service_name}`.",
    ),
    (services, "- The project has one root Settings type (`config/`); `apps` lists App packages explicitly."),
    (services, "- Each App package exports exactly one AppConfig instance named `app` (`startapp` writes it)."),
    (
        services,
        "- Code that reads settings works only inside a bootstrapped service; for experiments use\n  `./run.sh {service_name} shell`.",
    ),
    (services, "- Services never migrate on start."),
    (
        types("service"),
        "- `main()` in `services/{service_name}.py` is an example loop that logs a line every 10 seconds until\n"
        "  the service is stopped; replace its body with this service's work.",
    ),
    (
        types("api"),
        "- `apps/home/views.py` serves `/` (a health check, open to everyone), `/api/caller` (an API key in the\n"
        "  `X-API-Key` header) and `/api/ops` (HTTP Basic). The key and the account were generated with the\n"
        "  project; they are in `web.auth` of `data/{service_name}_settings.yaml`, which Git ignores.",
    ),
    (types("web"), "- `apps/home` serves the welcome page at `/`; every page extends `templates/base.html`."),
    (
        types("dashboard"),
        "- Every page needs a signed-in user. `apps/accounts` has the project's User model and installs the\n"
        "  framework's sign-in, account and user-management pages (`apps/accounts/routes.py`); `apps/home` is\n"
        "  the page after signing in.",
    ),
    (
        signs_users_in,
        "- Signing in keeps a session in Redis (`redis.SESSION` in the settings file); the service needs that\n  Redis running.",
    ),
    (
        with_admin,
        "- The built-in Admin is at `app_settings.admin.prefix` (default `/admin`); staff users sign in there.\n"
        "  Run `./run.sh {service_name} static collect` before starting, and again after upgrading the framework.",
    ),
    (
        types("dashboard"),
        "- First run, in order: Redis running; `uv sync`; `./run.sh {service_name} settings sync`; `./run.sh db migrate`\n"
        "  (terminal); `./run.sh {service_name} createsuperuser` (terminal); `pnpm install` and `pnpm build` in\n"
        "  `frontend/`; `./run.sh {service_name} static collect`; `./run.sh {service_name} start`.",
    ),
    (
        types("cli"),
        "- This is a script project: `main.py`, run with `uv run python main.py`. It has no `run.sh`, service,\n"
        "  settings file or database configuration; work that needs settings, an App or a model belongs in a\n"
        "  project of another type.",
    ),
)

DONE: tuple[tuple[Applies, str], ...] = (
    (everyone, "- You ran the real request or command and checked its output, including one failure case."),
    (services, "- Every new model has a migration generated by `db makemigrations` and applied by `db migrate`."),
    (services, "- Every process you started is stopped, using the project's stop command."),
)

GUIDE_STEP = """2. Read the guide for your task completely before writing code. It is required reading.

   | Task | Required guide (under `.oldman-docs/docs/public/`) |
   | --- | --- |
{rows}

"""


def selected(lines: Iterable[tuple[Applies, str]], project_type: str, admin: bool) -> list[str]:
    return [line for applies, line in lines if applies(project_type, admin)]


def agent_instructions(project_type: str, *, admin: bool, service_name: str) -> dict[str, str]:
    """The AGENTS.md template's variables for one project, every placeholder already filled in."""
    values = {"service_name": service_name, "startapp_template": project_type}

    def block(lines: Iterable[tuple[Applies, str]]) -> str:
        return "".join(line.format(**values) + "\n" for line in selected(lines, project_type, admin))

    guides = selected(GUIDES, project_type, admin)
    return {
        "agents_version_command": "./run.sh --version" if project_type in SERVICE_TYPES else "uv run oldman --version",
        # A script project has no guide to read first, so the index lookup becomes step 2.
        "agents_guide_step": GUIDE_STEP.format(rows="\n".join(f"   {row}" for row in guides)) if guides else "",
        "agents_index_step": "3" if guides else "2",
        "agents_rules": block(RULES),
        "agents_facts": block(FACTS),
        "agents_done": block(DONE),
    }
