# Distributed background tasks

Taskiq hands an asynchronous function to background execution. Web requests publish, Workers execute, and the Scheduler publishes when schedules are due. These differ from in-process `asyncio.create_task()`, long-lived Workers, and browser SSE.

The current combination is **Taskiq + NATS JetStream + Redis**: JetStream stores pending tasks; Redis stores results and dynamic schedules. No Celery, RabbitMQ, or additional Redis task broker is required. Python dependencies install with Oldman; deploy NATS and Redis separately.

This chapter directly corresponds to [tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py), [Task View](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tasks.py), [Worker Service](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_worker.py) and [Scheduler Service](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/services/task_scheduler.py) of EPG Demo. Complete [Run EPG Dashboard Demo](getting-started.md) first, and do not run these business commands in the framework repository.

## 1. Configure three independent services

The demo provides example YAML for `web`, `task_worker`, and `task_scheduler`. Following the running tutorial, prepare all five configuration files, including both Core receivers, then run project migrations. This chapter starts only the three required task services. Use sync to fill missing fields in existing files; do not overwrite database settings, keys, or connections:

```sh
./run.sh task_worker settings sync
./run.sh task_scheduler settings sync
./run.sh web settings sync
```

Configuration already comes from the examples. Do not repeat init on existing files. sync preserves existing values, so taskiq.enabled=false remains disabled.

This excerpt contains the Worker example's connections and Taskiq settings, not the whole file. Web/Scheduler share its namespace and connection aliases. workers, max_async_tasks, max_prefetch, and consume_queues configure consumption; publisher-only services do not need to copy them:

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

`TASKIQ` is an explicitly added connection alias, not one inferred by the framework. All three services must use the same NATS server and namespace. Shared results and schedules also require matching Redis addresses and database numbers. Taskiq defaults to disabled with no namespace. Enabling it requires a namespace containing only English letters, digits, underscores, and hyphens.

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

