"""Answer tui questions from a list, for tests of commands that ask."""

from __future__ import annotations

import io
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from oldman.cli.tui.inputs import Cancelled, _reader
from oldman.cli.tui.output import _descriptions_stream

#: What an answer can be: the text typed, or `KeyboardInterrupt` / `EOFError` to cancel there.
Answer = str | type[KeyboardInterrupt] | type[EOFError]


class SimulatedTerminal:
    """The answers still to give, and everything printed while the block ran."""

    def __init__(self, answers: Iterable[Answer]) -> None:
        self._answers = list(answers)
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()

    @property
    def stdout(self) -> str:
        return self._stdout.getvalue()

    @property
    def stderr(self) -> str:
        return self._stderr.getvalue()

    @property
    def remaining(self) -> list[Answer]:
        """Answers no question asked for."""
        return list(self._answers)

    def read(self, prompt: str, *, secret: bool) -> str:
        """Print the prompt and the answer the way a terminal would show them; secrets stay hidden."""
        stream = _descriptions_stream()
        stream.write(prompt)
        if not self._answers:
            raise RuntimeError(f"simulate_input ran out of answers at the prompt {prompt!r}")
        answer = self._answers.pop(0)
        if answer is KeyboardInterrupt or answer is EOFError:
            stream.write("\n")
            raise Cancelled("interrupt" if answer is KeyboardInterrupt else "end-of-input")
        assert isinstance(answer, str)
        stream.write(("" if secret else answer) + "\n")
        return answer


@contextmanager
def simulate_input(answers: Iterable[Answer]) -> Iterator[SimulatedTerminal]:
    """Answer the questions asked inside the block, in order, and capture stdout and stderr.

    Questions count as interactive here even though stdin is not a terminal. Running out of
    answers raises `RuntimeError` naming the prompt, so a test never waits on the real terminal.
    """
    terminal = SimulatedTerminal(answers)
    token = _reader.set(terminal)
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = terminal._stdout, terminal._stderr
    try:
        yield terminal
    finally:
        sys.stdout, sys.stderr = saved
        _reader.reset(token)


__all__ = ["SimulatedTerminal", "simulate_input"]
