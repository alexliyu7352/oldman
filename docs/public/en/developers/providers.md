# Redis and NATS providers

Providers manage external infrastructure connections without defining business-message semantics. Caching uses the Redis provider; Sessions and SSE can use it too, but are not cache submodules. The NATS provider offers inter-service publish/subscribe and request/reply. It is neither a browser notification center nor a durable task scheduler.

## Redis connections

The public object is `oldman.providers.redis.redis_client`. METRICS, read_metric, and the YAML below are **API reference examples** showing minimal named-connection wiring, not commands or services registered in the demo. For actual business use, compare the EPG [Caching](cache.md#actual-use-in-the-demo) and [retry_summary in tasks.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/tasks.py). The former uses CACHE through RedisCache; the latter uses the task service's actual alias through `redis_client.using(settings.taskiq.redis_alias)`. Do not invent a METRICS alias as a new demo prerequisite.

```python
from oldman.providers.redis import redis_client


async def read_metric() -> str | None:
    """Read an explicitly named business key in a bootstrapped service."""
    connection = await redis_client.using("METRICS").async_get_conn()
    return await connection.get("taskboard:metrics:latest")
```

Corresponding service YAML:

```yaml
redis:
  METRICS:
    redis_url: redis://127.0.0.1:6379/6
    decode_responses: true
    max_connections: 32
    connection_socket_connect_timeout: 2
    connection_socket_timeout: 5
```

redis_client is a process-wide RedisClientRegistry. using(alias) validates and caches case-sensitive alias objects without creating pools. The first async_get_conn creates a redis-py asynchronous client and pool; actual commands trigger network connections. A connecting log does not mean startup has already completed a Redis ping.

async_get_conn returns strings or bytes according to decode_responses. async_get_bin_conn forces bytes for msgspec, Pickle, and binary Pub/Sub messages. The same alias/decoding mode reuses a client; different modes can own two pools. The returned object is redis-py asyncio Redis. Await its public get/set/pipeline methods directly instead of introducing another complete Redis-command wrapper.

### Configuration fields

Built-in alias defaults follow. These are configuration defaults, not a guarantee that corresponding Redis servers are running locally:

| Alias | Default redis_url |
| --- | --- |
| DEFAULT | redis://localhost:6379/3 |
| CACHE | redis://localhost:6379/2 |
| SESSION | redis://localhost:6379/5 |

All three defaults use TCP. Redis does not enable Unix sockets by default, and socket paths vary by distribution/version, so defaults must not depend on them. In environments with a Unix socket enabled, set `redis_url` to `unix:///path/to/redis.sock?db=3`. Use `rediss://` for TLS.

Convenience methods without an alias, such as `redis_client.async_get_conn()`, use DEFAULT. Business code should prefer explicit using calls. Custom aliases require a URL; built-in aliases allow partial option overrides.

RedisConnectionConfig also includes decode_responses=True, max_connections=1024, health_check_interval=30, protocol=2 (or 3), retry_attempts=3, retry_on_timeout=True, backoff_base=0.1, backoff_cap=2.0, socket_keepalive=True, and TCP keepalive idle=60, interval=10, count=3. Pools belong to each actual client in each process, rather than enforcing a project-wide connection limit.

Other redis-py connection arguments use the connection_ prefix, as with the socket timeout above; it is stripped before passing to the pool. Do not use it to redeclare existing fields or inject another connection_pool/retry object. Configuration validation does not replace server address, credential, and TLS connection checks.

### Shutdown and standalone use

Default WebApplication/SimpleApplication shutdown closes global redis_client. Custom shutdown must still call the parent; do not close shared pools after each request. Owners must stop PubSub and their reader coroutines before closing the provider.

Standalone scripts without global Settings can create an explicit instance:

```python
from oldman.conf.schemas import RedisConfig
from oldman.providers.redis import RedisClientRegistry


async def ping_redis(url: str) -> bool:
    """Use the caller-supplied address and own and close an independent Registry."""
    registry = RedisClientRegistry(RedisConfig.model_validate({"DEFAULT": {"redis_url": url}}))
    try:
        connection = await registry.async_get_conn()
        return await connection.ping()
    finally:
        await registry.close()
```

The lower-level AsyncRedis(redis_url=..., ...) is also public, with async_get_conn/close and the same settings above. There is no need to create both AsyncRedis and Registry connections. Registry.close closes every created client, and later use can recreate pools; it does not reload configuration. Closure failures may raise BaseExceptionGroup. A missing alias raises RedisAliasNotConfiguredError; ordinary connection/command failures retain redis-py exceptions.

### Keys and namespaces

Every framework Redis key and channel starts with the service namespace: `core.namespace`, defaulting to `core.app_name` when unset. Construct project keys with the same function rather than handwritten prefixes:

```python
from oldman.providers.redis import redis_key

key = redis_key("reports", "daily", report_id)   # "<namespace>:reports:daily:<report_id>"
```

`redis_key` reads settings when called, so it can be used anywhere outside module-level initialization. Calling before service initialization raises a settings-not-configured error. Related services (a public site and dashboard) must share a namespace to share sessions, token revocation, and caches. Give independent services their own namespaces. Taskiq result and schedule keys are an exception: producers and consumers in one task group share `taskiq.namespace`.

### Locks and publish/subscribe

Alias objects offer three existing lock entry points. Do not mix their ownership rules. Names are placed under `<namespace>:lock:`; callers supply only the name:

- get_db_lock(key, expire_timeout=60) uses SET NX EX and returns bool. is_db_lock checks only the marker; it provides neither token ownership nor safe renewal.
- acquire_lock(lock_name, acquire_timeout=10, retry_interval=0.001, expire_timeout=None) returns a token or False. `acquire_timeout` is the wait duration; `expire_timeout` is the lease after acquisition. Omitting `expire_timeout` reuses `acquire_timeout` to preserve previous behavior. Explicitly set `expire_timeout` if the critical section may outlast the lease; do not extend the wait timeout as a way to extend the lease. release_lock(name, token) atomically compares and deletes. False can also mean a connection failure during release.
- `await get_locker(key, blocking_timeout=10, expire_timeout=60, sleep=0.01)` returns a redis-py Lock that has not yet been acquired. Use its asynchronous context or native lock interface.

Use pubsub()/publish() directly on binary connections for ordinary Pub/Sub and manage PubSub closure explicitly. Messages are not durable and are not replayed after offline periods. **Different Redis DB numbers do not isolate Pub/Sub channels**. Isolate applications/environments through channel names, also constructed with `redis_key(...)`. [Redis Pub/Sub delivery and isolation rules](https://redis.io/docs/latest/develop/pubsub/)

Browser applications need not operate Pub/Sub themselves: use oldman.web.sse for page delivery. This section defines provider boundaries for code needing native Redis commands directly.

## NATS connections and publishing

Ordinary Oldman applications use the process-wide concrete object:

```python
from oldman.providers.nats import bus
```

It is a concrete NATSConnection subclass instance, not a proxy or an object from request/app.ctx. Importing it and declaring decorators neither connects nor reads uninitialized Settings. The first asynchronous start binds service configuration and creates a Client. A running process reuses one Core connection rather than creating/closing it per request. Standalone scripts can own a NATSConnection, as described below.

Start with [Let running services communicate with each other](../users/service-communication.md) for actual usage. Shared messages/sending methods live in apps/examples/nats_messages.py and nats_example.py; receivers in apps/communication/events.py; services in services/nats_a.py and nats_b.py. The methods below are interface references rather than a second hypothetical demo.

### Configuration and defaults

`settings.nats` defines reusable named connections; `settings.nats_bus` controls Core communication. An address alone does not connect automatically. Both are general root settings independent of Web and belong neither in Admin nor in a business App.

| nats_bus field | Default | Meaning |
| --- | --- | --- |
| enabled | false | Whether the runtime entry point manages a Core connection |
| nats_alias | DEFAULT | Case-sensitive alias in settings.nats |
| consume | false | Whether long-lived Web/Simple services load and run installed Apps' events |
| namespace | None | Required when enabled; communicating projects/environments must match |
| peer_id | None | Explicit local identity for source headers and directed subscriptions |
| serializer_mode | msgpack | msgpack or msgspec_json; must match at both ends |
| startup_timeout | 30 | Total initial sending-connection budget in seconds |
| graceful_timeout | 10 | Shared normal-completion wait for all handlers during shutdown, in seconds |

namespace/peer_id retain case. Nonempty values allow only ASCII letters, digits, underscores, and hyphens. Identity is not inferred from service names, connection log labels, or PIDs. Enabling validates alias existence. Disabled configurations can retain settings, but invalid field values still need correction.

Named connection DEFAULT defaults to nats://localhost:4222. New aliases require nats_url. Other NATSConnectionConfig fields:

| Field | Default / constraints |
| --- | --- |
| connect_timeout | 2 seconds; timeout for one native connection attempt |
| reconnect_time_wait | 2 seconds; native reconnection interval |
| tls_ca_file | None; trusts this CA if supplied, otherwise uses system TLS trust |
| tls_cert_file / tls_key_file | Both None; must be supplied together for mutual TLS |
| credentials_file | None; native .creds file, mutually exclusive with URL credentials |

URLs accept nats:// and tls:// without query, fragment, or business paths. Percent-encoded user:password@host or token@host credentials are allowed. The framework separates credentials from server addresses before passing them to nats-py and does not include them in address logs. Do not dump credential-bearing URLs or configuration into logs. Configuration checks neither read certificates nor connect; actual startup reads deployment certificates/creds.

tls:// or certificate settings enable TLS with certificate/hostname validation, without a verification-disabled fallback. A plaintext-only server is rejected before sending credential-bearing CONNECT, and reconnects cannot downgrade either. Taskiq and bus can read the same named connection configuration but own separate Clients/resources rather than sharing Taskiq's private socket.

### Exact API

```python
def __init__(
    self,
    servers=("nats://localhost:4222",),
    name="nats-service",
    serializer_mode="msgpack",
    *,
    namespace=None,
    peer_id=None,
    startup_timeout=30.0,
    graceful_timeout=10.0,
    **broker_kwargs,
) -> None:
    ...
```

namespace may be omitted at construction but is required before connection or addressing. name is only a connection/log label. Timeouts must be finite and positive. Independent objects neither read Settings automatically nor close through Application. Native reconnection defaults are allow_reconnect=True, max_reconnect_attempts=-1, and reconnect_time_wait=2. Explicit broker_kwargs override native defaults, including callbacks, without duplicated parameters colliding across two kwargs sets. Client.connect parameters not exposed directly by FastStream (such as tls, user, and password) reach the actual Client too. Do not copy the broker merely to pass an option.

| Method | Contract |
| --- | --- |
| await publish(message, subject, *, peer_id=None, **kwargs) | message is MsgspecModel or encoded bytes; returns None without waiting for receiver business logic to finish |
| await request(message, subject, reply_type, *, peer_id=None, request_timeout=5.0) | Waits for one reply and decodes the specified MsgspecModel subclass; does not aggregate nodes |
| subscriber(subject, *, peer=False, **kwargs) | Decorates asynchronous handlers; queue, max_workers, Depends, native path parameters, etc. belong to FastStream |
| publisher(subject, **kwargs) | Decorates asynchronous functions; a non-None result is awaited through publish, then returned unchanged; None is not published |
| peer_id(nats_msg) | Static method reading source from a raw message header; empty string if absent |
| connection_info | servers/name/is_connected snapshot from actual Client state; not a delivery receipt |
| await start() | Connects and starts previously declared subscriptions |
| await stop() | Stops receiving, waits for handlers to exit, then closes the connection |
| async with connection / bus | Connects only for sending/RPC; closes on exit without starting receiver declarations |

Native publish headers are copied. The framework exclusively owns the x-nats-peer-id source header; callers cannot impersonate another source through headers. Other publish arguments, such as reply_to, pass through without an extra message envelope.

Register receivers before starting reception. Nested/concurrent starts of one object fail. An open connection permits concurrent publish/request calls. After normal closure, the object can be reused on a new event loop. Objects cleaned up after failure must not be reopened; end their owning process. Do not wrap a running application's bus in another async with.

### Addressing, source, and queue

Both ends use the same namespace, such as epg_demo in the demo:

| Call or declaration | Actual NATS subject |
| --- | --- |
| publish(message, "demo.events.compete"); default subscriber with the same business name | oldman.bus.epg_demo.shared.demo.events.compete |
| request(..., "project.status", ..., peer_id="monitor_a") | oldman.bus.epg_demo.peer.monitor_a.project.status |
| monitor_a's subscriber("project.status", peer=True) | oldman.bus.epg_demo.peer.monitor_a.project.status |

peer=True uses the receiver's configured peer_id and fails startup if absent. Receiving services (Web/Simple with `nats_bus.consume` enabled) check before connecting to NATS or running hooks. Commands and send-only services do not receive and skip this check. The sending peer_id argument is the **destination**. A handler's top-level peer_id parameter is the **source**, written from the sender's configuration rather than destination or name. A same-named body field retains its original data and is not overwritten by injection.

Ordinary subjects contain nonempty dot-separated tokens without whitespace/control characters. Publishing disallows wildcards. Subscriptions allow native whole-token *, terminal >, and FastStream path parameters. Do not manually repeat the oldman.bus prefix.

- Receivers on the same subject and queue compete for one copy; delivery is neither one copy each nor guaranteed evenly distributed.
- Receivers on the same subject without queue each receive a copy while online.
- Each distinct queue group gets a copy, with competition within the group.
- Multiple replicas of one peer are still multiple subscribers. For one replica to handle each RPC, use the same queue. Without queue, every replica may execute while the caller receives only the first reply.
- namespace isolates names; the peer header identifies sources. Neither replaces NATS accounts/ACLs, connection authentication, or business authorization.

### Typed messages and native features

Messages inherit `oldman.serializers.MsgspecModel`, rather than using a dynamic dict protocol. Pass models directly without to_json_str first. msgpack uses to_msgpack's MessagePack bytes; msgspec_json uses to_json_bytes' UTF-8 JSON bytes. Manually supplied bytes mean the caller already encoded the selected codec and are not wrapped again. Other languages can interoperate, but must agree on fields, types, and MessagePack extension types. Shared JSON/MessagePack alone does not guarantee business compatibility.

Receivers first decode bytes, then perform msgspec conversion using handler parameter types. Parameter models are created at declaration. Existing Depends, keyword-only parameters, NatsMessage injection, and native path parameters remain supported; not every parameter becomes a body field. Unknown bytes do not automatically become a valid business model; invalid request replies retain decoding exceptions. A returned handler model becomes the RPC reply. To also publish return values, put subscriber outside publisher.

Actual shared demo methods (excerpt from nats_example.py):

```python
from oldman.providers.nats import bus
from apps.examples.nats_messages import ProjectStatusRequest, ProjectStatusReply

async def query_project_status(project_id: int, peer_id: str) -> ProjectStatusReply:
    """The selected receiving service, not this caller, queries the database."""
    return await bus.request(
        ProjectStatusRequest(project_id=project_id), "project.status", ProjectStatusReply,
        peer_id=peer_id, request_timeout=3,
    )

@bus.publisher("project.status.read")
async def query_and_publish_status(project_id: int, peer_id: str) -> ProjectStatusReply:
    """Publish the real RPC reply, then return that same reply to the caller."""
    return await query_project_status(project_id, peer_id)
```

Function exceptions prevent publishing; publishing exceptions also propagate rather than silently creating a background Task. publisher is not a database-commit hook. To emit events after a transaction, business code calls it after leaving the transaction context.

### App and runtime lifecycle

AppConfig.events_module defaults to "events" and loads only from packages explicitly installed in settings.apps, without scanning the project directory. An absent default module is skipped normally; real errors such as missing internal dependencies propagate. Models load first. events must neither declare new tables nor connect to services. Put sending methods/message definitions in independently importable ordinary modules, so one RPC does not require importing every receiver.

| Entry point | Connection and receiving order | Shutdown order |
| --- | --- | --- |
| Ordinary Simple | init/models, events declarations (enabled and consume), prepare; asynchronous Core connection → Taskiq publishing connection → before_start → Core reception → main | Stop Core reception and wait for handlers → before_stop/after_stop → Taskiq shutdown → close Core → await model-cache invalidation → close caches/Redis/database |
| Web | Initialization only declares events; inside actual Sanic workers: Core → Taskiq → before_server_start; Core reception begins only after after_server_start returns | Inside actual workers: finish Core handlers → before_server_stop/after_server_stop → Taskiq shutdown → close Core → await model-cache invalidation → close caches/Redis/database |
| Ordinary asynchronous App Command | Storage → Core → Taskiq → before_command → handle; no automatic events loading or reception | after_command → Taskiq shutdown → close Core → await model-cache invalidation → close caches/Redis/database → close logging |
| Taskiq Worker execution child process | Core → native Taskiq startup/WORKER_STARTUP → ready/Receiver; send-only | Close Core after original Taskiq execution/shutdown and WORKER_SHUTDOWN complete |
| Taskiq Scheduler | Core → native Taskiq startup/CLIENT_STARTUP → SchedulerLoop; send-only | Close Core after original Scheduler/Taskiq CLIENT_SHUTDOWN |
| bootstrap/Shell/IDE | bootstrap configures settings/models only; the user's async with bus connects | Context exit closes the connection; caller owns other resources used |

Taskiq management parent processes do not connect to Core. Workers/Schedulers do not automatically load events even with consume=true. Use a separate Simple service for background reception instead of making every execution Worker an RPC receiver.

Worker Core and Taskiq connections share the existing taskiq.startup_timeout total budget rather than adding two default 30-second budgets. Core's own shorter budget still applies. Schedulers have no parent-process first-ready budget; Core's connection budget runs first, followed by the original Taskiq startup attempts. Startup/business-hook failures still attempt closure of communication resources established by this entry point. Original exceptions are retained; additional cleanup failures are logged separately.

An enabled connection's initial failure fails that entry point's startup rather than pretending to be available. Disabled bus loads no events and creates no Core Client. Web subclasses retain existing super calls. The framework does not discover/close arbitrary business resources created independently. In particular, database/HTTP resources used by handlers must stay open until those handlers exit. Business shutdown hooks can still send through Core to other online nodes, but stopped local subscribers no longer receive.

### Shutdown, failures, and guarantees

graceful_timeout is **shared** by all in-flight handlers waiting for normal completion, not repeated per subscription. When it expires, native subscriptions stop and unfinished handlers are cancelled. The framework awaits their asynchronous finally blocks, then performs final Client drain/close. Final drain has a separate 10-second limit; timeout cancels and awaits that cleanup task without leaving an orphaned shielded task.

This does not guarantee the entire service exits in 10 seconds. Python cancellation is cooperative: business code must not block the event loop or swallow CancelledError, and custom I/O needs timeouts. This API does not add Taskiq's process-group force-kill protocol to ordinary Simple/Web services.

| Situation | What callers should understand |
| --- | --- |
| Initial connection refusal, authentication/TLS failure, startup timeout | Startup exception; timeout preserves the last native connection cause where possible and cleans up a partial Client |
| Disconnection after connection establishment | Native reconnect/buffering applies; this does not mean each message was processed |
| Reconnect send buffer full / permanently closed connection | publish raises OutboundBufferLimitError / ConnectionClosedError instead of logging, dropping, and returning success |
| No responders | request raises NoRespondersError; check destination, namespace, service, and subscriptions |
| RPC timeout or caller cancellation | Original exception/cancellation propagates; remote work may already have run or still be running; no automatic resend |
| Receiver-handler programming exception | Logged at receiver; no cross-process exception-object protocol, so caller may see only timeout |
| Invalid reply | msgspec decoding/validation exception, not an empty result |
| Sending failure during shutdown | Connection cleanup is still attempted; closing resources is not called successful delivery |

Core provides online events/RPC without durable offline messages, processing ACKs, retry queues, group RPC, node directories, or replay. publish returning means only that the local sending step completed. Use [Taskiq interfaces and runtime](distributed-tasks.md) for durable queuing, delayed/periodic execution, and task results; use [SSE and WebSocket](sse.md) for browser delivery.

Native extensions were verified with FastStream 0.7.1, fast-depends 3.0.8, and nats-py 2.15.0; the nats-py dependency is pinned. Shutdown, request-Future cleanup, and TLS downgrade-prevention patches install only on Clients owned by Oldman, without modifying native classes or other clients. Upgrades must recheck the relevant private extension points and real-connection tests. Known native TLS-failure cleanup can still produce timeout/old StreamWriter warnings. Not every failed object is promised warning-free graceful reuse. These versions and limits define the actual acceptance scope.

### Shell, IDE, and independent connections

In an interpreter at the demo root, first start nats_a and prepare this service's YAML as described in the tutorial. Use real message types interactively:

```python
import asyncio
from oldman import bootstrap_service
from oldman.providers.nats import bus
from apps.examples.nats_messages import ProjectStatusRequest, ProjectStatusReply

context = bootstrap_service("web")  # Configuration/models only; no network access

async def query(project_id: int) -> ProjectStatusReply:
    """The caller selects a project ID that actually exists in the demo."""
    async with bus:
        return await bus.request(
            ProjectStatusRequest(project_id=project_id), "project.status", ProjectStatusReply,
            peer_id="monitor_a",
        )
```

In an ordinary Shell, run asyncio.run(query(actual_project_id)); in an IDE with an existing event loop, use await query(actual_project_id) rather than nesting asyncio.run. The context only sends; web/nats_a consume settings do not automatically start reception. bootstrap also does not close DB, Redis, HTTP, or Storage resources subsequently used by your code.

Standalone scripts without global Settings replace only the owned object in that example:

```python
from oldman.providers.nats import NATSConnection

connection = NATSConnection(
    servers=["nats://127.0.0.1:4222"],
    namespace="epg_demo", peer_id="manual_reader",
)
```

Use async with connection and connection.request in the same query function. Demo receiving services and message structures stay unchanged; a communication-only script need not bootstrap Web. For reception, declare @connection.subscriber before starting, prepare business resources, await connection.start(), then in finally await connection.stop() before closing handler dependencies. async with does not replace receiver startup, and Application must not assume global bus owns an independent object.

<!-- source: zh/developers/providers.md @ 69532437 -->
