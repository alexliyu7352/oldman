"""Run a command in the foreground, on the caller's terminal: for commands a person may answer."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Mapping
from typing import Any

from oldman.processes.subprocess import CommandArgument


async def run_foreground(
    program: CommandArgument,
    *args: CommandArgument,
    input: bytes | str | None = None,
    capture_output: bool = False,
    text: bool = False,
    timeout: float | None = None,
    check: bool = False,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Run one command in the foreground, on the caller's terminal, and wait for it to finish.

    For commands a person may need to answer: `sudo` asking for a password, a script that reads
    from the terminal. The child stays in the caller's session and process group, so it can open
    the terminal, and Ctrl-C at the terminal reaches it together with the caller. It is
    `subprocess.run` in a worker thread, so the event loop keeps serving the caller's other tasks
    while it waits; results and errors are the standard library's: `CompletedProcess`,
    `CalledProcessError` with `check`, `TimeoutExpired`, `FileNotFoundError` for a missing program.
    `input` is bytes, or str with `text`; `env` replaces the environment rather than adding to it.

    Nothing owns the child beyond that. A timeout kills the command but not what it started, and
    cancelling the await does not stop it: it runs to its end, and `asyncio.run` waits for it
    before it returns, so the tool does not exit until then. For children no person talks to,
    in a web service, a taskiq worker or a job whose whole process group must be cleaned up, use
    `run_subprocess_exec`.
    """
    command = [os.fspath(program), *(os.fspath(argument) for argument in args)]
    environment = None if env is None else dict(env)
    return await asyncio.to_thread(
        lambda: subprocess.run(
            command,
            input=input,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            check=check,
            cwd=cwd,
            env=environment,
        )
    )


__all__ = ["run_foreground"]
