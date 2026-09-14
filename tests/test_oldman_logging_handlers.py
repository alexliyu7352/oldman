"""Linux file-handler contracts for Oldman's direct multiprocess logging."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oldman.logging.handlers import AtomicAppendFileHandler, RotationPolicy


def _record(message: str) -> logging.LogRecord:
    """Build one predictable record without involving process-global logger routes."""
    return logging.LogRecord("handler-test", logging.INFO, __file__, 1, message, (), None)


class _MonotonicClock:
    """Expose one mutable monotonic value for deterministic reopen checks."""

    def __init__(self, now: float) -> None:
        self.now = now

    def monotonic(self) -> float:
        """Return the currently selected monotonic value."""
        return self.now


class _DescriptorWriteFault:
    """Inject writes only for one owned descriptor and preserve global writes."""

    def __init__(self, descriptor: int, *results: int) -> None:
        self.descriptor = descriptor
        self.results = iter(results)
        self.real_write = os.write

    def __call__(self, descriptor: int, payload: bytes | memoryview) -> int:
        if descriptor != self.descriptor:
            return self.real_write(descriptor, payload)
        return next(self.results)


class AtomicAppendFileHandlerTest(unittest.TestCase):
    """Verify direct writers append complete records and follow inode replacement."""

    def test_emit_writes_one_complete_utf8_record(self) -> None:
        """A normal record must become one UTF-8 payload in one ``os.write`` call."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "app.log")
            handler = AtomicAppendFileHandler(path)
            handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            try:
                with patch("oldman.logging.handlers.os.write", wraps=os.write) as write:
                    handler.handle(_record("中文"))
            finally:
                handler.close()

            self.assertEqual("INFO 中文\n", path.read_text(encoding="utf-8"))
            self.assertEqual(1, write.call_count)

            payload = write.call_args.args[1]
            self.assertIsInstance(payload, bytes)
            self.assertEqual("INFO 中文\n".encode(), payload)

    def test_negative_reopen_interval_is_rejected(self) -> None:
        """A reopen polling interval cannot move backwards."""
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ValueError,
                "reopen_check_interval must be greater than or equal to 0",
            ):
                AtomicAppendFileHandler(
                    Path(directory, "app.log"),
                    reopen_check_interval=-0.01,
                )

    def test_zero_reopen_interval_checks_before_each_subsequent_emit(self) -> None:
        """An explicit zero interval preserves per-record path checks."""
        clock = _MonotonicClock(100.0)
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(
                Path(directory, "app.log"),
                reopen_check_interval=0,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                with (
                    patch(
                        "time.monotonic",
                        side_effect=clock.monotonic,
                    ),
                    patch("oldman.logging.handlers.os.stat", wraps=os.stat) as stat,
                ):
                    handler.handle(_record("first"))
                    handler.handle(_record("second"))
                    handler.handle(_record("third"))
            finally:
                handler.close()

            self.assertEqual(2, stat.call_count)

    def test_emits_within_reopen_window_skip_path_stat(self) -> None:
        """The first emit opens once and same-window records avoid path stats."""
        clock = _MonotonicClock(100.0)
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(Path(directory, "app.log"))
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                with (
                    patch(
                        "time.monotonic",
                        side_effect=clock.monotonic,
                    ),
                    patch("oldman.logging.handlers.os.open", wraps=os.open) as open_fd,
                    patch("oldman.logging.handlers.os.stat", wraps=os.stat) as stat,
                ):
                    handler.handle(_record("first"))
                    clock.now = 100.99
                    handler.handle(_record("second"))
                    handler.handle(_record("third"))
            finally:
                handler.close()

            self.assertEqual(1, open_fd.call_count)
            self.assertEqual(0, stat.call_count)

    def test_first_emit_after_reopen_deadline_checks_path_once(self) -> None:
        """Only the first record at or after the deadline stats the active path."""
        clock = _MonotonicClock(100.0)
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(Path(directory, "app.log"))
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                with (
                    patch(
                        "time.monotonic",
                        side_effect=clock.monotonic,
                    ),
                    patch("oldman.logging.handlers.os.stat", wraps=os.stat) as stat,
                ):
                    handler.handle(_record("first"))
                    clock.now = 100.5
                    handler.handle(_record("within"))
                    clock.now = 101.0
                    handler.handle(_record("deadline"))
                    handler.handle(_record("same-time"))
            finally:
                handler.close()

            self.assertEqual(1, stat.call_count)

    def test_external_rotation_switches_files_after_reopen_window(self) -> None:
        """Window records stay archived and post-window records use the active path."""
        clock = _MonotonicClock(100.0)
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory, "app.log")
            archived = Path(directory, "app.log.1")
            handler = AtomicAppendFileHandler(active)
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                with patch(
                    "time.monotonic",
                    side_effect=clock.monotonic,
                ):
                    handler.handle(_record("before"))
                    active.rename(archived)
                    active.touch()
                    clock.now = 100.5
                    handler.handle(_record("within-window"))
                    clock.now = 101.0
                    handler.handle(_record("after-window"))
            finally:
                handler.close()

            archived_text = archived.read_text(encoding="utf-8")
            active_text = active.read_text(encoding="utf-8")
            combined = archived_text + active_text
            self.assertEqual("before\nwithin-window\n", archived_text)
            self.assertEqual("after-window\n", active_text)
            for token in ("before", "within-window", "after-window"):
                self.assertEqual(1, combined.count(token))

    def test_partial_write_uses_a_view_only_for_the_remaining_payload(self) -> None:
        """A rare partial syscall writes the exact remaining bytes through a view."""
        payload = b"complete-record\n"
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(Path(directory, "app.log"))
            handler._open_fd()
            descriptor = handler._fd
            assert descriptor is not None
            try:
                with patch(
                    "oldman.logging.handlers.os.write",
                    side_effect=_DescriptorWriteFault(descriptor, 2, len(payload) - 2),
                ) as write:
                    handler._write_all(payload)
            finally:
                handler.close()

            self.assertEqual(2, write.call_count)
            first_payload = write.call_args_list[0].args[1]
            remaining_payload = write.call_args_list[1].args[1]
            self.assertIsInstance(first_payload, bytes)
            self.assertEqual(payload, first_payload)
            self.assertIsInstance(remaining_payload, memoryview)
            self.assertEqual(payload[2:], remaining_payload.tobytes())

    def test_zero_length_write_enters_handler_error_boundary(self) -> None:
        """A syscall making no progress is delegated to logging error handling."""
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(Path(directory, "app.log"))
            record = _record("blocked")
            read_fd, write_fd = os.pipe()
            handler._open_fd()
            descriptor = handler._fd
            assert descriptor is not None
            try:
                with (
                    patch(
                        "oldman.logging.handlers.os.write",
                        side_effect=_DescriptorWriteFault(descriptor, 0),
                    ),
                    patch.object(handler, "handleError") as handle_error,
                ):
                    self.assertEqual(1, os.write(write_fd, b"x"))
                    self.assertEqual(b"x", os.read(read_fd, 1))
                    handler.handle(record)
            finally:
                os.close(read_fd)
                os.close(write_fd)
                handler.close()

            handle_error.assert_called_once_with(record)

    def test_close_resets_reopen_deadline(self) -> None:
        """Closing clears both inode state and the monotonic reopen deadline."""
        clock = _MonotonicClock(100.0)
        with tempfile.TemporaryDirectory() as directory:
            handler = AtomicAppendFileHandler(Path(directory, "app.log"))
            with patch(
                "time.monotonic",
                side_effect=clock.monotonic,
            ):
                handler.handle(_record("record"))
            handler.close()

            self.assertEqual(0.0, handler._next_reopen_check_at)

    def test_handler_declares_rotation_without_rotating_on_emit(self) -> None:
        """Rotation settings are metadata for the coordinator, never emit behavior."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "app.log")
            handler = AtomicAppendFileHandler(path, when="D", interval=1, backupCount=3)
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                handler.handle(_record("record"))
            finally:
                handler.close()

            self.assertEqual(RotationPolicy.time("D", 1, 3), handler.rotation_policy)
            self.assertEqual("record\n", path.read_text(encoding="utf-8"))
            self.assertEqual([path], list(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
