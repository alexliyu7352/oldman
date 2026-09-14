"""Direct-writer logging runtime lifecycle contracts."""

from __future__ import annotations

import io
import logging
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from oldman.logging import (
    ChildLoggingContext,
    LoggingRuntime,
    get_active_runtime,
    init_logging,
    logger,
)
from oldman.logging.handlers import AtomicAppendFileHandler


class _TrackingHandler(logging.Handler):
    """Record whether runtime cleanup closes an unrelated user handler."""

    def __init__(self) -> None:
        """Initialize the close counter."""
        super().__init__()
        self.close_calls = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Accept records without producing test output."""
        del record

    def close(self) -> None:
        """Count explicit closes before delegating to the standard handler."""
        self.close_calls += 1
        super().close()


class _TTYBuffer(io.StringIO):
    """Capture console output while reporting that it owns a terminal."""

    def isatty(self) -> bool:
        """Make the runtime's automatic color decision deterministic."""
        return True


class DirectLoggingRuntimeTest(unittest.TestCase):
    """Verify owner installation, child installation and resource ownership."""

    def tearDown(self) -> None:
        """Close an active Oldman runtime left by a failed assertion."""
        runtime = get_active_runtime()
        if runtime is not None:
            runtime.close()

    def test_main_runtime_installs_atomic_writers_and_closes_only_its_handlers(self) -> None:
        """The main runtime owns rotation but never closes a foreign handler."""
        foreign = _TrackingHandler()
        logger.addHandler(foreign)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime = init_logging(
                    "direct",
                    logger_path=tmp,
                    logger_level=logging.INFO,
                    color="never",
                )

                self.assertIsInstance(runtime, LoggingRuntime)
                self.assertIsInstance(runtime.child_context, ChildLoggingContext)
                self.assertTrue(runtime.owns_rotation)
                self.assertTrue(
                    any(isinstance(handler, AtomicAppendFileHandler) for handler in logger.handlers)
                )

                logger.info("direct-message")
                runtime.close()

                self.assertIn(
                    "direct-message",
                    (Path(tmp) / "direct.log").read_text(encoding="utf-8"),
                )
                self.assertFalse(
                    any(
                        getattr(handler, "_oldman_runtime_id", None) == runtime.runtime_id
                        for handler in logger.handlers
                    )
                )
                self.assertIn(foreign, logger.handlers)
                self.assertEqual(0, foreign.close_calls)

                runtime.close()
                self.assertTrue(runtime.closed)
        finally:
            logger.removeHandler(foreign)
            foreign.close()

    def test_child_context_replaces_inherited_owner_with_writer_only_runtime(self) -> None:
        """A child context creates atomic writers without a rotation coordinator."""
        with tempfile.TemporaryDirectory() as tmp:
            owner = init_logging(
                "child",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            child = owner.child_context.install()
            try:
                self.assertIsNot(owner, child)
                self.assertTrue(owner.closed)
                self.assertTrue(child.installed_from_context)
                self.assertFalse(child.owns_rotation)
                self.assertTrue(
                    any(isinstance(handler, AtomicAppendFileHandler) for handler in logger.handlers)
                )
            finally:
                child.close()

    def test_repeated_initialization_reuses_identity_and_replaces_changes(self) -> None:
        """An identical call reuses the runtime while a different sink replaces it."""
        with tempfile.TemporaryDirectory() as tmp:
            first = init_logging(
                "first",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            same = init_logging(
                "first",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            self.assertIs(first, same)

            replacement = init_logging(
                "replacement",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
            )
            try:
                self.assertIsNot(first, replacement)
                self.assertTrue(first.closed)
                self.assertIs(replacement, get_active_runtime())
                self.assertTrue(replacement.owns_rotation)
                self.assertFalse(
                    any(
                        getattr(handler, "_oldman_runtime_id", None) == first.runtime_id
                        for handler in logger.handlers
                    )
                )
            finally:
                replacement.close()

    def test_handler_configuration_failure_does_not_publish_a_runtime(self) -> None:
        """A broken user handler fails atomically before becoming the active runtime."""
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            ValueError,
            "unable to configure handler 'file'",
        ):
            init_logging(
                "invalid-handler",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="never",
                config={
                    "handlers": {
                        "file": {"class": "oldman.logging.missing.Handler"},
                    }
                },
            )

        self.assertIsNone(get_active_runtime())

    def test_runtime_applies_explicit_console_color_policy(self) -> None:
        """The public color option must reach formatters created by dictConfig."""
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(output):
            runtime = init_logging(
                "forced_color",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="always",
            )
            try:
                logger.warning("forced-color-token")
            finally:
                runtime.close()

        self.assertIn("\x1b[", output.getvalue())
        self.assertIn("forced-color-token", output.getvalue())

    def test_runtime_auto_color_uses_each_handlers_actual_stream(self) -> None:
        """stderr TTY detection must not reuse the state of a non-TTY stdout."""
        stdout = io.StringIO()
        stderr = _TTYBuffer()
        with (
            tempfile.TemporaryDirectory() as tmp,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            runtime = init_logging(
                "stream_color",
                logger_path=tmp,
                logger_level=logging.INFO,
                color="auto",
            )
            try:
                logging.getLogger("sanic.error").error("stderr-color-token")
            finally:
                runtime.close()

        self.assertNotIn("stderr-color-token", stdout.getvalue())
        self.assertIn("\x1b[", stderr.getvalue())
        self.assertIn("stderr-color-token", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
