"""Typed Core NATS communication; application lifecycle policy lives in runtime."""

import asyncio
import functools
import inspect
import math
import re
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Any, Literal, Self, TypeVar, cast
from urllib.parse import urlsplit

import anyio
from faststream._internal.endpoint.subscriber.mixins import ConcurrentMixin
from faststream._internal.endpoint.subscriber.utils import MultiLock
from faststream.nats import NatsBroker, NatsMessage, NatsRouter
from faststream.nats.schemas.js_stream import compile_nats_wildcard
from faststream.nats.subscriber.usecases.basic import LogicSubscriber
from nats.aio.client import Client
from nats.errors import ConnectionClosedError, OutboundBufferLimitError

from oldman.logging import get_logger
from oldman.providers.nats._compat import install_close_fix, install_request_fix, install_tls_requirement
from oldman.providers.nats.serializers import (
    MsgpackNatsSerializer,
    MsgspecJsonNatsSerializer,
    msgpack_decoder,
    msgspec_json_decoder,
)
from oldman.serializers.base import MsgspecModel

_M = TypeVar("_M", bound=MsgspecModel)


def _check_name(value: str | None, label: str) -> None:
    """Validate configured address tokens without normalizing their identity."""
    if value is not None and re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError(f"{label} must contain only ASCII letters, digits, '_' or '-'")


def _check_subject(subject: str, *, subscription: bool = False) -> None:
    """Validate NATS syntax after native parameter expansion; do not match messages."""
    if subscription:
        _, subject = compile_nats_wildcard(subject)
    parts = subject.split(".")
    if any(not part for part in parts) or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) < 160 for c in subject):
        raise ValueError("subject must have nonempty tokens and no whitespace or control characters")
    for index, part in enumerate(parts):
        if "*" in part or ">" in part:
            if subscription and (part == "*" or (part == ">" and index == len(parts) - 1)):
                continue
            raise ValueError("wildcards are allowed only as whole subscription tokens, with '>' last")


