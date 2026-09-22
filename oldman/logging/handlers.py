"""Linux direct-file handlers and rollover metadata for Oldman logging."""

from __future__ import annotations

import datetime
import logging
import os
import time
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RotationPolicy:
    """Describe rollover metadata without giving a writer rollover ownership."""

    kind: Literal["time", "size"]
    when: str | None = None
    interval: int = 1
    backup_count: int = 0
    max_bytes: int = 0
    utc: bool = False
    at_time: datetime.time | None = None

    @classmethod
    def time(
        cls,
        when: str,
        interval: int,
        backup_count: int,
        *,
        utc: bool = False,
        at_time: datetime.time | None = None,
    ) -> RotationPolicy:
        """Build a time-based policy using stdlib rotating-handler names."""
        return cls(
            kind="time",
            when=when,
            interval=interval,
            backup_count=backup_count,
            utc=utc,
            at_time=at_time,
        )

    @classmethod
    def size(cls, max_bytes: int, backup_count: int) -> RotationPolicy:
        """Build a size-based policy for coordinator-owned numbered backups."""
        return cls(
            kind="size",
            backup_count=backup_count,
            max_bytes=max_bytes,
        )


class AtomicAppendFileHandler(logging.Handler):
    """Append formatted records through a Linux ``O_APPEND`` file descriptor."""

    terminator = "\n"

    def __init__(
        self,
        filename: str | os.PathLike[str],
        mode: str = "a",
        encoding: str = "utf-8",
        errors: str | None = None,
        *,
        when: str | None = None,
        interval: int = 1,
        backupCount: int = 0,
        maxBytes: int = 0,
        utc: bool = False,
        atTime: datetime.time | None = None,
        reopen_check_interval: float = 1.0,
    ) -> None:
        """Open lazily and retain rollover settings only as coordinator metadata."""
        super().__init__()
        if mode != "a":
            raise ValueError("AtomicAppendFileHandler only supports append mode")
        if interval <= 0:
            raise ValueError("rotation interval must be greater than zero")
        if backupCount < 0:
            raise ValueError("backupCount cannot be negative")
        if maxBytes < 0:
            raise ValueError("maxBytes cannot be negative")
        if when is not None and maxBytes:
            raise ValueError("time and size rotation cannot be enabled together")
        if reopen_check_interval < 0:
            raise ValueError("reopen_check_interval must be greater than or equal to 0")

        self.baseFilename = os.path.abspath(os.fspath(filename))
        self.mode = mode
        self.encoding = encoding or "utf-8"
        self.errors = errors or "backslashreplace"
        self.rotation_policy = (
            RotationPolicy.time(
                when,
                interval,
                backupCount,
                utc=utc,
                at_time=atTime,
            )
            if when is not None
            else RotationPolicy.size(maxBytes, backupCount)
            if maxBytes
            else None
        )
        self._fd: int | None = None
        self._device_inode: tuple[int, int] | None = None
        self._reopen_check_interval = float(reopen_check_interval)
        self._next_reopen_check_at = 0.0

    def _open_fd(self) -> None:
        """Atomically replace this handler's descriptor with the active path."""
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
        new_fd = os.open(self.baseFilename, flags, 0o666)
        try:
            stat_result = os.fstat(new_fd)
            next_reopen_check_at = time.monotonic() + self._reopen_check_interval
        except BaseException:
            os.close(new_fd)
            raise
        old_fd = self._fd
        self._fd = new_fd
        self._device_inode = (stat_result.st_dev, stat_result.st_ino)
        self._next_reopen_check_at = next_reopen_check_at
        if old_fd is not None:
            os.close(old_fd)

    def _reopen_if_needed(self) -> None:
        """Follow a replaced activity path without participating in rollover."""
        if self._fd is None:
            self._open_fd()
            return
        now = time.monotonic()
        if now < self._next_reopen_check_at:
            return
        self._next_reopen_check_at = now + self._reopen_check_interval
        try:
            stat_result = os.stat(self.baseFilename)
        except FileNotFoundError:
            self._open_fd()
            return
        if (stat_result.st_dev, stat_result.st_ino) != self._device_inode:
            self._open_fd()

    def _write_all(self, payload: bytes) -> None:
        """Write a whole record once, retrying only a rare partial kernel write."""
        if self._fd is None:
            raise RuntimeError("log file descriptor is not open")
        written = os.write(self._fd, payload)
        if written <= 0:
            raise OSError("log file write made no progress")
        if written == len(payload):
            return
        remaining = memoryview(payload)[written:]
        while remaining:
            written = os.write(self._fd, remaining)
            if written <= 0:
                raise OSError("log file write made no progress")
            remaining = remaining[written:]

    def emit(self, record: logging.LogRecord) -> None:
        """Format, encode and append one record without a Python text buffer."""
        try:
            self._reopen_if_needed()
            rendered = f"{self.format(record)}{self.terminator}"
            self._write_all(rendered.encode(self.encoding, self.errors))
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        """Expose the logging handler contract; writes already enter kernel buffers."""
        return None

    def close(self) -> None:
        """Close only the descriptor owned by this process and handler instance."""
        self.acquire()
        try:
            fd = self._fd
            self._fd = None
            self._device_inode = None
            self._next_reopen_check_at = 0.0
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                super().close()
        finally:
            self.release()


__all__ = [
    "AtomicAppendFileHandler",
    "RotationPolicy",
]
