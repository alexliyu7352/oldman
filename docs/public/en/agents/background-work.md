# Agent guide: work that runs in the background

Use this guide whenever work should continue after a request has been answered, run on a schedule, run in another process,
or start an external program. Paths such as `docs/public/zh/developers/background.md` are relative to the framework
repository (your `.oldman-docs/` clone). Look up every `oldman` import in the [API index](../api/README.md).

## Choose by what the work needs

| The work… | Use |
| --- | --- |
| is fire-and-forget inside a web request (send a mail, write an audit line, handle a webhook) | `request.app.ctx.tasks.spawn(...)` — below |
| has a status or result someone will ask for, or must survive a restart or run in another process | Taskiq plus a database record — below |
| runs periodically inside one process | `BackgroundTaskManager`, or a `SimpleApplication` service's own `main()` |
| is synchronous CPU work that should not block the loop | `AsyncProcessManager` |
| is an external program nobody answers (a web service, a Taskiq worker, a machine job) | `run_subprocess_exec` / `create_subprocess_exec` |
| is an external program a person may answer (`sudo` asking for a password, a script with `read`) | `run_foreground` |
| needs several long-lived workers taking start/stop instructions | `BaseManager`, `BaseWorker`, `BaseTask` |
| is a message or RPC between separate services | the NATS provider (`docs/public/zh/developers/providers.md`) |

Never call `asyncio.create_task` in a view and never keep job state in a module-level dict: the task is not tracked,
nothing reports its failure, the state disappears on restart, and each worker process has its own copy. Do not add Redis,
NATS, a worker and new tables just because the user said "background": pick the row that matches.

## Fire-and-forget in a web request

Answer first, then process in the background with a time limit. The limit lives in the coroutine you hand over:

```python
import asyncio

from oldman.web import Request, json_response, router


async def process_update(update: dict) -> None:
    ...  # the business work


async def process_update_within(update: dict, seconds: float) -> None:
    async with asyncio.timeout(seconds):
        await process_update(update)


@router.post("/hooks/update", name="hooks_update")
async def hooks_update(request: Request):
    """Answer at once; handle the update in the background, for at most a minute."""
    request.app.ctx.tasks.spawn(process_update_within, request.json, 60)
    return json_response({"ok": True})
```

Verified: the reply took about 10 ms and the background work logged its result a second later.

- `spawn(coro_func, *args, name=None, **kwargs)` starts a one-time task at once and returns the `asyncio.Task`. When it
  ends (success, failure or cancellation) it is removed; a failure is logged and not retried. A timeout raises
  `TimeoutError` and is logged the same way.
- Pass the coroutine **function** and its arguments. Do not write `spawn(asyncio.wait_for, process_update(...), 60)`:
  that coroutine object is created before the task is registered and is never awaited if the service stops first.
- The work runs in the web worker process that received the request and stops with the service. Nothing records
  whether it finished: when anyone needs to know, use Taskiq and a record instead.
- The coroutine gets plain values (here the request JSON), not the request object or an open session.

## Work with a status or result: Taskiq and a record

Taskiq runs the function durably in a separate worker service (NATS JetStream keeps the queue, Redis keeps results and
schedules). The status the user asks for comes from a **database record** the task updates, because a missing Taskiq
result can mean "not finished", "expired", "ignored" or "wrong namespace" and never proves the task is still running.

If the project has no NATS and Redis yet, tell the user what this needs before adding it: a NATS server with JetStream,
a Redis server, and one more service process to run.

Verified on a generated `api` project with SQLite (services `api` and `worker`): a report went `queued` → `running` →
`done` with its content, and a report whose work raised went to `failed` with the error.

### 1. Settings and the worker service

```sh
OLDMAN_ANSWER_STARTSERVICE_TYPE=taskiq_worker ./run.sh startservice worker
./run.sh worker settings init
```

In **both** `data/api_settings.yaml` and `data/worker_settings.yaml`, point the connections at the user's NATS and Redis
and enable Taskiq with one shared namespace:

```yaml
nats:
  DEFAULT:
    nats_url: nats://127.0.0.1:4222
redis:
  DEFAULT:
    redis_url: redis://127.0.0.1:6379/3
taskiq:
  enabled: true
  namespace: shop
  nats_alias: DEFAULT
  redis_alias: DEFAULT
```

Both services must use the same NATS, namespace and Redis database. The worker also needs the App
(`apps: [apps.notes]`) and the same `database.url` as the web service. Never point these at a Redis or NATS you were not
told to use. `workers`, `max_async_tasks`, `max_prefetch` and `consume_queues` are the worker's consumer settings;
the web service only publishes and does not need them.

### 2. The record

In `apps/notes/models.py` (then the user runs `./run.sh db makemigrations` and `./run.sh db migrate`, see
[the create-service guide](create-service.md)):

```python
class Report(DatabaseModel):
    """One requested report and how far its generation got."""

    __tablename__ = "notes_report"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow)
```

### 3. The task

