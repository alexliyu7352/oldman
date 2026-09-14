"""API views for {{ app_slug }}."""

from __future__ import annotations

from oldman.serializers import MsgspecModel
from oldman.web import Request, get_app, json_response
from oldman.web.sse import SSEStream, sse
from oldman.web.websocket import WebSocket, websocket

app = get_app()


class StatusUpdate(MsgspecModel, kw_only=True):
    """Status payload used by the finite SSE example."""

    status: str


@app.get("/{{ app_slug }}", name="{{ app_slug }}_index")
async def {{ app_slug }}_index(request: Request):
    """Return a simple API response."""
    del request
    return json_response({"name": "{{ app_slug }}", "status": "ok"})


@app.get("/{{ app_slug }}/status/stream", name="{{ app_slug }}_status_stream")
@sse.streaming()
async def {{ app_slug }}_status_stream(request: Request, stream: SSEStream) -> None:
    """Stream a finite service-status example."""
    del request
    for event_id, status in enumerate(("starting", "ready"), start=1):
        await stream.send(
            StatusUpdate(status=status),
            event="status",
            id=str(event_id),
        )


@websocket("/{{ app_slug }}/ws", name="{{ app_slug }}_websocket")
async def {{ app_slug }}_websocket(request: Request, connection: WebSocket) -> None:
    """Echo messages over the runtime's native WebSocket connection."""
    del request
    async for message in connection:
        await connection.send(message)
