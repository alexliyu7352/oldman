# Agent guide: services, Apps and API endpoints

Use this guide to add an API endpoint (usually backed by a table) to an Oldman project, or to create the project itself.
Paths such as `docs/public/zh/developers/cli.md` are relative to the framework repository, which in a generated project
is your `.oldman-docs/` clone. Before using any `oldman` import, look it up in the [API index](../api/README.md).

## The common path: an endpoint backed by a table

This is the complete sequence, verified on a generated `api` project with SQLite whose service is `api`. Replace
`notes`, `Note` and the fields with what the user asked for; keep every step.

### 1. Create and register the App

```sh
OLDMAN_ANSWER_STARTAPP_TEMPLATE=api ./run.sh startapp notes
```

`startapp` writes `apps/notes/` with `apps.py` (the one AppConfig instance named `app`), `models.py`, `views.py` and
`migrations/`. Do not write an App package by hand. It does not register the App: add `apps.notes` to `apps` in
`data/api_settings.yaml`, then fill in any new settings:

```sh
./run.sh api settings sync
```

### 2. Declare the model

`apps/notes/models.py`:

```python
"""Data models for notes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import DatabaseModel
from oldman.utils.date import naive_utcnow


class Note(DatabaseModel):
    """A short note with a title and a body."""

    __tablename__ = "notes_note"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow)
```

`DatabaseModel` has no automatic id: declare the primary key. Name the table explicitly. Columns and types come from
SQLAlchemy; Oldman adds no query language.

### 3. Create and apply the migration — the user runs these

```sh
./run.sh db makemigrations
./run.sh db migrate
```

Both ask questions that need a real terminal: the first run on a new database, and every `makemigrations`. Without a
terminal they stop with "This migration decision requires an interactive terminal." Do not work around that: ask the
user to run the two commands (in Claude Code they can type `! ./run.sh db makemigrations`). Tell them what they will
be asked:

1. "Is this first use or was the state lost?" — `first use` for a new database.
2. "Migration description" — Enter keeps the suggestion, e.g. `create notes_note`.
3. `db migrate`: the first-use question again, then "Choose the migration scope" — `all`.

Once the database is initialized, `./run.sh db status` and `./run.sh db migrate` also run without a terminal. Check the
result yourself with `./run.sh db status`; it must show `pending=none` for the App. Never create, alter or drop tables
another way: no `create_all`, no SQL DDL, no scripts that write the migration state tables. Services never migrate on
start.

### 4. Write the endpoints

Replace the examples in `apps/notes/views.py`:

```python
"""HTTP API for notes."""

from __future__ import annotations

from sqlalchemy import select

from apps.notes.models import Note
from oldman.db import db_manager
from oldman.web import BadRequest, NotFound, Request, json_response, router


@router.post("/notes", name="notes_create")
async def notes_create(request: Request):
    """Create a note from a JSON body with ``title`` and an optional ``body``."""
    data = request.json if isinstance(request.json, dict) else {}
    title = str(data.get("title", "")).strip()
    if not title:
        raise BadRequest("title is required")
    async with db_manager.get_session() as session:
        note = Note(title=title, body=str(data.get("body", "")))
        session.add(note)
        await session.flush()
        payload = note.model_dump_dict()
    # The session commits when the block exits; answer only after that succeeded.
    return json_response(payload, status=201)


@router.get("/notes", name="notes_list")
async def notes_list(request: Request):
    """Return every note, newest first."""
    del request
    async with db_manager.get_read_session() as session:
        notes = (await session.execute(select(Note).order_by(Note.id.desc()))).scalars().all()
        return json_response([note.model_dump_dict() for note in notes])


@router.get("/notes/<note_id:int>", name="notes_detail")
async def notes_detail(request: Request, note_id: int):
    """Return one note, or 404 when it does not exist."""
    del request
    async with db_manager.get_read_session() as session:
        note = await session.get(Note, note_id)
        if note is None:
            raise NotFound("note not found")
        return json_response(note.model_dump_dict())
```

- Writes use `db_manager.get_session()`: it commits when the block exits normally and rolls back on an exception.
  `flush()` assigns the id; do not `commit()` inside the block yourself. Build the response inside, return it after.
- Reads use `db_manager.get_read_session()`.
- Raise `BadRequest`, `NotFound` and the other errors from `oldman.web`. The error body follows the request's
  `Accept` header: JSON for `Accept: application/json`, a text page otherwise.
- The views module is loaded because the App is registered; there is no route list to edit.

### 5. Run it and check real requests

Set `web.listen_host: 127.0.0.1` in `data/api_settings.yaml` (and another `web.listen_port` if 17998 is taken), then:

```sh
./run.sh api start          # foreground; run it in the background while you test
curl -s -X POST http://127.0.0.1:17998/notes -H 'Content-Type: application/json' -d '{"title":"First","body":"hello"}'
curl -s -X POST http://127.0.0.1:17998/notes -H 'Content-Type: application/json' -d '{"body":"no title"}'   # 400
curl -s http://127.0.0.1:17998/notes
curl -s -H 'Accept: application/json' http://127.0.0.1:17998/notes/999                                      # 404
./run.sh api stop
```

Stop the service with `./run.sh api stop` only. Never use `killall`, `pkill` or kill processes by name or port.

## Starting a new project

