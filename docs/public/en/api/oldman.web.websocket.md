# `oldman.web.websocket`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

WebSocket routing and connection protocol.

Import with `from oldman.web.websocket import <name>`.

## `WebSocket`

class · defined in `oldman.web.websocket`

```python
class WebSocket(Protocol)
```

Structural type for the runtime's native WebSocket connection.

Members:

- `subprotocol: str | None`
- `async def recv(timeout: float | None=None) -> str | bytes | None`
- `async def send(message: str | bytes) -> None`
- `async def close(code: int=1000, reason: str='') -> None`
- `async def ping(data: bytes=b'') -> None`
- `async def pong(data: bytes=b'') -> None`

## `websocket`

function · defined in `oldman.web.websocket`

```python
def websocket(path: str, *, name: str | None=None, subprotocols: list[str] | None=None, strict_slashes: bool | None=None) -> Callable[[_Handler], _Handler]
```

Register a handler on the active runtime application.
