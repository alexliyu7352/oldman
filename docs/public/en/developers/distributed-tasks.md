# Taskiq interfaces and runtime

Start by running the EPG demo through [the user tutorial](../users/distributed-tasks.md). This page explains where objects come from, who opens and closes connections, and which boundaries maintenance must preserve. It does not introduce another execution engine.

Agents: before writing code, read the [background work guide](../agents/background-work.md) to decide whether the work belongs in Taskiq at all; if it does, wire it up with the [Taskiq wiring guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/distributed-tasks.md) (`docs/public/zh/agents/distributed-tasks.md`).

## Public objects and import timing

```python
from oldman.runtime import TaskiqWorkerApplication, TaskiqSchedulerApplication
from oldman.tasks.distributed import broker, schedule_source
```

The first line can be used in service declarations before configuration loads. The second requires service bootstrap to be complete, `settings.taskiq.enabled=true`, and a configured namespace. `broker` is the current process's only actual TaskiqBroker instance, and `schedule_source is broker.schedule_source`. It is not a proxy, does not come from request.app.ctx, and is not created again for every publication.

broker inherits the installed PullBasedJetStreamBroker, retaining its native `task` decorator, kicker, `.kiq()`, task dependencies, and result objects. schedule_source inherits ListRedisScheduleSource and preserves its native ScheduledTask format. Applications must not instantiate these internal subclasses to create another set of global objects. Construction creates objects and pools without connecting to the network; the lifecycles below must establish those connections.

## App and service loading

AppConfig's `tasks_module` defaults to `"tasks"` and follows the same rules as models and views. A missing default module is skipped. If an existing module fails during an internal import, the original error propagates. The setting must not be None. Registry's `load_tasks()` imports only the precise modules of registered Apps, requires model loading to have finished, and does not repeat imports on subsequent calls. Task modules must not declare additional database tables. It neither scans every project file nor installs extra Apps automatically.

| Process or entry point | Taskiq behavior and shutdown ownership |
| --- | --- |
| Worker management process | After static discovery, configuration, and model loading, it starts the native ProcessManager. It opens no broker, database, or HTTP connection itself. |
| Worker execution child | After spawn, it bootstraps its own service. It sets is_worker_process before initializing Storage and loading tasks, then creates the native event loop, starts up, reports ready, and runs the native Receiver. On exit it closes the broker and framework database, cache, and Redis resources. |
| Scheduler | TaskiqSchedulerApplication inherits SimpleApplication, sets is_scheduler_process, and loads tasks. It passes native label sources and the shared Redis source to the native SchedulerLoop. It publishes tasks but does not execute them. |
| Ordinary Web service | Each Sanic worker starts and closes the broker within its asynchronous lifecycle. It does not scan all tasks automatically; business views explicitly import the tasks they need. |
| Ordinary SimpleApplication | The broker lifecycle wraps the existing before_start, main, and shutdown sequence. It does not create a Worker for the application. Business code imports tasks explicitly. |
| One-off App Command | After bootstrap, model loading, and command loading, the asynchronous command lifecycle owns the broker. It starts no Web service, Worker, or Scheduler. |
| Shell or IDE | bootstrap prepares only configuration and models. The caller enters `async with broker` on the actual event loop and closes it on exit. Clean shutdown permits reuse on a new loop. Nested or concurrent startup calls are not allowed. |

Workers and Schedulers automatically load only their own task Apps by default. Web does not import every unused task just to send one. Existing resource ownership in ordinary Web services, Simple services, and App commands does not change: business code still closes its own HTTP and NATS Clients. Overrides of Web's asynchronous lifecycle must retain super calls. The framework closes a dedicated Worker's shared database, Redis, and cache resources; do not close process-wide pools after each task.

### Core NATS communication inside tasks

When settings.nats_bus is enabled, the Worker **execution child** opens Core before Taskiq broker.startup and WORKER_STARTUP. It closes Core only after native tasks and WORKER_SHUTDOWN finish. The management parent does not connect. Core and Taskiq connection establishment share that taskiq.startup_timeout budget rather than adding two 30-second limits. A shorter Core startup_timeout still applies. Initial failure follows the existing startup-attempt rules; runtime process recovery and the task protocol are unchanged.

