# Distributed background tasks

Taskiq hands an asynchronous function to background execution. Web requests publish, Workers execute, and the Scheduler publishes when schedules are due. These differ from in-process `asyncio.create_task()`, long-lived Workers, and browser SSE.

The current combination is **Taskiq + NATS JetStream + Redis**: JetStream stores pending tasks; Redis stores results and dynamic schedules. No Celery, RabbitMQ, or additional Redis task broker is required. Python dependencies install with Oldman; deploy NATS and Redis separately.

This chapter directly corresponds to [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py), [Task View](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py), [Worker Service](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_worker.py) and [Scheduler Service](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_scheduler.py) of EPG Demo. Complete [Demo installation and data preparation](getting-started.md) first, and do not run these business commands in the framework repository.

## 1. Configure three independent services

The demo has provided example YAML for `web`, `task_worker`, and `task_scheduler`. First, follow the running tutorial to prepare five configurations including two Core receiving services from the sample, and then perform project migration; this chapter only starts the three required task-related services. Use sync to fill fields in existing files and cannot overwrite the original database, key or connection:

```sh
./run.sh task_worker settings sync
./run.sh task_scheduler settings sync
./run.sh web settings sync
```

The configuration has been created from the sample, no init is repeated for already existing files. sync retains the existing value, so the original service with taskiq.enabled=false will not be automatically started.

The following takes the connection and Taskiq parts of the Worker example as an example, not the entire file. Web/Scheduler uses the same namespace and connection alias; workers, max_async_tasks, max_prefetch, and consume_queues are the consumer settings of the Worker and do not require published-only services to copy them:

```yaml
nats:
  TASKIQ:
    nats_url: nats://127.0.0.1:4222
redis:
  TASKIQ:
    redis_url: redis://127.0.0.1:6379/7
taskiq:
  enabled: true
  namespace: epg_demo
  nats_alias: TASKIQ
  redis_alias: TASKIQ
  consume_queues: [reports, exports]
  workers: 2
  max_async_tasks: 3
  max_prefetch: 0
```

`TASKIQ` is the connection alias added explicitly here, not the connection automatically guessed by the framework. The three must connect to the same NATS and use the same namespace; when they need to read results and schedules from each other, the Redis address and database number must also be consistent. The framework is disabled by default and has no namespace; when enabled, the namespace must be filled in, and only English letters, numbers, underscores, and hyphens are allowed.

Worker/Scheduler install `oldman.auth`, `apps.accounts`, and `apps.examples`. Auth selects `apps.accounts.models.User`, using the same database as Web. Complete files are [task_worker_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/task_worker_settings.example.yaml) and [task_scheduler_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/task_scheduler_settings.example.yaml). Do not copy every Web App and view as prerequisites for background work. Export tasks use the Worker's `storages.default`. Choose shared storage across machines as required; local media is not synchronized automatically.

After checking, start in three terminals:

```sh
./run.sh task_worker settings check
./run.sh task_scheduler settings check
./run.sh web settings check
```

```sh
./run.sh task_worker start
```

```sh
./run.sh task_scheduler start
```

```sh
./run.sh web start
```

