"""Small interaction boundary shared by project database commands."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol, runtime_checkable


class MigrationInteractionRequired(RuntimeError):
    """Raised when a migration decision cannot be made without a real terminal."""


class MigrationInteraction(Protocol):
    """Collect explicit user intent without coupling migration logic to Typer."""

    def choose(self, prompt: str, choices: tuple[str, ...]) -> str:
        """Choose exactly one value from a non-empty set."""
        ...

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        """Return an explicit yes/no answer."""
        ...

    def text(self, prompt: str, *, default: str) -> str:
        """Return non-empty editable text, using the suggestion when accepted."""
        ...


@runtime_checkable
class ExactMigrationInteraction(MigrationInteraction, Protocol):
    """Optional destructive-confirmation capability used only when required."""

    def enter(self, prompt: str) -> str:
        """Return exact text without offering a destructive default."""
        ...


class ConsoleMigrationInteraction:
    """Ask migration decisions at an attached terminal, through `oldman.cli.tui`.

    Schema intent is never decided by pipes or automation, nor by someone who cannot see the
    question: unless stdin and stdout are both terminals every question raises
    `MigrationInteractionRequired`, and the questions have no preset-answer keys.
    """

    @property
    def is_interactive(self) -> bool:
        """Whether a person can see and answer the questions here (a terminal on stdin and stdout, or `tui.simulate_input` in tests)."""
        from oldman.cli.tui.inputs import _interactive

        return _interactive()

    def choose(self, prompt: str, choices: tuple[str, ...]) -> str:
        """Display numbered choices and require one of them."""
        from oldman.cli import tui

        self._require_terminal()
        if not choices:
            raise ValueError("Migration choices cannot be empty.")
        with _terminal_closing_is_an_error():
            return tui.choose(prompt, choices)

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        """Ask a yes/no question with an explicit visible default."""
        from oldman.cli import tui

        self._require_terminal()
        with _terminal_closing_is_an_error():
            return tui.confirm(prompt, default=default)

    def text(self, prompt: str, *, default: str) -> str:
        """Ask for editable text; an empty answer accepts the suggestion."""
        from oldman.cli import tui

        self._require_terminal()
        if not default.strip():
            raise ValueError("Migration text suggestions cannot be empty.")
        with _terminal_closing_is_an_error():
            return str(tui.ask(prompt, default=default))

    def enter(self, prompt: str) -> str:
        """Read exact confirmation text without offering a destructive default."""
        from oldman.cli import tui

        self._require_terminal()
        with _terminal_closing_is_an_error():
            return str(tui.ask(prompt, required=False) or "")

    def _require_terminal(self) -> None:
        """Prevent pipes and automation from silently choosing schema intent."""
        if not self.is_interactive:
            raise MigrationInteractionRequired("This migration decision requires an interactive terminal.")


@contextmanager
def _terminal_closing_is_an_error() -> Iterator[None]:
    """The end of input leaves a decision unmade: report it as such. Ctrl-C stops the command."""
    from oldman.cli import tui

    try:
        yield
    except tui.Cancelled as cancelled:
        if cancelled.reason == "interrupt":
            raise KeyboardInterrupt from None
        raise MigrationInteractionRequired("The interactive terminal closed before a migration decision was made.") from None


__all__ = [
    "ConsoleMigrationInteraction",
    "ExactMigrationInteraction",
    "MigrationInteraction",
    "MigrationInteractionRequired",
]
