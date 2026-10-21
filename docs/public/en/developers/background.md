# Processes and background tasks

`oldman.runtime` manages lifecycles; `oldman.processes` runs short-lived Python processes, controlled external commands, and interactive foreground commands; `oldman.tasks` manages same-process coroutines and long-lived Workers. Explicitly enabled oldman.tasks.distributed supplies durable queues. Local interfaces neither publish to NATS nor share an ambiguous MessageBus.

| Need | Entry point |
| --- | --- |
| Periodic sampling in one event loop | `BackgroundTaskManager`, or SimpleApplication's own `main()` |
| Fire-and-forget one-off coroutines in requests/commands (mail, audit writes) | `BackgroundTaskManager().spawn()`; Web handlers use `request.app.ctx.tasks.spawn()` |
| Concurrency-limited synchronous Python computation | `AsyncProcessManager` |
| External programs without a person at the terminal (Web services, taskiq workers, machine jobs), requiring timeouts/group cleanup | `run_subprocess_exec` / `create_subprocess_exec` |
| External programs that may prompt a person (`sudo` passwords, shell `read`) | [Processes and background tasks](#foreground-commands) |
| Several long-lived Workers receiving task start/stop instructions | `BaseManager`, `BaseWorker`, `BaseTask` |
| Durable asynchronous queuing, multiple execution processes, results, scheduled delivery | [Taskiq interfaces and runtime](distributed-tasks.md) |
| Messages/RPC between independent services | [Redis and NATS providers](providers.md#nats-connections-and-publishing) |

## Same-process coroutines

The actual EPG example is `BackgroundStats` and `sample_project_counts` in [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py); see [Run jobs in the background](../users/background-work.md#run-a-local-background-coroutine) for execution/errors. It is not a sleep-only placeholder: every sample creates a read Session, counts ExampleProject records, and optionally filters by a real team.

This registration excerpt comes from `BackgroundStats.handle()`. manager is this CLI process's `BackgroundTaskManager()`, counts is a result list, ready/cleaned are asyncio.Event objects, and team_id has passed CLI type validation:

```python
        manager.add_task(name, sample_project_counts, counts, ready, cleaned, team_id,
                         task_type=TaskType.PERSISTENT)
```

The complete file imports `asyncio`, SQLAlchemy `select/func`, framework `db_manager`, `Command`, `BackgroundTaskManager/TaskType`, and loaded demo models. commands.py publicly imports the command for discovery by registered examples App. Callers need not create an event loop manually. This excerpt is not a standalone script with unexplained parameters.

After starting, the sampler reads once per second, sets ready after its second sample, and continues waiting for the next sample. Its finally block sets cleaned/ready on failure or cancellation so the parent cannot wait forever for impossible results. The command waits at most 10 seconds, then checks `manager.tasks[name].task`. If it has finished, awaiting it propagates actual errors rather than declaring success from an event, name, or registration state alone.

Success first records the running get_task_status snapshot, then awaits stop_task and prints stopped state plus the coroutine-finally marker. In all cases, finally stops every task, removes its own registration, and closes the database last. PERSISTENT demonstrates cancellation here; it neither occupies a service indefinitely for one page request nor makes database statistics durable results.

`BackgroundTaskManager()` is a **process-wide singleton**, also used by Web/SimpleApplication `self.task_manager`. Do not repeatedly call `start_all()` for separate business features in one process. One lifecycle owner should start it once. `add_task()` and `spawn()` take coroutine functions and arguments, not already-created coroutine objects.

- `add_task(name, coro_func, *args, restart_delay=30, max_restarts=-1, task_type=PERSISTENT, auto_remove_on_complete=None, **kwargs)` registers without starting. Duplicate names raise `ValueError`; explicitly `remove_task()` before replacement.
- `spawn(coro_func, *args, name=None, **kwargs)` immediately starts a one-off task and returns `asyncio.Task`, requiring a running loop. Completion, failure, or cancellation automatically removes registration. Failures log without retry. Missing names generate unique ones. This is the fire-and-forget request-handler entry point; Web obtains the same manager through `request.app.ctx.tasks`. Shutdown cancels these alongside other tasks.
- `start_task(name)`, `stop_task(name)`, `remove_task(name)`, and `restart_task(name)` are asynchronous and return success booleans.
- `start_all()` starts registered tasks neither running nor awaiting restart. `stop_all()` cancels/awaits all tasks and pending restarts. `stop_all_sync()` only signals cancellation and cannot replace awaited asynchronous cleanup.
- `get_task_status(name)` returns a status dict or `{}` for unknown names; `get_all_status()` returns all registrations.

`PERSISTENT` means restart even after normal coroutine completion, not data persistence. `ONE_TIME` normally removes completed tasks. Done callbacks handle completion immediately without a polling monitor, so `get_task_status()` reads current state.

Automatic restart rules: `PERSISTENT` tasks restart restart_delay seconds after their previous start whether they returned, raised, or were cancelled by code outside the manager. max_restarts=-1 is unlimited, 0 disables it, and positive values cap restarts; exhaustion sets error state and logs. `ONE_TIME` failures do not restart by default, retrying only with positive max_restarts; external cancellation counts as stopping. Manager-owned stop_task/remove_task/stop_all never trigger restarts. `start_task()` resets the restart counter. This remains an unreliable retry mechanism without persistence, acknowledgments, or precise scheduling. Process exit loses it; use Taskiq for replayable jobs.

### Time-limited one-off tasks

Requests such as webhooks should respond before background processing and cap its duration. Put the limit in the coroutine, then pass it to `spawn()`:

```python
import asyncio

from oldman.web import Request, json_response, router


async def process_update(update: dict) -> None:
    ...  # Business processing


async def process_update_within(update: dict, seconds: float) -> None:
    async with asyncio.timeout(seconds):
        await process_update(update)


@router.post("/telegram/webhook", name="telegram_webhook")
async def telegram_webhook(request: Request):
    request.app.ctx.tasks.spawn(process_update_within, request.json, 60)
    return json_response({"ok": True})
```

Timeout raises `TimeoutError`, logged by the manager as task failure like other exceptions. Do not use `spawn(asyncio.wait_for, process_update(...), 60)`: it creates the coroutine before registration, so shutdown cancellation before execution leaves "coroutine was never awaited". `spawn()` has no timeout parameter because extra kwargs pass unchanged to business functions, which often have their own timeout.

### Periodically running synchronous blocking functions

For synchronous-only SDKs or blocking file/network calls, register `asyncio.to_thread` as the coroutine function. It runs the function in the default thread pool without blocking the loop:

```python
manager.add_task("poll-inventory", asyncio.to_thread, poll_inventory, restart_delay=60)
await manager.start_task("poll-inventory")
```

`poll_inventory` is a synchronous business-module function. `manager` belongs to this task's lifecycle owner, such as `self.task_manager` in a standalone SimpleApplication main(). Each Web Sanic worker runs its own copy, as above. Default PERSISTENT restarts after return. `restart_delay` measures from the previous **start**, so a run over 60 seconds restarts immediately. Shutdown cancels the task immediately, but an already-running thread call cannot be interrupted and runs to completion. With only this periodic task, `while True: await asyncio.to_thread(poll_inventory); await asyncio.sleep(60)` directly in main() is simpler and measures delay from completion.

## Short-lived Python processes

Targets must come from importable business modules, not startup-script `__main__`. The actual EPG [process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) imports Counter, os, Path, and time. Complete target:

```python
def inspect_projects(statuses: list[str], scenario: str, marker: str) -> dict:
    """Summarize real input, or deliberately exercise a documented failure mode."""
    pid = os.getpid()
    Path(marker).write_text(str(pid), encoding="utf-8")
    print(f"Python child {pid}: received {len(statuses)} project statuses", flush=True)
    if scenario == "error":
        raise ValueError("Demonstration: child calculation failed")
    if scenario in {"timeout", "cancel"}:
        time.sleep(30)
    return {"pid": pid, "counts": dict(sorted(Counter(statuses).items()))}
```

The caller is PythonProcessDemo in [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py), without another calculate.py or service. The [Run jobs in the background](../users/background-work.md#run-a-short-lived-python-subprocess) use CLI-loaded configuration/models and the asynchronous command lifecycle. The Command creates `AsyncProcessManager(workers=1)`; the parent reads statuses from the database, and TemporaryDirectory supplies this run's marker. Actual start:

```python
                job = asyncio.create_task(manager.run_with_timeout(
                    inspect_projects, (statuses, scenario.value, str(marker)),
                    _timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                ))
```

The cancellation branch waits for the target's PID marker before `job.cancel()` and await, confirming actual execution rather than cancelling a not-yet-spawned call. Other branches await the result. This example requires counts; None/empty results must not print successful statistics. finally awaits unfinished jobs, shuts down the manager, closes the database, confirms PID reaping, then exits TemporaryDirectory. PID files are observable demo evidence, not a framework result backend.

Every call creates a Billiard **spawn** process. `workers` limits concurrency rather than defining a prewarmed pool. Targets are synchronous, serializable module-level functions; arguments/results must cross process IPC. Do not run entries from stdin or pass lambdas, local functions, or startup-script targets. Parent waiting does not block the event loop. Do not use asynchronous targets or pass database Sessions, Redis/HTTP clients, or request objects.

`run_with_timeout(target, args=(), _timeout=30)` raises `ProcessTimeoutError` on timeout. Child-function exceptions print tracebacks and return `None` rather than propagating original exceptions across processes. Abnormal exit/shutdown may also return None, and result-queue read failure may return `{}`. For distinguishable business failures, return an explicit result dict from the target rather than interpreting None as success.

Cancellation, timeout, and shutdown reap the child. Call cancellation remains CancelledError rather than becoming a delayed task timeout. Every call has a separate result Queue and another stdout/stderr pipe. Cleanup signals and joins result-reader threads instead of leaving empty-queue waits until loop shutdown. The parent releases unused Queue write ends so abnormal child death can produce EOF. Optional constructor `logging_context=...` defaults to the active logging runtime before starting. Linux parent-death signals protect process lifecycles, not transactionality or idempotency.

## External commands

Choose between two entry points according to whether a person may answer:

- `run_subprocess_exec` / `create_subprocess_exec` run unattended programs launched by Web services, taskiq workers, or machine commands. A supervisor puts children in independent sessions detached from the terminal. Timeout, task cancellation, or host exit cleans the whole group, so Web worker restarts, cancelled requests, and taskiq worker exit leave no running children. The tradeoff is no controlling terminal or `/dev/tty`: sudo cannot prompt; terminal Ctrl-C reaches only the caller, which triggers framework group cleanup. Inherited stdin remains readable but is unsuitable for human interaction. Linux only.
- `run_foreground` runs commands that may prompt a person. Children stay in the caller's session/process group, share its terminal, allow sudo prompts, and receive terminal Ctrl-C directly. See [Processes and background tasks](#foreground-commands).

The actual EPG Command is [SubprocessDemo](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py); see [Run jobs in the background](../users/background-work.md#run-a-controlled-external-command) for execution. The module imports sys, json, asyncio, framework create_subprocess_exec/run_subprocess_exec, and result/error types. program is fixed to sys.executable, with `-m apps.examples.external_job` and enum-validated scenario arguments. data is UTF-8 JSON bytes from the parent's `_project_statuses()` query.

success/error/timeout use this actual call:

```python
                    result = await run_subprocess_exec(
                        *command, input=data, capture_output=True, check=True,
                        timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                    )
```

external_job.py prints startup information, reads JSON from stdin, and normally prints Counter summaries. error writes stderr and exits 7. When catching SubprocessError, Command first displays error.result stdout/stderr/process identifiers, then rethrows. SubprocessTimeoutError likewise displays retained output. Nonzero status is neither success nor another invented framework result object.

The cancel branch demonstrates the low-level handle: await create_subprocess_exec with stdin/stdout/stderr=PIPE, enter `async with process`, read one startup line, create communicate(data) as a Task, then cancel/await it. Cancellation cleans the process group and drains pipes; context exit ensures cleanup again. This example has a small startup line and no continuous stderr. General programs must consume both output streams concurrently; do not copy the first-line-first pattern for arbitrary high-output programs. Every parent path closes its database in finally, without child-module bootstrap or copied connections.

`run_subprocess_exec(program, *args, input=None, capture_output=False, timeout=None, check=False, stdin=None, stdout=None, stderr=None, cwd=None, env=None, limit=2**16, terminate_grace_period=..., kill_timeout=...)` uses an argument list without starting a shell. Do not concatenate user input into `sh -c`.

`input` is bytes, automatically enables PIPE, and excludes explicit stdin. `capture_output=True` captures stdout/stderr and excludes explicit versions of those streams. Output defaults to inheritance; captured values are bytes or None. `env` is the child environment mapping. Explicitly merge retained environment yourself rather than assuming it overrides only a few keys.

`CompletedSubprocess` provides args, actual-command pid, supervisor_pid, process_group, returncode, stdout, stderr, and check_returncode(). Nonzero status returns normally by default. `check=True` raises SubprocessError with output retained in result. Start failure is SubprocessStartError, timeout SubprocessTimeoutError, and incomplete cleanup SubprocessCleanupError, all operational errors under ManagedSubprocessError.

For long output, get ManagedSubprocess through `create_subprocess_exec()` and continuously read its stdout/stderr StreamReaders. It supports async with, wait(timeout=None), communicate(input=None, timeout=None), terminate(), and kill(). Both PIPE streams can fill. Do not read only stdout while large stderr goes unconsumed, or buffer unlimited logs through capture_output.

The Linux supervisor owns the controlled process group. Timeout/cancellation/exit cleans remaining members, and even normal command exit leaves no same-group background programs. It is not a security sandbox for arbitrary commands; deliberate group escape is not a supported protected business pattern.

### Foreground commands

`await run_foreground(program, *args, input=None, capture_output=False, text=False, timeout=None, check=False, cwd=None, env=None)` is `subprocess.run` in a worker thread. The event loop keeps handling other tasks while waiting. Results/exceptions are standard-library types: subprocess.CompletedProcess; CalledProcessError for nonzero status with check=True; TimeoutExpired on timeout; FileNotFoundError for missing executables. input is bytes, or str with text=True. env replaces the entire environment rather than extending it.

```python
from oldman.processes import run_foreground

completed = await run_foreground("sudo", "apt-get", "install", "-y", "nginx", check=True)
```

It does not own descendant cleanup: timeout kills only the command itself, not additional processes it launches. Cancelling this await does not stop the command; it continues, and asyncio.run waits before returning, so the tool stays alive until completion. For example, wrapping a five-minute command in asyncio.timeout still leaves the tool waiting for those five minutes. Use run_foreground's own timeout parameter when timeout must stop the command. Both [Operations primitives](ops.md#systemd) systemd operations and [Remote files](remote.md) scripts use it.

## Long-lived Workers: real project snapshots

The entry point is EPG `./run.sh web worker-demo --scenario success|error|stop`, without another worker_example.py. [Run jobs in the background](../users/background-work.md#run-a-long-lived-worker) covers results/cleanup for all three. Actual [worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) depends only on the standard library and oldman.tasks and defines ProjectSnapshotTask, its factory, and Worker:

```python
def create_snapshot(task_id: str, data: dict[str, Any]) -> BaseTask:
    """The existing Worker creator contract is synchronous, even for async tasks."""
    return ProjectSnapshotTask(task_id, data)


class ProjectSnapshotWorker(BaseWorker):
    """Register one task creator; no custom queue, ACK or result backend."""

    async def initialize(self) -> None:
        """Registration happens in this spawned Worker, not in the Web process."""
        self.register_task_creator("project_snapshot", create_snapshot)
```

This is a source excerpt. Any comes from typing; BaseTask/BaseWorker from oldman.tasks; ProjectSnapshotTask is defined in the same file. execute converts supplied project IDs and generates a report with task_id, actual worker_pid, and projects. Conversion failures save error, interpreted as business failure by the parent rather than relying on internal TaskStatus or original cross-process exceptions. Reports write a temporary file then atomically replace it, preventing partial JSON reads.

The manager owner is WorkerDemo in [worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py). After CLI initialization, the parent reads SQL, creates BaseManager(ProjectSnapshotWorker, num_workers=1) and its own TemporaryDirectory, then calls start/add_task. It passes only plain records/directory strings, not ORM instances, Sessions, Requests, or clients. Result files are actual business-example output, not a new framework backend.

success/error use ONE_TIME. stop uses PERSISTENT and awaits Event().wait() after reporting to stay active. Only after reading the report does the parent call manager.stop_task, then await the `.stopped` marker from execute finally. Both files have 10-second waits, and failure still enters finally. Worker `_handle_task_stop` calls task.cleanup before cancelling execution, so **a cleanup-hook call does not mean execute has exited**. Put coroutine-resource cleanup in execute try/finally; this example writes its final marker there. Applications call BaseManager.stop_task rather than the internal handler.

Finally it awaits manager.shutdown, closes the parent database, checks captured Worker PIDs no longer exist, then exits TemporaryDirectory to remove all output. The command exclusively owns one manager and accepts no arbitrary user temporary-directory paths. It writes no project data or new services/tables/result endpoints. `scripts/verify-worker-demo.py` serially runs actual CLI modes and checks results/failure/PID reaping.

`BaseManager(worker_class, num_workers=4, max_worker_restarts=-1, worker_restart_delay=5, monitor_interval=60, logging_context=None, process_start_method="spawn")` polls healthy Workers to assign tasks. start() launches children/monitoring; shutdown() stops/reaps them. forkserver/fork are available, but default spawn avoids copying active threads, loops, and pools. Normally retain it.

`add_task(task_data, task_type=PERSISTENT, restart_delay=5, max_restarts=-1, auto_remove_on_complete=None)` returns a task ID or None. Dictionary task_type names a business factory; the method's task_type is a TaskType lifecycle enum. They have different meanings. A task ID confirms local queuing, **not successful Worker execution**.

`BaseTask.execute()` is the asynchronous business entry; cleanup() is task-level cleanup. Coroutine-owned resources still belong in try/finally rather than inferring completion from synchronous status/cleanup order. BaseWorker.initialize() registers synchronous factories; initialize/close resources within that child. spawn does not bind parent service Settings automatically. If configuration is needed, call unified bootstrap_service() during Worker initialization instead of carrying opened parent connections.

Parent get_manager_status() reports Worker process health only. Worker get_task_status() is local state, not parent RPC. TaskMessage/MessageType control messages use multiprocessing Queue/MsgPack rather than Redis/NATS.

There is currently no job database, completion ACK, result backend, failure queue, power-loss recovery, or automatic replay after Worker restart. Persist business state when reliable completion records are needed. Use providers for cross-service RPC; this start/stop control protocol is not a reliable task platform.

<!-- source: zh/developers/background.md @ 8c13fdcf -->
