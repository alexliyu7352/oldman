"""Thread utility migration regression tests."""

from __future__ import annotations

import importlib
import threading
import unittest


class ThreadUtilitiesTest(unittest.TestCase):
    """Keep the generic thread helpers usable without a Django compatibility layer."""

    def test_module_imports_and_thread_pool_executes_a_task(self) -> None:
        thread_utils = importlib.import_module("oldman.utils.thread")
        completed = threading.Event()
        pool = thread_utils.ThreadPool(max_workers=1)
        try:
            pool.add_task("probe", completed.set)
            self.assertTrue(completed.wait(timeout=2))
        finally:
            pool.shutdown()

        self.assertTrue(hasattr(thread_utils, "AsyncTask"))
        self.assertTrue(hasattr(thread_utils, "ThreadPool"))
        self.assertTrue(hasattr(thread_utils, "handle_timeout"))


if __name__ == "__main__":
    unittest.main()
