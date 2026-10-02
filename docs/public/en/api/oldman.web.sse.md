# `oldman.web.sse`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Server-Sent Events support.

Import with `from oldman.web.sse import <name>`.

## `encode_sse_event`

function · defined in `oldman.web.sse.events`

```python
def encode_sse_event(event: ServerSentEvent) -> str
```

Encode one event without permitting field or line injection.

## `ServerSentEvent`

class · defined in `oldman.web.sse.events`

```python
class ServerSentEvent
```

A single Server-Sent Events frame.

Members:

- `data: str | None = None`
- `event: str | None = None`
- `id: str | None = None`
- `retry: int | None = None`
- `comment: str | None = None`

## `sse`

value · defined in `oldman.web.sse.extension`

```python
sse = SSEExtension()
```

## `SSEExtension`

class · defined in `oldman.web.sse.extension`

```python
class SSEExtension
```

Bind one Sanic worker to browser streams and one Redis subscriber.

Constructor:

```python
SSEExtension() -> None
```

Members:

- `def init_app(app: Sanic) -> None` — Attach once and validate local configuration without opening Redis.
- `async def after_server_start(_app: Sanic) -> None` — Start the Redis subscriber in the background and return immediately.
- `async def before_server_stop(_app: Sanic) -> None` — Stop Redis consumption before closing browser streams and provider pools.
- `def streaming(*, preflight: SSEPreflight | None=None, queue_mode: SSEQueueMode=SSEQueueMode.FIFO, queue_size: int | None=None, retry: int | None=None, session_guard: bool=False, login_url: SSELoginURL='/login') -> Callable[[SSEHandler], SSEHandler]` — Inject an SSEStream while retaining one native response writer.
- `def user_streams(user_id: int) -> tuple[SSEStream, ...]` — Return this worker's current connections for one authenticated user.

## `SSEPublishedMessage`

class · defined in `oldman.web.sse.messages`

```python
class SSEPublishedMessage(MsgspecModel, kw_only=True, frozen=True)
```

Versioned payload sent through the shared Redis SSE channel.

Members:

- `target_type: SSETargetType`
- `target: str`
- `event: str`
- `payload: bytes`
- `version: int = 1`

## `SSEPublisher`

class · defined in `oldman.web.sse.publisher`

```python
class SSEPublisher
```

Publish strongly typed events through one configured Redis alias.

Constructor:

```python
SSEPublisher(config: SSEConfig, *, registry: RedisClientRegistry | None=None) -> None
```

Members:

- `classmethod def from_settings() -> SSEPublisher` — Build a publisher from process settings without opening Redis.
- `async def publish_user(*, user_id: int, event: str, payload: MsgspecModel) -> bool` — Publish an event to every connected tab for one user.
- `async def publish_stream(*, stream: str, event: str, payload: MsgspecModel) -> bool` — Publish an event to browsers subscribed to one business stream.

## `SSEQueueMode`

class · defined in `oldman.web.sse.connection`

```python
class SSEQueueMode(StrEnum)
```

Supported bounded-queue behavior for one browser connection.

## `SSESessionInvalidatedPayload`

class · defined in `oldman.web.sse.messages`

```python
class SSESessionInvalidatedPayload(MsgspecModel, kw_only=True)
```

Final translated payload sent when a guarded browser session expires.

Members:

- `title: str`
- `message: str`
- `login_url: str`

## `SSEStream`

class · defined in `oldman.web.sse.stream`

```python
class SSEStream
```

Send strongly typed JSON through one connection-owned queue.

Constructor:

```python
SSEStream(connection: SSEConnection, *, pool: SSEConnectionPool | None=None, distributed_enabled: bool=False, guarded_user_id: int | None=None, translations: TranslationCatalog | None=None) -> None
```

Members:

- `property translations: TranslationCatalog | None` — Return the translation catalog captured when the connection opened.
- `property is_closed: bool` — Return whether the underlying writer has completed.
- `async def send(payload: MsgspecModel, *, event: str, id: str | None=None) -> None` — Encode one strongly typed JSON event and place it in the connection queue.
- `async def subscribe(stream: str) -> None` — Register this browser under one distributed business stream until close.
- `async def subscribe_user(user_id: int) -> None` — Register this guarded browser under its authenticated user until close.