`apps/notes/tasks.py` (the App's default tasks module; the worker loads it by itself):

```python
"""Background jobs for notes, run by the Taskiq worker service."""

from __future__ import annotations

import asyncio

from apps.notes.models import Report
from oldman.db import db_manager
from oldman.tasks.distributed import broker


async def _record(report_id: int, **changes: str) -> None:
    async with db_manager.get_session() as session:
        report = await session.get(Report, report_id)
        if report is not None:
            for field, value in changes.items():
                setattr(report, field, value)


@broker.task
async def generate_report(report_id: int) -> None:
    """Build one report, recording on its row when it starts, finishes or fails."""
    await _record(report_id, status="running")
    try:
        await asyncio.sleep(5)  # the real work goes here
        content = f"Report {report_id} is ready."
    except Exception as exc:
        await _record(report_id, status="failed", error=str(exc))
        raise
    await _record(report_id, status="done", content=content)
```

Pass plain, serializable values such as record ids and load data inside the task; never a request, a session, an ORM
object or a connection. `from oldman.tasks.distributed import broker` works only after the service is bootstrapped with
`taskiq.enabled: true`, which is the case for `tasks.py` and `views.py`.

### 4. Submit and query

In `apps/notes/views.py` (add `from apps.notes import tasks` and import `Report`):

```python
@router.post("/reports", name="reports_create")
async def reports_create(request: Request):
    """Record a report request, queue its generation and answer at once with its id."""
    del request
    async with db_manager.get_session() as session:
        report = Report(status="queued")
        session.add(report)
        await session.flush()
        report_id = report.id
    # Queue only after the row is committed, so the worker always finds it.
    try:
        await tasks.generate_report.kiq(report_id)
    except Exception:
        async with db_manager.get_session() as session:
            report = await session.get(Report, report_id)
            if report is not None:
                report.status = "failed"
                report.error = "could not be queued"
        raise
    return json_response({"id": report_id, "status": "queued"}, status=202)


@router.get("/reports/<report_id:int>", name="reports_detail")
async def reports_detail(request: Request, report_id: int):
    """Return a report's status, and its content once done."""
    del request
    async with db_manager.get_read_session() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise NotFound("report not found")
        return json_response(report.model_dump_dict())
```

`await ....kiq(...)` waits for the queue to confirm the message, not for the function to run. A job is executed by one
worker listening on its queue, not by every worker.

### 5. Run and check

Start the worker and the web service in separate processes (`./run.sh worker start`, `./run.sh api start`), submit, and
poll the record until it is `done`; make the work raise once to see `failed`. Stop both with `./run.sh worker stop` and
`./run.sh api stop`.

Queues, schedules, retries, results kept in Redis (`broker.result_backend.get_result(task_id)`, 24 hours by default) and
the EPG Demo's complete task pages are in `docs/public/zh/users/distributed-tasks.md`,
`docs/public/zh/developers/distributed-tasks.md` and `docs/public/zh/agents/distributed-tasks.md`.

## Other background work

Read `docs/public/zh/developers/background.md` for the entry point you chose. The EPG Demo
(`https://github.com/alexliyu7352/oldman-epg-dashboard`) has a finished, runnable example of each; take the shape from
there instead of building a collector or reporter service from scratch.

- **A coroutine inside a CLI command** (`apps/examples/background.py`, `commands.py`, command `background-stats`): the
  command owns the process-wide `BackgroundTaskManager`, registers and starts its sampler, reads the database twice,
  saves a status snapshot, stops the task and finally closes monitoring and connections. Put `start()`/`shutdown()` or
  `start_all()`/`stop_all()` in one owner's `try`/`finally`. A live web request must not use `start_all`/`stop_all` to
  stop other tasks. When a single async call is enough, just `await` it.
- **A long-running service** (`services/nats_a.py`): a `SimpleApplication` subclass whose `prepare` does no network I/O
  and whose `main` awaits the work. It already has `self.task_manager`; do not add a second global manager. The framework
  closes the database, cache and Redis at stop; `after_stop` closes only what the service created itself. Sampling in a
  web service runs once per Sanic worker; work that must run once belongs in its own `SimpleApplication` service.
- **Short Python processes** (`apps/examples/process_jobs.py`, `process_examples.py::PythonProcessDemo`, command
  `python-process --scenario ...`): the parent queries and passes plain lists; the child module imports no ORM or
  settings. Targets, worker classes and synchronous task creators are top-level functions so spawn can pickle them. A
  child that needs models calls `bootstrap_service("<service>")` itself; never pass the parent's session, Redis or HTTP
  client.
- **External programs** (`SubprocessDemo`, `apps/examples/external_job.py`): `run_subprocess_exec` with `stdin` bytes,
  `capture_output` and `check` for programs nobody answers; `run_foreground` when a person may need to answer (it keeps
  the terminal and does no group cleanup). Use a fixed program and argv; never build shell commands from input. Show
  `SubprocessError.result` on errors and the output kept by the timeout exception; do not wrap everything in a fake
  success.
- **Fixed workers** (`worker_examples.py::WorkerDemo`, `worker_jobs.py`): the command counts as done only after reading
  the worker's report; a queued instruction is not business success. Manager, temporary directory and database belong
  to the same command and are always shut down, closed and removed.

## Done means

1. The real path ran: the request answered, and the background work's effect was checked (a log line, a record, a file),
   not only that something was queued.
2. One real failure was checked: the work raising, a timeout, an external program exiting non-zero. Its outcome is
   recorded or logged; nothing reports success that did not happen.
3. After stopping, every process you started is gone (use the project's stop commands; check child processes too) and
   temporary output is removed. Never stop services that are not yours.
4. Nothing here is described as a durable queue unless it is Taskiq.
