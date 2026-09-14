"""Run external commands with Linux process-group ownership."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

type CommandArgument = str | os.PathLike[str]

_DEFAULT_TERMINATE_GRACE_PERIOD = 2.0
_DEFAULT_KILL_TIMEOUT = 3.0
_STARTUP_TIMEOUT = 5.0
_MAX_HANDSHAKE_BYTES = 64 * 1024
_POLL_INTERVAL = 0.02
_SUPERVISOR_PATH = Path(__file__).with_name("_subprocess_supervisor.py")
_SUPERVISOR_BOOTSTRAP = "import runpy,sys; script=sys.argv.pop(1); sys.argv[0]=script; runpy.run_path(script, run_name='__main__')"


class ManagedSubprocessError(RuntimeError):
    """Base error for managed subprocess startup, execution and cleanup."""


class SubprocessStartError(ManagedSubprocessError):
    """Report a command that could not start behind the private supervisor."""

    def __init__(self, command: tuple[str, ...], message: str) -> None:
        """Retain the normalized command and supervisor diagnostic."""
        self.command = command
        self.message = message
        super().__init__(f"unable to start managed subprocess {command!r}: {message}")


class SubprocessCleanupError(ManagedSubprocessError):
    """Report live process-group members after bounded SIGKILL cleanup."""

    def __init__(self, process_group: int, remaining_pids: tuple[int, ...]) -> None:
        """Retain the unsafe group and exact live PIDs."""
        self.process_group = process_group
        self.remaining_pids = remaining_pids
        super().__init__(f"managed subprocess group {process_group} still has live processes: {list(remaining_pids)}")


class SubprocessTimeoutError(TimeoutError, ManagedSubprocessError):
    """Report a timeout only after the complete owned process group is gone."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        pid: int,
        supervisor_pid: int,
        process_group: int,
        timeout: float,
        stdout: bytes | None = None,
        stderr: bytes | None = None,
    ) -> None:
        """Retain command identity and any output drained during cleanup."""
        self.command = command
        self.pid = pid
        self.supervisor_pid = supervisor_pid
        self.process_group = process_group
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"managed subprocess {pid} exceeded timeout {timeout:.3f}s: {command!r}")


@dataclass(frozen=True, slots=True)
class CompletedSubprocess:
    """Immutable result returned by the one-shot execution helper."""

    args: tuple[str, ...]
    pid: int
    supervisor_pid: int
    process_group: int
    returncode: int
    stdout: bytes | None
    stderr: bytes | None

    def check_returncode(self) -> None:
        """Raise a result-bearing error when the command did not succeed."""
        if self.returncode != 0:
            raise SubprocessError(self)


class SubprocessError(ManagedSubprocessError):
    """Report a completed non-zero command while preserving its full result."""

    def __init__(self, result: CompletedSubprocess) -> None:
        """Retain stdout, stderr, identity and return code for diagnosis."""
        self.result = result
        super().__init__(f"managed subprocess {result.pid} returned {result.returncode}: {result.args!r}")


def _normalize_command(
    program: CommandArgument,
    args: tuple[CommandArgument, ...],
) -> tuple[str, ...]:
    """Convert path-like command arguments to the supervisor's text protocol."""
    command = tuple(os.fsdecode(os.fspath(value)) for value in (program, *args))
    if not command or not command[0]:
        raise ValueError("managed subprocess program cannot be empty")
    if any("\x00" in value for value in command):
        raise ValueError("managed subprocess arguments cannot contain NUL bytes")
    return command


def _validate_durations(
    terminate_grace_period: float,
    kill_timeout: float,
) -> tuple[float, float]:
    """Reject cleanup periods that could disable the bounded safety contract."""
    grace = float(terminate_grace_period)
    kill = float(kill_timeout)
    if grace < 0:
        raise ValueError("terminate_grace_period cannot be negative")
    if kill <= 0:
        raise ValueError("kill_timeout must be greater than zero")
    return grace, kill


