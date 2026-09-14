"""Native Redis schedules with stable one-time task identities and owned cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from redis.asyncio import BlockingConnectionPool, Redis
from taskiq import ScheduledTask, TaskiqScheduler
from taskiq.abc.schedule_source import ScheduleSource
from taskiq.cli.scheduler.run import SchedulerLoop
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListRedisScheduleSource

if TYPE_CHECKING:
    from oldman.tasks.distributed.broker import TaskiqBroker

logger = logging.getLogger(__name__)


def _retrieve_send_error(task: asyncio.Task[Any]) -> None:
    """The native loop drops completed send tasks; retrieve errors already logged."""
    if not task.cancelled():
        task.exception()


class WaitingScheduler(TaskiqScheduler):
    """Keep Taskiq's scheduling loop, while owning its outstanding send cleanup."""

    def __init__(self, broker: TaskiqBroker) -> None:
        """Sources share the public broker; no second Redis source or connection."""
        self.labels = LabelScheduleSource(broker)
        super().__init__(broker, [self.labels, broker.schedule_source])
        self.loop = SchedulerLoop(self)
        self._inflight: set[asyncio.Task[Any]] = set()

    async def startup(self) -> None:
        """Load task labels once and bound initial connection attempts only."""
        await self.labels.startup()
        from oldman.tasks.distributed.broker import TaskiqBroker, startup_broker

        assert isinstance(self.broker, TaskiqBroker)
        await startup_broker(self.broker)

    async def on_ready(self, source: ScheduleSource, task: ScheduledTask) -> None:
        """Track native pre_send, publish and post_send as one in-flight operation."""
        current = asyncio.current_task()
        assert current is not None
        self._inflight.add(current)
        current.add_done_callback(_retrieve_send_error)
        try:
            await super().on_ready(source, task)
        except Exception:
            # Only failed one-time schedules must become eligible again. Native
            # cancellation is handled by super; cron/interval retain their clock.
            if task.time is not None and task.cron is None and task.interval is None:
                self.loop.time_tasks_last_run.pop(task.schedule_id, None)
            logger.exception("Taskiq schedule %s (%s) could not finish sending", task.schedule_id, task.task_name)
            raise
        finally:
            self._inflight.discard(current)

    async def drain(self) -> None:
        """After stopping the native loop, wait for its reads and started sends."""
        # A send scheduled on the last loop turn may not have entered on_ready.
        await asyncio.sleep(0)
        update = self.loop._update_schedules_task_future
        if update is not None:
            await update
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight), return_exceptions=True)

    async def shutdown(self) -> None:
        """Only the broker closes Redis; the labels source has no external pool."""
        try:
            await self.labels.shutdown()
        finally:
            await super().shutdown()


class RedisScheduleSource(ListRedisScheduleSource):
    """Preserve one-time identity without inventing a second scheduling format."""

    def __init__(self, url: str, *, id_generator: Callable[[], str], **options: Any) -> None:
        """Use the broker's native generator; construct a pool without connecting."""
        super().__init__(url, **options)
        self._id_generator = id_generator
        self._redis_url = url
        self._pool_options = {key: value for key, value in options.items() if key not in {"prefix", "serializer"}}
        self._pool_options["max_connections"] = self._pool_options.pop("max_connection_pool_size")
        self._closed = False

    def reopen_pool(self) -> None:
        """Reopen only after a clean close, including Shell's next event loop."""
        if self._closed:
            self._connection_pool = BlockingConnectionPool.from_url(self._redis_url, **self._pool_options)
            self._closed = False

    async def add_schedule(self, schedule: ScheduledTask) -> None:
        """Retry recovery must use the original time-task ID, not generate a new call."""
        if schedule.time is not None and schedule.task_id is None:
            schedule.task_id = self._id_generator()
        await super().add_schedule(schedule)

    async def startup(self) -> None:
        """Validate the independent schedule pool, keeping native source setup."""
        await super().startup()
        async with Redis(connection_pool=self._connection_pool) as client:
            await client.ping()

    async def shutdown(self) -> None:
        """The upstream source owns a pool but does not disconnect it itself."""
        await self._connection_pool.disconnect()
        self._closed = True
