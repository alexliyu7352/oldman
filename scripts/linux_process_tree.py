"""Linux-only ownership and cleanup for gate-launched process trees."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37


class ProcessTreeError(RuntimeError):
    """Raised when a gate cannot prove complete process-tree cleanup."""


def linux_process_table() -> dict[int, tuple[int, int, int, str]]:
    """Return PID -> (PPID, process group, start time, state) from procfs."""
    proc = Path("/proc")
    if sys.platform != "linux" or not proc.is_dir():
        raise ProcessTreeError("process-tree verification requires Linux procfs")
    processes: dict[int, tuple[int, int, int, str]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            pid = int(entry.name)
            raw = (entry / "stat").read_text(encoding="utf-8")
            fields = raw[raw.rfind(")") + 2 :].split()
            processes[pid] = (int(fields[1]), int(fields[2]), int(fields[19]), fields[0])
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError, IndexError):
            continue
    return processes


@contextmanager
def child_subreaper() -> Iterator[tuple[int, frozenset[tuple[int, int]]]]:
    """Adopt descendants that escape their original process group/session."""
    if sys.platform != "linux":  # pragma: no cover - release scope is Linux
        raise ProcessTreeError("process-tree verification requires Linux")
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
        raise ProcessTreeError(f"cannot read child-subreaper state: errno={ctypes.get_errno()}")
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise ProcessTreeError(f"cannot enable child-subreaper state: errno={ctypes.get_errno()}")
    parent_pid = os.getpid()
    table = linux_process_table()
    ignored = frozenset((pid, record[2]) for pid, record in table.items() if record[0] == parent_pid)
    try:
        yield parent_pid, ignored
    finally:
        if libc.prctl(PR_SET_CHILD_SUBREAPER, previous.value, 0, 0, 0) != 0:
            raise ProcessTreeError(f"cannot restore child-subreaper state: errno={ctypes.get_errno()}")


@dataclass
class ProcessTreeTracker:
    """Track one leader plus descendants, including adopted new-session children."""

    leader_pid: int
    adopted_parent: int
    ignored_adoptees: frozenset[tuple[int, int]]
    owned: dict[int, tuple[int, int]] = field(default_factory=dict)

    def remember(self) -> dict[int, tuple[int, int, int, str]]:
        table = linux_process_table()
        roots: set[int] = set()
        leader = table.get(self.leader_pid)
        identity = self.owned.get(self.leader_pid)
        if leader is not None and (identity is None or identity[0] == leader[2]):
            roots.add(self.leader_pid)
        roots.update(
            pid
            for pid, (start_time, _process_group) in self.owned.items()
            if (record := table.get(pid)) is not None and record[2] == start_time
        )
        roots.update(
            pid
            for pid, record in table.items()
            if record[0] == self.adopted_parent and (pid, record[2]) not in self.ignored_adoptees
        )
        discovered = set(roots)
        while True:
            children = {pid for pid, record in table.items() if record[0] in discovered}
            expanded = discovered | children
            if expanded == discovered:
                break
            discovered = expanded
        for pid in discovered:
            record = table.get(pid)
            if record is not None:
                self.owned.setdefault(pid, (record[2], record[1]))
        return table

    def live(self, table: Mapping[int, tuple[int, int, int, str]] | None = None) -> dict[int, tuple[int, int, int, str]]:
        current = linux_process_table() if table is None else table
        return {
            pid: record
            for pid, (start_time, _process_group) in self.owned.items()
            if (record := current.get(pid)) is not None and record[2] == start_time
        }

    def reap(self) -> None:
        for pid in self.owned:
            if pid == self.leader_pid:
                continue
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                continue

    def wait_for_exit(self, process: subprocess.Popen[Any], timeout: float) -> list[int]:
        deadline = time.monotonic() + timeout
        while True:
            process.poll()
            self.reap()
            self.remember()
            self.reap()
            survivors = self.live()
            if not survivors:
                return []
            if time.monotonic() >= deadline:
                return sorted(survivors)
            time.sleep(0.05)

    def signal_leader(self, signum: int, *, require_live_leader: bool = False) -> bool:
        """Signal only the live leader and prove delivery to its recorded identity."""
        table = self.remember()
        live = self.live(table)
        leader_signal_delivered = False
        leader = live.get(self.leader_pid)
        if leader is not None and leader[3] != "Z":
            try:
                os.kill(self.leader_pid, signum)
            except ProcessLookupError:
                pass
            else:
                leader_signal_delivered = True
        if require_live_leader and not leader_signal_delivered:
            raise ProcessTreeError("process leader exited before the gate delivered its shutdown signal")
        return leader_signal_delivered

    def wait_for_leader_state(self, expected: frozenset[str], timeout: float) -> bool:
        """Wait until the recorded leader identity enters one of the requested procfs states."""
        deadline = time.monotonic() + timeout
        while True:
            table = self.remember()
            leader = self.live(table).get(self.leader_pid)
            if leader is not None and leader[3] in expected:
                return True
            if leader is None or time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def signal(self, signum: int, *, require_live_leader: bool = False) -> bool:
        """Signal all live identities and report whether the leader accepted the signal."""
        leader_signal_delivered = self.signal_leader(signum, require_live_leader=require_live_leader)
        live = self.live()

        own_group = os.getpgrp()
        groups = {
            record[1]
            for pid, record in live.items()
            if pid != self.leader_pid and record[3] != "Z" and record[1] > 1 and record[1] != own_group
        }
        for process_group in sorted(groups, key=lambda value: value == self.leader_pid):
            try:
                os.killpg(process_group, signum)
            except ProcessLookupError:
                pass
        for pid, record in live.items():
            if pid == self.leader_pid or record[3] == "Z":
                continue
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass
        return leader_signal_delivered

    def terminate(
        self,
        process: subprocess.Popen[Any],
        *,
        require_live_leader: bool = True,
        term_timeout: float = 10.0,
        kill_timeout: float = 5.0,
    ) -> None:
        """Terminate, reap, and prove removal of the complete owned process tree."""
        leader_signalled = self.signal_leader(signal.SIGTERM, require_live_leader=require_live_leader)
        survivors = self.wait_for_exit(process, term_timeout) if leader_signalled else sorted(self.live())
        if survivors:
            self.signal(signal.SIGTERM)
            survivors = self.wait_for_exit(process, kill_timeout)
        if survivors:
            self.signal(signal.SIGKILL)
            survivors = self.wait_for_exit(process, kill_timeout)
        if survivors:
            raise ProcessTreeError(f"owned process tree survived SIGKILL: {survivors}")
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired as exc:
            raise ProcessTreeError(f"cannot reap process leader {self.leader_pid}") from exc


@contextmanager
def tracked_process_tree(process: subprocess.Popen[Any]) -> Iterator[ProcessTreeTracker]:
    """Create a subreaper-backed tracker for an already launched leader.

    Callers should prefer ``tracked_popen`` so subreaper activation precedes launch.
    """
    with child_subreaper() as (parent, ignored):
        tracker = ProcessTreeTracker(process.pid, parent, ignored)
        tracker.remember()
        yield tracker


@contextmanager
def tracked_popen(*args: Any, **kwargs: Any) -> Iterator[tuple[subprocess.Popen[Any], ProcessTreeTracker]]:
    """Launch one process after enabling subreaping and yield it with its tracker."""
    with child_subreaper() as (parent, ignored):
        process = subprocess.Popen(*args, **kwargs)
        tracker = ProcessTreeTracker(process.pid, parent, ignored)
        tracker.remember()
        yield process, tracker
