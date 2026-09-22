"""Persistent Worker queue lifecycle tests."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from oldman.tasks.manager import BaseManager, WorkerInfo
from oldman.tasks.worker import BaseWorker


class _StoppedProcess:
    """Expose the stopped-process state needed by the manager cleanup path."""

    def is_alive(self) -> bool:
        return False


class _QueueProbe:
    """Record ownership cleanup without allocating an operating-system queue."""

    def __init__(self) -> None:
        self.closed = False
        self.joined = False

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.joined = True


class _FailingProcess:
    """Represent a process that cannot cross the startup boundary."""

    def start(self) -> None:
        raise RuntimeError("start failed")


class BaseManagerQueueLifecycleTest(unittest.TestCase):
    """Require the parent manager to release every queue it creates."""

    def test_stop_worker_closes_queue_and_joins_feeder_thread(self) -> None:
        manager = BaseManager(BaseWorker, num_workers=0)
        queue = manager._mp_context.Queue()
        queue.put_nowait(b"probe")
        queue_state = cast(Any, queue)
        feeder_thread = queue_state._thread
        self.assertIsNotNone(feeder_thread)
        manager.workers[0] = WorkerInfo(
            0,
            cast(mp.Process, _StoppedProcess()),
            queue,
        )

        try:
            asyncio.run(manager._stop_worker(0))

            self.assertNotIn(0, manager.workers)
            self.assertTrue(queue_state._closed)
            self.assertFalse(feeder_thread.is_alive())
        finally:
            if not queue_state._closed:
                queue.close()
                queue.join_thread()

    def test_start_failure_closes_new_queue_and_joins_feeder(self) -> None:
        manager = BaseManager(BaseWorker, num_workers=0)
        queue = _QueueProbe()
        manager._mp_context = cast(Any, SimpleNamespace(Queue=lambda: queue))

        with patch.object(
            manager,
            "_create_worker_process",
            return_value=cast(mp.Process, _FailingProcess()),
        ):
            result = asyncio.run(manager._start_worker(0))

        self.assertFalse(result)
        self.assertTrue(queue.closed)
        self.assertTrue(queue.joined)
        self.assertNotIn(0, manager.workers)


if __name__ == "__main__":
    unittest.main()


class AsyncQueueRaceTest(unittest.IsolatedAsyncioTestCase):
    """`empty()` then `get_nowait()` is a race, and losing it is not a failure.

    The old code caught every exception, logged it and re-raised, with an unreachable
    `pass` underneath whose comment said the opposite: "ignore the concurrency issue in
    the empty check". Losing the race raises queue.Empty, which was then reported to the
    caller as a fault. The same bare handler also swallowed-then-reraised deserialization
    errors identically, so the two could not be told apart.
    """

    @staticmethod
    def _queue(behaviour: Any) -> Any:
        from oldman.tasks.queue import AsyncQueue

        instance = AsyncQueue.__new__(AsyncQueue)
        instance._is_setup = True
        instance.queue = behaviour
        instance._data_available = asyncio.Event()
        instance._data_available.set()
        return instance

    async def test_losing_the_race_keeps_waiting(self) -> None:
        import queue as queue_module

        from oldman.tasks.messages import MessageType, TaskMessage

        class RacyQueue:
            def __init__(self) -> None:
                self.calls = 0

            def empty(self) -> bool:
                return False

            def get_nowait(self) -> bytes:
                self.calls += 1
                if self.calls == 1:
                    raise queue_module.Empty
                return TaskMessage(type=MessageType.TASK_START, task_id="t-1").to_msgpack()

        racy = RacyQueue()
        message = await asyncio.wait_for(self._queue(racy).get(), timeout=3)
        self.assertEqual("t-1", message.task_id)
        self.assertEqual(2, racy.calls, "the consumer should have tried again, not raised")

    async def test_a_real_fault_still_reaches_the_caller(self) -> None:
        class BrokenQueue:
            def empty(self) -> bool:
                return False

            def get_nowait(self) -> bytes:
                raise ValueError("payload is not decodable")

        with self.assertRaises(ValueError):
            await asyncio.wait_for(self._queue(BrokenQueue()).get(), timeout=3)

    def test_the_unreachable_branch_is_gone(self) -> None:
        import inspect

        from oldman.tasks.queue import AsyncQueue

        source = inspect.getsource(AsyncQueue.get)
        self.assertIn("except queue.Empty", source)
        self.assertNotIn("raise\n                pass", source)
