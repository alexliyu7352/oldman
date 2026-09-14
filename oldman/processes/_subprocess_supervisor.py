"""Private Linux supervisor for :mod:`oldman.processes.subprocess`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from typing import NoReturn

_PARENT_DEATH_SIGNAL = signal.SIGUSR1
_POLL_INTERVAL = 0.02


def _write_handshake(control_fd: int, payload: dict[str, object]) -> None:
    """Send one bounded startup result without touching command stdout/stderr."""
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    view = memoryview(encoded)
    while view:
        written = os.write(control_fd, view)
        if written <= 0:
            raise OSError("subprocess supervisor handshake made no progress")
        view = view[written:]


def _kill_owned_group() -> NoReturn:
    """Kill this supervisor and every command process in its private group."""
    os.killpg(os.getpgrp(), signal.SIGKILL)
    os._exit(128 + signal.SIGKILL)


def _handle_parent_death(signum: int, frame: object) -> NoReturn:
    """Convert the kernel parent-death notification into whole-group cleanup."""
    del signum, frame
    _kill_owned_group()


def _hold_group_termination(signum: int, frame: object) -> None:
    """Keep the supervisor alive while the same signal reaches the command."""
    del signum, frame


def _parse_arguments(
    argv: Sequence[str],
) -> tuple[int, int, float, float, tuple[str, ...]]:
    """Parse the fixed private protocol and reject an empty command."""
    if (
        len(argv) < 11
        or argv[1] != "--parent-pid"
        or argv[3] != "--control-fd"
        or argv[5] != "--terminate-grace"
        or argv[7] != "--kill-timeout"
        or argv[9] != "--"
    ):
        raise ValueError("invalid managed subprocess supervisor arguments")
    try:
        parent_pid = int(argv[2])
        control_fd = int(argv[4])
        terminate_grace_period = float(argv[6])
        kill_timeout = float(argv[8])
    except ValueError as error:
        raise ValueError("invalid managed subprocess supervisor value") from error
    if terminate_grace_period < 0 or kill_timeout <= 0:
        raise ValueError("invalid managed subprocess cleanup duration")
    command = tuple(argv[10:])
    if not command:
        raise ValueError("managed subprocess command cannot be empty")
    return (
        parent_pid,
        control_fd,
        terminate_grace_period,
        kill_timeout,
        command,
    )


def _reap_exited_descendants() -> None:
    """Reap adopted descendants without waiting for a still-running process."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _process_children(pid: int) -> tuple[int, ...]:
    """Return direct Linux children for one live process."""
    path = f"/proc/{pid}/task/{pid}/children"
    try:
        with open(path, encoding="ascii") as children_file:
            payload = children_file.read().strip()
    except (FileNotFoundError, OSError):
        return ()
    if not payload:
        return ()
    try:
        return tuple(int(value) for value in payload.split())
    except ValueError:
        return ()


def _process_group_and_state(pid: int) -> tuple[int, str] | None:
    """Read the process group and state from one Linux procfs record."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat_file:
            fields = stat_file.read().rsplit(")", 1)[1].split()
        return int(fields[2]), fields[0]
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None


def _owned_descendant_pids() -> tuple[int, ...]:
    """Return live same-group descendants adopted by this subreaper."""
    process_group = os.getpgrp()
    pending = list(_process_children(os.getpid()))
    visited: set[int] = set()
    owned: list[int] = []
    while pending:
        pid = pending.pop()
        if pid in visited:
            continue
        visited.add(pid)
        pending.extend(_process_children(pid))
        process_state = _process_group_and_state(pid)
        if process_state is None:
            continue
        group, state = process_state
        if group == process_group and state != "Z":
            owned.append(pid)
    return tuple(sorted(owned))


def _wait_for_descendants(timeout: float) -> tuple[int, ...]:
    """Wait synchronously for adopted same-group descendants to disappear."""
    deadline = time.monotonic() + timeout
    while True:
        _reap_exited_descendants()
        remaining = _owned_descendant_pids()
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(_POLL_INTERVAL)


def _cleanup_lingering_descendants(
    terminate_grace_period: float,
    kill_timeout: float,
) -> None:
    """Remove same-group descendants before the safety supervisor exits."""
    remaining = _owned_descendant_pids()
    if not remaining:
        return

    # SIGTERM can target the complete group because this supervisor holds it.
    os.killpg(os.getpgrp(), signal.SIGTERM)
    remaining = _wait_for_descendants(terminate_grace_period)
    if not remaining:
        return

    # SIGKILL cannot target the group without killing the supervisor before it
    # proves cleanup. Kill known descendants, then rescan for fork races.
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
    if _wait_for_descendants(kill_timeout):
        _kill_owned_group()


def _mirror_returncode(returncode: int) -> NoReturn:
    """Exit with the command status while retaining signal return semantics."""
    if returncode < 0:
        child_signal = -returncode
        # SIGKILL and SIGSTOP cannot be caught or reset. Sending either signal
        # directly still preserves asyncio's negative return-code convention.
        if child_signal not in {signal.SIGKILL, signal.SIGSTOP}:
            signal.signal(child_signal, signal.SIG_DFL)
        os.kill(os.getpid(), child_signal)
        os._exit(128 + child_signal)
    raise SystemExit(returncode)


def main(argv: Sequence[str] | None = None) -> NoReturn:
    """Supervise one command until completion or owner death."""
    arguments = sys.argv if argv is None else argv
    (
        parent_pid,
        control_fd,
        terminate_grace_period,
        kill_timeout,
        command,
    ) = _parse_arguments(arguments)
    child: subprocess.Popen[bytes] | None = None
    try:
        # Install the handler before asking the kernel for the signal so there is
        # no default-action window after PR_SET_PDEATHSIG becomes active.
        signal.signal(_PARENT_DEATH_SIGNAL, _handle_parent_death)
        signal.signal(signal.SIGTERM, _hold_group_termination)

        from pyprctl import set_child_subreaper, set_pdeathsig

        set_pdeathsig(_PARENT_DEATH_SIGNAL)
        set_child_subreaper(True)
        if os.getppid() != parent_pid:
            _kill_owned_group()

        # The supervisor is already the session/group leader. The real command
        # inherits that group and the public stdio endpoints, but not control_fd.
        child = subprocess.Popen(command, close_fds=True)
        try:
            _write_handshake(
                control_fd,
                {
                    "ok": True,
                    "pid": child.pid,
                    "process_group": os.getpgrp(),
                },
            )
        except BaseException:
            _kill_owned_group()
        finally:
            os.close(control_fd)

        while True:
            try:
                returncode = child.wait()
                break
            except InterruptedError:
                continue
        _cleanup_lingering_descendants(
            terminate_grace_period,
            kill_timeout,
        )
        _mirror_returncode(returncode)
    except Exception as error:
        if child is not None:
            _kill_owned_group()
        try:
            _write_handshake(
                control_fd,
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
            )
        except (BrokenPipeError, OSError):
            pass
        try:
            os.close(control_fd)
        except OSError:
            pass
        raise SystemExit(127) from error


if __name__ == "__main__":
    main()
