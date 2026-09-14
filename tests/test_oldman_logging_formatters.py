"""Formatter contracts for terminal color and plain-text log files."""

from __future__ import annotations

import logging
import unittest

from oldman.logging.formatters import (
    AccessConsoleFormatter,
    ConsoleFormatter,
    PlainTextAccessFormatter,
    PlainTextFormatter,
)


class _TTYStream:
    """Provide the minimal stream contract needed by the auto color policy."""

    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        """Return the configured terminal state."""
        return self._is_tty


class LoggingFormatterTest(unittest.TestCase):
    """Verify console formatting cannot contaminate a shared file record."""

    def test_console_color_never_contaminates_file_record(self) -> None:
        """Console formatting must work on a copy of the source record."""
        record = logging.LogRecord(
            "default",
            logging.ERROR,
            __file__,
            17,
            "失败 %s",
            ("消息",),
            None,
        )
        original = (record.msg, record.args, record.levelname)

        console = ConsoleFormatter("%(levelname)s %(message)s", color="always").format(record)
        plain = PlainTextFormatter("%(levelname)s %(message)s").format(record)

        self.assertIn("\x1b[", console)
        self.assertNotIn("\x1b[", plain)
        self.assertEqual(original, (record.msg, record.args, record.levelname))
        self.assertEqual("ERROR 失败 消息", plain)

    def test_auto_and_never_color_policies_follow_the_stream(self) -> None:
        """Auto colors only a TTY while never remains plain on every stream."""
        record = logging.LogRecord("default", logging.WARNING, __file__, 1, "warning", (), None)

        tty = ConsoleFormatter("%(message)s", color="auto", stream=_TTYStream(True)).format(record)
        pipe = ConsoleFormatter("%(message)s", color="auto", stream=_TTYStream(False)).format(record)
        never = ConsoleFormatter("%(message)s", color="never", stream=_TTYStream(True)).format(record)

        self.assertIn("\x1b[", tty)
        self.assertEqual("warning", pipe)
        self.assertEqual("warning", never)

    def test_plain_text_removes_terminal_sequences_but_keeps_literal_brackets(self) -> None:
        """File output removes ANSI and paired Rich tags without erasing ordinary labels."""
        record = logging.LogRecord(
            "default",
            logging.INFO,
            __file__,
            1,
            "\x1b[31m失败\x1b[0m [red]详情[/red] [ERROR]",
            (),
            None,
        )

        rendered = PlainTextFormatter("%(message)s").format(record)

        self.assertEqual("失败 详情 [ERROR]", rendered)


class LoggingAccessFormatterTest(unittest.TestCase):
    """Verify Sanic access records use string-safe formatting and fallback."""

    def test_access_formatter_accepts_sanic_byte_variants(self) -> None:
        """Numeric and sentinel byte values must render without numeric coercion."""
        formatter = PlainTextAccessFormatter()
        for byte_value in (123, "chunked", "DISCONNECTED"):
            with self.subTest(byte_value=byte_value):
                record = logging.makeLogRecord(
                    {
                        "name": "sanic.access",
                        "levelno": logging.INFO,
                        "levelname": "INFO",
                        "msg": "",
                        "host": "127.0.0.1",
                        "request": "GET /",
                        "status": 200,
                        "byte": byte_value,
                        "duration": 0.01,
                    }
                )

                rendered = formatter.format(record)

                self.assertIn(str(byte_value), rendered)
                self.assertEqual(byte_value, record.__dict__["byte"])

    def test_missing_access_fields_fall_back_to_generic_message(self) -> None:
        """A non-access record sent through the access logger must not raise."""
        record = logging.LogRecord("sanic.access", logging.INFO, __file__, 1, "plain", (), None)

        rendered = PlainTextAccessFormatter().format(record)

        self.assertIn("plain", rendered)

    def test_access_console_color_does_not_mutate_field_types(self) -> None:
        """Access color applies after copying and normalizing the record."""
        record = logging.makeLogRecord(
            {
                "name": "sanic.access",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "",
                "host": "127.0.0.1",
                "request": "GET /health",
                "status": 204,
                "byte": 0,
            }
        )

        rendered = AccessConsoleFormatter(color="always").format(record)

        self.assertIn("\x1b[", rendered)
        self.assertEqual(204, record.__dict__["status"])
        self.assertEqual(0, record.__dict__["byte"])


if __name__ == "__main__":
    unittest.main()