def _live_process_group_pids(process_group: int) -> tuple[int, ...]:
    """Return live non-zombie Linux members of one owned process group."""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return ()
    except PermissionError:
        # The group is expected to be ours. If kernel permissions disagree,
        # retain the slower evidence path so cleanup fails closed.
        pass

    pids: list[int] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            state = fields[0]
            group = int(fields[2])
        except (FileNotFoundError, IndexError, OSError, ValueError):
            continue
        if group == process_group and state != "Z":
            pids.append(int(stat_path.parent.name))
    return tuple(sorted(pids))


def _signal_process_group(process_group: int, selected_signal: signal.Signals) -> None:
    """Send one signal to an owned group and tolerate an already-empty group."""
    try:
        os.killpg(process_group, selected_signal)
    except ProcessLookupError:
        return


async def _wait_for_group_exit(process_group: int, timeout: float) -> tuple[int, ...]:
    """Wait asynchronously for a group to contain no live non-zombie process."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = _live_process_group_pids(process_group)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        await asyncio.sleep(_POLL_INTERVAL)


async def _receive_handshake(
    control_socket: socket.socket,
    timeout: float,
) -> dict[str, Any]:
    """Read one bounded JSON line from the private supervisor socket."""
    loop = asyncio.get_running_loop()
    control_socket.setblocking(False)
    payload = bytearray()
    try:
        async with asyncio.timeout(timeout):
            while b"\n" not in payload:
                chunk = await loop.sock_recv(control_socket, 4096)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > _MAX_HANDSHAKE_BYTES:
                    raise SubprocessStartError((), "supervisor handshake exceeded 64 KiB")
    except TimeoutError as error:
        raise SubprocessStartError(
            (),
            f"supervisor did not answer within {timeout:.3f}s",
        ) from error
    except OSError as error:
        raise SubprocessStartError((), f"supervisor handshake failed: {error}") from error
    line = bytes(payload).partition(b"\n")[0]
    if not line:
        raise SubprocessStartError((), "supervisor closed without a startup result")
    try:
        result = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SubprocessStartError((), "supervisor returned invalid JSON") from error
    if not isinstance(result, dict):
        raise SubprocessStartError((), "supervisor result is not an object")
    return result


async def _abort_startup(process: asyncio.subprocess.Process) -> None:
    """Kill and reap a supervisor whose public handle was not constructed."""
    _signal_process_group(process.pid, signal.SIGKILL)
    try:
        async with asyncio.timeout(_DEFAULT_KILL_TIMEOUT):
            await process.wait()
    except TimeoutError as error:
        remaining = _live_process_group_pids(process.pid)
        raise SubprocessCleanupError(process.pid, remaining) from error
    remaining = await _wait_for_group_exit(process.pid, _DEFAULT_KILL_TIMEOUT)
    if remaining:
        raise SubprocessCleanupError(process.pid, remaining)


class ManagedSubprocess:
    """Own one external command, its supervisor and same-group descendants."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        pid: int,
        supervisor: asyncio.subprocess.Process,
        process_group: int,
        terminate_grace_period: float,
        kill_timeout: float,
    ) -> None:
        """Capture process identity and create one shared supervisor wait task."""
        self.args = command
        self.pid = pid
        self.supervisor_pid = supervisor.pid
        self.process_group = process_group
        self._process = supervisor
        self._terminate_grace_period = terminate_grace_period
        self._kill_timeout = kill_timeout
        self._wait_task = asyncio.create_task(supervisor.wait())
        self._cleanup_lock = asyncio.Lock()
        self._communicate_started = False
        self._group_reaped = False

    @property
    def stdin(self) -> asyncio.StreamWriter | None:
        """Return the command's inherited supervisor stdin pipe."""
        return self._process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        """Return the command's inherited supervisor stdout pipe."""
        return self._process.stdout

    @property
    def stderr(self) -> asyncio.StreamReader | None:
        """Return the command's inherited supervisor stderr pipe."""
        return self._process.stderr

    @property
    def returncode(self) -> int | None:
        """Return the mirrored command status after the supervisor exits."""
        return self._process.returncode

    async def __aenter__(self) -> Self:
        """Return this live handle for an async managed scope."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Clean the complete group when scope exit has not already done so."""
        del exc_type, exc_value, traceback
        await self.terminate()

    def send_signal(self, selected_signal: signal.Signals) -> None:
        """Send an application signal only to the actual command PID."""
        if self._wait_task.done():
            return
        try:
            if os.getpgid(self.pid) != self.process_group:
                return
            os.kill(self.pid, selected_signal)
        except (PermissionError, ProcessLookupError):
            return

    async def _cleanup_group(self, *, graceful: bool) -> int:
        """Stop the owned group once and return the mirrored command status."""
        async with self._cleanup_lock:
            if self._group_reaped:
                return await asyncio.shield(self._wait_task)
            if self._wait_task.done():
                returncode = await asyncio.shield(self._wait_task)
                remaining = _live_process_group_pids(self.process_group)
                if remaining:
                    raise SubprocessCleanupError(self.process_group, remaining)
                self._group_reaped = True
                return returncode

            remaining = _live_process_group_pids(self.process_group)
            if remaining:
                if graceful:
                    _signal_process_group(self.process_group, signal.SIGTERM)
                    remaining = await _wait_for_group_exit(
                        self.process_group,
                        self._terminate_grace_period,
                    )
                if remaining:
                    _signal_process_group(self.process_group, signal.SIGKILL)

            try:
                async with asyncio.timeout(self._kill_timeout):
                    returncode = await asyncio.shield(self._wait_task)
            except TimeoutError as error:
                remaining = _live_process_group_pids(self.process_group)
                raise SubprocessCleanupError(self.process_group, remaining) from error

            remaining = await _wait_for_group_exit(
                self.process_group,
                self._kill_timeout,
            )
            if remaining:
                raise SubprocessCleanupError(self.process_group, remaining)
            self._group_reaped = True
            return returncode

    async def _wait_and_cleanup_after_exit(self) -> int:
        """Wait for the command, then remove same-group children it left behind."""
        await asyncio.shield(self._wait_task)
        return await self._cleanup_group(graceful=True)

    async def _shielded_cleanup(self, *, graceful: bool) -> int:
        """Finish group cleanup even when the caller cancels the cleanup await."""
        cleanup_task = asyncio.create_task(self._cleanup_group(graceful=graceful))
        try:
            return await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup_task)
            raise

    async def wait(self, timeout: float | None = None) -> int:
        """Wait asynchronously, cleaning the whole group on timeout or cancellation."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        try:
            if timeout is None:
                return await self._wait_and_cleanup_after_exit()
            resolved_timeout = timeout
            async with asyncio.timeout(resolved_timeout):
                return await self._wait_and_cleanup_after_exit()
        except TimeoutError as error:
            await self._shielded_cleanup(graceful=True)
            raise SubprocessTimeoutError(
                command=self.args,
                pid=self.pid,
                supervisor_pid=self.supervisor_pid,
                process_group=self.process_group,
                timeout=resolved_timeout,
            ) from error
        except asyncio.CancelledError:
            await self._shielded_cleanup(graceful=True)
            raise

    async def communicate(
        self,
        input: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes | None, bytes | None]:
        """Drain both pipes while retaining the same timeout/cancellation cleanup."""
        if self._communicate_started:
            raise RuntimeError("communicate() can only be called once")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        self._communicate_started = True
        communicate_task = asyncio.create_task(self._process.communicate(input))

        async def finish() -> tuple[bytes | None, bytes | None]:
            """Reap the supervisor, clean lingering descendants, then drain EOF."""
            await self._wait_and_cleanup_after_exit()
            return await asyncio.shield(communicate_task)

        try:
            if timeout is None:
                return await finish()
            resolved_timeout = timeout
            async with asyncio.timeout(resolved_timeout):
                return await finish()
        except TimeoutError as error:
            await self._shielded_cleanup(graceful=True)
            stdout, stderr = await asyncio.shield(communicate_task)
            raise SubprocessTimeoutError(
                command=self.args,
                pid=self.pid,
                supervisor_pid=self.supervisor_pid,
                process_group=self.process_group,
                timeout=resolved_timeout,
                stdout=stdout,
                stderr=stderr,
            ) from error
        except asyncio.CancelledError:
            await self._shielded_cleanup(graceful=True)
            await asyncio.shield(communicate_task)
            raise

    async def terminate(self) -> int:
        """Gracefully stop the complete group and escalate after the grace period."""
        return await self._shielded_cleanup(graceful=True)

    async def kill(self) -> int:
        """Immediately SIGKILL the complete group and reap the supervisor."""
        return await self._shielded_cleanup(graceful=False)


async def create_subprocess_exec(
    program: CommandArgument,
    *args: CommandArgument,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 2**16,
    terminate_grace_period: float = _DEFAULT_TERMINATE_GRACE_PERIOD,
    kill_timeout: float = _DEFAULT_KILL_TIMEOUT,
) -> ManagedSubprocess:
    """Start one command behind an owner-death-aware Linux group supervisor."""
    if sys.platform != "linux":
        raise NotImplementedError("managed subprocess currently supports Linux only")
    command = _normalize_command(program, args)
    grace, kill = _validate_durations(terminate_grace_period, kill_timeout)
    parent_socket, child_socket = socket.socketpair()
    supervisor: asyncio.subprocess.Process | None = None
    try:
        supervisor = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            _SUPERVISOR_BOOTSTRAP,
            os.fspath(_SUPERVISOR_PATH),
            "--parent-pid",
            str(os.getpid()),
            "--control-fd",
            str(child_socket.fileno()),
            "--terminate-grace",
            str(grace),
            "--kill-timeout",
            str(kill),
            "--",
            *command,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            env=None if env is None else dict(env),
            limit=limit,
            start_new_session=True,
            pass_fds=(child_socket.fileno(),),
        )
        child_socket.close()
        try:
            handshake = await _receive_handshake(parent_socket, _STARTUP_TIMEOUT)
        except SubprocessStartError as error:
            raise SubprocessStartError(command, error.message) from error
        if handshake.get("ok") is not True:
            message = str(handshake.get("message") or "unknown supervisor error")
            raise SubprocessStartError(command, message)
        pid = handshake.get("pid")
        process_group = handshake.get("process_group")
        if not isinstance(pid, int) or not isinstance(process_group, int):
            raise SubprocessStartError(command, "supervisor omitted process identity")
        if process_group != supervisor.pid:
            raise SubprocessStartError(
                command,
                f"supervisor group {process_group} does not match PID {supervisor.pid}",
            )
        return ManagedSubprocess(
            command=command,
            pid=pid,
            supervisor=supervisor,
            process_group=process_group,
            terminate_grace_period=grace,
            kill_timeout=kill,
        )
    except BaseException:
        if supervisor is not None:
            await asyncio.shield(_abort_startup(supervisor))
        raise
    finally:
        parent_socket.close()
        child_socket.close()


async def run_subprocess_exec(
    program: CommandArgument,
    *args: CommandArgument,
    input: bytes | None = None,
    capture_output: bool = False,
    timeout: float | None = None,
    check: bool = False,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 2**16,
    terminate_grace_period: float = _DEFAULT_TERMINATE_GRACE_PERIOD,
    kill_timeout: float = _DEFAULT_KILL_TIMEOUT,
) -> CompletedSubprocess:
    """Run one command to completion with optional capture and return checking."""
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("capture_output cannot be combined with stdout or stderr")
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.PIPE
    if input is not None:
        if stdin is not None:
            raise ValueError("input cannot be combined with stdin")
        stdin = asyncio.subprocess.PIPE

    process = await create_subprocess_exec(
        program,
        *args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        limit=limit,
        terminate_grace_period=terminate_grace_period,
        kill_timeout=kill_timeout,
    )
    stdout_data, stderr_data = await process.communicate(input, timeout=timeout)
    returncode = process.returncode
    if returncode is None:
        raise RuntimeError("managed subprocess completed without a return code")
    result = CompletedSubprocess(
        args=process.args,
        pid=process.pid,
        supervisor_pid=process.supervisor_pid,
        process_group=process.process_group,
        returncode=returncode,
        stdout=stdout_data,
        stderr=stderr_data,
    )
    if check:
        result.check_returncode()
    return result


__all__ = [
    "CompletedSubprocess",
    "ManagedSubprocess",
    "ManagedSubprocessError",
    "SubprocessCleanupError",
    "SubprocessError",
    "SubprocessStartError",
    "SubprocessTimeoutError",
    "create_subprocess_exec",
    "run_subprocess_exec",
]
