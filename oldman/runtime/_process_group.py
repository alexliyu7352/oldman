"""Linux process-group ownership of a running service: its identity record and its bounded stop."""

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

from oldman.processes.subprocess import _finished_exiting, _group_has_live_members, _live_process_group_pids


def _process_identity(pid: int) -> tuple[int, int] | None:
    """Read PGID and kernel start ticks; a process that has finished exiting is not a live owner."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        if _finished_exiting(pid, fields[0]):
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
            raise RuntimeError("The service must own a process group before recording its identity")
        return cls(pid, current[0], current[1], Path("/proc/sys/kernel/random/boot_id").read_text().strip())

    def to_json(self) -> str:
        """Serialize the small ownership record without configuration or secrets."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> GroupIdentity:
        """Reject malformed or broad targets before any process signal is sent.

        Process and group 1 stay refused: killpg(1, sig) is kill(-1, sig), every process the caller
        may signal. A service that is its container's PID 1 (an exec-form entrypoint) therefore
        cannot be stopped with its stop command from inside the container; stop reports it and
        signals nothing. Accepted: a container is stopped from outside (docker stop sends PID 1 the
        SIGTERM the service handles), so stop and restart inside it are not the way it runs.
        """
        record = cls(**json.loads(value))
        if any(type(value) is not int or value <= 1 for value in (record.pid, record.pgid, record.start_ticks)):
            raise ValueError("Invalid service process identity")
        if record.pid != record.pgid or not isinstance(record.boot_id, str):
            raise ValueError("The process identity does not name a dedicated service group")
        return record


def group_members(identity: GroupIdentity) -> tuple[int, ...]:
    """The live processes still in the group `identity` records, this boot; empty once it is gone.

    A group can outlive its leader (Sanic workers whose primary was killed). The kernel does not
    reuse a PID while it still names a live process group, so live members under the recorded group
    id belong to that run; a leader PID now held by another process means the group is gone.
    """
    if identity.boot_id != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        return ()
    leader = _process_identity(identity.pid)
    if leader is not None and leader != (identity.pgid, identity.start_ticks):
        return ()
    return _live_process_group_pids(identity.pgid)


def leader_is_alive(identity: GroupIdentity) -> bool:
    """Whether the group's recorded leader still runs (the same process, not a reused PID)."""
    return _process_identity(identity.pid) == (identity.pgid, identity.start_ticks)


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
            # Take the foreground only when stdin is the terminal too: then a foreground script started
            # the service directly, and Ctrl-C must reach it. A script that puts the service in the
            # background with `&` gives it /dev/null for stdin (bash does), and it must leave the
            # foreground to the script, or Ctrl-C would reach only the service.
            was_foreground = terminal is not None and os.isatty(0) and os.tcgetpgrp(terminal) == previous_group
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
            except OSError:
                pass  # The terminal hung up (EIO) or the group to return it to is gone: there is no foreground to give back.
            finally:
                os.close(terminal)


def stop_process_group(identity: GroupIdentity, timeout: float, *, request_stop: bool = True) -> bool:
    """Stop the manager, wait for the whole verified group, then kill if necessary.

    Once stop has validated a live leader, original surviving members can anchor
    the same group if the leader exits early, and members the run starts while it
    stops are stopped with it (see the loop). A pre-existing orphaned group has
    no such evidence: never infer ownership from a stale PID file alone.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("The stop timeout must be a finite positive number")
    if identity.pid != identity.pgid or identity.pgid <= 1 or identity.pgid == os.getpgrp():
        raise RuntimeError("Refusing to stop a group that is not an independent service")
    if identity.boot_id != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise RuntimeError("The PID record belongs to a different system boot")
    members = _live_process_group_pids(identity.pgid)
    if not members:
        return False
    if _process_identity(identity.pid) != (identity.pgid, identity.start_ticks):
        raise RuntimeError("The service identity is stale or its leader is already gone; refusing to guess ownership")
    anchors = {pid: _process_identity(pid) for pid in members}
    known = set(members)
    deadline = time.monotonic() + timeout
    if request_stop:
        try:
            os.kill(identity.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    while _group_has_live_members(identity.pgid, known):
        if not any(value is not None and _process_identity(pid) == value for pid, value in anchors.items()):
            # Members may finish between the group scan and identity reads.
            # An empty group is successful exit, not an ownership change.
            if not _group_has_live_members(identity.pgid, known):
                return False
            # Every process verified so far has exited, yet the group has members: ones the run
            # started while it stopped (a child forked by a stop hook). The previous check, one poll
            # ago, saw a verified member alive, so the group has had members throughout. A group id is
            # not reused while the group has members, and process ids are handed out cyclically, so
            # its number cannot have gone round to another program within one poll: they are the
            # run's, and are stopped with it. The leader that would have ended them is gone, so they
            # are sent SIGTERM now, whatever request_stop says (it concerns the leader's own exit
            # code); the deadline stands. Accepted: process ids wrapping round within one poll would
            # make this signal another program's group.
            anchors = {pid: _process_identity(pid) for pid in known}
            try:
                os.killpg(identity.pgid, signal.SIGTERM)
            except ProcessLookupError:
                return False
        if time.monotonic() >= deadline:
            try:
                os.killpg(identity.pgid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            # SIGKILL delivery is asynchronous; wait until every member, every thread of it included, has
            # finished exiting, so the PID file lock and the port are free when stop returns.
            verify_deadline = time.monotonic() + 3
            while _group_has_live_members(identity.pgid, known):
                if time.monotonic() >= verify_deadline:
                    raise RuntimeError(f"Service group {identity.pgid} still has live processes after SIGKILL")
                time.sleep(0.05)
            return True
        time.sleep(0.1)
    return False


def spawn_stopper(identity: GroupIdentity, timeout: float) -> subprocess.Popen[bytes]:
    """Ctrl+C and startup failure use the same bounded stop, outside the target group."""
    return subprocess.Popen(
        [sys.executable, "-m", "oldman.runtime._process_group", identity.to_json(), str(timeout)],
        start_new_session=True,
    )


if __name__ == "__main__":
    # Private child entry only; users still have one service-level stop command.
    try:
        # This helper exists only after the owner has begun shutdown. Sending
        # another SIGTERM can hit Python finalization and replace its exit code.
        forced = stop_process_group(GroupIdentity.from_json(sys.argv[1]), float(sys.argv[2]), request_stop=False)
        if forced:
            print("Stop deadline reached; the verified service group was terminated.", file=sys.stderr)
    except Exception as error:
        print(f"Service stop failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