class _CloseSafeNatsBroker(NatsBroker):
    """Use native subscribers and Client, owning partial startup and final cleanup."""

    async def start(self) -> None:
        """Refresh native concurrency resources, without replaying an old receive buffer."""
        for subscriber in self.subscribers:
            if isinstance(subscriber, ConcurrentMixin):
                subscriber.send_stream.close()
                subscriber.receive_stream.close()
                subscriber.send_stream, subscriber.receive_stream = anyio.create_memory_object_stream(
                    max_buffer_size=subscriber.max_workers,
                )
                subscriber.limiter = anyio.Semaphore(subscriber.max_workers)
        await super().start()

    async def _connect(self) -> Client:
        """Hold the Client before connecting so cancellation cannot lose its resources."""
        connection = self._connection = Client()
        install_close_fix(connection)
        install_request_fix(connection)
        options = self._connection_kwargs
        if options.get("tls") is not None or any(urlsplit(url).scheme == "tls" for url in options["servers"]):
            install_tls_requirement(connection)
        await connection.connect(**options)
        self.config.connect(connection)
        return connection

    async def stop_consuming(self) -> None:
        """Own receiver cleanup even when the lifecycle's caller is cancelled."""
        task = asyncio.create_task(self._stop_subscribers())
        try:
            await asyncio.shield(task)
        finally:
            await asyncio.gather(task, return_exceptions=True)

    async def _stop_subscribers(self) -> None:
        """Stop all subscribers together; native cancellation must finish before return."""
        subscribers = tuple(self.subscribers)
        owned_tasks: list[asyncio.Task[Any]] = []
        for subscriber in subscribers:
            subscriber.running = False
            # Snapshot existing native tasks before stop clears their references.
            owned_tasks.extend(getattr(subscriber, "tasks", ()))
            subscription = getattr(subscriber, "subscription", None)
            task = getattr(subscription, "_wait_for_msgs_task", None)
            if task is not None:
                owned_tasks.append(task)
        locks = [sub.lock for sub in subscribers if isinstance(sub.lock, MultiLock)]
        try:
            async with asyncio.timeout(self.config.graceful_timeout):
                await asyncio.gather(*(lock.queue.join() for lock in locks))
        except TimeoutError:
            for subscriber in subscribers:
                if isinstance(subscriber.lock, MultiLock) and not subscriber.lock.empty:
                    self.config.logger.log(
                        f"NATS handler did not finish within graceful_timeout: {cast(LogicSubscriber, subscriber).subject}", 40,
                    )
        # The shared grace period just elapsed. Native stop now unsubscribes and
        # cancels, without waiting a second grace period for each subscriber.
        config = self.config.broker_config
        timeout = config.graceful_timeout
        config.graceful_timeout = 0
        try:
            results = await asyncio.gather(*(sub.stop() for sub in subscribers), return_exceptions=True)
        finally:
            config.graceful_timeout = timeout
        for task in owned_tasks:
            # An unsubscribe failure must not leave a reader alive; don't cancel
            # twice and interrupt an already-running handler's async finally.
            if not task.done() and not task.cancelling():
                task.cancel()
        # Native wait_release(None) does not wait. join uses its existing counter.
        await asyncio.gather(*(lock.queue.join() for lock in locks))
        await asyncio.gather(*owned_tasks, return_exceptions=True)
        for subscriber in subscribers:
            if isinstance(subscriber, ConcurrentMixin):
                subscriber.send_stream.close()
                subscriber.receive_stream.close()
        self.running = False
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _close_client(self, connection: Client, draining_tasks: list[asyncio.Task[Any]]) -> None:
        """Await only this client's cancelled tasks, never unrelated loop work."""
        tasks = [
            connection._reading_task, connection._ping_interval_task,
            connection._flusher_task, connection._reconnection_task,
            *(sub._wait_for_msgs_task for sub in connection._subs.values()),
            *draining_tasks,
        ]
        try:
            await connection.close()
        finally:
            await asyncio.gather(
                *(task for task in tasks if task is not None and task is not asyncio.current_task()),
                return_exceptions=True,
            )

    async def stop(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        """Drain with the native implementation; failed drain must still close."""
        connection = self._connection
        if connection is None:
            return
        # Native drain clears subscriptions before their cancelled callbacks have
        # necessarily exited. Retain those existing tasks until final cleanup.
        draining_tasks = [sub._wait_for_msgs_task for sub in connection._subs.values() if sub._wait_for_msgs_task is not None]
        try:
            try:
                if self.config.connection_state:
                    await connection.drain()
            except BaseException:
                try:
                    await self._close_client(connection, draining_tasks)
                except BaseException as error:
                    self.config.logger.log(f"NATS cleanup also failed: {type(error).__name__}", 40)
                raise
            else:
                await self._close_client(connection, draining_tasks)
        finally:
            self._connection = None
            self.config.disconnect()


class NATSConnection:
    """One explicitly managed connection, independent of global Settings.

    start() connects and starts declared subscribers. The async context only
    connects for publish/request. stop() ends receiving before final drain.
    namespace isolates shared/peer addresses; name is only a log label.
    Both codecs send bytes, without a message envelope or type registry.
    """

    _PEER_ID_HEADER = "x-nats-peer-id"

    def __init__(
        self,
        servers: Iterable[str] = ("nats://localhost:4222",),
        name: str = "nats-service",
        serializer_mode: Literal["msgpack", "msgspec_json"] = "msgpack",
        *,
        namespace: str | None = None,
        peer_id: str | None = None,
        startup_timeout: float = 30.0,
        graceful_timeout: float = 10.0,
        **broker_kwargs: Any,
    ) -> None:
        """Prepare declarations and codec/transport options, without connecting."""
        _check_name(namespace, "namespace")
        _check_name(peer_id, "peer_id")
        for label, value in (("startup_timeout", startup_timeout), ("graceful_timeout", graceful_timeout)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and greater than zero")
        self.servers = list(servers)
        self.name = name
        self.namespace = namespace
        self._peer_id = peer_id
        self.serializer_mode = serializer_mode
        self.startup_timeout = startup_timeout
        self._state = "idle"
        self._last_connect_error: Exception | None = None
        self.router = NatsRouter()
        self._peer_router = NatsRouter()
        self._logger = get_logger(f"default.{name}.nats")
        self._configure_broker(graceful_timeout=graceful_timeout, **broker_kwargs)

    def _configure_broker(self, *, graceful_timeout: float, **broker_kwargs: Any) -> None:
        """Build native options once; late configuration keeps existing declarations."""
        if self.serializer_mode == "msgpack":
            serializer, decoder = MsgpackNatsSerializer(), msgpack_decoder
        elif self.serializer_mode == "msgspec_json":
            serializer, decoder = MsgspecJsonNatsSerializer(), msgspec_json_decoder
        else:
            raise ValueError("serializer_mode must be 'msgpack' or 'msgspec_json'")
        options: dict[str, Any] = {
            "servers": self.servers, "name": self.name, "logger": self._logger,
            "allow_reconnect": True, "max_reconnect_attempts": -1, "reconnect_time_wait": 2,
            "serializer": serializer, "decoder": decoder, "graceful_timeout": graceful_timeout,
            "error_cb": self._error_callback, "disconnected_cb": self._disconnected_callback,
            "reconnected_cb": self._reconnected_callback, "closed_cb": self._closed_callback,
        }
        options.update(broker_kwargs)
        error_callback = options["error_cb"]

        async def record_error(error: Exception) -> None:
            """Retain native startup cause even when the caller supplies its callback."""
            self._last_connect_error = error
            if error_callback is not None:
                await error_callback(error)

        options["error_cb"] = record_error
        # FastStream exposes most Client options, but TLS/user/password are only
        # exposed through its security object. Preserve explicit native kwargs too.
        client_only = inspect.signature(Client.connect).parameters.keys() - inspect.signature(NatsBroker).parameters.keys()
        native_options = {key: options.pop(key) for key in client_only if key in options and key != "self"}
        self.broker = _CloseSafeNatsBroker(**options)
        self.broker._connection_kwargs.update(native_options)

    def _prefix(self, peer_id: str | None = None) -> str:
        """Build the one shared/peer addressing rule without changing case."""
        _check_name(self.namespace, "namespace")
        _check_name(peer_id, "peer_id")
        if self.namespace is None:
            raise ValueError("namespace is required before connecting or addressing messages")
        route = "shared" if peer_id is None else f"peer.{peer_id}"
        return f"oldman.bus.{self.namespace}.{route}."

    async def _connect(self) -> None:
        """Prepare sending only; declarations and imports never connect."""
        if self._state != "idle":
            raise RuntimeError(f"NATS lifecycle is {self._state}; cannot enter again (restart after failed cleanup)")
        self._prefix()
        self._state = "starting"
        self._last_connect_error = None
        try:
            try:
                async with asyncio.timeout(self.startup_timeout):
                    await self.broker.connect()
            except TimeoutError as error:
                self._logger.error("NATS startup timed out: %s", self.name)
                if self._last_connect_error is not None:
                    raise error from self._last_connect_error
                raise
        except BaseException:
            await self._cleanup_failed_start()
            raise
        self._state = "open"

    async def _start_consuming(self) -> None:
        """Attach native routers once, after configuration and before receiving."""
        if self._state != "open" or self.broker.running:
            raise RuntimeError("NATS must be connected and not already consuming")
        self._state = "starting"
        try:
            self.broker.include_router(self.router, prefix=self._prefix())
            if self._peer_router.subscribers:
                if self._peer_id is None:
                    raise ValueError("peer=True subscriber requires this connection's peer_id")
                self.broker.include_router(self._peer_router, prefix=self._prefix(self._peer_id))
            await self.broker.start()
            connection = self.broker._connection
            assert connection is not None
            async with asyncio.timeout(self.startup_timeout):
                # In pinned nats-py, flush's PING bypasses buffered SUB commands.
                # A marker on its existing sender queue waits for those writes first;
                # unlike force_flush, this wait cannot swallow a flush timeout.
                assert connection._flush_queue is not None
                sent = asyncio.get_running_loop().create_future()
                await connection._flush_queue.put(sent)
                await sent
                # Native flush falls back to an unconfirmed write if a loop died.
                # A sender completion must not turn that failure into startup success.
                if not connection.is_connected or any(
                    task is None or task.done() for task in (connection._reading_task, connection._flusher_task)
                ):
                    raise ConnectionClosedError
                # Keep native PING, heartbeat and reconnect behavior unchanged.
                await connection.flush(timeout=self.startup_timeout)  # pyright: ignore[reportArgumentType]
        except BaseException:
            await self._cleanup_failed_start()
            raise
        self._state = "open"

    async def _cleanup_failed_start(self) -> None:
        """Preserve the startup exception while attempting both cleanup phases."""
        self._state = "open"
        try:
            await self.stop()
        except BaseException as error:
            self._logger.error("NATS startup cleanup failed: %s", type(error).__name__)

    async def start(self) -> None:
        """Connect and receive; no automatic registration from other applications."""
        await self._connect()
        await self._start_consuming()

    async def _stop_consuming(self) -> None:
        """End handlers while retaining the sending connection for application hooks."""
        try:
            await self.broker.stop_consuming()
        finally:
            # A sending-only scope never attached its declared routers, but a
            # native concurrent declaration already allocated memory streams.
            for router in (self.router, self._peer_router):
                if router.parent is None:
                    for subscriber in router.subscribers:
                        if isinstance(subscriber, ConcurrentMixin):
                            subscriber.send_stream.close()
                            subscriber.receive_stream.close()

    async def _disconnect(self) -> None:
        """Own the final close task through timeout/cancellation, without orphan shielding."""
        task = asyncio.create_task(self.broker.stop())
        try:
            # wait_for alone can swallow timeout if native drain catches cancellation.
            done, _ = await asyncio.wait({task}, timeout=10.0)
            if not done:
                raise TimeoutError("NATS drain exceeded 10 seconds")
            await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stop(self) -> None:
        """Stop once; failed shutdown is not a reusable lifecycle."""
        if self._state in {"idle", "failed"}:
            return
        if self._state != "open":
            raise RuntimeError(f"NATS lifecycle is {self._state}; cannot stop concurrently")
        self._state = "stopping"
        try:
            try:
                await self._stop_consuming()
            except BaseException:
                try:
                    await self._disconnect()
                except BaseException as error:
                    self._logger.error("NATS final cleanup also failed: %s", type(error).__name__)
                raise
            else:
                await self._disconnect()
        except BaseException:
            self._state = "failed"
            raise
        self._state = "idle"

    async def __aenter__(self) -> Self:
        """Open a sending/RPC scope, without starting business subscribers."""
        await self._connect()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None,
    ) -> None:
        """Preserve a body exception if closing also fails."""
        try:
            await self.stop()
        except BaseException as error:
            if exc_type is None:
                raise
            self._logger.error("NATS context cleanup also failed: %s", type(error).__name__)

    async def _error_callback(self, error: Exception) -> None:
        """Report failure without printing potentially credential-bearing error text."""
        self._logger.error("NATS error in %s: %s", self.name, type(error).__name__)

    async def _disconnected_callback(self) -> None:
        """Report native disconnection; native reconnect policy remains in control."""
        self._logger.warning("NATS disconnected: %s", self.name)

    async def _reconnected_callback(self) -> None:
        """Report native reconnection without starting subscribers again."""
        self._logger.info("NATS reconnected: %s", self.name)

    async def _closed_callback(self) -> None:
        """Report final native close."""
        self._logger.info("NATS connection closed: %s", self.name)

    @property
    def connection_info(self) -> dict[str, Any]:
        """Return the actual Client state, not an invented private broker attribute."""
        client = self.broker._connection
        return {"servers": self.servers, "name": self.name, "is_connected": client is not None and client.is_connected}

    def subscriber(self, subject: str, *, peer: bool = False, **kwargs: Any) -> Callable:
        """Declare a native subscriber, optionally injecting the sender's peer_id.

        peer=True receives on this connection's configured peer address.
        queue, Depends, raw NatsMessage and native handler options stay native.
        """
        _check_subject(subject, subscription=True)
        registrar = self._peer_router.subscriber if peer else self.router.subscriber

        def decorator(func: Callable) -> Callable:
            """Adjust the DI signature once, never on the per-message hot path."""
            sig = inspect.signature(func, eval_str=True)
            if "peer_id" not in sig.parameters:
                return registrar(subject, **kwargs)(func)
            wants_message = "nats_msg" in sig.parameters
            params = [p for p in sig.parameters.values() if p.name != "peer_id"]
            if not wants_message:
                injected = inspect.Parameter("nats_msg", inspect.Parameter.KEYWORD_ONLY, annotation=NatsMessage)
                index = next((i for i, p in enumerate(params) if p.kind == inspect.Parameter.VAR_KEYWORD), len(params))
                params.insert(index, injected)

            @functools.wraps(func)
            async def wrapper(**kw: Any) -> Any:
                """Keep body fields intact; only the handler's top-level peer_id is injected."""
                message = kw["nats_msg"] if wants_message else kw.pop("nats_msg")
                return await func(peer_id=self.peer_id(message), **kw)

            wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]
            wrapper.__annotations__ = {p.name: p.annotation for p in params if p.annotation is not inspect.Parameter.empty}
            if sig.return_annotation is not inspect.Signature.empty:
                wrapper.__annotations__["return"] = sig.return_annotation
            return registrar(subject, **kwargs)(wrapper)

        return decorator

    def publisher(self, subject: str, **kwargs: Any) -> Callable:
        """Publish a non-None async result, await sending, then return that same result."""
        _check_subject(subject)

        def decorator(func: Callable) -> Callable:
            """Preserve the signature so subscriber can be the outer decorator."""
            @functools.wraps(func)
            async def wrapper(*args: Any, **kw: Any) -> Any:
                """Function/publish exceptions propagate; no hidden background task."""
                result = await func(*args, **kw)
                if result is not None:
                    await self.publish(result, subject, **kwargs)
                return result

            return wrapper

        return decorator

    def _headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Copy caller headers and own the source key; destination is not the sender."""
        result = dict(headers or {})
        result.pop(self._PEER_ID_HEADER, None)
        if self._peer_id is not None:
            result[self._PEER_ID_HEADER] = self._peer_id
        return result

    def _require_open(self) -> None:
        """Reject lifecycle misuse, but allow native reconnect buffering."""
        if self._state not in {"open", "stopping"} or self.broker._connection is None:
            raise RuntimeError("NATS is not open; use start() or an async context first")

    async def publish(
        self, message: MsgspecModel | bytes, subject: str, *, peer_id: str | None = None, **kwargs: Any,
    ) -> None:
        """Send without ACK/flush/retry; known local send failures propagate."""
        self._require_open()
        _check_subject(subject)
        subject = self._prefix(peer_id) + subject
        headers = self._headers(kwargs.pop("headers", None))
        try:
            await self.broker.publish(message, subject=subject, headers=headers, **kwargs)
        except (OutboundBufferLimitError, ConnectionClosedError) as error:
            self._logger.error("NATS publish failed (%s): %s", type(error).__name__, subject)
            raise

    @staticmethod
    def peer_id(nats_msg: NatsMessage) -> str:
        """Read explicit sender identity; absent identity is empty, never a log name."""
        raw_message = nats_msg.raw_message
        headers = (getattr(raw_message, "headers", None) or {}) if raw_message else {}
        return headers.get(NATSConnection._PEER_ID_HEADER, "")

    async def request(
        self, message: MsgspecModel | bytes, subject: str, reply_type: type[_M], *,
        peer_id: str | None = None, request_timeout: float = 5.0,
    ) -> _M:
        """Wait for one typed RPC reply; preserve native failure/timeout/cancellation."""
        self._require_open()
        _check_subject(subject)
        reply = await self.broker.request(
            message, subject=self._prefix(peer_id) + subject, timeout=request_timeout, headers=self._headers(),
        )
        if self.serializer_mode == "msgpack":
            return cast(_M, reply_type.from_msgpack(reply.body))
        return cast(_M, reply_type.from_json_bytes(reply.body))
