# Run jobs in the background

First distinguish a browser waiting for a single result from a service running continuously in the background. Use SimpleApplication for sampling or consumption tasks without HTTP. Use App Commands for one-off statistics or imports, without another long-running service.

## Current demo boundaries

Durable queuing and scheduled tasks have a complete [Distributed background tasks](distributed-tasks.md): database summaries/exports, two queues, online broadcasts, schedules, and results. It uses separate task_worker/task_scheduler services. The existing local coroutine and long-lived Worker interfaces below do not thereby become durable queues.

All four local execution examples use finite App Commands, releasing resources when they finish without requiring a persistent collector service. For actual persistent SimpleApplication wiring, see the [Let running services communicate with each other](service-communication.md); they receive events/RPC, without collecting monitoring data. Realtime tables replay existing database samples within Web requests; explicit publish buttons write samples for realtime charts. Opening a page in each browser does not repeatedly start background collectors.

### Run a local background coroutine

EPG Demo already provides `background-stats`, and there is no need to add a new collector service. After completing the Demo configuration, migration and optional `loaddata demo`, run in the Demo root directory:

```bash
./run.sh web background-stats
./run.sh web background-stats --team-id 1
```

The command registers and starts a BackgroundTaskManager coroutine, reads the project count from the database once per second, and stops after two samples. It does not start Web, write to the database, or launch a collector from browser connections. If YAML enables NATS/Taskiq, the App command lifecycle still connects to them first. For this example alone, disable `nats_bus.enabled` and `taskiq.enabled` in your local YAML; no Worker/Scheduler is needed.

Output includes `samples`, `running`, `stopped`, and `cleanup_completed`. With unchanged preset data, full-table samples are `[120, 120]` and team 1 samples are `[15, 15]`; use your actual database, without hardcoding counts. `running.is_alive=true` confirms that the coroutine is running. After explicit stop, `stopped.is_alive=false` and `cleanup_completed=true` confirm its finally block ran. The command stops the task, removes its registration, then closes the database.

`--team-id 0` is an argument error and exits with code 2. A valid but nonexistent ID causes a real query failure in the coroutine and exits with code 1, still cleaning up resources. An existing team with no projects returns `[0, 0]`, which is not an error. The command waits only for these two samples, for at most 10 seconds. Timeout also ends execution and cleans up without inventing results.

The complete source is [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py). [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) publicly imports its Command class for automatic App Registry discovery. This independent CLI process owns the entire manager. **Do not copy Command.handle into a Web service handling requests and call start_all/stop_all**; that would affect other tasks in the same process.

You can also write an asynchronous loop directly in SimpleApplication's `main()`. Use `self.task_manager` only when you need multiple independent coroutines with status/restart management. Registered tasks do not all start automatically: the application calls `start_all()` and awaits `stop_all()` on exit. Do not call `asyncio.create_task()` in `prepare()`, where no event loop exists.

## Choose execution method

### Run a short-lived Python subprocess

EPG's `python-process` reads project statuses from the database, passes them to a synchronous subprocess for aggregation, and outputs actual PIDs and status counts. It demonstrates wiring where the parent reads data and the child computes over plain data. Prefer `project-stats` SQL for ordinary simple statistics; process overhead is not claimed to make simple counting faster.

The preparation is the same as `background-stats`, run in the Demo root directory:

```bash
./run.sh web python-process
./run.sh web python-process --scenario error
./run.sh web python-process --scenario timeout
./run.sh web python-process --scenario cancel
```

- success: the child writes its PID and input count to stdout; the parent prints `counts`, then `child_pid=... reaped=true`, and exits 0.
- error: the example function deliberately raises ValueError. The framework prints its traceback and returns None; the command treats the missing result as failure and exits 1. **The original exception is not automatically raised across processes**.
- timeout: the example function waits 30 seconds, but this call has a 1-second deadline. It raises ProcessTimeoutError, exits 1, and reaps the child process.
- cancel: after the child function actually writes its PID, the command cancels the wait and observes CancelledError. This deliberate cancellation example exits normally with code 0 and outputs no project statistics.

All four paths close the manager/database in finally, verify that the child PID no longer exists, then remove their own PID file under `/tmp`. They neither modify project records nor use Worker queues. Run `.venv/bin/python scripts/verify-process-demos.py` to check the four Python and four external command paths sequentially. The script requires prepared demo configuration and database; it does not silently migrate or import fixtures.

Source code: [process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) is an importable top-level target that only relies on the standard library; [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) is the Command owner and is exposed through commands.py. Don't move target into stdin/local functions, and don't pass Session, Request, or live connections to child processes.

### Run a controlled external command

The same demo also provides `subprocess-demo`. It executes only a fixed Python module from the project, rather than accepting arbitrary shell commands:

```bash
./run.sh web subprocess-demo
./run.sh web subprocess-demo --scenario error
./run.sh web subprocess-demo --scenario timeout
./run.sh web subprocess-demo --scenario cancel
```

Default mode encodes actual project statuses as JSON bytes and passes them to the child program over stdin. stdout contains the startup PID and statistics. Processes communicate over standard input/output, rather than a Python object Queue. error mode makes the child write stderr and exit 7; the framework raises SubprocessError preserving that output, and the Oldman command exits 1. timeout raises SubprocessTimeoutError after 1 second while preserving startup output already read.

timeout/cancel also start a fixed sleep child in the same process group to check whether the framework reaps descendants too. cancel uses a streaming handle, cancels communicate after reading the startup line, displays CancelledError, and exits normally with 0. Output command_pid and process_group are actual values. The verification script checks the system to confirm that the whole group and printed descendant PIDs have disappeared; parent exit alone is not complete cleanup.

Source files are SubprocessDemo in [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) and the standard-library-only [external_job.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/external_job.py). SubprocessDemo shares its parent-process query function and Scenario enum with PythonProcessDemo; it creates no Shell service. When executing other programs in an application, still use a fixed executable/argument list. Do not concatenate untrusted input into `sh -c`.

### Run a long-lived Worker

`worker-demo` manages a long-lived Worker for the command's lifetime. A finite command demonstrates startup, task creation, and stop without requiring a permanent service. After preparing the same demo database, run:

```bash
./run.sh web worker-demo
./run.sh web worker-demo --scenario error
./run.sh web worker-demo --scenario stop
.venv/bin/python scripts/verify-worker-demo.py
```

The parent command reads actual project id/name/status values and passes plain records to the Worker. The Worker generates a JSON snapshot in its own temporary directory. After reading the complete file, the parent outputs `project_count`, `first_project`, and `worker_pid`; preset data contains 120 records. Manager status before output shows only process health, not task completion. Startup currently takes about 3 seconds; wait for the command to return.

- success: the one-off task finishes after export, and the command exits 0.
- error: the command adds an invalid project ID only to the transferred copy. The Worker's actual integer conversion fails and writes a business failure report; the parent reads it and exits 1. The database stays unchanged. This report is not a framework result/exception transport API.
- stop: after writing its snapshot, the task keeps waiting. The parent explicitly sends a stop instruction and waits for execute's finally block to write the completion marker. `execute_cleanup_completed=true` is actual cleanup evidence, rather than a state inferred from task_id.

All three paths close the manager, reap the Worker, close the parent database, and delete temporary files. `worker_pid=... reaped=true` corresponds to the verification script's system PID check. Missing results fail after at most 10 seconds and still trigger cleanup. Applications cannot use this temporary snapshot to recover tasks after power loss; use Taskiq for durable queues/results.

[worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py) owns the Command; [worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) defines importable Workers, synchronous factories, and tasks. The child does not inherit the parent's database connection and needs no Redis/NATS. If the entry point's settings enable NATS/Taskiq, the App command infrastructure prerequisites above still apply.

### Choose by the nature of the work (summary)

- Asynchronous sampling of the same process: no additional processes or message middleware required.
- CPU-intensive synchronous Python computation: use `AsyncProcessManager`; each call has concurrency and timeout limits.
- External commands: pass an executable and argument list, rather than constructing shell strings. Use controlled `run_subprocess_exec` for unattended execution (Web services, taskiq workers, automated tasks). Use `run_foreground` when a person must answer in the terminal (`sudo` asking for a password); see [Processes and background tasks](../developers/background.md#external-commands).
- Multiple long-lived Workers: use `BaseManager`. It sends only start/stop instructions and does not store reliable task results.
- Durable asynchronous function queues, results, and schedules: use [Distributed background tasks](distributed-tasks.md).
- Publishing or RPC between independent servers: Use NATS instead of exposing the Worker internal Queue to business services.

See [Processes and background tasks](../developers/background.md) for complete runnable examples, object origins, limitations, and shutdown methods. Computation examples without databases can run in a separate directory with Oldman installed. Workers depending on business Apps need the corresponding service configuration.

## Handle failure and shutdown

Task timeout or Worker shutdown does not undo business writes. Database writes still follow their own transaction management, and external calls may already have succeeded. Applications requiring idempotency define their own operation identifiers.

Use `try/finally` to close process managers, HTTP/NATS clients, and database pools you create. End tasks first, close connections they may still use next, and close logging last. Use `get_logger(__name__)` for ordinary business logging, without reinitializing logging for each task. See the [Logging](../developers/logging.md).

<!-- source: zh/users/background-work.md @ 8c13fdcf -->
