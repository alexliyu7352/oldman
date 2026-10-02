# `oldman.providers.nats`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.providers.nats import <name>`.

## `bus`

value · defined in `oldman.providers.nats.bus`

```python
bus = _ConfiguredNATSConnection(name='nats-bus')
```

## `msgpack_decoder`

function · defined in `oldman.providers.nats.serializers`

```python
async def msgpack_decoder(msg: StreamMessage[Any]) -> Any
```

替换 FastStream 默认的 decode_message，使用 msgspec.msgpack 解码。

## `MsgpackNatsSerializer`

class · defined in `oldman.providers.nats.serializers`

```python
class MsgpackNatsSerializer(SerializerProto)
```

用 MsgspecModel 内置 Msgpack 编码器完成序列化，全链路二进制，零 JSON 开销。

Members:

- `staticmethod def encode(message: MsgspecModel | bytes) -> bytes`

## `msgspec_json_decoder`

function · defined in `oldman.providers.nats.serializers`

```python
async def msgspec_json_decoder(msg: StreamMessage[Any]) -> Any
```

替换 FastStream 默认的 decode_message（stdlib json.loads）。

## `MsgspecJsonNatsSerializer`

class · defined in `oldman.providers.nats.serializers`

```python
class MsgspecJsonNatsSerializer(SerializerProto)
```

用 MsgspecModel 内置 JSON 编码器完成序列化，消除 stdlib json 中间层。

Members:

- `staticmethod def encode(message: MsgspecModel | bytes) -> bytes`

## `NATSConnection`

class · defined in `oldman.providers.nats.connection`

```python
class NATSConnection
```

One explicitly managed connection, independent of global Settings.

Constructor:

```python
NATSConnection(servers: Iterable[str]=('nats://localhost:4222',), name: str='nats-service', serializer_mode: Literal['msgpack', 'msgspec_json']='msgpack', *, namespace: str | None=None, peer_id: str | None=None, startup_timeout: float=30.0, graceful_timeout: float=10.0, **broker_kwargs: Any) -> None
```

Members:

- `async def start() -> None` — Connect and receive; no automatic registration from other applications.
- `async def stop() -> None` — Stop once; failed shutdown is not a reusable lifecycle.
- `property connection_info: dict[str, Any]` — Return the actual Client state, not an invented private broker attribute.
- `def subscriber(subject: str, *, peer: bool=False, **kwargs: Any) -> Callable` — Declare a native subscriber, optionally injecting the sender's peer_id.
- `def publisher(subject: str, **kwargs: Any) -> Callable` — Publish a non-None async result, await sending, then return that same result.
- `async def publish(message: MsgspecModel | bytes, subject: str, *, peer_id: str | None=None, **kwargs: Any) -> None` — Send without ACK/flush/retry; known local send failures propagate.
- `staticmethod def peer_id(nats_msg: NatsMessage) -> str` — Read explicit sender identity; absent identity is empty, never a log name.
- `async def request(message: MsgspecModel | bytes, subject: str, reply_type: type[_M], *, peer_id: str | None=None, request_timeout: float=5.0) -> _M` — Wait for one typed RPC reply; preserve native failure/timeout/cancellation.