NATS must enable JetStream with a persistent directory and capacity for file storage. Configure production authentication/TLS for actual addresses; do not expose unauthenticated demo loopback settings publicly. With Taskiq enabled, services check required NATS and Redis connections during their own lifecycle, rather than discovering unreachable configuration at the first task. For other pages, explicitly disable Web Taskiq; task pages show enabling instructions. The demo also enables a separate nats_bus, so disabling Taskiq alone still requires NATS. Disable both if using neither. See [Communication](service-communication.md#5-call-rpc-from-taskiq-task) for receiving services and RPC inside tasks.

`run.sh` is just a command entry, and the Web will not start the Worker/Scheduler for you. Only one Scheduler is deployed in the same namespace; adding more Workers does not require adding Schedulers.

## 2. Operate the real page

The default Web address is `http://127.0.0.1:17997`. Sign in with an active account. Data comes from demo fixtures, rather than invented fixed return values:

| Page | Actual operations and observations |
| --- | --- |
| `/examples/tasks/results` | Select a project, publish its summary, then query it; exports write to Storage; deliberate failure shows Worker exceptions; ignore-result demonstrates tasks without saved results |
| `/examples/tasks/schedules` | Execute once after 20 seconds, cancel schedule, 60 second period, cron every two minutes, retry after first intentional failure |
| `/examples/tasks/queues` | reports/exports share execution processes; ordinary refresh runs in one process, while broadcasts show every online process PID in logs; completing the same business record twice gives changed=false the second time |

GET pages create neither tasks nor schedules. Buttons create dynamic schedules, retaining at most ten demo schedules owned by the current user. Cancel unneeded schedules on the page. Fixed `refresh_project_counts` refreshes in-process statistics every 300 seconds without database writes; the first interval may run immediately after Scheduler startup.

You can stop the Worker first, keep the Web, record the ID after delivery, and then start the Worker and query the same ID to observe the real queue. Do not stop shared facilities or other people's services to try to troubleshoot. The page does not continuously poll, and there is no global task history table; refreshing the page may lose the last results panel, but the task itself will not be canceled.

## 3. Functions, delivery and results

The task function of Demo uses real `from oldman.tasks.distributed import broker` and decorates `async def project_summary(...)` with `@broker.task(queue_name="reports")`. It reads the ExampleProject and associated task number in `db_manager.get_read_session()` and returns a normal dictionary. For the complete function, see tasks.py at the beginning of this chapter; the record ID is passed as the parameter, and the request, ORM instance, connection or upload object is not passed.

The following is an excerpt of the actual delivery statement in Demo `example_task_run()`, which is not a script that can be executed alone. `tasks` comes from `apps.examples`, `identifier` is the UUID generated this time and registered for the current user, and `project_id` has been verified and confirmed to exist:

```python
await tasks.project_summary.kicker().with_task_id(identifier).with_labels(ignore_result=ignored).kiq(
    project_id, fail=operation == "fail"
)
```

Without these customizations, use the native shorthand `job = await project_summary.kiq(project_id)`. **This await waits for publication acknowledgment, not the function result.** An ordinary task executes once in one Worker listening to that queue, rather than in every Worker.

The query view directly uses the broker's native result backend. The task_id in the excerpt below has passed the current user ownership check; the broker has been started by the web lifecycle:

```python
from taskiq_redis.exceptions import ResultIsMissingError
from oldman.tasks.distributed import broker

try:
    result = await broker.result_backend.get_result(task_id)
except ResultIsMissingError:
    return await _result(request, outcome="unavailable", **owned)
```

`_result` and `owned` are the demo view's rendering helper and ownership data, rather than framework APIs. It then checks `result.is_err` to display `return_value` or `error`. Non-HTTP callers needing to wait can use native `await job.wait_result(timeout=...)`; the demo's browser requests do not wait for lengthy work this way.

Results persist for 86400 seconds (24 hours) from writing by default and expire through Redis TTL; queries do not renew them. A missing result may mean unfinished work, expiry, explicit ignore-result, a failed result write, or the wrong namespace/Redis. **It does not prove the task is still running and must not trigger automatic republication.** The demo reads once and handles absence, avoiding an EXISTS-then-GET expiry race. Actual Redis/decoding errors still propagate.

`ignore_result=True` can be declared in a decorator, or set for a kicker as above; it only skips result storage and does not cancel function execution. Do not wait for the return value of such a task. Logs will still be recorded if the task fails; ordinary business exceptions will not be automatically retried by default.

## 4. Queues, concurrency and broadcasting

The two worker processes in the demo each allow three concurrent tasks, and the total execution limit is six. Reports and exports share this limit, and each queue does not have six. When there are no free positions, tasks continue to be queued; an empty queue will not block another queue.

Don't confuse the three quantities:

- `max_async_tasks`: How many Taskiq functions are executed simultaneously by each process.
- `max_prefetch`: The number of additional waiting tasks accepted by the native Receiver, the default is zero; each subscription has at most one merged read slot, and the broadcast also has a bounded receiving buffer. It is not the total queue capacity.
- `stream_max_bytes`: The upper limit of bytes for JetStream to save tasks, the default is -1, and is ultimately still limited by server/account capacity. When full, new deliveries will be rejected and an error will be reported. The old backlog will not be deleted for new tasks. `max_ack_pending` limits the number of unconfirmed tasks in a queue. The default is 1000, which is not execution concurrency.

Direct `await project_summary(project_id)` is an ordinary function call using the parent task's current execution slot; the demo's export_project reuses summaries this way. `await project_summary.kiq(project_id)` publishes another queued task. If all slots are occupied by parents waiting for child results, they deadlock. Avoid this design: split queues across different Worker services or do not wait within the parent.

asyncio tasks or framework background coroutines created inside a task are not separately governed by Taskiq's concurrency limit and are not durable tasks. Business code must await and clean up its own coroutines. Do not use them to bypass capacity or assume execution resumes after process exit.

Demo's normal refresh and broadcast use the same registered function. The following is the actual call of the view; the operation has been limited to local or broadcast:

```python
await tasks.refresh_project_counts.kicker().with_task_id(identifier).with_labels(broadcast=operation == "broadcast").kiq()
```

Broadcasts use a separate Core NATS subject without writing the task Stream or using a queue group. Each execution process **online and listening to that queue_name** receives one copy. Results are forcibly ignored and exceptions are not retried automatically. Offline periods are not replayed; full slow-consumer buffers drop messages and log errors. Successful sending means only completion of server send/flush, not successful execution in every Worker. It does not suit work requiring individual acknowledgments.

## 5. Scheduling, Cancellation, and Explicit Retries

The Demo view uses a unique dynamic source via `from oldman.tasks.distributed import schedule_source` and does not create the RedisScheduleSource itself. The actual calls are `schedule_by_time`, `schedule_by_interval`, and `schedule_by_cron`; for example, one-time schedule:

```python
await tasks.project_summary.kicker().with_task_id(identifier).with_schedule_id(identifier).schedule_by_time(
    schedule_source, dt.datetime.now(dt.UTC) + dt.timedelta(seconds=20), project_id,
)
```

Here dt is `import datetime as dt`, and the time is in UTC. Cancellation is `await schedule_source.delete_schedule(schedule_id)`; Demo first verifies that this schedule belongs to the current user, and then deletes its own ownership record. Cancel only deletes future schedules and does not withdraw tasks that have been delivered; the round that has been cached before the Scheduler refreshes may also be sent. The default source refresh interval is five seconds, which does not guarantee precise timing to milliseconds, nor does it promise to fill every interval during downtime.

Fixed schedules use a task label such as `schedule=[{"interval": 300}]`, read at Scheduler startup; restart after code changes. Dynamic interval/cron schedules persist in Redis until explicitly canceled; the source removes one-time schedules after successful sending. Redis persistence, backups, and eviction policies determine schedule survival. The result TTL of 24 hours does not describe all schedules.

Demo `retry_summary` uses `retry_on_error=True, max_retries=3, delay=5`. The first time it intentionally throws an error after the real Redis count, the Scheduler then delivers and retries, and the second time it reads the real project. Its count is only used to demonstrate the first failure, not for business deduplication. There is no final result for intermediate failures; retry requires Scheduler, and the schedule will not execute itself when Scheduler is closed. Ordinary tasks are not retried by default, and broadcasts are never automatically retried.

## 6. Under what circumstances may it be repeated and how to deal with it?

| Situation | Actual behavior and processing |
| --- | --- |
| The server saved the task, but the release confirmation was lost in the network. | The framework tries at most two times with the same sending ID; JetStream deduplicates within the default 120-second window. It times out twice and still reports that the delivery result is unknown; do not generate a new ID and blindly resend |
| Worker has started/written business data, but crashed before confirmation. | JetStream re-submits unconfirmed tasks after the renewal is stopped; a new Worker may execute it again. Use unique constraints or conditions UPDATE for business writing, so that repeated calls will not produce repeated effects |
| Completion ACK did not reach the server | An ACK timeout retries once; final failure stops renewal, allowing redelivery if the server still has no acknowledgment. Losing only the ACK reply after server acknowledgment does not cause re-execution |
| manually clicks again, caller resends a new ID, or resends beyond the deduplication window. | belongs to another delivery or delivery outside the window, and automatic merging is not guaranteed; it is processed according to the status/unique identification of the business record, rather than relying solely on task_id |
| Explicit business exception retry | Deliberately execute the function again, retaining the task ID and changing the retry sequence so publication deduplication does not suppress the retry |
| The one-time schedule has been sent, but post_send failed to delete the schedule or the Scheduler subsequently exited. | The same schedule retains a stable task_id and may be resent after recovery; deduplication is performed within the window. It may still be executed after the window is exceeded. |

Long tasks are not redelivered merely because they exceed ack_wait. Renewal starts at receipt, including time waiting for execution, every ack_wait/3. A blocked event loop, prolonged disconnection, or process crash can still break renewal. Do not call time.sleep or run blocking computation directly in asynchronous tasks.

Demo's `complete_example_task()` uses a `UPDATE ... WHERE id = record_id AND is_completed = false` to change the record to complete, and then read the rowcount. The first time changed=true, the second time false; the commit is done by the existing database context. This is a natural constraint of the business status. It does not require every application to establish a universal deduplication system, nor does it require that all tasks must use a database. Read-only statistics allow recalculation; side effects such as external payment/sending are handled according to the idempotent keys or business status rules provided by the external interface.

The result and the business are not the same transaction. The current native Receiver may still ACK after result encoding or Redis writing failure: the task may have been executed successfully, but there is no checkable result. Logs must be retained; whether the key business is successful is based on its own records or external interfaces. Do not write again based on "Redis has no results".

## 7. Stopping, Troubleshooting and Scope

```sh
./run.sh task_scheduler stop
./run.sh task_worker stop
```

Stopping the Scheduler first prevents further due publications; a running Web service can still publish. One stop command requests cleanup with a default total deadline of 60 seconds, then automatically force-stops the entire identity-verified service process group on timeout, without a separate kill. The default resource-close budget is five seconds, separate from time waiting for business tasks. Unacknowledged tasks can be redelivered after a forced stop; this is not business rollback.

Initial startup attempts each execution slot at most three times by default; exhaustion of any initial slot fails startup. After normal startup, the native manager continuously replaces crashed Workers without that three-attempt limit. Monitor repeated crashes. systemd is an optional outer supervisor, rather than a second internal Worker manager. Stop through systemd when supervised, or its restart policy may restart a service you stopped.

Configuration conflicts will clearly report errors, existing Stream/consumers will not be modified, and the backlog will not be automatically cleared. Check whether the namespace, queue, ack_wait/capacity and other configurations are consistent with existing resources, and handle changes according to the deployment process. Namespace is naming isolation, not user permission boundary; NATS/Redis should use trusted networks, credentials and permissions, and cannot allow external users to arbitrarily send task names or read arbitrary result IDs.

Actual acceptance covered single-node JetStream, real Redis, two execution processes, one Scheduler, and demo Chrome operations. It did not fully validate deployment with 3/5-replica multi-node fault tolerance, production throughput, or power-loss recovery. The general NATS/FastStream RPC wrapper is a separate capability, outside this task API. See the [Developer Reference](../developers/distributed-tasks.md) for exact configuration, lifecycle, and maintenance points.

<!-- source: zh/users/distributed-tasks.md @ db5eb607 -->