Scheduler opens Core first, then enters native Taskiq startup, CLIENT_STARTUP, and SchedulerLoop. It closes Core after native CLIENT_SHUTDOWN. Unlike Worker, it has no parent-process deadline for initial readiness, so it first applies Core's budget and then the original Taskiq startup-attempt rules. Both dedicated services are **send-only**. They do not load events automatically when consume=true. Use an ordinary SimpleApplication for a service that only receives events or RPC.

Failure and cancellation still attempt shutdown. Dedicated services clean up framework database, cache, Redis, and Core resources after the original Taskiq shutdown. The existing shutdown_timeout and whole-group stop_timeout still apply. This is not a bus.stop business hook assumed to run last, nor a copy of the native Receiver or ProcessManager. Even if Taskiq and Core share nats_alias and namespace strings, they use separate Clients and distinct oldman.taskiq and oldman.bus subjects. Their acknowledgments, renewals, results, and buffers are not mixed.

The actual demo is apps/examples/tasks.py::project_rpc. Its task calls nats_example.query_project_status and returns the real reply and worker_pid. Enable nats_bus in Web and Worker, start nats_a, then submit and query the task at /examples/tasks/results. No Scheduler or repeated bus startup within the task is needed. The task does not retry automatically. An offline remote becomes a task failure displayed through the existing result path. See [the communication tutorial](../users/service-communication.md#5-call-rpc-from-taskiq-task) for complete preparation and source.

You can use the demo's actual task interactively in a Shell; this is not another script file in the demo. At its root, first run `context = bootstrap_service("task_worker")`, then import `apps.examples.tasks.project_summary`. Enter the broker context in your own asynchronous function and call `.kiq()`. This only publishes, so another process must still run a Worker. Do not enter another `async with broker` inside an already-started Web lifecycle.

## Configuration and defaults

The configuration type is `oldman.conf.schemas.TaskiqConfig`. Every duration in seconds must be positive. namespace and queue must each be one safe subject segment. Existing SettingsManager still generates complete YAML and manages App configuration; there are no new environment variables or separate task-configuration systems.

| Field | Default | Purpose |
| --- | --- | --- |
| enabled and namespace | false and None | Taskiq requires explicit enablement, with namespace required when enabled. |
| nats_alias and redis_alias | DEFAULT and DEFAULT | These identify configured named connections. Redis stores both results and dynamic schedules. |
| consume_queues | `["default"]` | These are the queues consumed by one execution-process group. The list must be nonempty and contain no duplicates. |
| workers, max_async_tasks, and max_prefetch | 2, 100, and 0 | These set the number of execution processes, total concurrency per process, and additional Receiver admission slots, respectively. |
| startup_timeout and startup_attempts | 30 and 3 | These set the budget for one initialization and the number of initial attempts, including the first. |
| shutdown_timeout and stop_timeout | 5 and 60 | These set the resource-shutdown budget and the total service-stop budget. |
| ack_wait and ack_timeout | 60 and 5 | These set the server acknowledgment wait used for renewal and the timeout for one completion ACK. |
| publish_timeout and duplicate_window | 5 and 120 | These set the wait for a publication acknowledgment and the server deduplication window. The window must cover at least two publish_timeout periods. |
| result_ex_time | 86400 | Result TTL starts at writing; reading does not renew it. |
| stream_max_bytes and stream_replicas | -1 and 1 | These set the byte limit and replica count. A limit of -1 uses the server restriction. Replicas must be 1, 3, or 5, with actual deployment nodes available. |
| max_ack_pending | 1000 | This limits unacknowledged messages for one queue across all listening processes. |
| schedule_update_interval | 5 | This sets the native schedule-source refresh interval. |

Neither ordinary non-Web services nor the two Taskiq service types generate a web section automatically. nats and taskiq are general root settings. With Taskiq disabled, its aliases are not checked for actual connectivity, and distributed is not imported automatically.

NATSConnectionConfig accepts `nats_url`, connect_timeout, reconnect_time_wait, credentials_file, tls_ca_file, tls_cert_file, and tls_key_file. Standard URL parsing decodes the user, password, or token and passes the identity separately to nats-py. A creds file and URL credentials must not be combined. Configuring TLS creates an SSLContext that validates certificates and hostnames. Client certificate and private-key files must be supplied together. A plaintext server is rejected before a credential-bearing CONNECT, and reconnection cannot downgrade. Deployments supply certificate paths. Credentials are not logged, and no fallback disables certificate validation.

Redis parameters reuse the provider's public conversion for retries, protocol, connection limits, and other options. Taskiq uses binary responses for its native result and schedule formats. Even if an alias URL sets decode_responses=true, it does not change the entire provider to binary mode. Results and sources each own separate pools, rather than borrowing RedisClientRegistry pools. Closing Taskiq does not close other consumers.

## Transport and resource names

For namespace `epg_demo`:

| Resource | Name and contract |
| --- | --- |
| Stream | `oldman_taskiq_epg_demo` uses FILE, WorkQueue, and DiscardNew, without expiration based on message age. |
| Durable task subject | The subject is `oldman.taskiq.epg_demo.tasks.<queue>`. |
| Durable consumer per queue | `workers_<queue>` uses explicit ACK and ALL, starts with all pending messages, and sets max_deliver=-1. |
| Online broadcast subject | `oldman.taskiq.epg_demo.broadcast.<queue>` uses Core NATS without a queue group or Stream persistence. |
| Result-key prefix | `oldman_taskiq_epg_demo_results` is combined into keys by the native Redis backend. |
| Dynamic schedule prefix | `oldman_taskiq_epg_demo_schedules` is managed by the native ListRedisScheduleSource. |

Ordinary publishers can create and validate Streams but cannot create consumers. Only Workers create or bind consumers and broadcast subscriptions. Existing resources are checked without updates. Concurrent creation handles only native already-exists conflicts, then rereads and validates the resource. It does not overwrite configuration to resolve conflicts or delete backlogs. Durable task subjects are not consumed together with ordinary RPC or Core subjects. namespace isolates names; it does not replace NATS or Redis ACLs.

## Receiving, execution, and acknowledgment

Each subscription has at most one asynchronous read slot. The merger passes these to the same native Receiver, and all queues and broadcasts share execution limits. `max_prefetch=0` does not mean the client never holds pending messages: Receiver admission capacity remains max_async_tasks, and the merger has up to one slot per source. Native broadcast subscription buffers are limited to 100 messages and 1 MiB. Do not describe max_prefetch as Stream length or a per-queue execution limit.

Receiving a durable message starts a renewal coroutine for that delivery. Renewal continues while waiting for Receiver and calls native in_progress every ack_wait divided by three seconds. Only the WHEN_SAVED policy is accepted; early-acknowledgment labels are rejected. The native Receiver still parses tasks, validates arguments, invokes dependencies, executes tasks, writes results, and acknowledges them. RenewingReceiver only releases this delivery's renewal in finally; it does not copy execution logic.

Completion uses native ack_sync, retrying once only on timeout. Final failure stops renewal. Parsing errors, callback exceptions, and shutdown also release it. Renewal does not continue forever after failure, and an ACK error does not rerun the function in place.

For durable publication, Nats-Msg-Id is a stable digest of subject, task_name, task_id, and retry number. Only a native NATS timeout causes a resend, at most once, with identical bytes and identifier. Capacity errors, permission errors, missing Streams, and encoding failures are not retried as acknowledgment timeouts. Final failure surfaces through native SendTaskError with its cause retained. Losing an acknowledgment does not establish that the task was never sent.

Ordinary JSON data, Chinese text, and native time schedules use Taskiq's native format and ORJSON. Arguments first pass through native model formatting. Unserializable arguments may raise PydanticSerializationError before reaching ORJSON, so not every encoding failure is TypeError. ignore_result skips results before encoding. Native result-save failure logs an exception but may still ACK; the framework does not change that behavior. See [duplicate delivery and result boundaries](../users/distributed-tasks.md#6-under-what-circumstances-may-it-be-repeated-and-how-to-deal-with-it) for precise scenarios and business handling.

## Scheduling and runtime recovery

WaitingScheduler reuses LabelScheduleSource, the shared RedisScheduleSource, and native SchedulerLoop.run. It adds only tracking and shutdown handling for actual sends, plus recovery of one-off failures. If pre_send, publication, or post_send fails, it logs the original exception and makes that one-off schedule eligible again. It does not implement another scheduler loop.

Dynamic one-off schedules receive a stable task_id before saving, without changing explicit IDs. interval and cron schedules do not reuse that ID for every occurrence. SmartRetry uses the same source and leaves retry_on_error disabled by default. Only explicit labels produce delayed retries, retaining the task ID and increasing the retry number. Intermediate failures do not save a final result. Broadcasts force ignore_result=true and retry_on_error=false only for that message, without modifying shared labels on the decorated function.

Native reconnection and source refresh recover temporary connection errors during operation and log them. Refresh has a delay; failed reads do not guarantee that the latest schedules have taken effect. Failure to delete a schedule after sending can cause another send. Stable-ID deduplication still has a window and does not provide exactly-once delivery. The first interval occurrence may be due immediately, including after restart. Missed downtime intervals are not all replayed. Cancellation withdraws neither queued messages nor an occurrence already cached and being sent.

Shutdown stops the native loop first, then waits for source refreshes and sends already in progress, including post_send, before closing the source and broker. Only the broker closes the Redis source pool; scheduler and broker must not each close it. There is no second schedule-state table, leader election, or deduplication protocol for multiple Schedulers. Run one Scheduler per namespace.

## Processes and exceptional shutdown

Worker uses Taskiq's native ProcessManager.start, adding initial-ready checks only through prepare_workers and the native action queue. Each execution slot has a finite number of initial attempts, and every slot must actually connect before reporting ready. During normal operation, native max_fails=-1 continually replaces crashed processes. The initial three-attempt budget does not limit runtime recovery.

Worker and Scheduler share a private process-group lifecycle. They retain numeric PID files and additionally record verifiable group identity. start holds the PID lock. stop verifies identity first, requests shutdown, and waits until the total deadline. If necessary, it kills the service's entire group and confirms exit. restart must confirm the old group has ended before proceeding. Terminal Ctrl+C uses the same deadline mechanism without signaling the caller's shell or unrelated processes. Users call one stop operation; no second kill command is required.

Each broker startup has a total budget. Startup exceptions also enter the default five-second shutdown budget. Closing partially established native TLS connections can hang. Preserve the original connection or certificate exception rather than replacing it with the final cleanup timeout. Successful cleanup permits underlying resources to be recreated for a new event loop. Failed cleanup marks the object unusable; exit the process rather than silently resetting it. Record final process exit separately from graceful closure of every library object.

Waiting for business tasks is not limited by the five-second resource budget. The service's stop_timeout bounds final exit of the whole group. Record normal shutdown, forced termination at the deadline, and initialization failure separately. A kill in a test's finally block is not acceptance evidence for normal shutdown.

## Maintenance and direct verification

The actual adapters are [broker.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/broker.py), [receiver.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/receiver.py), [results.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/results.py), [scheduler.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/scheduler.py), [worker.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/tasks/distributed/worker.py), and [runtime/taskiq.py](https://github.com/alexliyu7352/oldman/blob/main/oldman/runtime/taskiq.py). Protocols use native types. Internal private fields and hooks are not user extension APIs.

pyproject.toml pins Taskiq 0.12.6, taskiq-nats 0.6.0, taskiq-redis 1.2.3, and nats-py 2.15.0. The Redis requirement is `>=8,<9`, and the version actually verified in this round was 8.1.0. Do not describe that tested version as an exact installation pin. Upgrades must review Receiver admission, ACK and result-failure semantics; ProcessManager action extensions; SchedulerLoop refresh and shutdown; Redis-source closure; and nats-py TLS and close patches on instances. Successful imports alone do not justify an upgrade.

`tests/test_oldman_distributed_tasks.py` belongs to the regular Python gate. It starts its own NATS and Redis and creates isolated ports, directories, and namespaces. See [Test isolation requirements](testing.md#real-service-checks) for executable discovery. `tests/taskiq_fault_checks.py` is its fault-testing helper, not a production runner. The demo tests its task functions with actual SQLite and Storage in `tests/test_examples_tasks.py`. Separate browser checks cover actual clicks, permissions, queuing, results, schedules, shutdown, and failure feedback.

Verified single-node results under small concurrency do not establish cluster fault tolerance, arbitrary load support, or recovery from power loss. Record unfinished work in implementation and acceptance documents rather than stating it as a public guarantee.

<!-- source: zh/developers/distributed-tasks.md @ 84e6ddf1 -->
