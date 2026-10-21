# Run jobs in the background

First distinguish a browser waiting for a single result from a service running continuously in the background. Use SimpleApplication for sampling or consumption tasks without HTTP. Use App Commands for one-off statistics or imports, without another long-running service.

## Demo's current bounds

Durable queuing and scheduled tasks have a complete [Taskiq demo](distributed-tasks.md): database summaries/exports, two queues, online broadcasts, schedules, and results. It uses separate task_worker/task_scheduler services. The existing local coroutine and long-lived Worker interfaces below do not thereby become durable queues.

All four local execution examples use finite App Commands, releasing resources when they finish without requiring a persistent collector service. For actual persistent SimpleApplication wiring, see the [NATS receiving services](service-communication.md); they receive events/RPC, without collecting monitoring data. Realtime tables replay existing database samples within Web requests; explicit publish buttons write samples for realtime charts. Opening a page in each browser does not repeatedly start background collectors.

### Run a local background coroutine

EPG Demo already provides `background-stats`, and there is no need to add a new collector service. After completing the Demo configuration, migration and optional `loaddata demo`, run in the Demo root directory:

```bash
./run.sh web background-stats
./run.sh web background-stats --team-id 1
```

The command registers and starts a BackgroundTaskManager coroutine, reads the project count from the database once per second, and stops after two samples. It does not start Web, write to the database, or launch a collector from browser connections. If YAML enables NATS/Taskiq, the App command lifecycle still connects to them first. For this example alone, disable `nats_bus.enabled` and `taskiq.enabled` in your local YAML; no Worker/Scheduler is needed.

Output includes `samples`, `running`, `stopped`, and `cleanup_completed`. With unchanged preset data, full-table samples are `[120, 120]` and team 1 samples are `[15, 15]`; use your actual database, without hardcoding counts. `running.is_alive=true` confirms that the coroutine is running. After explicit stop, `stopped.is_alive=false` and `cleanup_completed=true` confirm its finally block ran. The command stops the task, removes its registration, then closes the database.

`--team-id 0` is a parameter error, exit code 2; legal but non-existent ID is a real query failure in the coroutine, exit code 1, and resources will be cleaned up. Teams that exist but have no projects return `[0, 0]`, which is not an error. Only wait for this two samples, up to 10 seconds; the timeout will also end and be cleared, and no false results will be output.

The complete source is [background.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/background.py). [commands.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/commands.py) publicly imports its Command class for automatic App Registry discovery. This independent CLI process owns the entire manager. **Do not copy Command.handle into a Web service handling requests and call start_all/stop_all**; that would affect other tasks in the same process.

SimpleApplication's `main()` can also write asynchronous loops directly. Use `self.task_manager` only if you need multiple independent coroutines and state/restart management. It will not automatically start all registered tasks. The application is responsible for `start_all()` and waits for `stop_all()` when exiting; do not call `asyncio.create_task()` in `prepare()` without an event loop.

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

- Success: The child process stdout displays the PID/input number, the parent process displays `counts`, and finally `child_pid=... reaped=true`, exiting 0.
- error: The demonstration function deliberately throws ValueError, the framework prints its stack and returns None; the command treats this missing result as a failure and exits 1,**It is not the original exception that is automatically thrown across processes**.
- timeout: The demonstration function waits for 30 seconds, but the upper limit of this call is 1 second; in actuality, ProcessTimeoutError is thrown, exits with 1, and the child process is recycled.
- cancel: Cancel waiting after the sub-function actually writes out the PID, and observe CancelledError; this is an actively selected cancellation demonstration, exits 0 normally, and does not output project statistics.

All four paths close the manager/database in finally, verify that the child PID no longer exists, then remove their own PID file under `/tmp`. They neither modify project records nor use Worker queues. Run `.venv/bin/python scripts/verify-process-demos.py` to check the four Python and four external command paths sequentially. The script requires prepared demo configuration and database; it does not silently migrate or import fixtures.

Source code: [process_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_jobs.py) is an importable top-level target that only relies on the standard library; [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py) is the Command owner and is exposed through commands.py. Don't move target into stdin/local functions, and don't pass Session, Request, or live connections to child processes.

### Run a controlled external command

The same Demo also provides `subprocess-demo`, which only executes the project's own fixed Python module, not a background where you can enter any shell command:

```bash
./run.sh web subprocess-demo
./run.sh web subprocess-demo --scenario error
./run.sh web subprocess-demo --scenario timeout
./run.sh web subprocess-demo --scenario cancel
```

