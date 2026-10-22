# SSE and WebSocket

SSE is a one-way connection for browsers to receive server events, not a reliable message queue or notification business layer. `oldman.web.sse` supports both data generated directly by the current request and data published through Redis by other processes. Ordinary notifications are only one consumer.

Agents: before writing code, read the [real-time page guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md) (`docs/public/zh/agents/realtime.md`). It says which interface the task needs, how to wire it and what counts as done.

## Direct output from the current request

The actual example is EPG demo `/examples/tables/realtime`, routed in [apps/examples/views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py). WebApplication already initializes public `sse`; do not create an extension per request. This is the module's complete route method. The file imports `router`, `asyncio`, `itertools.cycle`, `apps.examples.services`, `login_required` (from `oldman.web.auth`), and SSE types:

```python
@router.get("/examples/tables/realtime/events", name="example_realtime_table_events")
@login_required()
@sse.streaming(queue_mode=SSEQueueMode.LATEST, session_guard=True, login_url="/login")
async def example_realtime_table_events(request: Request, stream: SSEStream) -> None:
    """Replay database-backed server samples through one page-owned SSE stream."""
    del request
    snapshots = await services.list_server_metric_snapshots()
    for samples in cycle(snapshots):
        if stream.is_closed:
            return
        # Viewing the demo replays stored samples; only explicit publishing writes data.
        await stream.send(services._realtime_payload(samples), event="examples.table.metrics")
        await asyncio.sleep(1)
```

`services._realtime_payload()` returns the demo's own `_RealtimeTablePayload(MsgspecModel)` with `rows: list[_RealtimeTableRow]`. Each row has `id: int` and `cells: dict[str, str]`. See [Real-time delivery guide (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md) for the complete payload, DOM, and page component. The loop replays existing database samples without writing on page open. Queries run only at connection start; the loop holds no database Session.

Direct `stream.send()` bypasses Redis Pub/Sub and does not require `web.sse.enabled=true`; that switch enables only **cross-process** publish/subscribe. However, this actual demo route checks Session identity and therefore still needs Session Redis. No Redis transport does not mean the entire demo needs no Redis.

`@sse.streaming(*, preflight=None, queue_mode=SSEQueueMode.FIFO, queue_size=None, retry=None, session_guard=False, login_url=None)` injects `SSEStream` after the route handler's request parameter without registering the route. `login_url` is the sign-in destination after session invalidation, defaulting to site `web.account.login_url`. Optional asynchronous `preflight(request)` runs before HTTP headers are sent. Ordinary permissions should use existing decorators outside streaming.

`stream.send(payload, *, event, id=None)` accepts `MsgspecModel` and outputs JSON text as SSE data. Use stable `event` names such as `server.metrics`; `id` is an optional string. Set `retry` in the streaming decorator, in milliseconds, to affect native EventSource reconnection. `id` does not make the framework store/replay events automatically.

A single writer owns the HTTP response; business send only enqueues. Normal handler completion drains queued data before closing, and disconnection cancels the handler. Put resources in `try/finally` and do not swallow `CancelledError`. Do not also write the same response through `request.respond()`.

## Cross-process configuration

Receiving/publishing services use the same Redis alias and project/environment channel prefix. The following nodes are required for SSE in demo [web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml); retain other settings:

```yaml
redis:
  SSE:
    redis_url: redis://127.0.0.1:6379/6
web:
  sse:
    enabled: true
    redis_alias: SSE
    heartbeat_interval: 15.0
    session_check_interval: 30.0
    queue_size: 100
    max_message_size: 65536
```

Merge these into existing service YAML and run service `settings sync/check`. SimpleApplication configuration tools do not automatically add Web subtrees; background publishers needing them must declare the nodes explicitly. Redis DB numbers do not isolate Pub/Sub. The channel is `<core.namespace>:events:v1`, isolated by service namespace. Background publishers and SSE Web services must share `core.namespace`; different projects/environments need different namespaces.

Web initialization validates local settings only. After startup, every Sanic worker starts one subscriber coroutine; first Redis access connects. Redis failure logs ERROR and reconnects with backoff without stopping Web. Recovery logs too. Messages before subscription or during disconnection may be lost.

## Where publishers come from

The actual publishing endpoint is `example_realtime_chart_publish()` in [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py). This is its complete route method, not another background collection service. `db_manager` comes from `oldman.db`, `SSEPublisher` from `oldman.web.sse`, response types/functions from `oldman.web.api/response`, and `_` is `gettext_lazy`. `_server_id`, `CHART_EVENT="examples.chart.metric"`, and all imports are in that file; business queries/payloads are in services.py:

```python
@router.post("/examples/charts/realtime/publish", name="example_realtime_chart_publish")
@csrf_protect()
@login_required()
async def example_realtime_chart_publish(request: Request):
    """Commit one metric, then publish it through the configured SSE Redis channel."""
    server_id = _server_id(request)
    async with db_manager.get_session() as session:
        try:
            payload = await services.create_server_metric(session, server_id)
        except ValueError as exc:
            raise BadRequest("Unknown example server") from exc
    published = await SSEPublisher.from_settings().publish_stream(
        stream=services.realtime_chart_stream(server_id),
        event=CHART_EVENT,
        payload=payload,
    )
    if not published:
        return api_response(
            DefaultApiResponse(
                error_code=ApiErrorCode.INVALID_REQUEST,
                message=_("The metric was saved, but Redis delivery failed."),
            )
        )
    return api_response(
        DefaultApiResponse(
            message=_("A new database metric was published."),
            actions=[
                FeedbackAction(title=_("Realtime metric published."), icon="success")
            ],
        )
    )
```

It exits the database context to commit before publishing. Failure must not be described as no database write and does not roll back the committed sample. In the same file, browser endpoint `example_realtime_chart_events()` first receives at most six recent historical samples, then calls `await stream.subscribe(services.realtime_chart_stream(server_id))` for new metrics. The page button invokes this actual POST rather than browser-simulated counts.

Publishers own no separate pool. Each demo request creates a lightweight object through `from_settings()` while reusing Redis provider connections underneath. Ordinary background processes can create/reuse one after `bootstrap_service()`/Application initialization. The API also accepts explicit `SSEPublisher(config: SSEConfig, *, registry=None)`, defaulting to the global provider. It is not a Sanic extension and needs neither request nor `app.ctx.sse`. There is no separate close API; provider/Application lifecycle closes connections.

- `publish_stream(*, stream, event, payload) -> bool` targets connections authorized to subscribe to a business stream.
- `publish_user(*, user_id: int, event, payload) -> bool` targets all subscribed online tabs/devices for that user.
- True means only successful Redis publishing, not an online recipient or displayed content. Redis network failure returns False; disabled settings, invalid types/names, and oversized payloads still raise exceptions.

Event segments begin with a letter and may then contain letters, digits, underscores, or hyphens. Dots separate segments; maximum length is 128 characters. Business streams need at least two segments, such as `servers.metrics`; events may have one. User IDs require strict int without implicit strings/bools.

Publishers encode typed payloads as MsgPack bytes, then place them in a versioned byte envelope, default maximum 65536 bytes overall. Messages are not converted to JSON before encoding. Ordinary Struct payloads must retain object form rather than `array_like=True`; subscribers require decoded JSON objects.

## Receiving user events and business streams

User routes reuse authenticated identity rather than accepting arbitrary browser user_id. Framework `AccountFlow` installs dashboard user events at `web.account.user_events_url` (default `/user-events`) only when `web.sse.enabled` is on. The following comes from `AccountFlow.register_routes()` in `oldman/web/auth/account.py`, with method indentation removed. `allow` defaults to signed-in access; `refuse` uses the sign-in protocol for anonymous requests and 403 for authenticated-but-denied requests. `request_user(request)` is the user recorded by the authentication pipeline:

```python
if self.user_events_path is None or not conf.settings.web.sse.enabled:
    return None
from oldman.web.sse import sse

@sse.streaming(session_guard=True, login_url=self.login_path)
async def stream_user_events(request: Any, stream: SSEStream) -> None:
    await stream.subscribe_user(cast(int, request_user(request).id))

async def user_events(request: Any):
    if not allow(request):
        return await refuse(request)
    return await stream_user_events(request)

target.add_route(cast(Any, user_events), self.user_events_path, methods=["GET"], name=f"{name_prefix}user_events")
return self.user_events_path
```

`allow` is checked before entering `sse.streaming`: rejected requests receive ordinary 403/sign-in responses before any event stream is established.

`subscribe_user()` requires session_guard=True and checks user_id against the connection's authenticated user. It waits until closure rather than returning immediately after registration; no separate permanent sleep is needed.

Business streams likewise use `await stream.subscribe("servers.metrics")`. Before subscribing, business code checks resource access. Stream names are routing labels, **not permissions**. Multi-tenant applications must not let browser queries choose arbitrary streams. Use `asyncio.gather()` to await multiple authorized subscriptions concurrently on one connection, with common cleanup at closure.

`sse.user_streams(user_id)` returns only the current worker's connection snapshot, not reliable global online-user state. Use publishers across processes.

## Session expiration, translation, and backpressure

