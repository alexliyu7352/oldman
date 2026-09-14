"""Sanic attachment, distributed subscriber, and browser connection routing."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from functools import wraps
from typing import Any, Final, cast

import msgspec
from sanic import Request, Sanic
from sanic.exceptions import Unauthorized
from sanic.response import HTTPResponse

from oldman.conf.schemas import SSEConfig
from oldman.i18n.serialization import _decode_translatable_msgpack
from oldman.logging import get_logger
from oldman.providers.redis import RedisAliasClient, redis_client
from oldman.web.session import Session, SessionData, get_session_data
from oldman.web.sse.connection import (
    SSEConnection,
    SSEConnectionClosedError,
    SSEQueueMode,
    SSESessionGuard,
    SSEWriter,
)
from oldman.web.sse.events import ServerSentEvent, encode_sse_event
from oldman.web.sse.messages import (
    SSEPublishedMessage,
    SSESessionInvalidatedPayload,
    SSETargetType,
)
from oldman.web.sse.pool import SSEConnectionPool
from oldman.web.sse.publisher import validate_event_name, validate_stream_name, validate_user_id
from oldman.web.sse.stream import SSEStream

SSEHandler = Callable[..., Coroutine[Any, Any, Any]]
SSEPreflight = Callable[[Request], Awaitable[None]]
SSELoginURL = str | Callable[[Request], str]

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store, no-transform",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}
_SESSION_INVALIDATED_EVENT = "oldman.session.invalidated"
_SUBSCRIBER_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
_USER_TARGET_PATTERN: Final = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)\Z")


class SSEExtension:
    """Bind one Sanic worker to browser streams and one Redis subscriber."""

    def __init__(self) -> None:
        self._app: Sanic | None = None
        self._config: SSEConfig | None = None
        self._pool = SSEConnectionPool()
        self._redis: RedisAliasClient | None = None
        self._channel = ""
        self._subscriber_task: asyncio.Task[None] | None = None
        self._subscriber_stopping = asyncio.Event()
        self._subscriber_ready = asyncio.Event()
        self._logger = get_logger("default.sse")
        self._retry_delays: tuple[float, ...] = _SUBSCRIBER_RETRY_DELAYS

    def init_app(self, app: Sanic) -> None:
        """Attach once and validate local configuration without opening Redis."""
        if self._app is not None:
            raise RuntimeError("SSEExtension is already initialized")
        if not isinstance(app, Sanic):
            raise TypeError("app must be a Sanic application")

        from oldman.conf import settings

        config = settings.web.sse
        redis_alias: RedisAliasClient | None = None
        channel = ""
        if config.enabled:
            # Alias lookup validates configuration but remains network-lazy.
            redis_alias = redis_client.using(config.redis_alias)
            channel = f"{config.channel_prefix}:events:v1"

        self._app = app
        self._config = config
        self._redis = redis_alias
        self._channel = channel
        app.register_listener(self.after_server_start, "after_server_start")
        app.register_listener(self.before_server_stop, "before_server_stop")

    async def after_server_start(self, _app: Sanic) -> None:
        """Start the Redis subscriber in the background and return immediately."""
        if self._redis is None:
            return
        if self._subscriber_task is not None and not self._subscriber_task.done():
            return
        self._subscriber_task = asyncio.create_task(
            self._run_subscriber(),
            name="oldman-sse-redis-subscriber",
        )

    async def before_server_stop(self, _app: Sanic) -> None:
        """Stop Redis consumption before closing browser streams and provider pools."""
        self._subscriber_stopping.set()
        subscriber = self._subscriber_task
        if subscriber is not None:
            subscriber.cancel()
            await asyncio.gather(subscriber, return_exceptions=True)
            self._subscriber_task = None
        self._subscriber_ready.clear()

        streams = self._pool.all_streams()
        for stream in streams:
            stream._abort()
        if streams:
            await asyncio.gather(*(stream._wait_closed() for stream in streams))

    def streaming(
        self,
        *,
        preflight: SSEPreflight | None = None,
        queue_mode: SSEQueueMode = SSEQueueMode.FIFO,
        queue_size: int | None = None,
        retry: int | None = None,
        session_guard: bool = False,
        login_url: SSELoginURL = "/login",
    ) -> Callable[[SSEHandler], SSEHandler]:
        """Inject an SSEStream while retaining one native response writer."""
        if not isinstance(queue_mode, SSEQueueMode):
            raise TypeError("queue_mode must be an SSEQueueMode")
        if queue_size is not None and (type(queue_size) is not int or queue_size <= 0):
            raise ValueError("queue_size must be a positive integer")
        if queue_mode is SSEQueueMode.LATEST and queue_size not in (None, 1):
            raise ValueError("LATEST queues must have queue_size=1")
        if retry is not None:
            encode_sse_event(ServerSentEvent(retry=retry))
        if type(session_guard) is not bool:
            raise TypeError("session_guard must be a boolean")
        if not isinstance(login_url, str) and not callable(login_url):
            raise TypeError("login_url must be a path or synchronous callback")
        if callable(login_url) and inspect.iscoroutinefunction(login_url):
            raise TypeError("login_url callback must be synchronous")
        if isinstance(login_url, str):
            _validate_login_url(login_url)

        def decorator(handler: SSEHandler) -> SSEHandler:
            @wraps(handler)
            async def wrapped(request: Request, *args: Any, **kwargs: Any) -> None:
                _app, config = self._runtime(request)
                if preflight is not None:
                    await preflight(request)

                guarded_user_id: int | None = None
                session_check: SSESessionGuard | None = None
                if session_guard:
                    guarded_user_id, session_check = self._prepare_session_guard(
                        request,
                        login_url,
                    )

                response = cast(
                    HTTPResponse,
                    await request.respond(
                        headers=_SSE_HEADERS,
                        content_type="text/event-stream; charset=utf-8",
                    ),
                )
                resolved_queue_size = 1 if queue_mode is SSEQueueMode.LATEST else queue_size or config.queue_size
                connection = SSEConnection(
                    cast(SSEWriter, response),
                    queue_mode=queue_mode,
                    queue_size=resolved_queue_size,
                    heartbeat_interval=config.heartbeat_interval,
                    retry=retry,
                    session_guard=session_check,
                    session_check_interval=(config.session_check_interval if session_check is not None else None),
                )
                translations = getattr(getattr(request, "ctx", None), "translations", None)
                stream = SSEStream(
                    connection,
                    pool=self._pool,
                    distributed_enabled=config.enabled,
                    guarded_user_id=guarded_user_id,
                    translations=translations,
                )
                self._pool.add(stream)
                try:
                    await self._serve(handler, request, stream, connection, args, kwargs)
                finally:
                    self._pool.discard(stream)

            return cast(SSEHandler, wrapped)

        return decorator

    def user_streams(self, user_id: int) -> tuple[SSEStream, ...]:
        """Return this worker's current connections for one authenticated user."""
        return self._pool.user_streams(validate_user_id(user_id))

    def _runtime(self, request: Request) -> tuple[Sanic, SSEConfig]:
        """Require the request to belong to this extension's one application."""
        app = self._app
        config = self._config
        if app is None or config is None:
            raise RuntimeError("SSEExtension is not initialized")
        if request.app is not app:
            raise RuntimeError("SSE request belongs to a different Sanic application")
        return app, config

    def _prepare_session_guard(
        self,
        request: Request,
        login_url: SSELoginURL,
    ) -> tuple[int, SSESessionGuard]:
        """Capture trusted Session identity and build the writer's periodic check."""
        data = get_session_data(request, SessionData)
        if not data.is_authenticated() or data.user_id is None:
            raise Unauthorized("Authentication required")
        user_id = validate_user_id(data.user_id)
        manager = Session.get_session_manager(request)
        session_id = manager.get_session_id(request)
        resolved_login_url = _resolve_login_url(login_url, request)
        translations = getattr(getattr(request, "ctx", None), "translations", None)

        async def check() -> str | None:
            if await manager.validate_session(session_id, user_id):
                return None
            payload = SSESessionInvalidatedPayload(
                title=_translate(translations, "Session expired"),
                message=_translate(
                    translations,
                    "Your session has expired. Please sign in again.",
                ),
                login_url=resolved_login_url,
            )
            return encode_sse_event(
                ServerSentEvent(
                    event=_SESSION_INVALIDATED_EVENT,
                    data=payload.to_json_str(),
                )
            )

        return user_id, check

    async def _run_subscriber(self) -> None:
        """Consume the worker's one Redis channel with bounded reconnect backoff."""
        redis_alias = self._redis
        if redis_alias is None:
            return
        retry_index = 0
        failure_active = False

        while not self._subscriber_stopping.is_set():
            pubsub: Any = None
            try:
                connection = await redis_alias.async_get_bin_conn()
                pubsub = connection.pubsub()
                await pubsub.subscribe(self._channel)
                self._subscriber_ready.set()
                if failure_active:
                    self._logger.info("SSE Redis subscriber recovered")
                    failure_active = False
                retry_index = 0

                async for message in pubsub.listen():
                    if self._subscriber_stopping.is_set():
                        return
                    if message.get("type") not in ("message", b"message"):
                        continue
                    self._handle_redis_payload(message.get("data"))

                if not self._subscriber_stopping.is_set():
                    raise ConnectionError("SSE Redis subscription ended")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._subscriber_ready.clear()
                if not failure_active:
                    self._logger.error("SSE Redis subscriber failed: %s", error)
                    failure_active = True
                delay = self._retry_delays[min(retry_index, len(self._retry_delays) - 1)]
                retry_index += 1
                try:
                    await asyncio.wait_for(self._subscriber_stopping.wait(), timeout=delay)
                except TimeoutError:
                    pass
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.aclose()

    def _handle_redis_payload(self, payload: object) -> None:
        """Validate one untrusted Pub/Sub payload and route it without yielding."""
        config = self._config
        if config is None:
            raise RuntimeError("SSEExtension is not initialized")
        if not isinstance(payload, bytes):
            self._logger.warning("Dropped invalid SSE Redis payload type")
            return
        if len(payload) > config.max_message_size:
            self._logger.warning("Dropped oversized SSE Redis payload")
            return
        try:
            message = SSEPublishedMessage.from_msgpack(payload)
            if message.version != 1:
                raise ValueError("unsupported SSE message version")
            event = validate_event_name(message.event)
            if message.target_type is SSETargetType.USER:
                targets = self._pool.user_streams(_decode_user_target(message.target))
            elif message.target_type is SSETargetType.STREAM:
                targets = self._pool.business_streams(validate_stream_name(message.target))
            else:  # pragma: no cover - msgspec rejects unknown enum values
                raise ValueError("unsupported SSE target type")
            if not targets:
                return
            decoded_payload = _decode_translatable_msgpack(message.payload)
            if not isinstance(decoded_payload, dict):
                raise ValueError("SSE message payload must be a JSON object")
        except (msgspec.DecodeError, TypeError, ValueError) as error:
            self._logger.warning("Dropped invalid SSE Redis payload: %s", error)
            return

        for stream in targets:
            try:
                stream._enqueue_published(payload=decoded_payload, event=event)
            except SSEConnectionClosedError:
                # A slow or closing browser must not delay the shared subscriber.
                continue
            except Exception as error:
                self._logger.warning(
                    "Dropped SSE event for one browser connection: %s",
                    error,
                )

    async def _serve(
        self,
        handler: SSEHandler,
        request: Request,
        stream: SSEStream,
        connection: SSEConnection,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Coordinate handler and writer completion without concurrent response writes."""
        writer_task = asyncio.create_task(connection.run_writer())
        handler_task = asyncio.create_task(handler(request, stream, *args, **kwargs))
        try:
            done, _pending = await asyncio.wait(
                {handler_task, writer_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            connection.abort()
            writer_task.cancel()
            handler_task.cancel()
            await asyncio.gather(writer_task, handler_task, return_exceptions=True)
            raise

        if writer_task in done:
            writer_error = _task_exception(writer_task)
            if handler_task.done():
                handler_error = _task_exception(handler_task)
                if handler_error is not None and not isinstance(handler_error, asyncio.CancelledError):
                    self._logger.error("SSE handler failed: %s", handler_error, exc_info=handler_error)
            else:
                handler_task.cancel()
            await asyncio.gather(handler_task, return_exceptions=True)
            if writer_error is not None and not isinstance(writer_error, asyncio.CancelledError):
                self._logger.debug("SSE browser connection closed: %s", writer_error)
            return

        handler_error = _task_exception(handler_task)
        if handler_error is None:
            connection.finish()
        else:
            connection.abort()
            if isinstance(handler_error, asyncio.CancelledError):
                writer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await writer_task
                raise handler_error
            self._logger.error("SSE handler failed: %s", handler_error, exc_info=handler_error)

        try:
            await writer_task
        except asyncio.CancelledError:
            raise
        except Exception as writer_error:
            self._logger.debug("SSE browser connection closed: %s", writer_error)


def _decode_user_target(value: object) -> int:
    """Decode the publisher's canonical decimal user target at the Redis boundary."""
    if not isinstance(value, str) or _USER_TARGET_PATTERN.fullmatch(value) is None:
        raise ValueError("SSE user target must be a canonical decimal integer")
    return int(value)


def _resolve_login_url(value: SSELoginURL, request: Request) -> str:
    """Resolve one synchronous callback and validate its same-site result."""
    resolved = value(request) if callable(value) else value
    if inspect.isawaitable(resolved):
        if inspect.iscoroutine(resolved):
            resolved.close()
        raise TypeError("login_url callback must be synchronous")
    return _validate_login_url(resolved)


def _validate_login_url(value: object) -> str:
    """Accept only an absolute same-site path with one leading slash."""
    if not isinstance(value, str):
        raise TypeError("login_url must resolve to a string")
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("login_url must be a same-site path starting with one slash")
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("login_url must not contain backslashes or control characters")
    return value


def _translate(catalog: Any, message: str) -> str:
    """Translate against the catalog captured when the long-lived request opened."""
    gettext = getattr(catalog, "gettext", None)
    return str(gettext(message)) if callable(gettext) else message


def _task_exception(task: asyncio.Task[Any]) -> BaseException | None:
    """Read one completed task without letting cancellation escape inspection."""
    try:
        return task.exception()
    except asyncio.CancelledError as error:
        return error


sse = SSEExtension()

__all__ = ["SSEExtension", "sse"]