Install the CLI for the documented version with uv (`--python 3.13` because `uv tool install` does not check the
package's `requires-python`), then answer the two questions up front: an agent's shell is not a terminal, and without
the answers the command stops and names the variable it needs. Piped answers are not read.

```sh
uv tool install --python 3.13 oldman
OLDMAN_ANSWER_STARTPROJECT_TYPE=api OLDMAN_ANSWER_STARTPROJECT_DATABASE=sqlite oldman startproject my_site
cd my_site
uv sync
./run.sh api settings sync
./run.sh api settings check
./run.sh api start
```

Project types are `cli`, `service`, `api`, `web`, `dashboard`; databases are `none`, `sqlite`, `mysql`, `postgres`
(`dashboard` needs one). The full table of preset answers is in `docs/public/zh/developers/cli.md`. A new
service has no business routes yet: `/` answers 404. If uv itself is missing, the user installs it
(`curl -LsSf https://astral.sh/uv/install.sh | sh`); do not run installers on their machine without asking.

### Using a local framework checkout instead of the published package

Only when the user develops Oldman itself. In the new project, instead of `uv sync`:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r pyproject.toml --editable /path/to/oldman
```

Skip `uv venv` when `.venv` exists and belongs to this project. Afterwards use `./run.sh` or `.venv/bin/python`, not
`uv sync`/`uv run`, which would reinstall the published package. The project's dependency file is not changed.

## Where code goes

| Need | Choice |
| --- | --- |
| An existing site needs an API | Add views to an installed App; no new port |
| Its own listen address, settings or process boundary | A new `WebApplication` service |
| Long-running work without HTTP | `SimpleApplication` |
| Async functions queued durably, shared by several processes | `TaskiqWorkerApplication` (see `docs/public/zh/agents/distributed-tasks.md`) |
| Publishing due schedules and delayed retries | `TaskiqSchedulerApplication`; one per namespace |
| A one-off operation (import data, create an admin) | A `Command` in an installed App |

The service name is the file name: `services/<name>.py`, configured by `data/<name>_settings.yaml`. Do not add a
second service id. Services run as separate processes, share the project's one root Settings type and each read their
own YAML. Migrations stay project-level (`./run.sh db …`, not `./run.sh <service> db …`).

To add a service to an existing project, pick its type (`simple`, `web`, `taskiq_worker`, `taskiq_scheduler`):
`OLDMAN_ANSWER_STARTSERVICE_TYPE=simple ./run.sh startservice collector`, then `./run.sh collector settings init` for its
new settings file. Existing files use `settings sync` and `settings check`;
nothing rewrites settings at start. Each service lists its Apps explicitly: putting a models file in a directory does
not install it.

Work that continues after a request returns, and work that must survive a restart, are covered by
`docs/public/en/agents/background-work.md`.

## A one-off project command

Commands live in an installed App's `commands.py` and are listed in its `__all__`; the App's display name groups them
in `--help`, and they run as `./run.sh <service> <command>`. The full contract is in
`docs/public/zh/developers/cli.md` (section "自定义 App 命令"). The EPG Demo's `ProjectStats`
(`apps/examples/commands.py`, run as `./run.sh web project-stats [--team-id 1]`) shows the shape:

- The entry point is `async handle()`. Options are validated with `typing.Annotated` and `typer.Option`
  (`Annotated[int | None, typer.Option(min=1)]`); do not parse argv yourself.
- It reads existing records; an empty result succeeds, a missing team or a database error fails. Do not catch SQL
  errors and report success.
- The command selects a service's settings but starts no HTTP listener or background receivers.
- The session closes with its `async with` block. A command that owns `db_manager` releases it in its own `finally`;
  do not call such a command's `handle` from a web request.
- Built-in commands such as `loaddata`, `dumpdata` and `createsuperuser` already exist; do not copy them into an App.

## Shell and IDE

Run `./run.sh <service> shell` for a bootstrapped Python shell, or in an IDE call `bootstrap_service("<service>")`
(`from oldman import bootstrap_service`) before importing App models. One process uses one service's settings. Code
that reads settings outside a bootstrapped service fails with "Oldman settings are not configured".

## The EPG Demo as a reference

The full Demo (`https://github.com/alexliyu7352/oldman-epg-dashboard`) is a separate repository. Its `services/web.py`
is a `WebApplication` that also installs CSRF, templates and the browser bundle; `services/task_worker.py` and
`services/task_scheduler.py` are Taskiq services; `services/nats_a.py` and `services/nats_b.py` are `SimpleApplication`
receivers. Useful files: `config/schemas.py` and `config/settings.py` (the one root Settings type),
`data/web_settings.example.yaml`, `apps/examples/apps.py` (AppConfig label, display name, icon and the `app`
instance), `apps/examples/models.py`, `apps/examples/views/tables.py` (routes, permissions, queries, responses). These
are a dashboard's wiring: a plain API service does not need its session, Redis or front-end setup.

## Done means

1. The App is registered in the service's `apps`, settings were synced, and the service starts.
2. Real requests were made: the success path and at least one failure (validation error, missing record). A failed
   write adds no row.
3. Every model change has a migration made by `db makemigrations` and applied by `db migrate`; `db status` shows
   nothing pending.
4. A one-off command starts no HTTP; a background service loads no web views.
5. Every process you started is stopped with the project's stop command; nothing of the user's is stopped.

`AppNotInstalledError` or "settings are not configured" means the load order is wrong; see
`docs/public/zh/developers/applications.md` (section "实际加载顺序"). Do not add default-settings fallbacks, aliases
or resets to get past it.