NATS must enable JetStream with a persistent directory and capacity for file storage. Configure production authentication/TLS for actual addresses; do not expose unauthenticated demo loopback settings publicly. With Taskiq enabled, services check required NATS and Redis connections during their own lifecycle, rather than discovering unreachable configuration at the first task. For other pages, explicitly disable Web Taskiq; task pages show enabling instructions. The demo also enables a separate nats_bus, so disabling Taskiq alone still requires NATS. Disable both if using neither. See [Let running services communicate with each other](service-communication.md#5-call-rpc-from-taskiq-task) for receiving services and RPC inside tasks.

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

The demo imports `from oldman.tasks.distributed import broker` and decorates `async def project_summary(...)` with `@broker.task(queue_name="reports")`. The function reads ExampleProject and its related task count inside `db_manager.get_read_session()` and returns a plain dictionary. See tasks.py linked above for the complete function. Pass record IDs, not requests, ORM instances, connections, or uploaded objects.

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

Each of the demo's two Worker processes allows three concurrent tasks, giving six execution slots total. reports and exports share those six slots; each queue does not get six of its own. Tasks remain queued when all slots are occupied. An empty queue does not block another queue.

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

## 5. Scheduling, cancellation, and explicit retries

The Demo view uses a unique dynamic source via `from oldman.tasks.distributed import schedule_source` and does not create the RedisScheduleSource itself. The actual calls are `schedule_by_time`, `schedule_by_interval`, and `schedule_by_cron`; for example, one-time schedule:

```python
await tasks.project_summary.kicker().with_task_id(identifier).with_schedule_id(identifier).schedule_by_time(
    schedule_source, dt.datetime.now(dt.UTC) + dt.timedelta(seconds=20), project_id,
)
```

Here dt is `import datetime as dt`, and the time is in UTC. Cancellation is `await schedule_source.delete_schedule(schedule_id)`; Demo first verifies that this schedule belongs to the current user, and then deletes its own ownership record. Cancel only deletes future schedules and does not withdraw tasks that have been delivered; the round that has been cached before the Scheduler refreshes may also be sent. The default source refresh interval is five seconds, which does not guarantee precise timing to milliseconds, nor does it promise to fill every interval during downtime.

Fixed schedules use a task label such as `schedule=[{"interval": 300}]`, read at Scheduler startup; restart after code changes. Dynamic interval/cron schedules persist in Redis until explicitly canceled; the source removes one-time schedules after successful sending. Redis persistence, backups, and eviction policies determine schedule survival. The result TTL of 24 hours does not describe all schedules.

The demo's `retry_summary` uses `retry_on_error=True, max_retries=3, delay=5`. Its first execution increments an actual Redis counter and deliberately raises an error; Scheduler publishes the retry, and the second execution reads the real project. The counter demonstrates first-attempt failure, rather than acting as a business deduplication lock. Intermediate failures store no final result. Retries require Scheduler; schedules do not run while it is stopped. Ordinary tasks default to no retries; broadcasts never retry automatically.

## 6. Under what circumstances may it be repeated and how to deal with it?

| Situation | Actual behavior and processing |
| --- | --- |
| Server stored the task but its publication acknowledgment was lost | The framework makes at most two attempts using the same publication ID. JetStream deduplicates within the default 120-second window. Two timeouts still report an unknown publication outcome; do not generate a new ID and resend blindly |
| Worker began execution or wrote business data, then crashed before acknowledgment | After renewal stops, JetStream redelivers unacknowledged tasks and another Worker may execute them. Use unique constraints or conditional UPDATE for business writes so repetition does not duplicate effects |
| Completion ACK did not reach the server | An ACK timeout retries once; final failure stops renewal, allowing redelivery if the server still has no acknowledgment. Losing only the ACK reply after server acknowledgment does not cause re-execution |
| User clicks again, a caller sends a new ID, or a retry is outside the deduplication window | This is another publication or one outside the window, without guaranteed merging. Use business record state/identifiers, rather than relying only on task_id |
| Explicit business exception retry | Deliberately execute the function again, retaining the task ID and changing the retry sequence so publication deduplication does not suppress the retry |
| The one-time schedule has been sent, but post_send failed to delete the schedule or the Scheduler subsequently exited. | The same schedule retains a stable task_id and may be resent after recovery; deduplication is performed within the window. It may still be executed after the window is exceeded. |

Long tasks are not redelivered merely because they exceed ack_wait. Renewal starts at receipt, including time waiting for execution, every ack_wait/3. A blocked event loop, prolonged disconnection, or process crash can still break renewal. Do not call time.sleep or run blocking computation directly in asynchronous tasks.

The demo's `complete_example_task()` runs `UPDATE ... WHERE id = record_id AND is_completed = false`, then reads rowcount. changed is true the first time and false the second. The existing database context commits it. This uses natural business state constraints; it requires neither a generic deduplication system in every application nor databases for all tasks. Read-only statistics may be recomputed. Handle external payments/emails through upstream idempotency keys or business state rules.

Results and business effects do not share a transaction. The native Receiver may still ACK after result encoding or Redis writes fail: work may have succeeded without a queryable result. Retain logs. Determine critical business success from business records or the external API, rather than repeating writes because Redis has no result.

## 7. Stopping, troubleshooting, and scope

```sh
./run.sh task_scheduler stop
./run.sh task_worker stop
```

Stopping the Scheduler first prevents further due publications; a running Web service can still publish. One stop command requests cleanup with a default total deadline of 60 seconds, then automatically force-stops the entire identity-verified service process group on timeout, without a separate kill. The default resource-close budget is five seconds, separate from time waiting for business tasks. Unacknowledged tasks can be redelivered after a forced stop; this is not business rollback.

Initial startup attempts each execution slot at most three times by default; exhaustion of any initial slot fails startup. After normal startup, the native manager continuously replaces crashed Workers without that three-attempt limit. Monitor repeated crashes. systemd is an optional outer supervisor, rather than a second internal Worker manager. Stop through systemd when supervised, or its restart policy may restart a service you stopped.

Configuration conflicts fail explicitly, without changing existing Streams/consumers or clearing backlogs. Check namespace, queues, ack_wait, and capacity against existing resources, then handle changes through deployment procedures. A namespace isolates names; it is not a user permission boundary. Use trusted networks, credentials, and permissions for NATS/Redis. Do not let external users publish arbitrary task names or read arbitrary result IDs.

Actual acceptance covered single-node JetStream, real Redis, two execution processes, one Scheduler, and demo Chrome operations. It did not fully validate deployment with 3/5-replica multi-node fault tolerance, production throughput, or power-loss recovery. The general NATS/FastStream RPC wrapper is a separate capability, outside this task API. See the [Taskiq interfaces and runtime](../developers/distributed-tasks.md) for exact configuration, lifecycle, and maintenance points.

<!-- source: zh/users/distributed-tasks.md @ db5eb607 -->
