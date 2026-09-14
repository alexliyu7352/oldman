"""Small interaction boundary shared by project database commands."""

from __future__ import annotations

import sys
from typing import Protocol, TextIO, runtime_checkable


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
    """Read migration decisions only from an attached interactive terminal."""

    def __init__(
        self,
        *,
        input_stream: TextIO = sys.stdin,
        output_stream: TextIO = sys.stdout,
    ) -> None:
        """Keep streams injectable without weakening the production TTY rule."""
        self._input = input_stream
        self._output = output_stream

    @property
    def is_interactive(self) -> bool:
        """Return whether both streams support the decisions required by commands."""
        return self._input.isatty() and self._output.isatty()

    def choose(self, prompt: str, choices: tuple[str, ...]) -> str:
        """Display numbered choices and require one valid selection."""
        self._require_terminal()
        if not choices:
            raise ValueError("Migration choices cannot be empty.")
        self._output.write(f"{prompt}\n")
        for index, choice in enumerate(choices, start=1):
            self._output.write(f"  {index}. {choice}\n")
        self._output.flush()
        while True:
            answer = self._read("Select a number: ")
            try:
                index = int(answer)
            except ValueError:
                continue
            if 1 <= index <= len(choices):
                return choices[index - 1]

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        """Ask a yes/no question with an explicit visible default."""
        self._require_terminal()
        suffix = " [Y/n]: " if default else " [y/N]: "
        while True:
            answer = self._read(f"{prompt}{suffix}").casefold()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False

    def text(self, prompt: str, *, default: str) -> str:
        """Ask for editable text and reject an empty final value."""
        self._require_terminal()
        if not default.strip():
            raise ValueError("Migration text suggestions cannot be empty.")
        answer = self._read(f"{prompt} [{default}]: ")
        return answer or default

    def enter(self, prompt: str) -> str:
        """Read exact confirmation text without accepting an empty default."""
        self._require_terminal()
        return self._read(f"{prompt}: ")

    def _require_terminal(self) -> None:
        """Prevent pipes and automation from silently choosing schema intent."""
        if not self._input.isatty() or not self._output.isatty():
            raise MigrationInteractionRequired("This migration decision requires an interactive terminal.")

    def _read(self, prompt: str) -> str:
        """Write one prompt and read a stripped line from the configured stream."""
        self._output.write(prompt)
        self._output.flush()
        value = self._input.readline()
        if value == "":
            raise MigrationInteractionRequired("The interactive terminal closed before a migration decision was made.")
        return value.strip()


__all__ = [
    "ConsoleMigrationInteraction",
    "ExactMigrationInteraction",
    "MigrationInteraction",
    "MigrationInteractionRequired",
]
