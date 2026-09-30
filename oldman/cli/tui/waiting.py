"""Waiting indicators: a spinner for work of unknown length, a bar for work that can be counted.

On a terminal Rich redraws them from its own thread, so they keep moving while the code inside
awaits. Anything else gets plain lines. They go where status lines go: stdout, or stderr inside
a `raw_stdout` command.

While one is shown, prints to its stream appear above it. A logging handler configured with
`ext://sys.stdout` keeps the stream it had at startup and writes over the indicator line, and so
does anything written to the terminal directly, such as sudo asking for a password: the next
redraw wipes it. Run such commands outside an indicator.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from oldman.cli.tui.output import _descriptions_console, _descriptions_stream, _is_terminal, _raw_stdout

if TYPE_CHECKING:
    from rich.progress import Progress, TaskID


def _animated() -> bool:
    """Whether to draw an animation: only on a stream that is a terminal by its own isatty().

    Rich also draws when FORCE_COLOR is set, which would put the animation, and the data relayed
    above it, into a file.
    """
    return _is_terminal(_descriptions_stream())


def _redirect_stdout() -> bool:
    """Whether the indicator may take over stdout: only when it is drawn there, outside `raw_stdout`.

    Rich redirects both streams by default, which inside a `raw_stdout` command would send the
    data written to stdout onto the indicator's stderr. The command's routing decides it, not the
    console's file: under an outer indicator sys.stderr is Rich's proxy, not the file.
    """
    return not _raw_stdout.get()


@contextmanager
def spinner(label: object) -> Iterator[None]:
    """Show a spinner with `label` while the block runs; off a terminal, print `label` once."""
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text

    console = _descriptions_console()
    text = Text(str(label))
    if not _animated():
        console.print(text, soft_wrap=True)
        yield
        return
    with Live(
        Spinner("dots", text=text),
        console=console,
        transient=True,
        redirect_stdout=_redirect_stdout(),
        redirect_stderr=True,
    ):
        yield


class ProgressBar:
    """What the `progress` block gets: move the bar on, or change its numbers or label."""

    def __init__(self, label: str, total: float | None, bar: tuple[Progress, TaskID] | None) -> None:
        self._label = label
        self._total = total
        self._completed: float = 0
        self._bar = bar

    def advance(self, amount: float = 1) -> None:
        """Count `amount` more units done."""
        self._completed += amount
        if self._bar is not None:
            progress, task = self._bar
            progress.advance(task, amount)

    def update(self, *, completed: float | None = None, total: float | None = None, label: object | None = None) -> None:
        """Set how much is done, the total, or the label."""
        if completed is not None:
            self._completed = completed
        if total is not None:
            self._total = total
        if label is not None:
            self._label = str(label)
        if self._bar is not None:
            progress, task = self._bar
            progress.update(task, completed=completed, total=total, description=None if label is None else self._label)

    def _summary(self) -> str:
        done = _number(self._completed)
        return f"{self._label}: {done}" if self._total is None else f"{self._label}: {done}/{_number(self._total)}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@contextmanager
def progress(label: object, *, total: float | None = None) -> Iterator[ProgressBar]:
    """Show a progress bar while the block runs; `total=None` when the amount is not known.

    Off a terminal it prints `label` when the block starts and `label: done/total` when it
    finishes normally.
    """
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.text import Text

    console = _descriptions_console()
    if not _animated():
        bar = ProgressBar(str(label), total, None)
        console.print(Text(str(label)), soft_wrap=True)
        yield bar
        console.print(Text(bar._summary()), soft_wrap=True)
        return
    columns = (
        SpinnerColumn(),
        TextColumn("{task.description}", markup=False),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console, redirect_stdout=_redirect_stdout(), redirect_stderr=True) as rich_progress:
        task = rich_progress.add_task(str(label), total=total)
        yield ProgressBar(str(label), total, (rich_progress, task))


__all__ = ["ProgressBar", "progress", "spinner"]
