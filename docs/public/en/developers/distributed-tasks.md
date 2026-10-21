# Taskiq interfaces and runtime

First run the EPG demo through [Distributed background tasks](../users/distributed-tasks.md). This page explains object origins, connection ownership, and boundaries that maintenance must preserve. It is not another execution engine.

## Public objects and import timing

```python
from oldman.runtime import TaskiqWorkerApplication, TaskiqSchedulerApplication
from oldman.tasks.distributed import broker, schedule_source
```

The first line supports service declarations before configuration loads. The second requires service bootstrap, `settings.taskiq.enabled=true`, and a configured namespace. `broker` is the process's unique real TaskiqBroker instance, with `schedule_source is broker.schedule_source`. It is neither a proxy nor obtained from request.app.ctx, and is not recreated per publication.

broker inherits installed PullBasedJetStreamBroker, preserving native task decorators, kickers, .kiq(), dependencies, and results. schedule_source inherits ListRedisScheduleSource, preserving native ScheduledTask format. Applications must not instantiate these internal subclasses for another global object set. Construction creates objects/pools without networking; lifecycle handling below opens connections.

## App and service loading

AppConfig `tasks_module` defaults to `"tasks"`, with models/views semantics: a missing default module is skipped, an existing module's internal import error propagates, and None is invalid. Registry `load_tasks()` imports only registered App modules, requires completed model loading, avoids repeated imports, and rejects extra table declarations in task modules. It neither scans all project files nor installs Apps automatically.

| Process/entry point | Taskiq behavior and shutdown ownership |
| --- | --- |
| Worker management process | Discovers static service declarations, loads configuration/models, then starts native ProcessManager; opens no broker/database/HTTP itself |
| Worker execution child | Bootstraps its service after spawn; sets is_worker_process before Storage initialization/task loading; creates the native event loop, starts up, reports ready, and executes native Receiver; closes broker/framework DB/Cache/Redis on exit |
| Scheduler | TaskiqSchedulerApplication inherits SimpleApplication, sets is_scheduler_process, and loads tasks; native labels/shared Redis sources feed native SchedulerLoop; publishes without executing tasks |
| Ordinary Web | Each Sanic worker starts/closes broker through its asynchronous lifecycle without scanning all tasks; business views explicitly import needed tasks |
| Ordinary SimpleApplication | Wraps the existing before_start/main/shutdown chain with broker lifecycle; creates no Worker; business code imports tasks explicitly |
| One-off App Command | After bootstrap/models/commands, the asynchronous command lifecycle owns broker; starts no Web/Worker/Scheduler |
| Shell/IDE | bootstrap prepares settings/models only; caller enters `async with broker` on the actual event loop and closes on exit. Clean closure permits reuse on a new loop; nested/concurrent startup is invalid |

Workers/Schedulers automatically load only their own task Apps by default. Web does not import unused tasks just to publish one. Existing business-resource ownership in ordinary Web, Simple, and App commands does not transfer: custom HTTP/NATS Clients remain business-owned. Web asynchronous lifecycle overrides must retain super. Framework shutdown closes dedicated Worker shared DB/Redis/Cache; do not close process-wide pools per task.

### Core NATS communication inside tasks

With settings.nats_bus enabled, the Worker **execution child** opens Core before Taskiq broker.startup/WORKER_STARTUP and closes it only after native tasks/WORKER_SHUTDOWN finish. The parent does not connect. Core/Taskiq share this taskiq.startup_timeout budget rather than adding two 30-second limits. A shorter Core startup_timeout still applies. Initial failures follow existing startup attempts; runtime process recovery and task protocols remain unchanged.

Scheduler opens Core before native Taskiq startup/CLIENT_STARTUP and SchedulerLoop, then closes after native CLIENT_SHUTDOWN. It has no Worker-parent first-ready deadline, so Core's budget runs first, followed by original Taskiq startup attempts. Both dedicated services are **send-only** and do not load events for consume=true. Use ordinary SimpleApplication for event/RPC reception alone.

Failures/cancellation still attempt closure. Dedicated services clean framework DB/Cache/Redis/Core after original Taskiq shutdown; existing shutdown_timeout/group stop_timeout remain effective. This does not register bus.stop as a business hook and assume it runs last or copy native Receiver/ProcessManager. Even with identical nats_alias/namespace strings, Taskiq/Core use distinct Clients and oldman.taskiq / oldman.bus subjects without mixing ACKs, renewal, results, or buffers.

