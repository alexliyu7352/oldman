"""Check actual spawned children and result-reader shutdown, not mocked handles."""

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

from oldman.processes import AsyncProcessManager, ProcessTimeoutError


def slow_target(marker: str) -> None:
    """Signal that the target has started before the parent cancels it."""
    Path(marker).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(30)


def large_target() -> dict:
    """Exceed the pipe buffer so concurrent Queue draining is exercised."""
    return {"payload": b"x" * (2**20)}


class ProcessCancellationTests(unittest.IsolatedAsyncioTestCase):
    """A cancellation is prompt and remains cancellation, followed by normal reuse."""

    async def test_running_child_cancel_timeout_and_large_result(self) -> None:
        manager = AsyncProcessManager(workers=1)
        with tempfile.TemporaryDirectory(prefix="oldman-process-test-", dir="/tmp") as temporary:
            marker = Path(temporary) / "pid"
            try:
                task = asyncio.create_task(manager.run_with_timeout(slow_target, (str(marker),), _timeout=30))
                async with asyncio.timeout(5):
                    while not marker.exists() or not marker.read_text():
                        await asyncio.sleep(.02)
                pid = int(marker.read_text())
                started = time.monotonic()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertLess(time.monotonic() - started, 2)
                self.assertFalse(Path(f"/proc/{pid}").exists())
                self.assertEqual(manager.active_processes, set())
                result = await manager.run_with_timeout(large_target, _timeout=5)
                assert result is not None
                self.assertEqual(result["payload"], b"x" * (2**20))
                with self.assertRaises(ProcessTimeoutError):
                    await manager.run_with_timeout(slow_target, (str(marker),), _timeout=1)
                self.assertFalse(Path(f"/proc/{int(marker.read_text())}").exists())
            finally:
                await manager.shutdown()
            started = time.monotonic()
            await asyncio.get_running_loop().shutdown_default_executor()
            self.assertLess(time.monotonic() - started, 2, "Queue reader survived operation cleanup")
