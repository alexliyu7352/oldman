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
