"""Adversarial tests for gate-owned Linux process-tree cleanup."""

from __future__ import annotations

import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from oldman.testing.process_tree import ProcessTreeError, linux_process_table, tracked_popen


@unittest.skipUnless(sys.platform == "linux", "release process-tree scope is Linux-only")
class LinuxProcessTreeTest(unittest.TestCase):
    def test_leader_can_be_identity_safely_suspended_and_resumed(self) -> None:
        with tracked_popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True) as (
            process,
            tracker,
        ):
            tracker.signal_leader(signal.SIGSTOP, require_live_leader=True)
            self.assertTrue(tracker.wait_for_leader_state(frozenset({"T", "t"}), 2))
            tracker.signal_leader(signal.SIGCONT, require_live_leader=True)
            tracker.terminate(process, require_live_leader=True, term_timeout=1, kill_timeout=1)

    def test_detached_new_session_descendant_is_killed_and_reaped(self) -> None:
        child_source = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        parent_source = (
            "import pathlib,signal,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],start_new_session=True); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(60)"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "child.pid"
            with tracked_popen(
                [sys.executable, "-c", parent_source, str(marker), child_source],
                start_new_session=True,
            ) as (process, tracker):
                deadline = time.monotonic() + 5
                while not marker.is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.is_file())
                child_pid = int(marker.read_text())
                tracker.remember()

                tracker.terminate(process, term_timeout=0.2, kill_timeout=2)

                self.assertNotIn(child_pid, linux_process_table())

    def test_shutdown_requires_signal_delivery_to_the_live_leader_identity(self) -> None:
        with tracked_popen([sys.executable, "-c", "pass"], start_new_session=True) as (process, tracker):
            process.wait(timeout=5)

            with self.assertRaisesRegex(ProcessTreeError, "before the gate delivered"):
                tracker.terminate(process, require_live_leader=True, term_timeout=0.1, kill_timeout=0.1)

            self.assertEqual(0, process.returncode)


if __name__ == "__main__":
    unittest.main()
