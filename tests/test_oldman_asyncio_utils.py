"""run_sync keeps one event loop per thread and closes it with the thread; safe_cancellable_sleep swallows a cancellation whole."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from pathlib import Path

from oldman.utils.asyncio_utils import run_sync, safe_cancellable_sleep

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


async def current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


class RunSyncTest(unittest.TestCase):
    def test_a_thread_reuses_its_loop_and_the_loop_closes_when_the_thread_ends(self) -> None:
        """G5-5: every thread that called run_sync used to keep its loop, and its file descriptors, until exit."""
        loops: list[tuple[asyncio.AbstractEventLoop, asyncio.AbstractEventLoop]] = []

        def worker() -> None:
            loops.append((run_sync(current_loop), run_sync(current_loop)))

        for _ in range(5):
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()

        self.assertEqual(5, len(loops))
        for first, second in loops:
            self.assertIs(first, second)
        deadline = time.monotonic() + 2
        while not all(first.is_closed() for first, _ in loops) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(all(first.is_closed() for first, _ in loops))

    def test_exit_closes_the_loops_left_and_skips_one_still_running(self) -> None:
        """G5-5: a thread stopped inside run_sync at exit made closing fail and kept the other loops open."""
        script = textwrap.dedent(
            """
            import asyncio
            import threading
            import weakref

            from oldman.utils.asyncio_utils import run_sync

            class Probe:
                pass

            loops = {}
            probe = Probe()
            # Created before any runner, so at exit it runs after theirs (finalizers run newest first).
            weakref.finalize(probe, lambda: print("main loop closed:", loops["main"].is_closed(), flush=True))

            started = threading.Event()

            async def forever():
                started.set()
                await asyncio.sleep(3600)

            async def current_loop():
                return asyncio.get_running_loop()

            threading.Thread(target=run_sync, args=(forever,), daemon=True).start()
            started.wait(5)
            loops["main"] = run_sync(current_loop)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("main loop closed: True", completed.stdout, completed.stdout + completed.stderr)
        self.assertNotIn("Cannot close a running event loop", completed.stderr)


class SafeCancellableSleepTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_swallowed_cancellation_leaves_no_count_behind(self) -> None:
        """G5-6: two cancels left one on the count, and a TaskGroup in the cleanup then ended cancelled (3.13+)."""
        started = asyncio.Event()

        async def background_loop() -> tuple[bool, int]:
            started.set()
            slept = await safe_cancellable_sleep(10, log_cancel=False)
            task = asyncio.current_task()
            assert task is not None
            return slept, task.cancelling()

        task = asyncio.create_task(background_loop())
        await started.wait()
        task.cancel()
        task.cancel()

        self.assertEqual((False, 0), await task)


if __name__ == "__main__":
    unittest.main()