## `SSETargetType`

class · defined in `oldman.web.sse.messages`

```python
class SSETargetType(StrEnum)
```

Supported routing targets for one distributed browser event.

## Module `oldman.web.sse.connection`

One-writer connection and backpressure rules for browser SSE streams.

Import with `from oldman.web.sse.connection import <name>`.

### `SSEBackpressureError`

class · defined in `oldman.web.sse.connection`

```python
class SSEBackpressureError(SSEConnectionClosedError)
```

Raised after a full FIFO queue closes a slow browser connection.

### `SSEConnection`

class · defined in `oldman.web.sse.connection`

```python
class SSEConnection
```

Serialize queue events, heartbeat, retry, and EOF through one task.

Constructor:

```python
SSEConnection(response: SSEWriter, *, queue_mode: SSEQueueMode, queue_size: int, heartbeat_interval: float, retry: int | None, session_guard: SSESessionGuard | None=None, session_check_interval: float | None=None) -> None
```

Members:

- `property is_closed: bool` — Return whether the writer has completed its cleanup.
- `async def enqueue(frame: str) -> None` — Add one encoded frame without allowing producers to write the response.
- `def enqueue_nowait(frame: str) -> None` — Add one frame without yielding the worker-wide Redis subscriber.
- `def finish() -> None` — Drain already queued events and then close the connection.
- `def abort() -> None` — Discard pending events and ask the writer to close promptly.
- `async def wait_closed() -> None` — Wait until the writer has sent EOF or failed.
- `async def run_writer() -> None` — Write every protocol frame and EOF from this single coroutine.

### `SSEConnectionClosedError`

class · defined in `oldman.web.sse.connection`

```python
class SSEConnectionClosedError(ConnectionError)
```

Raised when business code writes after connection shutdown started.

## Module `oldman.web.sse.pool`

Process-local indexes for browser SSE connections.

Import with `from oldman.web.sse.pool import <name>`.

### `SSEConnectionPool`

class · defined in `oldman.web.sse.pool`

```python
class SSEConnectionPool
```

Index active streams by user and distributed business stream.

Constructor:

```python
SSEConnectionPool() -> None
```

Members:

- `def add(stream: SSEStream) -> None` — Track one connection for worker shutdown.
- `def discard(stream: SSEStream) -> None` — Remove one connection and any subscriptions it still owns.
- `def subscribe_user(user_id: int, stream: SSEStream) -> None` — Register one guarded connection under its authenticated user.
- `def unsubscribe_user(user_id: int, stream: SSEStream) -> None` — Remove one user subscription and its empty index bucket.
- `def subscribe_stream(name: str, stream: SSEStream) -> None` — Register one connection under a distributed business stream.
- `def unsubscribe_stream(name: str, stream: SSEStream) -> None` — Remove one business subscription and its empty index bucket.
- `def user_streams(user_id: int) -> tuple[SSEStream, ...]` — Return a stable snapshot of this worker's user connections.
- `def business_streams(name: str) -> tuple[SSEStream, ...]` — Return a stable snapshot of one distributed business route.
- `def all_streams() -> tuple[SSEStream, ...]` — Return a stable snapshot used by worker shutdown.

## Module `oldman.web.sse.publisher`

Redis publisher for browser events produced outside Sanic workers.

Import with `from oldman.web.sse.publisher import <name>`.

### `SSEMessageTooLargeError`

class · defined in `oldman.web.sse.publisher`

```python
class SSEMessageTooLargeError(ValueError)
```

Raised when one encoded Redis SSE envelope exceeds its limit.

### `validate_event_name`

function · defined in `oldman.web.sse.publisher`

```python
def validate_event_name(value: object) -> str
```

Return one safe simple or namespaced browser event name.

### `validate_stream_name`

function · defined in `oldman.web.sse.publisher`

```python
def validate_stream_name(value: object) -> str
```

Return one namespaced distributed stream route.

### `validate_user_id`

function · defined in `oldman.web.sse.publisher`

```python
def validate_user_id(value: object) -> int
```

Return one integer user identity without implicit conversion.
