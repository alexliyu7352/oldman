"""Main-process rollover coordination for direct multiprocess log writers."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

from oldman.logging.handlers import AtomicAppendFileHandler, RotationPolicy

type _RotatingHelper = RotatingFileHandler | TimedRotatingFileHandler


@dataclass(frozen=True, slots=True)
class _RotationTarget:
    """Identify one normalized activity path and its single rollover policy."""

    path: str
    policy: RotationPolicy


def _iter_loggers() -> tuple[logging.Logger, ...]:
    """Return root and every materialized named logger without placeholders."""
    named = (
        entry
        for entry in logging.root.manager.loggerDict.values()
        if isinstance(entry, logging.Logger)
    )
    return (logging.getLogger(), *named)


def _emergency_write(error: BaseException) -> None:
    """Report coordinator failures without recursively entering logging."""
    payload = f"oldman log rotation failed: {error!r}\n".encode(
        "utf-8",
        "backslashreplace",
    )
    try:
        os.write(2, payload)
    except OSError:
        return


class RotationCoordinator:
    """Poll Oldman-managed handlers and rotate their paths only in the owner PID."""

    def __init__(self, runtime_id: str, *, check_interval: float = 1.0) -> None:
        """Bind one runtime without starting a thread or opening another file fd."""
        if check_interval <= 0:
            raise ValueError("rotation check_interval must be greater than zero")
        self.runtime_id = runtime_id
        self.owner_pid = os.getpid()
        self.check_interval = check_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._operation_lock = threading.Lock()
        self._helpers: dict[
            str,
            tuple[RotationPolicy, _RotatingHelper],
        ] = {}

    @property
    def is_alive(self) -> bool:
        """Return whether this process owns a currently running coordinator thread."""
        return bool(
            os.getpid() == self.owner_pid
            and self._thread is not None
            and self._thread.is_alive()
        )

    def _targets(self) -> tuple[_RotationTarget, ...]:
        """Discover and deduplicate current runtime handlers by absolute real path."""
        policies: dict[str, RotationPolicy] = {}
        seen_handlers: set[int] = set()
        for configured_logger in _iter_loggers():
            for handler in configured_logger.handlers:
                identity = id(handler)
                if identity in seen_handlers:
                    continue
                seen_handlers.add(identity)
                if not isinstance(handler, AtomicAppendFileHandler):
                    continue
                if getattr(handler, "_oldman_runtime_id", None) != self.runtime_id:
                    continue
                policy = handler.rotation_policy
                if policy is None:
                    continue
                path = os.path.realpath(handler.baseFilename)
                existing = policies.get(path)
                if existing is not None and existing != policy:
                    raise ValueError(
                        f"conflicting rotation policies for activity path {path!r}"
                    )
                policies[path] = policy
        return tuple(
            _RotationTarget(path=path, policy=policy)
            for path, policy in sorted(policies.items())
        )

    @staticmethod
    def _new_helper(target: _RotationTarget) -> _RotatingHelper:
        """Create one delayed stdlib helper that never handles a LogRecord."""
        policy = target.policy
        if policy.kind == "time":
            return TimedRotatingFileHandler(
                target.path,
                when=policy.when or "D",
                interval=policy.interval,
                backupCount=policy.backup_count,
                encoding="utf-8",
                delay=True,
                utc=policy.utc,
                atTime=policy.at_time,
            )
        if policy.kind == "size":
            return RotatingFileHandler(
                target.path,
                maxBytes=policy.max_bytes,
                backupCount=policy.backup_count,
                encoding="utf-8",
                delay=True,
            )
        raise ValueError(f"unsupported rotation policy kind: {policy.kind!r}")

    def _helper_for(self, target: _RotationTarget) -> _RotatingHelper:
        """Reuse a helper while replacing stale state after policy changes."""
        existing = self._helpers.get(target.path)
        if existing is not None and existing[0] == target.policy:
            return existing[1]
        if existing is not None:
            existing[1].close()
        helper = self._new_helper(target)
        self._helpers[target.path] = (target.policy, helper)
        return helper

    @staticmethod
    def _is_due(
        target: _RotationTarget,
        helper: _RotatingHelper,
        now: float,
    ) -> bool:
        """Check one path without formatting a synthetic record."""
        try:
            stat_result = os.stat(target.path)
        except FileNotFoundError:
            return False
        if target.policy.kind == "size":
            return target.policy.max_bytes > 0 and stat_result.st_size >= target.policy.max_bytes
        timed = helper
        if not isinstance(timed, TimedRotatingFileHandler):
            raise TypeError("time policy did not create a timed rotating helper")
        return now >= timed.rolloverAt

    def _discard_stale_helpers(self, active_paths: set[str]) -> None:
        """Close helper objects for handlers removed from the main logger registry."""
        for path in tuple(self._helpers):
            if path in active_paths:
                continue
            _, helper = self._helpers.pop(path)
            helper.close()

    def run_once(self, now: float | None = None) -> None:
        """Perform one owner-only discovery and rollover pass synchronously."""
        if os.getpid() != self.owner_pid:
            return
        current_time = time.time() if now is None else now
        with self._operation_lock:
            targets = self._targets()
            self._discard_stale_helpers({target.path for target in targets})
            for target in targets:
                try:
                    helper = self._helper_for(target)
                    if self._is_due(target, helper, current_time):
                        helper.doRollover()
                except Exception as error:
                    _emergency_write(error)

    def _run(self) -> None:
        """Wait interruptibly between passes until the owner closes the runtime."""
        while not self._stop.wait(self.check_interval):
            try:
                self.run_once()
            except Exception as error:
                _emergency_write(error)

    def start(self) -> None:
        """Start exactly one owner thread after validating current path policies."""
        if os.getpid() != self.owner_pid or self.is_alive or self._stop.is_set():
            return
        if not self._targets():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="oldman-log-rotation",
            daemon=True,
        )
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        """Stop the owner thread and close delayed helper handlers within a bound."""
        if os.getpid() != self.owner_pid:
            return
        if timeout < 0:
            raise ValueError("rotation close timeout cannot be negative")
        deadline = time.monotonic() + timeout
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, deadline - time.monotonic()))
        acquired = self._operation_lock.acquire(
            timeout=max(0.0, deadline - time.monotonic())
        )
        if not acquired:
            _emergency_write(TimeoutError("log rotation coordinator did not stop in time"))
            return
        try:
            for _, helper in self._helpers.values():
                helper.close()
            self._helpers.clear()
        finally:
            self._operation_lock.release()
        if thread is None or not thread.is_alive():
            self._thread = None


__all__ = ["RotationCoordinator"]
