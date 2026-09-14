"""Process execution primitives with explicit lifecycle ownership."""

from oldman.processes.executor import AsyncProcessManager, ProcessTimeoutError
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
    "run_subprocess_exec",
]
