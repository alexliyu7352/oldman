"""Terminal output for commands and ops tools: data lines, status lines, tables and rules.

Everything is plain text: values are never read as Rich markup, so a database string or a
file path prints as it is. Colors and Unicode symbols appear only where the stream can show
them; a non-UTF-8 stream gets ASCII.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from rich.console import Console

#: Set while a `raw_stdout` command runs: its stdout carries only data, so everything
#: meant for a person (status lines, tables, waiting indicators) goes to stderr.
_raw_stdout: ContextVar[bool] = ContextVar("oldman_cli_tui_raw_stdout", default=False)

# kind: (symbol, ASCII symbol, style)
_STATUS = {
    "success": ("✓", "[ok]", "green"),
    "warning": ("⚠", "[!]", "yellow"),
    "error": ("✗", "[x]", "red"),
}


@contextmanager
def _command_stdout(*, raw_stdout: bool) -> Iterator[None]:
    """For the CLI command dispatcher: route output for one command by its `raw_stdout`."""
    token = _raw_stdout.set(raw_stdout)
    try:
        yield
    finally:
        _raw_stdout.reset(token)


def _console(*, stderr: bool) -> Console:
    """A console on the stream as it is now, so redirection and test capture take effect."""
    from rich.console import Console

    return Console(file=sys.stderr if stderr else sys.stdout, markup=False, highlight=False, emoji=False)


def _is_terminal(stream: TextIO | None) -> bool:
    """Whether `stream` is a terminal by its own isatty(), whatever FORCE_COLOR says to Rich."""
    # A standard stream closed when the process started is None (`python app.py 0<&-`).
    return stream is not None and stream.isatty()


def _descriptions_stream() -> TextIO:
    """Where text meant for a person goes: stdout, or stderr inside a `raw_stdout` command."""
    return sys.stderr if _raw_stdout.get() else sys.stdout


def _descriptions_console() -> Console:
    return _console(stderr=_descriptions_stream() is sys.stderr)


def echo(message: object = "") -> None:
    """Write one line of data to stdout, exactly as given."""
    # Not through Rich: its Text drops control characters and expands tabs, which would change
    # data such as tab-separated rows. Inside a waiting indicator drawn on a terminal, Rich still
    # relays the line above the indicator and shows tabs as spaces; that only affects the screen,
    # since off a terminal there is no indicator to relay through.
    stream = sys.stdout
    if stream is None:
        # stdout closed when the process started (`command >&-`): nowhere to write, as with Rich.
        return
    stream.write(f"{message}\n")
    stream.flush()


def info(message: object) -> None:
    """Write a line of explanation."""
    from rich.text import Text

    _descriptions_console().print(Text(str(message)), soft_wrap=True)


def _status(kind: str, message: object, console: Console) -> None:
    from rich.text import Text

    symbol, ascii_symbol, style = _STATUS[kind]
    prefix = ascii_symbol if console.options.ascii_only else symbol
    console.print(Text(f"{prefix} ", style=style) + Text(str(message)), soft_wrap=True)


def success(message: object) -> None:
    """Write a line saying something worked."""
    _status("success", message, _descriptions_console())


def warning(message: object) -> None:
    """Write a line saying something needs attention."""
    _status("warning", message, _descriptions_console())


def error(message: object) -> None:
    """Write a line saying something failed; always to stderr."""
    _status("error", message, _console(stderr=True))


def table(
    rows: Iterable[Sequence[object]],
    *,
    headers: Sequence[object] | None = None,
    title: object | None = None,
) -> None:
    """Write a table. Cells are plain text; `None` shows as an empty cell.

    A cell too wide for the terminal wraps inside its column instead of being cut. When the
    output is not a terminal Rich lays the table out 80 columns wide (or `$COLUMNS`), so one
    row may take several lines.
    """
    from rich.table import Table
    from rich.text import Text

    materialized = [list(row) for row in rows]
    width = len(headers) if headers is not None else max((len(row) for row in materialized), default=0)
    for row in materialized:
        if len(row) > width:
            raise ValueError(f"table row has {len(row)} cells but the table has {width} columns")

    grid = Table(title=None if title is None else Text(str(title)), show_header=headers is not None)
    for index in range(width):
        grid.add_column(Text(str(headers[index])) if headers is not None else "", overflow="fold")
    for row in materialized:
        grid.add_row(*(Text("" if cell is None else str(cell)) for cell in row))
    _descriptions_console().print(grid)


def rule(title: object = "") -> None:
    """Write a horizontal line, with a title in it if one is given."""
    from rich.rule import Rule
    from rich.text import Text

    _descriptions_console().print(Rule(Text(str(title))))


__all__ = ["echo", "error", "info", "rule", "success", "table", "warning"]