Before the first write and every 30 seconds by default, session_guard checks SID/user Session indexes in Redis without querying the User database again. Invalidation first sends `oldman.session.invalidated` (title, message, login_url), then closes. Heartbeats do not extend sign-in; permission changes require business Session revocation. Redis-check errors fail the connection and must not be treated as confirmed Session expiration.

One writer schedules both checks and heartbeats, including Session checks on busy connections. The interval is not a hard real-time guarantee under network congestion; actual delivery depends on a writable connection. Default heartbeats are SSE comments, not business messages.

For lazy-translated text, inherit `oldman.i18n.TranslatableMsgspecModel`, declare `LazyTranslation` fields, and use `gettext_lazy()` values. Ordinary `MsgspecModel` does not support this dedicated MsgPack extension. Generic SSE subscribers restore lazy text and output JSON using each connection's request translation catalog. No notification-specific subscriber or manual business decoding is needed. Direct `stream.send()` serializes in the current request translation context.

Connections retain their establishment language and must reconnect after language changes. Lazy parameters allow only JSON scalars; do not put database objects/functions in translation variables. Notification databases store the same bytes; see [Page messages, feedback, and notifications](messages.md).

`FIFO` defaults to capacity 100. A full queue disconnects slow clients without blocking other connections; it is not unlimited buffering. `LATEST` has fixed capacity 1 and replaces unsent messages, suitable for **complete latest snapshots**. It does not retain one entry per row/event name. When sending server metrics row by row, do not assume every row survives; send a complete batch or use FIFO where needed.

## Browser API and recovery

The actual browser consumer is [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts). `ExampleChart` inherits Component from `oldman-web/core` and imports EventStreamClient from `oldman-web/sse`. Its complete method follows:

```typescript
  private connect(url: string): void {
    const client = new EventStreamClient(url);
    client.on<unknown>("examples.chart.metric", (payload) => this.applyRealtime(payload));
    client.onOpen(() => this.setRequestState(this.i18n.t("SSE connected")));
    client.onError(() => this.setRequestState(this.i18n.t("SSE reconnecting")));
    this.cleanup(() => client.close());
  }
```

`mount()` calls this after the first `om:chart:render`. The URL comes from root `data-om-realtime-chart-url`. `applyRealtime()` validates payloads before calling the same Page's mounted ApexChart `appendData()` for CPU/memory series. `setRequestState()` updates example status text without new Feedback. ExamplesPage's private loader mounts the component; cleanup closes the connection on departure. Do not move this method to permanently running module-level code.

`EventStreamClient(url, options: EventSourceInit={})` wraps native EventSource. `on<T>()` parses named JSON events and returns an unsubscribe function; T is static typing, not runtime validation. `onOpen()` includes reconnect opens, and `onError()` leaves native reconnection active. `close()` permanently closes/removes listeners and is idempotent.

When listening for invalidation, the client closes before business handling to stop reconnects. Custom Pages must still display feedback. DashboardPage already listens, shows shell Feedback, and redirects to sign-in after acknowledgment. Its `<meta name="oldman-user-events-url" content="/user-events">` must be unique and use an absolute same-site path. Without it, no user connection is created.

Extend Dashboard's existing user connection with `protected bindUserEventStream(client): StopEventStreamHandler[]`, returning your unsubscribe functions rather than opening another identical user connection. Page-specific metric streams may have independent connections, closed on teardown. The entire product is not forced onto one connection, nor does every event need its own.

There is no offline queue, replay, ACK, or exactly-once delivery during disconnection. Direct-send id/retry are SSE protocol fields only. Publishers currently carry no event ID, and services do not recover from Last-Event-ID. Refetch current state through existing APIs/database on reconnection, as notification topbars do. Reuse connections on high-frequency pages; reverse proxies must not buffer SSE. See the deployment guide.

## Use WebSocket for bidirectional communication

`oldman.web.websocket` supplies only route helpers and structural types for native connections, without adding WebSocket to SSE publishers. This independent API reference is not a demo page or registered route:

```python
from oldman.web.request import Request
from oldman.web.websocket import WebSocket, websocket

@websocket("/examples/echo")
async def echo(request: Request, ws: WebSocket) -> None:
    async for message in ws:
        await ws.send(message)
```

Register during App view loading. `websocket(path, *, name=None, subprotocols=None, strict_slashes=None)` delegates to Sanic. Connections support recv/send/close, asynchronous iteration, and ping/pong. WebSocket size/ping settings live in `settings.web`. The example is echo only, without business permissions. Real endpoints must validate identity, Origin, and resource access before handshake and validate input too. It has no built-in Redis routing, reliable offline delivery, or SSE-style periodic Session checks.

<!-- source: zh/developers/sse.md @ 84e6ddf1 -->