The actual example is Demo apps/examples/tasks.py::project_rpc, which calls nats_example.query_project_status and returns its real reply plus worker_pid. Enable nats_bus in Web/Worker, start nats_a, then publish/query at /examples/tasks/results. No Scheduler or repeated task-local bus startup is needed. The task has no automatic retries; offline remote failures appear through native task results. See [Let running services communicate with each other](../users/service-communication.md#5-call-rpc-from-taskiq-task) for setup/source.

Shell can use the demo's real task (interactive instructions, not another demo script). At the demo root, call `context = bootstrap_service("task_worker")`, then import `apps.examples.tasks.project_summary`; enter the broker context in your async function and call .kiq(). This only publishes, so a separate Worker process is still required. Do not nest async with broker within an already-started Web lifecycle.

## Configuration and defaults

The type is `oldman.conf.schemas.TaskiqConfig`. Seconds are positive; namespace/queue each form one safe subject segment. Existing SettingsManager still generates full YAML/manages App configuration, without new environment variables or task-only settings systems.

| Field | Default | Purpose |
| --- | --- | --- |
| enabled / namespace | false / None | Explicit opt-in; namespace required when enabled |
| nats_alias / redis_alias | DEFAULT / DEFAULT | Configured named connections; Redis supplies results and dynamic schedules |
| consume_queues | `["default"]` | Nonempty unique queues consumed by this execution-process group |
| workers / max_async_tasks / max_prefetch | 2 / 100 / 0 | Execution processes, per-process concurrency, extra Receiver admission slots |
| startup_timeout / startup_attempts | 30 / 3 | Per-initialization budget, initial attempts including the first |
| shutdown_timeout / stop_timeout | 5 / 60 | Resource-close budget, total service-stop budget |
| ack_wait / ack_timeout | 60 / 5 | Server acknowledgment wait/renewal basis, per-completion ACK timeout |
| publish_timeout / duplicate_window | 5 / 120 | Per-publication acknowledgment wait, server deduplication window; window must cover at least two publish_timeout periods |
| result_ex_time | 86400 | Result TTL from writing; reads do not renew |
| stream_max_bytes / stream_replicas | -1 / 1 | Byte limit (-1 uses server limits); replicas accept only 1/3/5, requiring actual deployment nodes |
| max_ack_pending | 1000 | Maximum unacknowledged messages for one queue across all listening processes |
| schedule_update_interval | 5 | Native schedule-source refresh interval |

Ordinary non-Web and both Taskiq service types do not automatically generate web sections; nats/taskiq are common root settings. With Taskiq disabled, aliases are not checked for connectivity and distributed is not imported automatically.

NATSConnectionConfig accepts nats_url, connect_timeout, reconnect_time_wait, credentials_file, tls_ca_file, tls_cert_file, and tls_key_file. Standard URL parsing decodes user/password/token and passes them separately to nats-py; creds and URL identity are mutually exclusive. TLS builds an SSLContext validating certificates/hostnames; client certificates/private keys come together. Plaintext servers are rejected before credential-bearing CONNECT, including on reconnection. Deployments supply certificate paths. Credentials are not logged, and no unverified fallback connection is created.

Redis settings reuse public provider conversion, including retries, protocol, and connection limits. Taskiq uses binary responses for native result/schedule formats without changing the whole provider to binary even if alias URLs specify decode_responses=true. Results/sources own separate pools rather than borrowing RedisClientRegistry pools or closing other consumers during Taskiq shutdown.

## Transport and resource names

For namespace `epg_demo`:

| Resource | Name/contract |
| --- | --- |
| Stream | `oldman_taskiq_epg_demo`: FILE, WorkQueue, DiscardNew, no message-age expiration |
| Durable task subject | `oldman.taskiq.epg_demo.tasks.<queue>` |
| Durable consumer per queue | `workers_<queue>`: explicit ACK, ALL, starts with all pending messages, max_deliver=-1 |
| Online broadcast subject | `oldman.taskiq.epg_demo.broadcast.<queue>`: Core NATS, no queue group or Stream persistence |
| Result-key prefix | `oldman_taskiq_epg_demo_results`, composed by the native Redis backend |
| Dynamic schedule prefix | `oldman_taskiq_epg_demo_schedules`, managed by native ListRedisScheduleSource |

Ordinary publishers can create/validate Streams but not consumers. Only Workers create/bind consumers and broadcast subscriptions. Existing resources are checked without updates. Concurrent creation handles only native already-exists conflicts, then rereads/validates. It does not overwrite settings to resolve conflicts or delete backlogs. Durable task and ordinary RPC/Core subjects are not consumed together. namespace isolates names rather than replacing NATS/Redis ACLs.

## Receiving, execution, and acknowledgment

Each subscription has at most one asynchronous read slot, merged into the same native Receiver. All queues/broadcasts share execution limits. max_prefetch=0 does not mean no client-side pending messages: Receiver admission still holds max_async_tasks, and the merger has at most one slot per source. Native broadcast buffers cap at 100 messages/1 MiB. max_prefetch is neither Stream length nor a per-queue execution limit.

Receiving a durable message creates a renewal coroutine for this delivery, including while waiting for Receiver. It calls native in_progress every ack_wait/3. Only WHEN_SAVED acknowledgment is accepted; early-ACK labels are rejected. Native Receiver still parses, validates arguments, invokes dependencies, executes, writes results, and acknowledges. RenewingReceiver only releases this renewal in finally without copying execution logic.

Completion uses native ack_sync, retrying once only on timeout. Final failure stops renewal; parsing/callback errors and shutdown also release it. Failure does not renew forever or rerun the function in place after an ACK error.

Durable Nats-Msg-Id is a stable digest of subject, task_name, task_id, and retry number. Only native NATS timeout resends identical bytes/ID, at most once. Capacity, permission, missing-Stream, and encoding errors are not acknowledgment-timeout retries. Final failure surfaces through native SendTaskError with cause retained. Lost acknowledgments do not establish that a task was never sent.

Ordinary JSON data, Chinese text, and native time schedules use native Taskiq/ORJSON formats. Arguments first undergo native model formatting; unserializable arguments can raise PydanticSerializationError before ORJSON, so not every encoding failure is TypeError. ignore_result skips before result encoding. Native result-save failure logs an exception but may still ACK; the framework preserves that behavior. See [Distributed background tasks](../users/distributed-tasks.md#6-under-what-circumstances-may-it-be-repeated-and-how-to-deal-with-it) for precise scenarios/business handling.

## Scheduling and runtime recovery

WaitingScheduler reuses LabelScheduleSource, shared RedisScheduleSource, and native SchedulerLoop.run. It adds only actual-send tracking/shutdown and one-off failure recovery. Failure anywhere in pre_send→publish→post_send logs the original exception and makes that one-off schedule eligible again, without a replacement scheduler loop.

Dynamic one-off schedules receive a stable task_id before saving, preserving explicit IDs. interval/cron do not fix every occurrence to that ID. SmartRetry uses the same source and defaults retry_on_error off. Only explicit labels create delayed retries, preserving task IDs and increasing retry numbers; intermediate failures do not save final results. Broadcasts force ignore_result=true and retry_on_error=false on this message only, without changing decorated-function shared labels.

Native reconnection/source refresh recovers and logs temporary runtime connection failures. Refresh is delayed, and failed reads do not guarantee latest schedules have taken effect. Failure to delete after sending may resend; stable-ID deduplication still has a window, not exactly-once guarantees. Initial intervals may be due immediately, including after restart, without replaying every missed interval. Cancellation does not withdraw queued messages or an already-cached occurrence whose sending has begun.

Shutdown first stops the native loop, awaits started source refreshes/sends including post_send, then closes source/broker. Only broker closes the Redis source pool, not both scheduler and broker. There is no second schedule-state table, leader election, or multi-Scheduler deduplication protocol. Run one Scheduler per namespace.

## Processes and exceptional shutdown

Worker uses native Taskiq ProcessManager.start, extending only prepare_workers/native action-queue checks for first readiness. Every execution slot has finite initial attempts; all slots must genuinely connect before ready. Normal runtime uses native max_fails=-1 to replace crashes continuously rather than reusing the initial three-attempt budget.

Worker/Scheduler share a private process-group lifecycle. Existing numeric PID files remain, with additional verifiable group identity. start owns the PID lock. stop verifies identity, requests shutdown, waits to the total deadline, and if needed kills/verifies the service's entire group. restart first confirms old-group exit. Terminal Ctrl+C follows the same deadline without signaling the caller shell or unrelated processes. Users call one stop, without a required second kill command.

Each broker startup has a total budget. Startup exceptions also enter the default five-second shutdown budget. Native partial TLS connections may hang on closure; preserve original connection/certificate exceptions rather than replacing them with cleanup timeout. Successful cleanup permits recreated underlying resources on a new loop. Failed cleanup marks objects unreusable and requires process exit rather than silent reset. Record dedicated-process exit separately from graceful closure of every library object.

Business-task waiting does not use the five-second resource budget; service stop_timeout bounds final group exit. Distinguish normal shutdown, deadline force-stop, and initialization failure. A test-finally kill does not establish normal shutdown acceptance.

## Maintenance and direct verification

Actual adapters are [broker.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/broker.py), [receiver.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/receiver.py), [results.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/results.py), [scheduler.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/scheduler.py), [worker.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/worker.py), and [runtime/taskiq.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/runtime/taskiq.py). Protocols use native types. Internal private fields/hooks are not user extension APIs.

pyproject.toml pins Taskiq 0.12.6, taskiq-nats 0.6.0, taskiq-redis 1.2.3, and nats-py 2.15.0. Redis is declared `>=8,<9`; this round verified 8.1.0, which is not an exact installation pin. Upgrades must review Receiver admission/ACK/result-failure semantics, ProcessManager action extensions, SchedulerLoop refresh/shutdown, Redis-source closure, and nats-py TLS/close instance patches. Import success alone is insufficient.

`tests/test_oldman_distributed_tasks.py` belongs to ordinary Python gates and starts its own NATS/Redis with isolated ports/directories/namespaces; see [Test isolation requirements](testing.md#real-service-checks) for executable discovery. `tests/taskiq_fault_checks.py` is a fault helper rather than a production runner. Demo real SQLite/Storage/task-function tests live in its `tests/test_examples_tasks.py`. Browser checks additionally cover real clicks, permissions, queuing, results, schedules, exit, and failure feedback.

Verified single-node/small-concurrency results do not establish cluster fault tolerance, arbitrary loads, or power-loss recovery. Track unfinished work in implementation/acceptance documents rather than public guarantees.

<!-- source: zh/developers/distributed-tasks.md @ 60ab2b58 -->