The default mode encodes the real project status into JSON bytes and hands it to the external program via stdin; stdout contains the startup PID and statistics. This is standard input/output between processes, not the Python object Queue. error mode explicitly lets the subroutine write to stderr and exit 7, the SubprocessError thrown by the framework preserves output, and the Oldman command exits 1. timeout throws SubprocessTimeoutError after 1 second, and the read startup information can still be seen in the output.

timeout/cancel also start a fixed sleep child in the same process group to check whether the framework reaps descendants too. cancel uses a streaming handle, cancels communicate after reading the startup line, displays CancelledError, and exits normally with 0. Output command_pid and process_group are actual values. The verification script checks the system to confirm that the whole group and printed descendant PIDs have disappeared; parent exit alone is not complete cleanup.

The source files are SubprocessDemo of [process_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/process_examples.py), and [external_job.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/external_job.py) which only relies on the standard library. Shares the parent process query function and Scenario enumeration with PythonProcessDemo, and does not create a new Shell service. When the actual business executes other programs, the fixed program/argument list is still used, and untrusted input is not concatenated into `sh -c`.

### Run a long-lived Worker

`worker-demo` manages a long-lived Worker for the command's lifetime. A finite command demonstrates startup, task creation, and stop without requiring a permanent service. After preparing the same demo database, run:

```bash
./run.sh web worker-demo
./run.sh web worker-demo --scenario error
./run.sh web worker-demo --scenario stop
.venv/bin/python scripts/verify-worker-demo.py
```

The parent command reads actual project id/name/status values and passes plain records to the Worker. The Worker generates a JSON snapshot in its own temporary directory. After reading the complete file, the parent outputs `project_count`, `first_project`, and `worker_pid`; preset data contains 120 records. Manager status before output shows only process health, not task completion. Startup currently takes about 3 seconds; wait for the command to return.

- Success: The one-time task ends after exporting, and the command exits 0.
- error: only the illegal project ID is added to the transfer copy, the actual integer conversion of the Worker fails, and a business failure report is written; the parent command exits 1 after reading the report. The database remains unchanged and this report is not falsely referred to as the framework's result/exception callback API.
- stop: The task is still waiting after generating a snapshot; the parent command explicitly sends a stop command, and waits for the finally of task execute to write the end mark before continuing. `execute_cleanup_completed=true` is the actual cleanup evidence, not the status guessed based on task_id.

All three paths close the manager, reap the Worker, close the parent database, and delete temporary files. `worker_pid=... reaped=true` corresponds to the verification script's system PID check. Missing results fail after at most 10 seconds and still trigger cleanup. Applications cannot use this temporary snapshot to recover tasks after power loss; use Taskiq for durable queues/results.

Source code: [worker_examples.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_examples.py) is the Command owner; [worker_jobs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/worker_jobs.py) defines importable Workers, synchronous factories and tasks. The child process does not inherit the database connection of the parent process and does not require Redis/NATS. If NATS/Taskiq is enabled in the portal configuration, the facility prerequisites of the above App command still apply.

### Choose by the nature of the work (summary)

- Asynchronous sampling of the same process: no additional processes or message middleware required.
- CPU-intensive synchronous Python computation: use `AsyncProcessManager`; each call has concurrency and timeout limits.
- External commands: pass an executable and argument list, rather than constructing shell strings. Use controlled `run_subprocess_exec` for unattended execution (Web services, taskiq workers, automated tasks). Use `run_foreground` when a person must answer in the terminal (`sudo` asking for a password); see [External commands](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/background.md#外部命令).
- Multiple long-lived Workers: use `BaseManager`; need to know that it only transmits start/stop instructions and does not save reliable task results.
- Persistent queuing of asynchronous functions, results and plans: using [Taskiq](distributed-tasks.md).
- Publishing or RPC between independent servers: Use NATS instead of exposing the Worker internal Queue to business services.

For the corresponding complete runnable example, object sources, restrictions and shutdown methods, see [Process and Task Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/background.md). Computing examples that do not require a database can be executed directly in the independent directory where Oldman is installed; only Workers that rely on business apps require corresponding service configuration.

## Handle failure and shutdown

Task timeout or Worker shutdown does not undo business writes. Database writes still follow their own transaction management, and external calls may already have succeeded. Applications requiring idempotency define their own operation identifiers.

Use `try/finally` to close process managers, HTTP/NATS clients, and database pools you create. End tasks first, close connections they may still use next, and close logging last. Use `get_logger(__name__)` for ordinary business logging, without reinitializing logging for each task. See the [Logging reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/logging.md).

<!-- source: zh/users/background-work.md @ 8c13fdcf -->
