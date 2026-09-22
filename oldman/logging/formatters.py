"""Oldman-owned console and plain-text logging formatters."""

from __future__ import annotations

import copy
import logging
import re
import sys
from typing import Any, Literal

from oldman.logging.config import ColorPolicy

_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_RICH_TAG_RE = re.compile(r"(?<!\\)\[(?P<tag>/?[^\[\]]+)]")
_GENERIC_FORMAT = "%(asctime)s [%(process)s] [%(levelname)s] %(message)s"
_ACCESS_FORMAT = "%(asctime)s - (%(name)s)[%(levelname)s][%(host)s]: %(request)s %(message)s %(status)s %(byte)s"
_ACCESS_FIELDS = ("host", "request", "status", "byte")
_RESET = "\x1b[0m"


def _rich_tag_name(tag: str) -> tuple[bool, str]:
    """Return whether a Rich tag closes a canonical style name."""
    normalized = tag.strip()
    closing = normalized.startswith("/")
    if closing:
        normalized = normalized[1:].strip()
    return closing, normalized.split("=", 1)[0].lower()


def _strip_paired_rich_tags(text: str) -> str:
    """Remove paired Rich tags while preserving ordinary bracketed log labels."""
    stack: list[tuple[re.Match[str], str]] = []
    removed_spans: set[tuple[int, int]] = set()
    for match in _RICH_TAG_RE.finditer(text):
        closing, name = _rich_tag_name(match.group("tag"))
        if not closing:
            stack.append((match, name))
            continue

        if not stack:
            continue
        if not name:
            opening_match, _ = stack.pop()
        else:
            opening_index = next(
                (index for index in range(len(stack) - 1, -1, -1) if stack[index][1] == name),
                None,
            )
            if opening_index is None:
                continue
            opening_match, _ = stack.pop(opening_index)
        removed_spans.add(opening_match.span())
        removed_spans.add(match.span())

    if not removed_spans:
        return text
    for start, end in sorted(removed_spans, reverse=True):
        text = f"{text[:start]}{text[end:]}"
    return text


def strip_terminal_markup(text: str) -> str:
    """Remove ANSI control sequences and paired Rich markup from file output."""
    return _strip_paired_rich_tags(_ANSI_ESCAPE_RE.sub("", text))


def _stream_is_tty(stream: Any) -> bool:
    """Read a stream's terminal state without allowing a custom stream to break logging."""
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _colorize(level: int, text: str) -> str:
    """Apply one terminal color derived only from the record level."""
    if level >= logging.CRITICAL:
        color = "\x1b[1;31m"
    elif level >= logging.ERROR:
        color = "\x1b[31m"
    elif level >= logging.WARNING:
        color = "\x1b[33m"
    elif level >= logging.INFO:
        color = "\x1b[32m"
    else:
        color = "\x1b[36m"
    return f"{color}{text}{_RESET}"


def _copy_access_record(record: logging.LogRecord) -> logging.LogRecord:
    """Copy and stringify the Sanic fields that previously caused type mismatches."""
    cloned = copy.copy(record)
    for field_name in _ACCESS_FIELDS:
        if not hasattr(record, field_name):
            raise AttributeError(field_name)
        setattr(cloned, field_name, str(getattr(record, field_name)))
    if hasattr(record, "duration"):
        cloned.duration = str(record.__dict__["duration"])
    return cloned


class ConsoleFormatter(logging.Formatter):
    """Color a copied record according to policy without mutating other handlers' input."""

    def __init__(
        self,
        *args: Any,
        color: ColorPolicy = "auto",
        stream: Any = None,
        **kwargs: Any,
    ) -> None:
        """Resolve the color policy once when the formatter is configured."""
        super().__init__(*args, **kwargs)
        if color not in {"auto", "always", "never"}:
            raise ValueError(f"unsupported console color policy: {color!r}")
        target_stream = sys.stdout if stream is None else stream
        self._color_enabled = color == "always" or (color == "auto" and _stream_is_tty(target_stream))

    def format(self, record: logging.LogRecord) -> str:
        """Render a shallow copy so message, args and level metadata stay unchanged."""
        cloned = copy.copy(record)
        rendered = super().format(cloned)
        return _colorize(record.levelno, rendered) if self._color_enabled else rendered


class PlainTextFormatter(logging.Formatter):
    """Render a copied record and remove terminal-only markup from the result."""

    def format(self, record: logging.LogRecord) -> str:
        """Keep the source record reusable by console and queue handlers."""
        cloned = copy.copy(record)
        return strip_terminal_markup(super().format(cloned))


class AccessConsoleFormatter(ConsoleFormatter):
    """Render Sanic access fields safely and fall back to a generic console line."""

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
        *,
        color: ColorPolicy = "auto",
        stream: Any = None,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        """Use Oldman's string-safe access format unless the user supplies one."""
        super().__init__(
            fmt or _ACCESS_FORMAT,
            datefmt,
            style,
            validate,
            color=color,
            stream=stream,
            defaults=defaults,
        )
        self._fallback = ConsoleFormatter(
            _GENERIC_FORMAT,
            datefmt,
            style,
            validate,
            color=color,
            stream=stream,
            defaults=defaults,
        )

    def format(self, record: logging.LogRecord) -> str:
        """Fall back instead of leaking a formatter exception into Sanic logging."""
        try:
            return super().format(_copy_access_record(record))
        except Exception:
            return self._fallback.format(record)


class PlainTextAccessFormatter(PlainTextFormatter):
    """Render Sanic access fields as UTF-8-safe plain text for file handlers."""

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        validate: bool = True,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        """Use the historical access layout without numeric placeholders."""
        super().__init__(fmt or _ACCESS_FORMAT, datefmt, style, validate, defaults=defaults)
        self._fallback = PlainTextFormatter(
            _GENERIC_FORMAT,
            datefmt,
            style,
            validate,
            defaults=defaults,
        )

    def format(self, record: logging.LogRecord) -> str:
        """Fall back to a generic plain line for incomplete or malformed records."""
        try:
            return super().format(_copy_access_record(record))
        except Exception:
            return self._fallback.format(record)


__all__ = [
    "AccessConsoleFormatter",
    "ConsoleFormatter",
    "PlainTextAccessFormatter",
    "PlainTextFormatter",
    "strip_terminal_markup",
]
