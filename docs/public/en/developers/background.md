# Processes and background tasks

`oldman.runtime` manages lifecycles. `oldman.processes` runs short-lived Python processes, controlled external commands, and interactive foreground commands. `oldman.tasks` manages coroutines within the same process and long-lived Workers. The separately enabled `oldman.tasks.distributed` handles durable queues. Local interfaces do not publish to NATS or share an ambiguous MessageBus.

Agents: before writing code, read the [background work guide](../agents/background-work.md). It says which interface the task needs, how to wire it and what counts as done.

| Requirement | Entry point |
| --- | --- |
| Periodic sampling within one event loop | Use [`BackgroundTaskManager`](#same-process-coroutines), or implement it in SimpleApplication's own `main()`. |
| A one-off coroutine that a request or command starts without waiting, such as sending mail or writing an audit record | Use [`BackgroundTaskManager().spawn()`](#time-limited-one-off-tasks). Web handlers use `request.app.ctx.tasks.spawn()`. |
| Synchronous Python computation with limited concurrency | Use [`AsyncProcessManager`](#short-lived-python-processes). |
| An external program without a person at the terminal, such as a Web service, a taskiq worker, or a command's machine job, requiring a timeout and process-group cleanup | Use [`run_subprocess_exec` or `create_subprocess_exec`](#external-commands). |
| An external program that may ask a person for input, such as `sudo` requesting a password or a script using `read` | Use [`run_foreground`](#foreground-commands). |
| Several long-lived Workers receiving instructions to start or stop tasks | Use [`BaseManager`, `BaseWorker`, and `BaseTask`](#long-lived-workers-real-project-snapshots). |
| Durable queuing of asynchronous functions, multiple execution processes, results, and scheduled delivery | Use [Taskiq](distributed-tasks.md). |
| Messages or RPC between independent services | Use the [NATS provider](providers.md#nats-connections-and-publishing). |

## Same-process coroutines

The actual EPG example is `BackgroundStats` and `sample_project_counts` in [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py). See [the local-coroutine tutorial](../users/background-work.md#run-a-local-background-coroutine) for execution instructions and errors. This is not a placeholder that only sleeps: every sample opens a read Session and counts ExampleProject records, optionally filtering by a real team.

The following registration comes from `BackgroundStats.handle()`. In this CLI invocation, manager is a `BackgroundTaskManager()` instance, counts holds results, ready and cleaned are asyncio.Event objects, and team_id has passed CLI type validation:

```python
        manager.add_task(name, sample_project_counts, counts, ready, cleaned, team_id,
                         task_type=TaskType.PERSISTENT)
```

The full file imports `asyncio`, SQLAlchemy's `select/func`, the framework's `db_manager`, `Command`, and `BackgroundTaskManager/TaskType`, and the loaded demo models. The registered examples App discovers the command through its public import in `commands.py`. Callers do not create an event loop themselves. Do not treat this excerpt as a standalone script without the original sources of its arguments.

Once started, the sampler reads once per second. It sets ready after the second sample and continues waiting for later samples. On an exception or cancellation, its finally block sets both cleaned and ready, so the parent cannot wait forever for a result that will never arrive. The command waits at most 10 seconds, then examines `manager.tasks[name].task`. If that Task has finished, the command awaits it to propagate the actual error. An event, name, or registration alone does not establish success.

On success, the command records the running snapshot from `get_task_status`, awaits stop_task, and prints the stopped status and the coroutine's finally marker. Whether it succeeds or fails, its finally block stops all tasks, removes its own registration, and closes the database last. This example uses PERSISTENT to demonstrate cancellation. It neither lets a page request occupy the service indefinitely nor promises durable database-statistics results.

`BackgroundTaskManager()` is a **process-wide singleton**, also used by `self.task_manager` in Web and SimpleApplication services. Do not repeatedly call `start_all()` for separate business features in one process. One lifecycle owner should start it once. Both `add_task()` and `spawn()` accept coroutine functions with their arguments, rather than coroutine objects that have already been created.

- `add_task(name, coro_func, *args, restart_delay=30, max_restarts=-1, task_type=PERSISTENT, auto_remove_on_complete=None, **kwargs)` registers a task without starting it. Registering the same name again raises `ValueError`; call `remove_task()` explicitly before replacing it.
- `spawn(coro_func, *args, name=None, **kwargs)` immediately starts a one-off task and returns an `asyncio.Task`. It requires a running event loop. Registration is removed automatically after success, failure, or cancellation. Failures are logged without retries. Omitting `name` generates a unique name. Use this entry point for work that request handlers start without waiting for completion. Web processes obtain the same manager through `request.app.ctx.tasks`; shutdown cancels these tasks alongside the others.
- `start_task(name)`, `stop_task(name)`, `remove_task(name)`, and `restart_task(name)` are asynchronous methods that return whether the operation succeeded.
- `start_all()` starts registered tasks that are neither running nor waiting to restart. `stop_all()` cancels all tasks and pending restarts, then awaits them. `stop_all_sync()` only requests cancellation; it does not replace asynchronous resource cleanup that must be awaited.
- `get_task_status(name)` returns a status dictionary, or `{}` for an unknown name. `get_all_status()` returns all registered entries.

`PERSISTENT` means that a coroutine should restart even after returning normally; it does not mean persistent data. `ONE_TIME` tasks are removed by default after normal completion. A done callback handles completion immediately, without a polling monitor, so `get_task_status()` reports current state.

Automatic restart follows these rules. A `PERSISTENT` task restarts once `restart_delay` seconds have elapsed since its previous start, whether it returned normally, raised an exception, or was cancelled outside the manager. `max_restarts=-1` allows unlimited restarts, `0` disables them, and a positive value sets a limit. When that limit is exhausted, status becomes `error` and a message is logged. A `ONE_TIME` task does not restart after failure by default; it retries only when `max_restarts` is positive, and external cancellation counts as stopping. The manager's own `stop_task`, `remove_task`, and `stop_all` operations never trigger restarts. `start_task()` resets the restart count. This is still not a reliable retry queue: it has no persistence, acknowledgment, or precise scheduling, and state disappears when the process exits. Use Taskiq for jobs that need replay.

### Time-limited one-off tasks

A webhook should respond first, process its work in the background, and impose a maximum duration. Put the time limit inside the coroutine, then pass that function to `spawn()`:

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

Expiration raises `TimeoutError`, which the manager logs as a task failure like any other exception. Do not write `spawn(asyncio.wait_for, process_update(...), 60)`. That creates the coroutine before registration; if shutdown cancels the task before it starts, the coroutine never runs and produces a "coroutine was never awaited" warning. `spawn()` has no `timeout` parameter because extra keyword arguments pass unchanged to the business function, which may have its own `timeout`.

### Periodically running synchronous blocking functions

For an SDK with only a synchronous interface, or a blocking file or network call, register `asyncio.to_thread` as the coroutine function. The function then runs in the default thread pool without blocking the event loop:

```python
manager.add_task("poll-inventory", asyncio.to_thread, poll_inventory, restart_delay=60)
await manager.start_task("poll-inventory")
```

`poll_inventory` is a synchronous function in a business module. `manager` belongs to this task's lifecycle owner; for example, an independent SimpleApplication service can use `self.task_manager` in `main()`. Each Sanic worker of a Web service runs its own copy, as described above. The default is `PERSISTENT`, which restarts after each return. `restart_delay` is measured from the previous **start**, so a run exceeding 60 seconds is followed immediately by another. Shutdown cancels the task immediately, but cannot interrupt a call already executing in a thread; that call runs until it returns. If this is the only periodic task, a simpler option in `main()` is `while True: await asyncio.to_thread(poll_inventory); await asyncio.sleep(60)`, which measures the interval from completion.

## Short-lived Python processes

The target function must live in an importable business module, not in the startup script's `__main__`. The actual EPG [process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) imports Counter, os, Path, and time. Its complete target is:

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

The caller is PythonProcessDemo in [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py); no additional calculate.py or service is needed. When running the [four paths](../users/background-work.md#run-a-short-lived-python-subprocess), the CLI has already loaded configuration and models and prepared the asynchronous command lifecycle. The Command creates `AsyncProcessManager(workers=1)`. The parent reads statuses from the database, and TemporaryDirectory supplies this invocation's marker. The actual launch code is:

```python
                job = asyncio.create_task(manager.run_with_timeout(
                    inspect_projects, (statuses, scenario.value, str(marker)),
                    _timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                ))
```

The cancellation branch waits until the target writes its PID, then calls `job.cancel()` and awaits it. This confirms that the child actually ran, rather than merely cancelling a call before spawn. Other branches await the return value. This example requires counts; a None or empty result must not be reported as successful statistics. The finally block awaits an unfinished job, shuts down the manager, closes the database, confirms that the PID has been reaped, and then exits TemporaryDirectory. The PID file provides observable evidence for this example; it is not a framework result backend.

Each call creates one Billiard **spawn** process. `workers` limits concurrency rather than providing a prewarmed pool. Targets must be synchronous, serializable, module-level functions, and their arguments and results must pass through process IPC. Do not run the entry point from stdin or pass a lambda, local function, or target defined in the startup script. Waiting in the parent does not block its event loop. Do not pass asynchronous functions as targets, database Sessions, Redis or HTTP connections, or request objects.

`run_with_timeout(target, args=(), _timeout=30)` raises `ProcessTimeoutError` on timeout. A child-function exception prints a traceback and returns `None`; it does not rethrow the original exception across processes. Abnormal exit or shutdown may also return `None`, and a failed result-queue read may return `{}`. If business failure must be distinguishable, return an explicit result dictionary from the target. Do not interpret `None` as success.

Cancellation, timeout, and shutdown reap the child created for this call. Cancellation still raises CancelledError rather than being delayed and converted to task timeout. Every call owns a separate result Queue, while stdout and stderr use another pipe. Cleanup signals the result-reader thread and waits for its exit, rather than leaving it waiting on an empty queue until event-loop shutdown. The parent releases its unused Queue write end, so abnormal child death can produce EOF. Construction accepts optional `logging_context=...`; when omitted, the active logging runtime is obtained before launch. Linux parent-death signals protect process lifecycles but do not make business operations transactional or idempotent.

## External commands

Choose an entry point according to whether a person may need to answer:

- `run_subprocess_exec` and `create_subprocess_exec` are for unattended programs launched by Web services, taskiq workers, or machine jobs in commands. A supervisor places the child in a separate session detached from the terminal. Timeout, task cancellation, and host-process exit clean up the whole group. Therefore Web worker restart, request cancellation, and taskiq worker exit do not leave running children. The tradeoff is that the child has no controlling terminal and cannot open `/dev/tty`. `sudo` cannot request a password, and terminal Ctrl-C reaches only the caller, after which the framework cleans up the group. Inherited stdin remains readable but is unsuitable for human interaction. This interface supports Linux only.
- `run_foreground` is for commands that may ask a person for input. The child remains in the caller's session and process group and shares its terminal. `sudo` can prompt for a password, and terminal Ctrl-C reaches the child too. See [foreground commands](#foreground-commands).

The actual EPG Command is [SubprocessDemo](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py); see [the external-command tutorial](../users/background-work.md#run-a-controlled-external-command) for execution instructions. The module imports sys, json, asyncio, the framework's create_subprocess_exec and run_subprocess_exec, and the result and exception types. program is fixed to sys.executable. Its arguments are `-m apps.examples.external_job` and a scenario checked against an enumeration. data contains bytes produced by json.dumps(...).encode("utf-8") from the parent's `_project_statuses()` query.

The success, error, and timeout branches use this actual call:

```python
                    result = await run_subprocess_exec(
                        *command, input=data, capture_output=True, check=True,
                        timeout=1 if scenario == ProcessScenario.TIMEOUT else 10,
                    )
```

The external program `external_job.py` prints startup information and reads JSON from stdin. Normally it prints a Counter summary; the error branch writes to stderr and exits with code 7. When Command catches SubprocessError, it first displays the stdout, stderr, and process identifiers retained in error.result, then rethrows the exception. SubprocessTimeoutError likewise displays the retained output. A nonzero exit code is neither treated as success nor converted to another framework result type.

The cancel branch demonstrates the low-level handle. It awaits create_subprocess_exec with stdin, stdout, and stderr set to PIPE, then enters `async with process`. It reads one startup line, creates a Task for communicate(data), then cancels and awaits it. Cancellation makes the framework clean up the process group and drain its pipes; context exit ensures cleanup again. This example has a small startup line and no continuous stderr output. General programs need concurrent consumption of both streams: do not copy the "read one line first" sequence for arbitrary high-output programs. The parent closes the database in finally on every path, without bootstrapping child modules or copying connections.

`run_subprocess_exec(program, *args, input=None, capture_output=False, timeout=None, check=False, stdin=None, stdout=None, stderr=None, cwd=None, env=None, limit=2**16, terminate_grace_period=..., kill_timeout=...)` accepts an argument list without starting a shell. Do not concatenate user input and pass it to `sh -c`.

`input` is bytes and automatically enables PIPE, so it cannot be combined with stdin. `capture_output=True` captures stdout and stderr and cannot be combined with explicit versions of those streams. Output is inherited by default; captured output is bytes or `None`. `env` is the environment mapping passed to the child. If existing variables must be retained, the caller explicitly merges them; do not assume the mapping overrides only a few keys.

The `CompletedSubprocess` result provides `args`, the actual command's `pid`, `supervisor_pid`, `process_group`, `returncode`, `stdout`, `stderr`, and `check_returncode()`. By default, a nonzero exit still returns a result. With `check=True`, it raises `SubprocessError`, whose `result` retains the output. Launch failure raises `SubprocessStartError`, timeout raises `SubprocessTimeoutError`, and incomplete cleanup raises `SubprocessCleanupError`. Their common operational-error base is `ManagedSubprocessError`.

For long output, use `create_subprocess_exec()` to obtain a `ManagedSubprocess` and continuously consume its `stdout` and `stderr` StreamReaders. It supports `async with`, `wait(timeout=None)`, `communicate(input=None, timeout=None)`, `terminate()`, and `kill()`. Both PIPE streams can fill. Do not consume stdout while leaving substantial stderr unread, or use `capture_output` to buffer an unlimited log stream.

The Linux supervisor owns the controlled process group. Timeout, cancellation, and exit remove remaining group members; even normal command exit leaves no background programs in that group. This is not a security sandbox for arbitrary commands. Deliberately escaping the process group is not a supported protected business pattern.

### Foreground commands

`await run_foreground(program, *args, input=None, capture_output=False, text=False, timeout=None, check=False, cwd=None, env=None)` runs `subprocess.run` in a worker thread. The event loop continues handling other tasks while it waits. Results and exceptions are standard-library types: `subprocess.CompletedProcess`, `CalledProcessError` for a nonzero exit with `check=True`, `TimeoutExpired` on timeout, and `FileNotFoundError` for a missing executable. `input` is bytes, or str with `text=True`. `env` replaces the entire environment rather than extending it.

```python
from oldman.processes import run_foreground

completed = await run_foreground("sudo", "apt-get", "install", "-y", "nginx", check=True)
```

This function does not clean up descendants. Timeout kills only the command itself, not other processes it launches. Cancelling this await does not stop the command: it keeps running, and `asyncio.run` waits for it before returning. Thus the tool exits only after the command finishes. For example, wrapping a five-minute command in `asyncio.timeout` still leaves the tool waiting until those five minutes have elapsed. If timeout must stop the command, use `run_foreground`'s own `timeout` parameter. Both the systemd operations in [operations primitives](ops.md#systemd) and the scripts in [remote files](remote.md) use this function.

## Long-lived Workers: real project snapshots

The actual entry point is EPG `./run.sh web worker-demo --scenario success|error|stop`, rather than another worker_example.py. [The user tutorial](../users/background-work.md#run-a-long-lived-worker) explains the three results and their cleanup. The actual [worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) depends only on the standard library and oldman.tasks and defines ProjectSnapshotTask, its factory, and Worker:

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

This is an excerpt from the source file. Any comes from typing, BaseTask and BaseWorker come from oldman.tasks, and ProjectSnapshotTask is defined in that file. The task's execute method converts ids in the supplied project records and produces a report containing task_id, the actual worker_pid, and projects. Conversion failure saves error, which the parent command treats as business failure. It does not rely on internal TaskStatus or catch original exceptions across processes. Reports are written to temporary files before atomic replacement, so the parent never reads partial JSON.

WorkerDemo in [worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py) owns the manager. After CLI initialization, the parent reads SQL, creates BaseManager(ProjectSnapshotWorker, num_workers=1) and its own TemporaryDirectory, then starts the manager and adds the task. It passes only ordinary records and directory strings, not ORM instances, Sessions, Requests, or clients. The result file is this business example's actual output, not a new framework result backend.

The success and error branches use ONE_TIME. The stop branch uses PERSISTENT, writes its report, and awaits Event().wait() to remain active. After reading the report, the parent calls the manager's stop_task and waits for the `.stopped` file written by execute's finally block. Each file has a maximum wait of 10 seconds, and failure still enters finally. The Worker's internal `_handle_task_stop` calls task.cleanup before cancelling the execution coroutine. Therefore **calling the cleanup hook does not mean execute has exited**. Put resource release in execute's try and finally blocks when coroutine cleanup must be guaranteed. This example writes its final marker there. Applications call BaseManager.stop_task rather than the internal handler.

Finally, the command awaits manager.shutdown, closes the parent's database, confirms the captured Worker PID no longer exists, and exits TemporaryDirectory to remove all output from this invocation. The command exclusively owns one manager, and its temporary directory does not accept arbitrary user paths. It neither writes project data nor adds services, tables, or result-query endpoints. `scripts/verify-worker-demo.py` runs all three modes through the actual CLI in sequence and checks results, failure, and PID reaping.

`BaseManager(worker_class, num_workers=4, max_worker_restarts=-1, worker_restart_delay=5, monitor_interval=60, logging_context=None, process_start_method="spawn")` assigns tasks by polling healthy Workers. `start()` launches children and monitoring; `shutdown()` stops and reaps them. forkserver and fork are available, but default spawn avoids copying active threads, event loops, and connection pools. Normally retain that default.

`add_task(task_data, task_type=PERSISTENT, restart_delay=5, max_restarts=-1, auto_remove_on_complete=None)` returns a task ID or `None`. The dictionary's `task_type` names a business factory, whereas the method argument `task_type` is the lifecycle enumeration `TaskType`. These are distinct meanings. A task ID indicates that the instruction entered the local queue; it is **not acknowledgment of successful Worker execution**.

`BaseTask.execute()` is the asynchronous business entry point, and `cleanup()` performs task-level cleanup. Coroutine-owned resources still belong in `try/finally`; do not infer that every coroutine has stopped from synchronous state fields or cleanup order. `BaseWorker.initialize()` registers synchronous factories. Initialize and close resources inside that child process. spawn does not automatically bind the parent's service Settings. If business code needs configuration, call the unified `bootstrap_service()` during Worker initialization rather than passing opened parent connections.

The parent's `get_manager_status()` reports Worker process health only. A Worker's `get_task_status()` is local state, not a parent-process RPC. Control messages `TaskMessage` and `MessageType` use multiprocessing Queue and MsgPack, not Redis or NATS.

There is currently no job database, completion ACK, result backend, failure queue, recovery after power loss, or automatic task replay following Worker restart. Persist business state yourself when reliable completion records are required. Use providers for cross-service RPC; do not treat this start-and-stop control protocol as a reliable task platform.

<!-- source: zh/developers/background.md @ eb01bd54 -->
