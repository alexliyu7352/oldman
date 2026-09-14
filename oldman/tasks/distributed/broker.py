"""Taskiq's native task API with owned JetStream delivery and Redis resources."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

from nats.aio.client import Client
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, DiscardPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import APIError, NotFoundError
from taskiq import AsyncBroker, BrokerMessage
from taskiq.middlewares import SmartRetryMiddleware
from taskiq.serializers import ORJSONSerializer
from taskiq_nats import PullBasedJetStreamBroker

from oldman.conf.schemas import DefaultSettings, validate_taskiq_name
from oldman.providers.nats._compat import install_close_fix, install_tls_requirement
from oldman.providers.nats.config import nats_connection_options
from oldman.tasks.distributed.middleware import TaskPolicyMiddleware, is_broadcast
from oldman.tasks.distributed.receiver import RenewingMessage
from oldman.tasks.distributed.results import OptionalResultBackend, binary_redis_options
from oldman.tasks.distributed.scheduler import RedisScheduleSource

logger = logging.getLogger(__name__)


async def startup_broker(broker: TaskiqBroker) -> None:
    """Bound first-start attempts for owners without a Worker process manager."""
    for attempt in range(1, broker.config.startup_attempts + 1):
        try:
            await broker.startup()
            return
        except Exception:
            if attempt == broker.config.startup_attempts or broker._broken:
                raise
            logger.exception("Taskiq startup attempt %s failed; retrying", attempt)


class TaskiqBroker(PullBasedJetStreamBroker):
    """Keep native decoration/execution; adapt only routing and resource ownership."""

    def __init__(self, settings: DefaultSettings) -> None:
        """Create the process objects without opening NATS or Redis connections."""
        config = settings.taskiq
        if not config.enabled or config.namespace is None:
            raise RuntimeError("Enable settings.taskiq and configure its namespace before importing distributed tasks")
        self.config = config
        self._nats_config = settings.nats[config.nats_alias]
        self._subject_prefix = f"oldman.taskiq.{config.namespace}.tasks"
        self._broadcast_prefix = f"oldman.taskiq.{config.namespace}.broadcast"
        super().__init__(servers=[], stream_name=f"oldman_taskiq_{config.namespace}", subject=f"{self._subject_prefix}.*")
        self.stream_config = StreamConfig(
            name=self.stream_name, subjects=[self.subject], storage=StorageType.FILE,
            retention=RetentionPolicy.WORK_QUEUE, discard=DiscardPolicy.NEW,
            max_bytes=config.stream_max_bytes, max_age=0, num_replicas=config.stream_replicas,
            duplicate_window=config.duplicate_window,
        )
        redis_url, pool_options = binary_redis_options(settings.redis[config.redis_alias])
        self.results = OptionalResultBackend(
            redis_url, **pool_options, serializer=ORJSONSerializer(), keep_results=True,
            result_ex_time=config.result_ex_time, prefix_str=f"oldman_taskiq_{config.namespace}_results",
        )
        self.schedule_source = RedisScheduleSource(
            redis_url, **pool_options, serializer=ORJSONSerializer(), id_generator=self.id_generator,
            prefix=f"oldman_taskiq_{config.namespace}_schedules",
        )
        self.with_serializer(ORJSONSerializer()).with_result_backend(self.results).with_middlewares(
            TaskPolicyMiddleware(),
            SmartRetryMiddleware(
                default_retry_label=False, default_retry_count=3, default_delay=5,
                use_jitter=False, use_delay_exponent=False, no_result_on_retry=True,
                schedule_source=self.schedule_source,
            ),
        )
        self._started = False
        self._initializing = False
        self._native_started = False
        self._closed = False
        self._broken = False
        self._subscriptions: list[JetStreamContext.PullSubscription | Subscription] = []
        self._deliveries: dict[int, RenewingMessage] = {}

    async def _connection_error(self, error: Exception) -> None:
        """Native reconnection continues; errors remain visible to service logging."""
        logger.error("Taskiq NATS connection: %s", error)

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        """Keep the native context entry; failed cleanup cannot hide a body error."""
        try:
            await self.shutdown()
        except BaseException:
            if exc_value is None:
                raise
            logger.exception("Taskiq context cleanup failed; preserving the original body error")

    async def startup(self) -> None:
        """One bounded attempt; the owning Application decides initial retry count."""
        if self._started or self._initializing:
            raise RuntimeError("Taskiq broker already has an active lifecycle; nested startup is not supported")
        if self._broken:
            raise RuntimeError("Taskiq broker cleanup failed; restart this process before using it again")
        self._initializing = True
        try:
            async with asyncio.timeout(self.config.startup_timeout):
                if self._closed:
                    # Upstream marks client Final, but a clean Shell lifecycle on a
                    # new loop must use a fresh client, not its old loop-bound tasks.
                    self.client = Client()  # type: ignore[misc]
                    self._closed = False
                self.results.reopen_pool()
                self.schedule_source.reopen_pool()
                options = nats_connection_options(self._nats_config)
                install_close_fix(self.client)
                if options.get("tls") is not None:
                    install_tls_requirement(self.client)
                await self.client.connect(**options, error_cb=self._connection_error)
                self.js = self.client.jetstream(timeout=self.config.publish_timeout)
                await self._prepare_stream()
                if self.is_worker_process:
                    await self._startup_consumer()
                await self.schedule_source.startup()
                self._native_started = True
                await AsyncBroker.startup(self)
                self._started = True
        except BaseException as error:
            # Native TLS failure can hang while closing its partial transport.
            # In that case the outer deadline must not hide the certificate error.
            cause = self.client.last_error if isinstance(error, TimeoutError) and not self.client.is_connected else None
            try:
                await self.shutdown()
            except BaseException:
                logger.exception("Taskiq startup cleanup failed; preserving the original startup error")
            if cause is not None:
                raise cause from error
            raise
        finally:
            self._initializing = False

    async def _shutdown_native(self) -> None:
        """Keep native hooks, but a failed hook cannot skip the result pool close."""
        try:
            if self._native_started:
                await AsyncBroker.shutdown(self)
        finally:
            if not self.results.close_attempted:
                await self.results.shutdown()
            self._native_started = False

    async def shutdown(self) -> None:
        """Close only owned resources, after the caller has finished its business."""
        if self._closed:
            return
        self._started = False
        try:
            async with asyncio.timeout(self.config.shutdown_timeout):
                for delivery in tuple(self._deliveries.values()):
                    await delivery.release()
                results = await asyncio.gather(
                    self._shutdown_native(), self.schedule_source.shutdown(), self.client.close(),
                    return_exceptions=True,
                )
                failures = [error for error in results if isinstance(error, BaseException)]
                if failures:
                    raise BaseExceptionGroup("Taskiq resource cleanup failed", failures)
        except BaseException:
            self._broken = True
            raise
        else:
            self._subscriptions.clear()
            self._closed = True

    async def _prepare_stream(self) -> None:
        """Create missing resources, never update an existing shared Stream."""
        try:
            info = await self.js.stream_info(self.stream_name)
        except NotFoundError:
            try:
                await self.js.add_stream(self.stream_config)
            except APIError as error:
                if error.err_code != 10058:  # Concurrent create with a different config.
                    raise
            info = await self.js.stream_info(self.stream_name)
        actual = info.config
        expected = self.stream_config
        fields = (
            "name", "subjects", "storage", "retention", "discard", "max_bytes", "num_replicas", "duplicate_window",
        )
        differences = {name: (getattr(actual, name), getattr(expected, name)) for name in fields
                       if getattr(actual, name) != getattr(expected, name)}
        for name in ("max_age", "allow_msg_ttl", "no_ack", "sealed", "allow_rollup_hdrs"):
            if getattr(actual, name):
                differences[name] = (getattr(actual, name), False if name != "max_age" else 0)
        self._check_resource(self.stream_name, differences)

    @staticmethod
    def _check_resource(name: str, differences: dict[str, tuple[Any, Any]]) -> None:
        """Explain conflicts without discarding pending tasks or changing resources."""
        if differences:
            details = "; ".join(f"{field}: existing={old!r}, required={new!r}" for field, (old, new) in differences.items())
            raise RuntimeError(
                f"Taskiq resource {name!r} conflicts: {details}. Coordinate configuration and adjust it with NATS tools; "
                "Oldman will not modify or recreate the resource. Do not clear pending tasks."
            )

    async def _startup_consumer(self) -> None:
        """Bind one existing-or-new durable pull consumer per configured queue."""
        for queue in self.config.consume_queues:
            name = f"workers_{queue}"
            config = ConsumerConfig(
                name=name, durable_name=name, filter_subject=f"{self._subject_prefix}.{queue}",
                deliver_policy=DeliverPolicy.ALL, ack_policy=AckPolicy.EXPLICIT,
                ack_wait=self.config.ack_wait, max_deliver=-1, max_ack_pending=self.config.max_ack_pending,
            )
            try:
                info = await self.js.consumer_info(self.stream_name, name)
            except NotFoundError:
                # nats-py add_consumer means create OR update. The native API's
                # action=create prevents a racing service from updating this one.
                request = {"stream_name": self.stream_name, "config": config.as_dict(), "action": "create"}
                try:
                    await self.js._api_request(
                        f"$JS.API.CONSUMER.CREATE.{self.stream_name}.{name}.{config.filter_subject}",
                        json.dumps(request).encode(), timeout=self.config.publish_timeout,
                    )
                except APIError as error:
                    if error.err_code != 10148:
                        raise
                info = await self.js.consumer_info(self.stream_name, name)
            actual = info.config
            fields = ("name", "durable_name", "filter_subject", "deliver_policy", "ack_policy", "ack_wait", "max_deliver", "max_ack_pending")
            differences = {field: (getattr(actual, field), getattr(config, field)) for field in fields
                           if getattr(actual, field) != getattr(config, field)}
            for field in ("deliver_subject", "backoff", "filter_subjects", "inactive_threshold"):
                if getattr(actual, field):
                    differences[field] = (getattr(actual, field), None)
            self._check_resource(f"{self.stream_name}/{name}", differences)
            self._subscriptions.append(await self.js.pull_subscribe_bind(stream=self.stream_name, durable=name))
            # No queue group: every online execution process gets its own copy.
            self._subscriptions.append(await self.client.subscribe(
                f"{self._broadcast_prefix}.{queue}", pending_msgs_limit=100, pending_bytes_limit=1024 * 1024,
            ))
        # nats-py annotates int, but passes seconds to asyncio.wait_for unchanged.
        await self.client.flush(timeout=self.config.publish_timeout)  # type: ignore[arg-type]

    async def kick(self, message: BrokerMessage) -> None:
        """Use Core NATS for transient broadcast, otherwise await durable PubAck."""
        if not self._started:
            raise RuntimeError("Taskiq broker is not started; use the service lifecycle or 'async with broker'")
        queue = validate_taskiq_name(message.labels.get("queue_name", "default"))
        if is_broadcast(message.labels):
            if not self.client.is_connected:
                raise RuntimeError("Taskiq broadcast requires an online NATS connection")
            await self.client.publish(f"{self._broadcast_prefix}.{queue}", message.message)
            # Flush confirms client/server I/O, not execution by every subscriber.
            # A concurrent disconnect may still leave the send outcome unknown.
            await self.client.flush(timeout=self.config.publish_timeout)  # type: ignore[arg-type]
            return
        subject = f"{self._subject_prefix}.{queue}"
        identity = [subject, message.task_name, message.task_id, int(message.labels.get("_retries", 0))]
        message_id = hashlib.sha256(json.dumps(identity, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        for attempt in range(2):
            try:
                await self.js.publish(
                    subject, message.message, headers={"Nats-Msg-Id": message_id}, timeout=self.config.publish_timeout,
                )
                return
            except NatsTimeoutError:
                if attempt:
                    logger.error("Taskiq publication confirmation failed for %s; delivery outcome is unknown", message.task_id)
                    raise

    def _delivery(self, message: Msg) -> RenewingMessage:
        """Begin renewal immediately, including time spent waiting for Receiver."""
        async def renew() -> None:
            """Renew until this specific delivery is ACKed, abandoned or closed."""
            while True:
                await asyncio.sleep(self.config.ack_wait / 3)
                try:
                    await message.in_progress()
                except Exception:
                    logger.exception("Taskiq delivery renewal failed for %s", message.subject)

        async def release() -> None:
            """Idempotent cleanup shared by ACK, Receiver and broker shutdown."""
            if self._deliveries.pop(id(wire), None) is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)

        async def acknowledge() -> None:
            """Only an ACK timeout permits one retry; never rerun the function here."""
            try:
                for attempt in range(2):
                    try:
                        await message.ack_sync(timeout=self.config.ack_timeout)
                        return
                    except NatsTimeoutError:
                        if attempt:
                            raise
            except Exception:
                logger.exception("Taskiq completion ACK failed for %s; stopping renewal", message.subject)
                raise
            finally:
                await release()

        wire = RenewingMessage(data=message.data, ack=acknowledge, release=release)
        self._deliveries[id(wire)] = wire
        renewal = asyncio.create_task(renew(), name=f"taskiq-renew:{message.subject}")
        return wire

    async def _receive_one(self, subscription: JetStreamContext.PullSubscription | Subscription) -> RenewingMessage | bytes:
        """Merge bounded durable pulls and transient Core messages fairly."""
        while True:
            try:
                if isinstance(subscription, Subscription):
                    return (await subscription.next_msg(timeout=1)).data
                messages = await subscription.fetch(batch=1, timeout=1)
            except NatsTimeoutError:
                continue
            if messages:
                return self._delivery(messages[0])

    async def listen(self) -> AsyncGenerator[RenewingMessage | bytes, None]:
        """Bound each source to one pending read, feeding the same Receiver."""
        if not self._started or not self._subscriptions:
            raise RuntimeError("Start the Taskiq worker broker before listening")
        pending = {asyncio.create_task(self._receive_one(sub)): sub for sub in self._subscriptions}
        try:
            while pending:
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                # Insertion order rotates after each delivery, avoiding starvation.
                for future in tuple(pending):
                    if future in done:
                        subscription = pending.pop(future)
                        yield future.result()
                        pending[asyncio.create_task(self._receive_one(subscription))] = subscription
        finally:
            for future in pending:
                future.cancel()
            for outcome in await asyncio.gather(*pending, return_exceptions=True):
                if isinstance(outcome, RenewingMessage):
                    await outcome.release()
            for subscription in self._subscriptions:
                await subscription.unsubscribe()
            self._subscriptions.clear()
