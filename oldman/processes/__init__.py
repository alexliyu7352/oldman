"""Process execution primitives with explicit lifecycle ownership.

`run_subprocess_exec` / `create_subprocess_exec` run children no person talks to (in a web
service, a taskiq worker, or a job a command runs), owning their whole process group;
`run_foreground` runs a command a person may answer on the caller's terminal; `AsyncProcessManager`
runs synchronous Python in a process pool.
"""

from oldman.processes.executor import AsyncProcessManager, ProcessTimeoutError
from oldman.processes.foreground import run_foreground
from oldman.processes.subprocess import (
    CompletedSubprocess,
    ManagedSubprocess,
    ManagedSubprocessError,
    SubprocessCleanupError,
    SubprocessError,
    SubprocessStartError,
    SubprocessTimeoutError,
    create_subprocess_exec,
    run_subprocess_exec,
)

__all__ = [
    "AsyncProcessManager",
    "CompletedSubprocess",
    "ManagedSubprocess",
    "ManagedSubprocessError",
    "ProcessTimeoutError",
    "SubprocessCleanupError",
    "SubprocessError",
    "SubprocessStartError",
    "SubprocessTimeoutError",
    "create_subprocess_exec",
    "run_foreground",
    "run_subprocess_exec",
]
