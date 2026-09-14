"""Linux process-group ownership shared by the two dedicated Taskiq services."""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from oldman.processes.subprocess import _live_process_group_pids


def _process_identity(pid: int) -> tuple[int, int] | None:
    """Read PGID and kernel start ticks; an unreaped zombie is not a live owner."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return int(fields[2]), int(fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


@dataclass(frozen=True, slots=True)
class GroupIdentity:
    """Private runtime record, not a new user setting or a replacement PID format."""

    pid: int
    pgid: int
    start_ticks: int
    boot_id: str

    @classmethod
    def current(cls) -> GroupIdentity:
        """Capture identity only after the dedicated service has its own group."""
        pid = os.getpid()
        current = _process_identity(pid)
        if current is None or current[0] != pid:
            raise RuntimeError("Taskiq service must own a process group before recording its identity")
        return cls(pid, current[0], current[1], Path("/proc/sys/kernel/random/boot_id").read_text().strip())

    def to_json(self) -> str:
        """Serialize the small ownership record without configuration or secrets."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> GroupIdentity:
        """Reject malformed or broad targets before any process signal is sent."""
        record = cls(**json.loads(value))
        if any(type(value) is not int or value <= 1 for value in (record.pid, record.pgid, record.start_ticks)):
            raise ValueError("Invalid Taskiq process identity")
        if record.pid != record.pgid or not isinstance(record.boot_id, str):
            raise ValueError("Taskiq process identity does not name a dedicated service group")
        return record


def _set_foreground(terminal: int, group: int) -> None:
    """Changing a background group's terminal ownership must not suspend it."""
    previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        os.tcsetpgrp(terminal, group)
    finally:
        signal.signal(signal.SIGTTOU, previous)


@contextmanager
def service_process_group() -> Iterator[GroupIdentity]:
    """Keep the controlling terminal; only create a group when the shell did not."""
    previous_group = os.getpgrp()
    terminal: int | None = None
    restore_foreground: int | None = None
    try:
        try:
            terminal = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        except OSError:
            pass  # A non-interactive service has no controlling terminal.
        if previous_group != os.getpid():
            was_foreground = terminal is not None and os.tcgetpgrp(terminal) == previous_group
            os.setpgid(0, 0)
            if was_foreground and terminal is not None:
                restore_foreground = previous_group
                _set_foreground(terminal, os.getpgrp())
        yield GroupIdentity.current()
    finally:
        if terminal is not None:
            try:
                if restore_foreground is not None and os.tcgetpgrp(terminal) == os.getpgrp():
                    _set_foreground(terminal, restore_foreground)
            finally:
                os.close(terminal)


def stop_process_group(identity: GroupIdentity, timeout: float, *, request_stop: bool = True) -> bool:
    """Stop the manager, wait for the whole verified group, then kill if necessary.

    Once stop has validated a live leader, original surviving members can anchor
    the same group if the leader exits early. A pre-existing orphaned group has
    no such evidence: never infer ownership from a stale PID file alone.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Taskiq stop timeout must be a finite positive number")
    if identity.pid != identity.pgid or identity.pgid <= 1 or identity.pgid == os.getpgrp():
        raise RuntimeError("Refusing to stop a group that is not an independent Taskiq service")
    if identity.boot_id != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise RuntimeError("Taskiq PID record belongs to a different system boot")
    members = _live_process_group_pids(identity.pgid)
    if not members:
        return False
    if _process_identity(identity.pid) != (identity.pgid, identity.start_ticks):
        raise RuntimeError("Taskiq service identity is stale or its leader is already gone; refusing to guess ownership")
    anchors = {pid: _process_identity(pid) for pid in members}
    deadline = time.monotonic() + timeout
    if request_stop:
        try:
            os.kill(identity.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    while _live_process_group_pids(identity.pgid):
        if not any(value is not None and _process_identity(pid) == value for pid, value in anchors.items()):
            # Members may finish between the group scan and identity reads.
            # An empty group is successful exit, not an ownership change.
            if not _live_process_group_pids(identity.pgid):
                return False
            raise RuntimeError("Taskiq group ownership changed during stop; refusing to signal it")
        if time.monotonic() >= deadline:
            try:
                os.killpg(identity.pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            # SIGKILL delivery is asynchronous; verify live members, not zombies.
            verify_deadline = time.monotonic() + 3
            while _live_process_group_pids(identity.pgid):
                if time.monotonic() >= verify_deadline:
                    raise RuntimeError(f"Taskiq group {identity.pgid} still has live processes after SIGKILL")
                time.sleep(0.05)
            return True
        time.sleep(0.1)
    return False


def spawn_stopper(identity: GroupIdentity, timeout: float) -> subprocess.Popen[bytes]:
    """Ctrl+C and startup failure use the same bounded stop, outside the target group."""
    return subprocess.Popen(
        [sys.executable, "-m", "oldman.runtime._taskiq_process", identity.to_json(), str(timeout)],
        start_new_session=True,
    )


if __name__ == "__main__":
    # Private child entry only; users still have one service-level stop command.
    try:
        # This helper exists only after the owner has begun shutdown. Sending
        # another SIGTERM can hit Python finalization and replace its exit code.
        forced = stop_process_group(GroupIdentity.from_json(sys.argv[1]), float(sys.argv[2]), request_stop=False)
        if forced:
            print("Taskiq stop deadline reached; the verified service group was terminated.", file=sys.stderr)
    except Exception as error:
        print(f"Taskiq service stop failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
