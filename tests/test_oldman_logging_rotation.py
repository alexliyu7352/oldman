"""Coordinator contracts for main-process-only log rotation."""

from __future__ import annotations

import logging
import multiprocessing
import os
import re
import tempfile
import threading
import time
import unittest
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from oldman.logging import get_active_runtime, init_logging, logger
from oldman.logging.handlers import AtomicAppendFileHandler
from oldman.logging.rotation import RotationCoordinator
from tests.fixtures.logging_direct_service import write_across_rotation


def _rotation_record_counts(payload: bytes) -> Counter[tuple[str, int]]:
    """Count every matched writer record without masking duplicate entries."""
    return Counter(
        (producer.decode("ascii"), int(sequence))
        for producer, sequence in re.findall(
            rb"ROTATE_RECORD:([a-z0-9-]+):(\d+)",
            payload,
        )
    )


class _AttachedHandler:
    """Attach one runtime-marked handler and always restore global logging state."""

    def __init__(self, handler: AtomicAppendFileHandler, runtime_id: str) -> None:
        """Bind a unique non-propagating logger to the supplied handler."""
        self.handler = handler
        self.logger = logging.getLogger(f"rotation-test-{uuid.uuid4().hex}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        handler.__dict__["_oldman_runtime_id"] = runtime_id

    def __enter__(self) -> logging.Logger:
        """Publish the handler so coordinator discovery sees it."""
        self.logger.addHandler(self.handler)
        return self.logger

    def __exit__(self, *_args: object) -> None:
        """Detach and close the handler even when an assertion fails."""
        self.logger.removeHandler(self.handler)
        self.handler.close()


class RotationCoordinatorTest(unittest.TestCase):
    """Verify rollover discovery, stdlib policy behavior and PID ownership."""

    def test_size_rotation_keeps_records_before_and_after_rollover(self) -> None:
        """A coordinator rotates once while the writer follows the new path."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "app.log")
            handler = AtomicAppendFileHandler(
                path,
                maxBytes=1,
                backupCount=2,
                reopen_check_interval=0,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            with _AttachedHandler(handler, "runtime") as attached_logger:
                attached_logger.warning("before")
                coordinator = RotationCoordinator("runtime")
                coordinator.run_once()
                attached_logger.warning("after")

            combined = "".join(
                file.read_text(encoding="utf-8")
                for file in sorted(Path(directory).glob("app.log*"))
            )
            self.assertIn("before", combined)
            self.assertIn("after", combined)
            self.assertTrue(Path(directory, "app.log.1").exists())

    def test_time_rotation_uses_stdlib_suffix_and_recreates_active_file(self) -> None:
        """Daily rollover retains stdlib naming while the writer reopens afterward."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "app.log")
            handler = AtomicAppendFileHandler(
                path,
                when="D",
                interval=1,
                backupCount=3,
                reopen_check_interval=0,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            with _AttachedHandler(handler, "runtime") as attached_logger:
                attached_logger.warning("before")
                now = time.time()
                two_days_ago = now - (2 * 24 * 60 * 60)
                os.utime(path, (two_days_ago, two_days_ago))

                coordinator = RotationCoordinator("runtime")
                coordinator.run_once(now=now)
                attached_logger.warning("after")

            archives = list(Path(directory).glob("app.log.20??-??-??"))
            self.assertEqual(1, len(archives))
            self.assertEqual("before\n", archives[0].read_text(encoding="utf-8"))
            self.assertEqual("after\n", path.read_text(encoding="utf-8"))

    def test_forked_copy_cannot_start_or_close_parent_coordinator(self) -> None:
        """A copied runtime PID must never control its parent's live thread object."""
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(
                Path(directory, "app.log"),
                when="D",
                backupCount=1,
            )
            with _AttachedHandler(handler, "runtime"):
                coordinator = RotationCoordinator("runtime", check_interval=60)
                coordinator.start()
                try:
                    self.assertTrue(coordinator.is_alive)
                    with patch(
                        "oldman.logging.rotation.os.getpid",
                        return_value=coordinator.owner_pid + 1,
                    ):
                        coordinator.start()
                        coordinator.close()
                    self.assertTrue(coordinator.is_alive)
                finally:
                    coordinator.close()
                self.assertFalse(coordinator.is_alive)

    def test_conflicting_policies_for_one_path_are_rejected(self) -> None:
        """One activity path cannot have ambiguous time and size policies."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "app.log")
            timed = AtomicAppendFileHandler(path, when="D", backupCount=3)
            sized = AtomicAppendFileHandler(path, maxBytes=1, backupCount=2)
            with _AttachedHandler(timed, "runtime"), _AttachedHandler(sized, "runtime"):
                coordinator = RotationCoordinator("runtime")
                with self.assertRaisesRegex(ValueError, "conflicting rotation policies"):
                    coordinator.start()

    def test_close_remains_bounded_while_a_rotation_pass_owns_its_lock(self) -> None:
        """Shutdown must not wait forever for a stalled filesystem operation."""
        coordinator = RotationCoordinator("runtime")
        coordinator._operation_lock.acquire()
        closer = threading.Thread(target=coordinator.close, kwargs={"timeout": 0.01})
        try:
            with patch("oldman.logging.rotation._emergency_write") as emergency_write:
                closer.start()
                closer.join(0.1)
                self.assertFalse(closer.is_alive())
                emergency_write.assert_called_once()
        finally:
            coordinator._operation_lock.release()
            closer.join(1)

    def test_four_writers_preserve_records_during_forced_rotation(self) -> None:
        """Concurrent child writers follow one coordinator rename without record loss."""
        context: Any = multiprocessing.get_context("spawn")
        producers = [f"writer-{index}" for index in range(4)]
        records_per_phase = 100
        with tempfile.TemporaryDirectory() as directory:
            runtime = init_logging(
                "rotation_pressure",
                logger_path=directory,
                logger_level=logging.INFO,
                color="never",
                config={
                    "handlers": {
                        "file": {
                            "when": None,
                            "maxBytes": 1,
                            "backupCount": 3,
                        }
                    },
                    "root": {"handlers": ["file"]},
                    "loggers": {"default": {"handlers": ["file"]}},
                },
            )
            file_handlers = {
                handler
                for handler in cast(Any, runtime)._handlers
                if isinstance(handler, AtomicAppendFileHandler)
            }
            self.assertTrue(file_handlers)
            self.assertEqual(
                {1.0},
                {handler._reopen_check_interval for handler in file_handlers},
            )
            coordinator = cast(Any, runtime)._coordinator
            self.assertIsNotNone(coordinator)
            # Stop periodic polling so this test controls the sole rollover instant.
            coordinator.close()
            active = Path(directory) / "rotation_pressure.log"
            logger.info("ROTATION_SEED")
            inode_before = active.stat().st_ino
            barrier = context.Barrier(len(producers) + 1)
            processes = [
                context.Process(
                    target=write_across_rotation,
                    args=(
                        runtime.child_context,
                        producer,
                        records_per_phase,
                        barrier,
                    ),
                )
                for producer in producers
            ]
            for process in processes:
                process.start()
            barrier.wait(timeout=15)
            coordinator.run_once()
            for process in processes:
                process.join(15)
            reopen_probes: list[str] = []
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                reopen_probe = f"ROTATION_REOPEN_PROBE:{uuid.uuid4().hex}"
                reopen_probes.append(reopen_probe)
                logger.info(reopen_probe)
                if active.exists() and reopen_probe.encode() in active.read_bytes():
                    break
                time.sleep(0.02)
            else:
                self.fail("active log did not receive a reopen probe within 2.5 seconds")
            inode_after = active.stat().st_ino
            runtime.close()
            try:
                for process in processes:
                    self.assertFalse(process.is_alive())
                    self.assertEqual(0, process.exitcode)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join(2)

            combined = b"".join(
                path.read_bytes()
                for path in sorted(Path(directory).glob("rotation_pressure.log*"))
            )
            expected = {
                (producer, sequence)
                for producer in producers
                for sequence in range(records_per_phase * 2)
            }
            observed = _rotation_record_counts(combined)
            self.assertNotEqual(inode_before, inode_after)
            self.assertEqual(
                len(producers) * records_per_phase * 2,
                sum(observed.values()),
            )
            self.assertEqual(Counter(expected), observed)
            self.assertIn(reopen_probes[-1].encode(), active.read_bytes())
            for reopen_probe in reopen_probes:
                self.assertEqual(1, combined.count(reopen_probe.encode()))
            self.assertTrue(Path(directory, "rotation_pressure.log.1").exists())
            self.assertTrue(
                all(line.endswith(b"\n") for line in combined.splitlines(keepends=True))
            )

    def tearDown(self) -> None:
        """Close a runtime left active by a failed pressure assertion."""
        runtime = get_active_runtime()
        if runtime is not None:
            runtime.close()


class RotationRecordCountTest(unittest.TestCase):
    """Verify duplicate writer records remain visible to completeness checks."""

    def test_duplicate_sample_preserves_both_occurrences(self) -> None:
        """Two identical matches must produce a count of two, never one set key."""
        sample = b"ROTATE_RECORD:writer-0:0\nROTATE_RECORD:writer-0:0\n"

        counts = _rotation_record_counts(sample)

        self.assertEqual(2, counts[("writer-0", 0)])


if __name__ == "__main__":
    unittest.main()
