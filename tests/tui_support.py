"""Tests of commands that ask through oldman.cli.tui."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from oldman.cli.tui import ANSWER_ENV_PREFIX


class TerminalStream(io.StringIO):
    """A stream that says it is a terminal, to stand in for stdin, stdout or stderr."""

    def isatty(self) -> bool:
        return True


@contextmanager
def without_preset_answers() -> Iterator[None]:
    """Hide the `OLDMAN_ANSWER_*` variables of the developer's shell during the block.

    A preset answer wins over the answers a test gives, so one left exported in the shell would
    answer the test's questions for it.
    """
    with patch.dict(os.environ):
        for name in [name for name in os.environ if name.startswith(ANSWER_ENV_PREFIX)]:
            del os.environ[name]
        yield
