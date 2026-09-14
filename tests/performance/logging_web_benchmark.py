"""Benchmark real Sanic 1/2/4-worker logging against a timed-file reference.

Run the fixed Linux release gate with no arguments::

    .venv/bin/python -m tests.performance.logging_web_benchmark

``--smoke`` is the only adjustable mode.  Its smaller counts exercise startup,
both handler variants, exact file counts, failure exits, and bounded cleanup
without changing any release constant below.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import math
import os
import platform
import re
import resource
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import aiohttp
from aiohttp.client import IDEMPOTENT_METHODS

type HandlerVariant = Literal["current", "timed_reference", "no_logging"]
type InjectFault = Literal[
    "none",
    "skip_database",
    "after_first_run_exception",
]
type JsonObject = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "logging_web_performance_service.py"

# These are the immutable no-argument release-gate values from the accepted design.
RELEASE_WORKERS = (1, 2, 4)
RELEASE_ROUNDS = 6
RELEASE_WARMUP_REQUESTS = 2_000
RELEASE_MEASURED_REQUESTS = 20_000
RELEASE_CONCURRENCY = 100
RELEASE_NESTED_ASYNC_RECORDS = 1_000
RELEASE_NESTED_ASYNC_RUNS = 3
RELEASE_NESTED_SUBPROCESS_BYTES = 1_048_576
MINIMUM_QPS_RATIO = 0.98
MAXIMUM_P99_RATIO = 1.05
MAXIMUM_CPU_RATIO = 1.05

# Smoke defaults stay deliberately small, and CLI overrides are rejected unless
# --smoke is present so they cannot silently weaken a release invocation.
SMOKE_ROUNDS = 1
SMOKE_WARMUP_REQUESTS = 20
SMOKE_MEASURED_REQUESTS = 100
SMOKE_CONCURRENCY = 10
SMOKE_NESTED_ASYNC_RECORDS = 20
SMOKE_NESTED_ASYNC_RUNS = 1
SMOKE_NESTED_SUBPROCESS_BYTES = 65_536

REFERENCE_ROLLOVER_AT = 2**63 - 1
FUTURE_ROTATION_WHEN = "S"
FUTURE_ROTATION_INTERVAL = 2**31 - 1
EXPECTED_RESPONSE_BYTES = 129
STARTUP_TIMEOUT_SECONDS = 30.0
PHASE_TIMEOUT_SECONDS = 180.0
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30.0
FORCE_SHUTDOWN_TIMEOUT_SECONDS = 5.0
PROCESS_GROUP_EXIT_TIMEOUT_SECONDS = 5.0
HTTP_REQUEST_TIMEOUT_SECONDS = 30.0
ANSI_ESCAPE = b"\x1b"
FILE_KINDS = ("main", "database", "access")
BENCHMARK_HTTP_METHOD = "POST"


class BenchmarkFailure(RuntimeError):
    """Signal a correctness, lifecycle, environment, or performance failure."""


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Hold either the immutable release contract or explicit smoke settings."""

    mode: Literal["release", "smoke"]
    workers: tuple[int, ...]
    rounds: int
    warmup_requests: int
    measured_requests: int
    concurrency: int
    inject_fault: InjectFault
    enforce_ratios: bool


def _aiohttp_retry_contract() -> JsonObject:
    """Prove the benchmark method is outside aiohttp's automatic retry set."""
    idempotent_methods = sorted(IDEMPOTENT_METHODS)
    get_retry_eligible = "GET" in IDEMPOTENT_METHODS
    benchmark_retry_eligible = BENCHMARK_HTTP_METHOD in IDEMPOTENT_METHODS
    return {
        "aiohttp_version": aiohttp.__version__,
        "benchmark_method": BENCHMARK_HTTP_METHOD,
        "idempotent_methods": idempotent_methods,
        "get_connection_retry_eligible": get_retry_eligible,
        "benchmark_connection_retry_eligible": benchmark_retry_eligible,
        "passed": (
            BENCHMARK_HTTP_METHOD == "POST"
            and get_retry_eligible
            and not benchmark_retry_eligible
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    """Build a CLI whose adjustable counts are legal only in smoke mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run one-worker diagnostics instead of the fixed release gate",
    )
    parser.add_argument("--warmup-requests", type=int)
    parser.add_argument("--measured-requests", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--rounds", type=int)
    parser.add_argument(
        "--inject-fault",
        choices=("none", "skip_database", "after_first_run_exception"),
        default="none",
        help="smoke-only exact-count failure contract",
    )
    return parser


def _positive(name: str, value: int) -> int:
    """Reject empty smoke phases and invalid task counts."""
    if value <= 0:
        raise BenchmarkFailure(f"{name} must be greater than zero, got {value}")
    return value


def _config_from_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> BenchmarkConfig:
    """Resolve CLI values while proving no release constant was overridden."""
    adjustable = (
        args.warmup_requests,
        args.measured_requests,
        args.concurrency,
        args.rounds,
    )
    if not args.smoke:
        if any(value is not None for value in adjustable) or args.inject_fault != "none":
            parser.error(
                "count overrides and --inject-fault require --smoke; "
                "the no-argument release contract is immutable"
            )
        return BenchmarkConfig(
            mode="release",
            workers=RELEASE_WORKERS,
            rounds=RELEASE_ROUNDS,
            warmup_requests=RELEASE_WARMUP_REQUESTS,
            measured_requests=RELEASE_MEASURED_REQUESTS,
            concurrency=RELEASE_CONCURRENCY,
            inject_fault="none",
            enforce_ratios=True,
        )

    warmup = _positive(
        "warmup_requests",
        args.warmup_requests or SMOKE_WARMUP_REQUESTS,
    )
    measured = _positive(
        "measured_requests",
        args.measured_requests or SMOKE_MEASURED_REQUESTS,
    )
    concurrency = _positive(
        "concurrency",
        args.concurrency or SMOKE_CONCURRENCY,
    )
    rounds = _positive("rounds", args.rounds or SMOKE_ROUNDS)
    return BenchmarkConfig(
        mode="smoke",
        workers=(1,),
        rounds=rounds,
        warmup_requests=warmup,
        measured_requests=measured,
        concurrency=concurrency,
        inject_fault=cast(InjectFault, args.inject_fault),
        enforce_ratios=False,
    )


def _reserve_port() -> int:
    """Reserve and release one loopback port for an isolated fixture process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_group_pids(process_group: int) -> list[int]:
    """List Linux PIDs in one dedicated fixture process group."""
    pids: list[int] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            stat = stat_path.read_text(encoding="utf-8")
            fields = stat.rsplit(")", 1)[1].split()
            group = int(fields[2])
        except (IndexError, OSError, ValueError):
            continue
        if group == process_group:
            pids.append(int(stat_path.parent.name))
    return sorted(pids)


def _wait_for_group_exit(process_group: int, timeout: float) -> list[int]:
    """Wait within a deadline and return any remaining group PIDs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = _process_group_pids(process_group)
        if not remaining:
            return []
        time.sleep(0.02)
    return _process_group_pids(process_group)


def _signal_process_group(process_group: int, signal_number: int) -> None:
    """Signal an existing fixture group while tolerating a concurrent exit."""
    try:
        os.killpg(process_group, signal_number)
    except ProcessLookupError:
        pass


def _structured_error(exc: BaseException) -> JsonObject:
    """Return JSON-safe error identity for retained diagnostic evidence."""
    return {
        "type": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "message": str(exc),
    }


def _parse_process_stat(pid: int, stat: str) -> JsonObject:
    """Parse identity and cumulative CPU fields from one Linux stat record."""
    try:
        suffix = stat.rsplit(")", 1)[1].split()
        state = suffix[0]
        ppid = int(suffix[1])
        process_group = int(suffix[2])
        user_time_ticks = int(suffix[11])
        system_time_ticks = int(suffix[12])
        start_time_ticks = int(suffix[19])
    except (IndexError, ValueError) as exc:
        raise BenchmarkFailure(f"invalid /proc/{pid}/stat record") from exc
    return {
        "pid": pid,
        "ppid": ppid,
        "process_group": process_group,
        "state": state,
        "user_time_ticks": user_time_ticks,
        "system_time_ticks": system_time_ticks,
        "start_time_ticks": start_time_ticks,
        "read_error": None,
    }


def _read_process_stat(pid: int) -> JsonObject:
    """Read one process identity while retaining structured races/errors."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return _parse_process_stat(pid, stat)
    except BaseException as exc:
        return {
            "pid": pid,
            "ppid": None,
            "process_group": None,
            "state": None,
            "user_time_ticks": None,
            "system_time_ticks": None,
            "start_time_ticks": None,
            "read_error": _structured_error(exc),
        }


def _process_group_cpu_snapshot(process_group: int) -> JsonObject:
    """Capture cumulative CPU ticks for every process in one stable group."""
    ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
    processes = [
        _read_process_stat(pid) for pid in _process_group_pids(process_group)
    ]
    errors: list[str] = []
    if not processes:
        errors.append(f"process group {process_group} has no processes")
    for process in processes:
        pid = process.get("pid")
        if process.get("read_error") is not None:
            errors.append(f"PID {pid} stat failed: {process['read_error']}")
        elif process.get("process_group") != process_group:
            errors.append(
                f"PID {pid} moved from process group {process_group}: {process}"
            )
    return {
        "process_group": process_group,
        "ticks_per_second": ticks_per_second,
        "processes": processes,
        "errors": errors,
        "passed": not errors,
    }


def _process_group_cpu_delta(
    before: JsonObject,
    after: JsonObject,
    *,
    request_count: int,
    elapsed_seconds: float,
) -> JsonObject:
    """Calculate server CPU only when the measured process identities are stable."""
    errors = [
        *(str(error) for error in before.get("errors", [])),
        *(str(error) for error in after.get("errors", [])),
    ]
    before_processes: dict[int, JsonObject] = {}
    after_processes: dict[int, JsonObject] = {}
    for label, snapshot, target in (
        ("before", before, before_processes),
        ("after", after, after_processes),
    ):
        for process in snapshot.get("processes", []):
            if not isinstance(process, dict):
                errors.append(f"{label} CPU snapshot contains a non-object process")
                continue
            pid = process.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool):
                errors.append(f"{label} CPU snapshot contains invalid PID {pid!r}")
                continue
            target[pid] = cast(JsonObject, process)
    if set(before_processes) != set(after_processes):
        errors.append(
            "measured process-group PID set changed: "
            f"before={sorted(before_processes)} after={sorted(after_processes)}"
        )
    ticks_per_second = before.get("ticks_per_second")
    if (
        not isinstance(ticks_per_second, int)
        or isinstance(ticks_per_second, bool)
        or ticks_per_second <= 0
        or after.get("ticks_per_second") != ticks_per_second
    ):
        errors.append(
            "invalid or changing clock tick rate: "
            f"before={ticks_per_second!r} after={after.get('ticks_per_second')!r}"
        )

    user_ticks = 0
    system_ticks = 0
    process_deltas: list[JsonObject] = []
    for pid in sorted(set(before_processes) & set(after_processes)):
        prior = before_processes[pid]
        current = after_processes[pid]
        if prior.get("start_time_ticks") != current.get("start_time_ticks"):
            errors.append(f"PID {pid} identity changed during measurement")
            continue
        try:
            process_user_ticks = int(current["user_time_ticks"]) - int(
                prior["user_time_ticks"]
            )
            process_system_ticks = int(current["system_time_ticks"]) - int(
                prior["system_time_ticks"]
            )
        except (KeyError, TypeError, ValueError):
            errors.append(f"PID {pid} has invalid CPU counters")
            continue
        if process_user_ticks < 0 or process_system_ticks < 0:
            errors.append(f"PID {pid} CPU counters moved backwards")
            continue
        user_ticks += process_user_ticks
        system_ticks += process_system_ticks
        process_deltas.append(
            {
                "pid": pid,
                "user_time_ticks": process_user_ticks,
                "system_time_ticks": process_system_ticks,
            }
        )

    valid_denominators = request_count > 0 and elapsed_seconds > 0
    if not valid_denominators:
        errors.append(
            f"invalid CPU denominators: requests={request_count} elapsed={elapsed_seconds}"
        )
    if not isinstance(ticks_per_second, int) or ticks_per_second <= 0:
        user_seconds = system_seconds = total_seconds = None
    else:
        user_seconds = user_ticks / ticks_per_second
        system_seconds = system_ticks / ticks_per_second
        total_seconds = user_seconds + system_seconds
    passed = not errors and total_seconds is not None and total_seconds > 0
    if total_seconds == 0 and not errors:
        errors.append("server CPU delta is zero")
        passed = False
    return {
        "before": before,
        "after": after,
        "process_deltas": process_deltas,
        "process_count": len(process_deltas),
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_request": (
            total_seconds / request_count
            if total_seconds is not None and request_count > 0
            else None
        ),
        "average_cores": (
            total_seconds / elapsed_seconds
            if total_seconds is not None and elapsed_seconds > 0
            else None
        ),
        "errors": errors,
        "passed": passed,
    }


def _self_cpu_snapshot() -> JsonObject:
    """Capture cumulative user and system CPU for the benchmark client process."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
    }


def _self_cpu_delta(
    before: JsonObject,
    after: JsonObject,
    *,
    request_count: int,
    elapsed_seconds: float,
) -> JsonObject:
    """Calculate client CPU separately so it cannot be mistaken for server cost."""
    user_seconds = float(after["user_seconds"]) - float(before["user_seconds"])
    system_seconds = float(after["system_seconds"]) - float(
        before["system_seconds"]
    )
    total_seconds = user_seconds + system_seconds
    errors: list[str] = []
    if user_seconds < 0 or system_seconds < 0:
        errors.append("client CPU counters moved backwards")
    if request_count <= 0 or elapsed_seconds <= 0:
        errors.append(
            f"invalid CPU denominators: requests={request_count} elapsed={elapsed_seconds}"
        )
    if total_seconds <= 0:
        errors.append("client CPU delta is zero")
    return {
        "before": before,
        "after": after,
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_request": (
            total_seconds / request_count if request_count > 0 else None
        ),
        "average_cores": (
            total_seconds / elapsed_seconds if elapsed_seconds > 0 else None
        ),
        "errors": errors,
        "passed": not errors,
    }


def _filesystem_evidence(path: Path) -> JsonObject:
    """Retain byte and inode capacity for the run's backing filesystem."""
    try:
        stat = os.statvfs(path)
    except BaseException as exc:
        return {
            "path": str(path),
            "capacity_bytes": None,
            "free_bytes": None,
            "available_bytes": None,
            "capacity_inodes": None,
            "free_inodes": None,
            "available_inodes": None,
            "error": _structured_error(exc),
        }
    return {
        "path": str(path),
        "block_size": stat.f_bsize,
        "fragment_size": stat.f_frsize,
        "capacity_bytes": stat.f_blocks * stat.f_frsize,
        "free_bytes": stat.f_bfree * stat.f_frsize,
        "available_bytes": stat.f_bavail * stat.f_frsize,
        "capacity_inodes": stat.f_files,
        "free_inodes": stat.f_ffree,
        "available_inodes": stat.f_favail,
        "error": None,
    }


def _storage_probe(directory: Path) -> JsonObject:
    """Run one bounded same-directory durable atomic-write probe."""
    probe_id = uuid.uuid4().hex
    source = directory / f".storage-probe-{probe_id}.tmp"
    destination = directory / f".storage-probe-{probe_id}.done"
    prefix = b"oldman-storage-probe-v1\n"
    payload = prefix + (b"x" * (4_096 - len(prefix)))
    step = "create"
    error: JsonObject | None = None
    cleanup_errors: list[JsonObject] = []
    try:
        with source.open("xb") as handle:
            step = "write"
            written = handle.write(payload)
            if written != len(payload):
                raise OSError(
                    errno.EIO,
                    f"short probe write: {written}/{len(payload)}",
                )
            step = "flush"
            handle.flush()
            step = "fsync"
            os.fsync(handle.fileno())
        step = "atomic_replace"
        source.replace(destination)
        step = "delete"
        destination.unlink()
        step = "complete"
    except BaseException as exc:
        error = _structured_error(exc)
    finally:
        for candidate in (source, destination):
            try:
                candidate.unlink(missing_ok=True)
            except BaseException as exc:
                cleanup_errors.append(
                    {"path": str(candidate), **_structured_error(exc)}
                )
    if error is None and cleanup_errors:
        step = "cleanup"
        error = cleanup_errors[0]
    return {
        "passed": error is None,
        "step": step,
        "bytes": len(payload),
        "error": error,
        "cleanup_errors": cleanup_errors,
    }


def _pre_shutdown_evidence(
    process: subprocess.Popen[bytes],
    run_dir: Path,
) -> JsonObject:
    """Capture process and storage boundaries immediately before SIGTERM."""
    primary_poll = process.poll()
    process_group = process.pid
    discovered_pids = _process_group_pids(process_group)
    snapshot_pids = set(discovered_pids)
    if primary_poll is None:
        snapshot_pids.add(process.pid)
    processes: list[JsonObject] = []
    for pid in sorted(snapshot_pids):
        process_state = dict(_read_process_stat(pid))
        process_state["expected_process_group"] = process_group
        if process_state["read_error"] is None:
            process_group_matches = (
                process_state["process_group"] == process_group
            )
            process_state["process_group_matches"] = process_group_matches
            process_state["identity_error"] = (
                None
                if process_group_matches
                else {
                    "type": "ProcessGroupMismatch",
                    "errno": None,
                    "message": (
                        f"pid {pid} expected process group {process_group}, "
                        f"got {process_state['process_group']}"
                    ),
                }
            )
        else:
            process_state["process_group_matches"] = None
            process_state["identity_error"] = None
        processes.append(process_state)
    filesystem = _filesystem_evidence(run_dir)
    storage_probe = _storage_probe(run_dir)
    final_primary_poll = process.poll()
    errors: list[str] = []
    if primary_poll is not None:
        errors.append(
            f"primary exited before process snapshot with exit code {primary_poll}"
        )
    for process_state in processes:
        if process_state["read_error"] is not None:
            errors.append(
                f"process {process_state['pid']} stat failed: "
                f"{process_state['read_error']}"
            )
        if process_state["identity_error"] is not None:
            errors.append(
                f"process {process_state['pid']} identity mismatch: "
                f"{process_state['identity_error']}"
            )
    if primary_poll is None and process.pid not in discovered_pids:
        errors.append(f"live primary pid {process.pid} missing from process group")
    if filesystem["error"] is not None:
        errors.append(f"statvfs failed: {filesystem['error']}")
    if not storage_probe["passed"]:
        errors.append(f"storage probe failed: {storage_probe}")
    if final_primary_poll is not None:
        errors.append(
            "primary exited before shutdown signal with exit code "
            f"{final_primary_poll}"
        )
    return {
        "primary_poll": primary_poll,
        "final_primary_poll": final_primary_poll,
        "process_group": process_group,
        "discovered_process_group_pids": discovered_pids,
        "processes": processes,
        "filesystem": filesystem,
        "storage_probe": storage_probe,
        "errors": errors,
        "passed": not errors,
    }


def _cleanup_run_directory(run_dir: Path, *, successful: bool) -> JsonObject:
    """Remove complete successful artifacts and retain failed runs to unwind."""
    if not successful:
        return {
            "attempted": False,
            "removed": False,
            "retained": True,
            "error": None,
            "passed": True,
        }
    try:
        shutil.rmtree(run_dir)
        if run_dir.exists():
            raise OSError(errno.EIO, f"run directory still exists: {run_dir}")
    except BaseException as exc:
        return {
            "attempted": True,
            "removed": False,
            "retained": run_dir.exists(),
            "error": _structured_error(exc),
            "passed": False,
        }
    return {
        "attempted": True,
        "removed": True,
        "retained": False,
        "error": None,
        "passed": True,
    }


def _shutdown_process_group(process: subprocess.Popen[bytes]) -> JsonObject:
    """Bound graceful shutdown, escalation, reaping, and PID disappearance."""
    process_group = process.pid
    observed_pids = _process_group_pids(process_group)
    action = "already_exited"
    if observed_pids:
        action = "sigterm"
        # Sanic's primary owns coordinated worker shutdown.  Signalling every
        # worker directly makes WorkerManager classify normal teardown as a
        # worker failure; group-wide SIGKILL is reserved for bounded escalation.
        try:
            process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass

    try:
        process.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        action = "sigkill"
        _signal_process_group(process_group, signal.SIGKILL)
        try:
            process.wait(timeout=FORCE_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            action = "unreaped"

    remaining_pids = _wait_for_group_exit(
        process_group,
        PROCESS_GROUP_EXIT_TIMEOUT_SECONDS,
    )
    if remaining_pids:
        action = "sigkill" if action != "unreaped" else action
        _signal_process_group(process_group, signal.SIGKILL)
        remaining_pids = _wait_for_group_exit(
            process_group,
            FORCE_SHUTDOWN_TIMEOUT_SECONDS,
        )

    # wait() is idempotent and reaps a process that raced the first deadline.
    if process.poll() is None:
        try:
            process.wait(timeout=FORCE_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    all_observed_pids = sorted({*observed_pids, process.pid})
    live_observed_pids = [
        pid for pid in all_observed_pids if Path(f"/proc/{pid}").exists()
    ]
    return {
        "process_group": process_group,
        "observed_pids": all_observed_pids,
        "action": action,
        "exit_code": process.returncode,
        "remaining_group_pids": remaining_pids,
        "live_observed_pids": live_observed_pids,
        "process_group_gone": not remaining_pids,
        "all_observed_pids_gone": not live_observed_pids,
        "passed": (
            action in {"sigterm", "already_exited"}
            and process.returncode == 0
            and not remaining_pids
            and not live_observed_pids
        ),
    }


def _read_json_file(path: Path) -> JsonObject:
    """Strictly read one fixture state snapshot as a JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BenchmarkFailure(f"fixture state is not an object: {value!r}")
    return cast(JsonObject, value)


def _wait_for_ready(
    process: subprocess.Popen[bytes],
    port: int,
    state_file: Path,
) -> JsonObject:
    """Poll bounded state and HTTP readiness without retrying benchmark requests."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    state: JsonObject | None = None
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BenchmarkFailure(
                f"fixture exited during startup pid={process.pid} "
                f"exit_code={process.returncode} last_error={last_error!r}"
            )
        try:
            state = _read_json_file(state_file)
            remaining = max(0.01, deadline - time.monotonic())
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/ready",
                timeout=min(0.5, remaining),
            ) as response:
                ready = json.loads(response.read().decode("utf-8"))
            if (
                ready.get("ready") is True
                and state.get("manager_ack_complete") is True
            ):
                return state
        except (
            ConnectionError,
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            urllib.error.URLError,
        ) as exc:
            last_error = exc
            time.sleep(0.02)
    raise BenchmarkFailure(
        f"fixture pid={process.pid} was not ready within "
        f"{STARTUP_TIMEOUT_SECONDS}s; state={state!r}; last_error={last_error!r}"
    )


def _validate_fixture_state(
    state: JsonObject,
    variant: HandlerVariant,
    workers: int,
) -> None:
    """Prove the fixture selected only the intended process-local handlers."""
    if state.get("variant") != variant or state.get("workers") != workers:
        raise BenchmarkFailure(f"fixture state identity mismatch: {state}")
    if state.get("response_bytes") != EXPECTED_RESPONSE_BYTES:
        raise BenchmarkFailure(f"fixture response size mismatch: {state}")
    if state.get("benchmark_method") != BENCHMARK_HTTP_METHOD:
        raise BenchmarkFailure(f"fixture benchmark method mismatch: {state}")
    expected_logging_disabled = variant == "no_logging"
    if state.get("logging_disabled") is not expected_logging_disabled:
        raise BenchmarkFailure(f"fixture logging mode mismatch: {state}")
    if state.get("access_log") is not (not expected_logging_disabled):
        raise BenchmarkFailure(f"fixture access logging mode mismatch: {state}")
    if state.get("manager_ack_complete") is not True:
        raise BenchmarkFailure(f"fixture manager ACK is incomplete: {state}")
    if state.get("owns_rotation_coordinator") is not True:
        raise BenchmarkFailure(f"fixture rotation coordinator is missing: {state}")

    handler_groups = state.get("handlers")
    if not isinstance(handler_groups, dict) or set(handler_groups) != {
        "files",
        "console",
    }:
        raise BenchmarkFailure(f"fixture handler groups mismatch: {handler_groups!r}")
    handlers = handler_groups["files"]
    if not isinstance(handlers, dict) or set(handlers) != {
        "file",
        "database_file",
        "access_file",
    }:
        raise BenchmarkFailure(f"fixture file handler set mismatch: {handlers!r}")
    for name, handler in handlers.items():
        if not isinstance(handler, dict):
            raise BenchmarkFailure(f"fixture handler state is invalid: {handler!r}")
        class_name = handler.get("class")
        rollover_at = handler.get("rollover_at")
        rotation = handler.get("rotation")
        expected_formatter = (
            "oldman.logging.formatters.PlainTextAccessFormatter"
            if name == "access_file"
            else "oldman.logging.formatters.PlainTextFormatter"
        )
        if handler.get("formatter") != expected_formatter or handler.get("level") != 0:
            raise BenchmarkFailure(f"file {name} formatter/level mismatch: {handler}")
        if rotation != {
            "when": FUTURE_ROTATION_WHEN,
            "interval": FUTURE_ROTATION_INTERVAL,
            "backup_count": 3,
        }:
            raise BenchmarkFailure(f"file {name} rotation config mismatch: {handler}")
        if variant in {"current", "no_logging"}:
            if class_name != "oldman.logging.handlers.AtomicAppendFileHandler":
                raise BenchmarkFailure(f"current {name} wiring mismatch: {handler}")
            if rollover_at is not None:
                raise BenchmarkFailure(f"current {name} reference state leaked: {handler}")
        elif (
            class_name != "logging.handlers.TimedRotatingFileHandler"
            or rollover_at != REFERENCE_ROLLOVER_AT
        ):
            raise BenchmarkFailure(f"reference {name} wiring mismatch: {handler}")

    console_handlers = handler_groups["console"]
    expected_console_formatters = {
        "console": "oldman.logging.formatters.ConsoleFormatter",
        "error_console": "oldman.logging.formatters.ConsoleFormatter",
        "access_console": "oldman.logging.formatters.AccessConsoleFormatter",
    }
    if not isinstance(console_handlers, dict) or set(console_handlers) != set(
        expected_console_formatters
    ):
        raise BenchmarkFailure(
            f"fixture console handler set mismatch: {console_handlers!r}"
        )
    for name, expected_formatter in expected_console_formatters.items():
        handler = console_handlers[name]
        if (
            not isinstance(handler, dict)
            or handler.get("class") != "logging.StreamHandler"
            or handler.get("formatter") != expected_formatter
            or handler.get("level") != 0
        ):
            raise BenchmarkFailure(f"console {name} wiring mismatch: {handler!r}")


def _final_fixture_state_errors(state: object) -> list[str]:
    """Return every fail-closed lifecycle error without hiding raw evidence."""
    if not isinstance(state, dict):
        return ["final_fixture_state must be an object"]

    errors: list[str] = []
    if state.get("manager_ack_complete") is not True:
        errors.append("manager_ack_complete must be true")

    signal_count = state.get("shutdown_signal_count")
    if type(signal_count) is not int or signal_count != 1:
        errors.append(
            f"shutdown_signal_count must be 1, got {signal_count!r}"
        )
    signals = state.get("shutdown_signals")
    if not isinstance(signals, list):
        errors.append("shutdown_signals must be a list")
    else:
        if len(signals) != signal_count:
            errors.append(
                "shutdown_signals length must equal shutdown_signal_count, "
                f"got {len(signals)} and {signal_count!r}"
            )
        for index, event in enumerate(signals, start=1):
            if not isinstance(event, dict):
                errors.append(f"shutdown signal {index} must be an object")
                continue
            if event.get("name") != "SIGTERM":
                errors.append(
                    f"shutdown signal {index} name must be SIGTERM, "
                    f"got {event.get('name')!r}"
                )
            if event.get("already_shutting_down") is not False:
                errors.append(
                    f"shutdown signal {index} already_shutting_down must be false"
                )
            if event.get("original_returned") is not True:
                errors.append(
                    f"shutdown signal {index} original_returned must be true"
                )
            if event.get("exception") is not None:
                errors.append(
                    f"shutdown signal {index} exception must be null, "
                    f"got {event.get('exception')!r}"
                )

    kill_count = state.get("manager_kill_count")
    if type(kill_count) is not int or kill_count != 0:
        errors.append(f"manager_kill_count must be 0, got {kill_count!r}")
    manager_kills = state.get("manager_kills")
    if not isinstance(manager_kills, list):
        errors.append("manager_kills must be a list")
    elif manager_kills:
        errors.append(f"manager_kills must be empty, got {manager_kills!r}")

    if state.get("sanic_serve_returned") is not True:
        errors.append("sanic_serve_returned must be true")
    if state.get("main_returned") is not True:
        errors.append("main_returned must be true")
    if state.get("unhandled_exception") is not None:
        errors.append(
            "unhandled_exception must be null, "
            f"got {state.get('unhandled_exception')!r}"
        )
    return errors


def _nearest_rank(values: list[float], percentile: float) -> float:
    """Return the deterministic nearest-rank percentile from raw latencies."""
    if not values:
        raise BenchmarkFailure("cannot calculate a percentile without observations")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


async def _request_worker(
    session: aiohttp.ClientSession,
    port: int,
    token_prefix: str,
    phase: Literal["W", "M"],
    worker_index: int,
    task_count: int,
    request_count: int,
    start_event: asyncio.Event,
) -> list[float]:
    """Issue one disjoint sequence without retries and return client latencies."""
    await start_event.wait()
    latencies: list[float] = []
    for sequence in range(worker_index, request_count, task_count):
        token = f"{token_prefix}_{phase}_{sequence:08d}"
        started_at = time.perf_counter()
        async with session.post(
            f"http://127.0.0.1:{port}/bench/{token}"
        ) as response:
            payload = await response.read()
            if response.status != 200 or len(payload) != EXPECTED_RESPONSE_BYTES:
                raise BenchmarkFailure(
                    f"request {token} returned status={response.status} "
                    f"bytes={len(payload)}"
                )
        latencies.append(time.perf_counter() - started_at)
    return latencies


async def _run_phase(
    session: aiohttp.ClientSession,
    port: int,
    token_prefix: str,
    phase: Literal["W", "M"],
    request_count: int,
    concurrency: int,
) -> JsonObject:
    """Run one bounded client phase and account for every created task."""
    task_count = min(concurrency, request_count)
    start_event = asyncio.Event()
    tasks = [
        asyncio.create_task(
            _request_worker(
                session,
                port,
                token_prefix,
                phase,
                worker_index,
                task_count,
                request_count,
                start_event,
            ),
            name=f"oldman-web-benchmark-{phase}-{worker_index}",
        )
        for worker_index in range(task_count)
    ]
    started_at = time.perf_counter()
    start_event.set()
    error: str | None = None
    latency_groups: list[list[float]] = []
    try:
        async with asyncio.timeout(PHASE_TIMEOUT_SECONDS):
            latency_groups = await asyncio.gather(*tasks)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        final_results = await asyncio.gather(*tasks, return_exceptions=True)
        if not latency_groups:
            latency_groups = [
                item for item in final_results if isinstance(item, list)
            ]
    elapsed = time.perf_counter() - started_at
    latencies = [latency for group in latency_groups for latency in group]
    unfinished = [task.get_name() for task in tasks if not task.done()]
    cancelled = sum(task.cancelled() for task in tasks)
    completed = len(latencies)
    passed = error is None and completed == request_count and not unfinished
    return {
        "phase": "warmup" if phase == "W" else "measurement",
        "request_count": request_count,
        "completed_requests": completed,
        "elapsed_seconds": elapsed,
        "qps": request_count / elapsed if passed and elapsed > 0 else None,
        "latency_seconds": (
            {
                "count": len(latencies),
                "minimum": min(latencies),
                "p50": _nearest_rank(latencies, 0.50),
                "p95": _nearest_rank(latencies, 0.95),
                "p99": _nearest_rank(latencies, 0.99),
                "maximum": max(latencies),
            }
            if latencies
            else None
        ),
        "client_tasks": {
            "created": len(tasks),
            "cancelled": cancelled,
            "unfinished_after_cleanup": unfinished,
            "all_finished": not unfinished,
        },
        "error": error,
        "passed": passed,
    }


async def _run_load(
    port: int,
    token_prefix: str,
    config: BenchmarkConfig,
    process_group: int,
) -> JsonObject:
    """Warm and measure one server while separating server and client CPU."""
    connector = aiohttp.TCPConnector(
        limit=config.concurrency,
        limit_per_host=config.concurrency,
    )
    timeout = aiohttp.ClientTimeout(total=HTTP_REQUEST_TIMEOUT_SECONDS)
    warmup: JsonObject | None = None
    measurement: JsonObject | None = None
    session_closed = False
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        warmup = await _run_phase(
            session,
            port,
            token_prefix,
            "W",
            config.warmup_requests,
            config.concurrency,
        )
        if warmup["passed"]:
            server_cpu_before = _process_group_cpu_snapshot(process_group)
            client_cpu_before = _self_cpu_snapshot()
            measurement = await _run_phase(
                session,
                port,
                token_prefix,
                "M",
                config.measured_requests,
                config.concurrency,
            )
            client_cpu_after = _self_cpu_snapshot()
            server_cpu_after = _process_group_cpu_snapshot(process_group)
            elapsed = measurement.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
                measurement["server_cpu"] = _process_group_cpu_delta(
                    server_cpu_before,
                    server_cpu_after,
                    request_count=config.measured_requests,
                    elapsed_seconds=float(elapsed),
                )
                measurement["client_cpu"] = _self_cpu_delta(
                    client_cpu_before,
                    client_cpu_after,
                    request_count=config.measured_requests,
                    elapsed_seconds=float(elapsed),
                )
            else:
                measurement["server_cpu"] = {
                    "errors": [f"invalid measurement elapsed time: {elapsed!r}"],
                    "passed": False,
                }
                measurement["client_cpu"] = {
                    "errors": [f"invalid measurement elapsed time: {elapsed!r}"],
                    "passed": False,
                }
            measurement["passed"] = bool(
                measurement["passed"]
                and measurement["server_cpu"]["passed"]
                and measurement["client_cpu"]["passed"]
            )
    session_closed = connector.closed
    return {
        "warmup": warmup,
        "measurement": measurement,
        "session_closed": session_closed,
        "passed": bool(
            warmup
            and warmup["passed"]
            and measurement
            and measurement["passed"]
            and session_closed
        ),
    }


async def _run_nested_processes(port: int, token: str) -> JsonObject:
    """Invoke the nested-process route through the real one-worker server."""
    timeout = aiohttp.ClientTimeout(total=60.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"http://127.0.0.1:{port}/nested/processes/{token}"
        ) as response:
            payload = await response.json()
            if response.status != 200 or not isinstance(payload, dict):
                raise BenchmarkFailure(
                    f"nested process route failed status={response.status} payload={payload!r}"
                )
            return cast(JsonObject, payload)


def _expected_phase_counts(request_count: int) -> Counter[int]:
    """Build the exact sequence multiset expected in each log file."""
    return Counter(range(request_count))


def _phase_token_result(
    observed: Counter[int],
    expected_count: int,
) -> JsonObject:
    """Report missing, duplicate, and unexpected tokens without hiding samples."""
    expected = _expected_phase_counts(expected_count)
    missing = list((expected - observed).elements())
    unexpected = list((observed - expected).elements())
    duplicates = sum(count - 1 for count in observed.values() if count > 1)
    return {
        "expected_tokens": expected_count,
        "observed_occurrences": sum(observed.values()),
        "observed_unique_tokens": len(observed),
        "missing_tokens": len(missing),
        "missing_samples": missing[:10],
        "duplicate_tokens": duplicates,
        "unexpected_tokens": len(unexpected),
        "unexpected_samples": unexpected[:10],
        "passed": observed == expected,
    }


def _validate_log_file(
    path: Path,
    token_prefix: str,
    config: BenchmarkConfig,
) -> JsonObject:
    """Strictly decode one file and verify separate warmup/measurement multisets."""
    result: JsonObject = {
        "file": path.name,
        "bytes": 0,
        "utf8_valid": False,
        "ansi_free": False,
        "newline_terminated": False,
        "warmup": None,
        "measurement": None,
        "error": None,
        "passed": False,
    }
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    token_pattern = re.compile(
        rf"(?<![0-9A-Za-z_]){re.escape(token_prefix)}_(W|M)_(\d{{8}})"
        r"(?![0-9A-Za-z_])"
    )
    warmup: Counter[int] = Counter()
    measurement: Counter[int] = Counter()
    measurement_process_ids: Counter[int] = Counter()
    process_pattern = re.compile(r"\[(\d+)\]")
    for line in text.splitlines():
        for phase, sequence_text in token_pattern.findall(line):
            target = warmup if phase == "W" else measurement
            target[int(sequence_text)] += 1
            if phase == "M":
                process_match = process_pattern.search(line)
                if process_match is not None:
                    measurement_process_ids[int(process_match.group(1))] += 1

    warmup_result = _phase_token_result(warmup, config.warmup_requests)
    measurement_result = _phase_token_result(
        measurement,
        config.measured_requests,
    )
    result.update(
        {
            "bytes": len(payload),
            "utf8_valid": True,
            "ansi_free": ANSI_ESCAPE not in payload,
            "newline_terminated": bool(payload) and payload.endswith(b"\n"),
            "warmup": warmup_result,
            "measurement": measurement_result,
            "measurement_process_ids": dict(sorted(measurement_process_ids.items())),
        }
    )
    result["passed"] = bool(
        result["utf8_valid"]
        and result["ansi_free"]
        and result["newline_terminated"]
        and warmup_result["passed"]
        and measurement_result["passed"]
    )
    return result


def _validate_disabled_log_file(path: Path, token_prefix: str) -> JsonObject:
    """Accept an absent/empty file only when it contains no benchmark records."""
    result: JsonObject = {
        "file": path.name,
        "exists": path.exists(),
        "bytes": 0,
        "utf8_valid": True,
        "ansi_free": True,
        "newline_terminated_or_empty": True,
        "token_occurrences": 0,
        "measurement_process_ids": {},
        "error": None,
        "passed": False,
    }
    if not path.exists():
        result["passed"] = True
        return result
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        result["utf8_valid"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    token_pattern = re.compile(
        rf"(?<![0-9A-Za-z_]){re.escape(token_prefix)}_(?:W|M)_\d{{8}}"
        r"(?![0-9A-Za-z_])"
    )
    token_occurrences = len(token_pattern.findall(text))
    result.update(
        {
            "bytes": len(payload),
            "ansi_free": ANSI_ESCAPE not in payload,
            "newline_terminated_or_empty": not payload or payload.endswith(b"\n"),
            "token_occurrences": token_occurrences,
        }
    )
    result["passed"] = bool(
        result["ansi_free"]
        and result["newline_terminated_or_empty"]
        and token_occurrences == 0
    )
    return result


def _validate_log_files(
    log_dir: Path,
    app_name: str,
    token_prefix: str,
    config: BenchmarkConfig,
    workers: int,
    variant: HandlerVariant,
) -> JsonObject:
    """Validate exact active logs or prove the disabled baseline emitted none."""
    prefix = app_name.lower().strip().replace(" ", "_")
    paths = {
        "main": log_dir / f"{prefix}.log",
        "database": log_dir / f"{prefix}_database.log",
        "access": log_dir / f"{prefix}_access.log",
    }
    if variant == "no_logging":
        files = {
            kind: _validate_disabled_log_file(path, token_prefix)
            for kind, path in paths.items()
        }
    else:
        files = {
            kind: _validate_log_file(path, token_prefix, config)
            for kind, path in paths.items()
        }
    sidecars = {
        kind: sorted(candidate.name for candidate in path.parent.glob(f"{path.name}.*"))
        for kind, path in paths.items()
    }
    main_process_ids = files["main"].get("measurement_process_ids", {})
    worker_processes_observed = (
        len(main_process_ids) if isinstance(main_process_ids, dict) else 0
    )
    return {
        "files": files,
        "sidecars": sidecars,
        "no_sidecars": not any(sidecars.values()),
        "expected_worker_processes": workers,
        "observed_worker_processes": worker_processes_observed,
        "worker_process_ids": main_process_ids,
        "logging_disabled": variant == "no_logging",
        "passed": (
            all(file_result["passed"] for file_result in files.values())
            and not any(sidecars.values())
            and (
                variant == "no_logging"
                or worker_processes_observed == workers
            )
        ),
    }


def _validate_nested_processes(
    response: JsonObject,
    token: str,
    variant: HandlerVariant,
    log_dir: Path,
    app_name: str,
    mode: Literal["release", "smoke"],
) -> JsonObject:
    """Validate Web-worker managers, subprocesses, CPU evidence and exact logs."""
    async_records = (
        RELEASE_NESTED_ASYNC_RECORDS
        if mode == "release"
        else SMOKE_NESTED_ASYNC_RECORDS
    )
    async_runs = (
        RELEASE_NESTED_ASYNC_RUNS if mode == "release" else SMOKE_NESTED_ASYNC_RUNS
    )
    subprocess_bytes = (
        RELEASE_NESTED_SUBPROCESS_BYTES
        if mode == "release"
        else SMOKE_NESTED_SUBPROCESS_BYTES
    )
    errors: list[str] = []
    async_result = response.get("async_manager")
    labels: dict[str, int] = {}
    child_pids: set[int] = set()
    if not isinstance(async_result, dict):
        errors.append("nested AsyncProcessManager result is missing")
    else:
        runs = async_result.get("runs")
        if not isinstance(runs, list) or len(runs) != async_runs:
            errors.append(
                f"nested AsyncProcessManager run count is wrong: {runs!r}"
            )
            runs = []
        for child in runs:
            if not isinstance(child, dict) or child.get("records") != async_records:
                errors.append(f"nested async child result is invalid: {child!r}")
                continue
            labels[str(child["label"])] = async_records
            child_pids.add(int(child["pid"]))
            runtime = child.get("runtime")
            if (
                not isinstance(runtime, dict)
                or runtime.get("owns_rotation") is not False
                or runtime.get("rotation_threads") != []
            ):
                errors.append(f"nested async child owns coordinator state: {runtime!r}")
        if async_result.get("timed_out") is not True:
            errors.append("nested AsyncProcessManager timeout did not propagate")
        if async_result.get("sigkill_result") is not None:
            errors.append("nested SIGKILL child returned a fake result")
        recovery = async_result.get("recovery")
        if not isinstance(recovery, dict) or recovery.get("records") != async_records:
            errors.append(f"nested recovery result is invalid: {recovery!r}")
        else:
            labels[str(recovery["label"])] = async_records
            child_pids.add(int(recovery["pid"]))
        if async_result.get("pipe_reader_threads") != []:
            errors.append(
                "nested AsyncProcessManager left pipe reader threads: "
                f"{async_result.get('pipe_reader_threads')!r}"
            )

    subprocess_result = response.get("subprocess")
    if not isinstance(subprocess_result, dict):
        errors.append("nested subprocess result is missing")
    else:
        output = subprocess_result.get("output")
        cleanup = subprocess_result.get("cleanup")
        if not isinstance(output, dict):
            errors.append("nested subprocess output result is missing")
        else:
            child_pids.update(
                (int(output["inherited_pid"]), int(output["pipe_pid"]))
            )
            if output.get("inherited_returncode") != 0 or output.get("pipe_returncode") != 0:
                errors.append("nested normal subprocess returned nonzero")
            if output.get("pipe_stdout_bytes") != subprocess_bytes:
                errors.append("nested PIPE stdout byte count is wrong")
            if output.get("pipe_stderr_bytes") != subprocess_bytes:
                errors.append("nested PIPE stderr byte count is wrong")
            if not isinstance(output.get("event_loop_ticks"), int) or output["event_loop_ticks"] <= 0:
                errors.append("nested PIPE subprocess blocked the worker event loop")
        if not isinstance(cleanup, dict):
            errors.append("nested subprocess cleanup result is missing")
        else:
            child_pids.update(
                (int(cleanup["timeout_pid"]), int(cleanup["cancelled_pid"]))
            )
            for key in (
                "timed_out",
                "timeout_group_gone",
                "cancelled",
                "cancelled_group_gone",
            ):
                if cleanup.get(key) is not True:
                    errors.append(f"nested subprocess cleanup flag {key} is not true")
            for key in (
                "timeout_group_pids_before_cleanup",
                "cancelled_group_pids_before_cleanup",
            ):
                group_pids = cleanup.get(key)
                if not isinstance(group_pids, list) or len(group_pids) < 2:
                    errors.append(
                        "nested subprocess descendant was not observed: "
                        f"{key}={group_pids!r}"
                    )

    prefix = app_name.lower().strip().replace(" ", "_")
    path = log_dir / f"{prefix}.log"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(
        rf"PROCESS_PERF token={re.escape(token)} label=([^ ]+) sequence=(\d{{8}})"
    )
    observed: dict[str, Counter[int]] = {}
    for label, sequence in pattern.findall(text):
        observed.setdefault(label, Counter())[int(sequence)] += 1
    if variant == "no_logging":
        if observed:
            errors.append(f"disabled nested logging emitted records: {observed}")
    else:
        if set(observed) != set(labels):
            errors.append(
                f"nested log labels mismatch expected={sorted(labels)} "
                f"observed={sorted(observed)}"
            )
        for label, count in labels.items():
            if observed.get(label, Counter()) != Counter(range(count)):
                errors.append(f"nested label {label} sequence multiset mismatch")
        if text.count(f"PROCESS_PERF_TIMEOUT token={token}") != 1:
            errors.append("nested timeout marker count is not exactly one")
        if text.count(f"PROCESS_PERF_SIGKILL token={token}") != 1:
            errors.append("nested SIGKILL marker count is not exactly one")

    live_pids = sorted(pid for pid in child_pids if Path(f"/proc/{pid}").exists())
    if live_pids:
        errors.append(f"nested child PIDs remain after route completion: {live_pids}")
    return {
        "labels": labels,
        "observed_labels": {
            label: sum(counts.values()) for label, counts in observed.items()
        },
        "child_pids": sorted(child_pids),
        "errors": errors,
        "passed": not errors,
    }


def _base_run_result(
    workers: int,
    round_number: int,
    order_index: int,
    variant: HandlerVariant,
) -> JsonObject:
    """Create a JSON-safe run shell before startup can fail."""
    return {
        "workers": workers,
        "round": round_number,
        "order_index": order_index,
        "variant": variant,
        "server_pid": None,
        "fixture_state": None,
        "final_fixture_state": None,
        "pre_shutdown_evidence": None,
        "artifact_cleanup": None,
        "load": None,
        "nested_processes": None,
        "log_validation": None,
        "shutdown": None,
        "error": None,
        "passed": False,
    }


def _run_variant(
    root: Path,
    workers: int,
    round_number: int,
    order_index: int,
    variant: HandlerVariant,
    config: BenchmarkConfig,
) -> JsonObject:
    """Run, measure, shut down, and validate one fresh real Sanic server."""
    result = _base_run_result(workers, round_number, order_index, variant)
    run_id = uuid.uuid4().hex
    app_name = f"web_perf_{workers}_{round_number}_{order_index}_{run_id[:8]}"
    token_prefix = f"WEBPERF_{run_id.upper()}"
    run_dir = root / f"w{workers}-r{round_number}-o{order_index}-{variant}"
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True)
    state_file = run_dir / "state.json"
    port = _reserve_port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "OLDMAN_WEB_BENCH_LOG_DIR": str(log_dir),
            "OLDMAN_WEB_BENCH_STATE_FILE": str(state_file),
            "OLDMAN_WEB_BENCH_APP_NAME": app_name,
            "OLDMAN_WEB_BENCH_VARIANT": variant,
            "OLDMAN_WEB_BENCH_WORKERS": str(workers),
            "OLDMAN_WEB_BENCH_PORT": str(port),
            "OLDMAN_WEB_BENCH_NESTED_ASYNC_RECORDS": str(
                RELEASE_NESTED_ASYNC_RECORDS
                if config.mode == "release"
                else SMOKE_NESTED_ASYNC_RECORDS
            ),
            "OLDMAN_WEB_BENCH_NESTED_ASYNC_RUNS": str(
                RELEASE_NESTED_ASYNC_RUNS
                if config.mode == "release"
                else SMOKE_NESTED_ASYNC_RUNS
            ),
            "OLDMAN_WEB_BENCH_NESTED_SUBPROCESS_BYTES": str(
                RELEASE_NESTED_SUBPROCESS_BYTES
                if config.mode == "release"
                else SMOKE_NESTED_SUBPROCESS_BYTES
            ),
            "OLDMAN_WEB_BENCH_FAULT": (
                config.inject_fault
                if config.inject_fault == "skip_database"
                else "none"
            ),
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(FIXTURE)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    result["server_pid"] = process.pid
    primary_error: BaseException | None = None
    try:
        state = _wait_for_ready(process, port, state_file)
        _validate_fixture_state(state, variant, workers)
        result["fixture_state"] = state
        result["load"] = asyncio.run(
            _run_load(port, token_prefix, config, process.pid)
        )
        if not result["load"]["passed"]:
            raise BenchmarkFailure(f"client load failed: {result['load']}")
        if workers == 1:
            nested_token = f"NESTEDPERF_{run_id.upper()}"
            nested_response = asyncio.run(
                _run_nested_processes(port, nested_token)
            )
            result["nested_processes"] = {
                "token": nested_token,
                "response": nested_response,
            }
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            result["pre_shutdown_evidence"] = _pre_shutdown_evidence(
                process,
                run_dir,
            )
        except BaseException as exc:
            fallback_poll = process.poll()
            result["pre_shutdown_evidence"] = {
                "primary_poll": fallback_poll,
                "final_primary_poll": fallback_poll,
                "process_group": process.pid,
                "discovered_process_group_pids": [],
                "processes": [],
                "filesystem": None,
                "storage_probe": None,
                "errors": [
                    "pre-shutdown evidence raised unexpectedly: "
                    f"{_structured_error(exc)}"
                ],
                "passed": False,
            }
        result["shutdown"] = _shutdown_process_group(process)

    final_state_read_error: str | None = None
    try:
        result["final_fixture_state"] = _read_json_file(state_file)
    except BaseException as exc:
        final_state_read_error = f"{type(exc).__name__}: {exc}"

    result["log_validation"] = _validate_log_files(
        log_dir,
        app_name,
        token_prefix,
        config,
        workers,
        variant,
    )
    nested_validation: JsonObject | None = None
    if workers == 1 and isinstance(result.get("nested_processes"), dict):
        nested = cast(JsonObject, result["nested_processes"])
        nested_validation = _validate_nested_processes(
            cast(JsonObject, nested["response"]),
            cast(str, nested["token"]),
            variant,
            log_dir,
            app_name,
            config.mode,
        )
        nested["validation"] = nested_validation
    errors: list[str] = []
    if primary_error is not None:
        errors.append(f"{type(primary_error).__name__}: {primary_error}")
    if not result["shutdown"]["passed"]:
        errors.append(f"bounded process cleanup failed: {result['shutdown']}")
    if not result["log_validation"]["passed"]:
        errors.append(f"log correctness failed: {result['log_validation']}")
    if nested_validation is not None and not nested_validation["passed"]:
        errors.append(f"nested process matrix failed: {nested_validation}")
    if final_state_read_error is not None:
        errors.append(f"final fixture state read failed: {final_state_read_error}")
    else:
        final_state = cast(JsonObject, result["final_fixture_state"])
        try:
            _validate_fixture_state(final_state, variant, workers)
        except BaseException as exc:
            errors.append(
                "final fixture state wiring failed: "
                f"{type(exc).__name__}: {exc}"
            )
        lifecycle_errors = _final_fixture_state_errors(final_state)
        if lifecycle_errors:
            errors.append(
                "final fixture lifecycle failed: " + "; ".join(lifecycle_errors)
            )
    if not result["pre_shutdown_evidence"]["passed"]:
        errors.append(
            "pre-shutdown evidence failed: "
            f"{result['pre_shutdown_evidence']}"
        )
    result["error"] = "; ".join(errors) if errors else None
    result["passed"] = not errors
    result["artifact_cleanup"] = _cleanup_run_directory(
        run_dir,
        successful=result["passed"],
    )
    if not result["artifact_cleanup"]["passed"]:
        errors.append(
            f"run artifact cleanup failed: {result['artifact_cleanup']}"
        )
        result["error"] = "; ".join(errors)
        result["passed"] = False
    return result


def _round_order(
    round_number: int,
) -> tuple[HandlerVariant, HandlerVariant, HandlerVariant]:
    """Balance every position and pairwise before/after order over six rounds."""
    orders: tuple[
        tuple[HandlerVariant, HandlerVariant, HandlerVariant],
        ...,
    ] = (
        ("current", "timed_reference", "no_logging"),
        ("timed_reference", "no_logging", "current"),
        ("no_logging", "current", "timed_reference"),
        ("no_logging", "timed_reference", "current"),
        ("current", "no_logging", "timed_reference"),
        ("timed_reference", "current", "no_logging"),
    )
    return orders[(round_number - 1) % len(orders)]


def _measurement_value(
    run: JsonObject,
    key: Literal["qps", "p99", "server_cpu_per_request"],
) -> float:
    """Extract one measured scalar only from a complete successful run."""
    load = run.get("load")
    if not isinstance(load, dict):
        raise BenchmarkFailure(f"run has no load result: {run}")
    measurement = load.get("measurement")
    if not isinstance(measurement, dict):
        raise BenchmarkFailure(f"run has no measurement result: {run}")
    if key == "qps":
        value = measurement.get("qps")
    elif key == "p99":
        latency = measurement.get("latency_seconds")
        value = latency.get("p99") if isinstance(latency, dict) else None
    else:
        server_cpu = measurement.get("server_cpu")
        value = (
            server_cpu.get("seconds_per_request")
            if isinstance(server_cpu, dict)
            else None
        )
    if not isinstance(value, (float, int)):
        raise BenchmarkFailure(f"run measurement {key} is invalid: {run}")
    return float(value)


def _nested_scenario_metrics(run: JsonObject) -> dict[str, JsonObject]:
    """Extract Web-worker child logging and subprocess PIPE measurements."""
    nested = run.get("nested_processes")
    if not isinstance(nested, dict):
        raise BenchmarkFailure(f"one-worker run has no nested process result: {run}")
    response = nested.get("response")
    if not isinstance(response, dict):
        raise BenchmarkFailure(f"nested process response is invalid: {nested}")
    async_result = response.get("async_manager")
    subprocess_result = response.get("subprocess")
    if not isinstance(async_result, dict) or not isinstance(subprocess_result, dict):
        raise BenchmarkFailure(f"nested process response is incomplete: {response}")
    children = [
        *cast(list[JsonObject], async_result["runs"]),
        cast(JsonObject, async_result["recovery"]),
    ]
    records = sum(int(child["records"]) for child in children)
    elapsed = sum(float(child["elapsed_seconds"]) for child in children)
    cpu_seconds = sum(
        float(cast(JsonObject, child["cpu"])["total_seconds"])
        for child in children
    )
    output = cast(JsonObject, subprocess_result["output"])
    output_bytes = int(output["pipe_stdout_bytes"]) + int(output["pipe_stderr_bytes"])
    return {
        "async_process_manager": {
            "throughput": records / elapsed,
            "cpu_per_unit": cpu_seconds / records,
        },
        "subprocess_pipe": {
            "throughput": output_bytes / float(output["pipe_elapsed_seconds"]),
            "cpu_per_unit": float(
                cast(JsonObject, output["child_cpu"])["seconds_per_unit"]
            ),
        },
    }


def _nested_process_comparison(
    rounds: dict[int, dict[HandlerVariant, JsonObject]],
    expected_rounds: int,
) -> JsonObject:
    """Summarize nested Web-worker performance without applying a threshold."""
    result: JsonObject = {}
    for scenario in ("async_process_manager", "subprocess_pipe"):
        values: dict[HandlerVariant, dict[str, list[float]]] = {
            variant: {"throughput": [], "cpu_per_unit": []}
            for variant in ("current", "timed_reference", "no_logging")
        }
        paired: list[JsonObject] = []
        for round_number in range(1, expected_rounds + 1):
            metrics: dict[HandlerVariant, JsonObject] = {
                variant: _nested_scenario_metrics(run)[scenario]
                for variant, run in rounds[round_number].items()
            }
            for variant, measurement in metrics.items():
                values[variant]["throughput"].append(
                    float(measurement["throughput"])
                )
                values[variant]["cpu_per_unit"].append(
                    float(measurement["cpu_per_unit"])
                )
            paired.append(
                {
                    "round": round_number,
                    "throughput_current_over_stdlib": (
                        metrics["current"]["throughput"]
                        / metrics["timed_reference"]["throughput"]
                    ),
                    "cpu_current_over_stdlib": (
                        metrics["current"]["cpu_per_unit"]
                        / metrics["timed_reference"]["cpu_per_unit"]
                    ),
                    "throughput_current_over_no_logging": (
                        metrics["current"]["throughput"]
                        / metrics["no_logging"]["throughput"]
                    ),
                    "cpu_current_over_no_logging": (
                        metrics["current"]["cpu_per_unit"]
                        / metrics["no_logging"]["cpu_per_unit"]
                    ),
                }
            )
        result[scenario] = {
            "medians": {
                variant: {
                    metric: statistics.median(measurements)
                    for metric, measurements in metrics.items()
                }
                for variant, metrics in values.items()
            },
            "paired_ratio_medians": {
                key: statistics.median(item[key] for item in paired)
                for key in (
                    "throughput_current_over_stdlib",
                    "cpu_current_over_stdlib",
                    "throughput_current_over_no_logging",
                    "cpu_current_over_no_logging",
                )
            },
            "paired_rounds": paired,
        }
    return {"gating": False, "scenarios": result}


def _comparison(
    workers: int,
    runs: list[JsonObject],
    enforce: bool,
    *,
    expected_rounds: int = RELEASE_ROUNDS,
) -> JsonObject:
    """Compare strictly matched three-way rounds and gate only existing A/B limits."""
    rounds: dict[int, dict[HandlerVariant, JsonObject]] = {}
    for run in runs:
        round_number = run.get("round")
        if not isinstance(round_number, int) or isinstance(round_number, bool):
            raise BenchmarkFailure(f"run has an invalid round number: {run}")
        raw_variant = run.get("variant")
        if raw_variant not in ("current", "timed_reference", "no_logging"):
            raise BenchmarkFailure(f"run has an invalid variant: {run}")
        variant = cast(HandlerVariant, raw_variant)
        round_variants = rounds.setdefault(round_number, {})
        if variant in round_variants:
            raise BenchmarkFailure(
                f"round {round_number} has duplicate {variant} variant"
            )
        round_variants[variant] = run

    expected_round_numbers = set(range(1, expected_rounds + 1))
    if set(rounds) != expected_round_numbers:
        raise BenchmarkFailure(
            f"comparison requires exactly {expected_rounds} rounds numbered "
            f"1..{expected_rounds}; got {sorted(rounds)}"
        )

    variants: dict[HandlerVariant, list[JsonObject]] = {
        "current": [],
        "timed_reference": [],
        "no_logging": [],
    }
    paired_ratios: list[JsonObject] = []
    for round_number in range(1, expected_rounds + 1):
        round_variants = rounds[round_number]
        missing = [
            variant
            for variant in ("current", "timed_reference", "no_logging")
            if variant not in round_variants
        ]
        if missing:
            raise BenchmarkFailure(
                f"round {round_number} must contain exactly one of every variant; "
                f"missing {', '.join(missing)}"
            )
        current = round_variants["current"]
        reference = round_variants["timed_reference"]
        no_logging = round_variants["no_logging"]
        variants["current"].append(current)
        variants["timed_reference"].append(reference)
        variants["no_logging"].append(no_logging)

        order_indexes = {
            variant: run.get("order_index")
            for variant, run in round_variants.items()
        }
        if (
            any(
                not isinstance(index, int) or isinstance(index, bool)
                for index in order_indexes.values()
            )
            or set(order_indexes.values()) != {1, 2, 3}
        ):
            raise BenchmarkFailure(
                f"round {round_number} has invalid execution order indexes: "
                f"{order_indexes}"
            )
        ordered_runs = sorted(
            (current, reference, no_logging),
            key=lambda item: cast(int, item["order_index"]),
        )
        order = [cast(str, run["variant"]) for run in ordered_runs]
        if tuple(order) != _round_order(round_number):
            raise BenchmarkFailure(
                f"round {round_number} execution order {tuple(order)} does not match "
                f"{_round_order(round_number)}"
            )
        current_qps = _measurement_value(current, "qps")
        reference_qps = _measurement_value(reference, "qps")
        no_logging_qps = _measurement_value(no_logging, "qps")
        current_p99 = _measurement_value(current, "p99")
        reference_p99 = _measurement_value(reference, "p99")
        no_logging_p99 = _measurement_value(no_logging, "p99")
        current_cpu = _measurement_value(current, "server_cpu_per_request")
        reference_cpu = _measurement_value(reference, "server_cpu_per_request")
        no_logging_cpu = _measurement_value(no_logging, "server_cpu_per_request")
        if min(
            current_qps,
            reference_qps,
            no_logging_qps,
            current_p99,
            reference_p99,
            no_logging_p99,
            current_cpu,
            reference_cpu,
            no_logging_cpu,
        ) <= 0:
            raise BenchmarkFailure(
                f"round {round_number} measurements must all be positive"
            )
        paired_ratios.append(
            {
                "round": round_number,
                "order": order,
                "current_order_index": current.get("order_index"),
                "reference_order_index": reference.get("order_index"),
                "no_logging_order_index": no_logging.get("order_index"),
                "current_qps": current_qps,
                "reference_qps": reference_qps,
                "no_logging_qps": no_logging_qps,
                "current_p99_seconds": current_p99,
                "reference_p99_seconds": reference_p99,
                "no_logging_p99_seconds": no_logging_p99,
                "current_server_cpu_seconds_per_request": current_cpu,
                "reference_server_cpu_seconds_per_request": reference_cpu,
                "no_logging_server_cpu_seconds_per_request": no_logging_cpu,
                "qps_current_over_reference": current_qps / reference_qps,
                "p99_current_over_reference": current_p99 / reference_p99,
                "server_cpu_per_request_current_over_reference": (
                    current_cpu / reference_cpu
                ),
                "qps_current_over_no_logging": current_qps / no_logging_qps,
                "p99_current_over_no_logging": current_p99 / no_logging_p99,
                "server_cpu_per_request_current_over_no_logging": (
                    current_cpu / no_logging_cpu
                ),
                "qps_reference_over_no_logging": reference_qps / no_logging_qps,
                "p99_reference_over_no_logging": reference_p99 / no_logging_p99,
                "server_cpu_per_request_reference_over_no_logging": (
                    reference_cpu / no_logging_cpu
                ),
            }
        )

    raw_qps = {
        variant: [_measurement_value(run, "qps") for run in variant_runs]
        for variant, variant_runs in variants.items()
    }
    raw_p99 = {
        variant: [_measurement_value(run, "p99") for run in variant_runs]
        for variant, variant_runs in variants.items()
    }
    raw_server_cpu_per_request = {
        variant: [
            _measurement_value(run, "server_cpu_per_request")
            for run in variant_runs
        ]
        for variant, variant_runs in variants.items()
    }
    median_qps = {
        variant: statistics.median(values) for variant, values in raw_qps.items()
    }
    median_p99 = {
        variant: statistics.median(values) for variant, values in raw_p99.items()
    }
    legacy_qps_ratio = median_qps["current"] / median_qps["timed_reference"]
    legacy_p99_ratio = median_p99["current"] / median_p99["timed_reference"]
    paired_ratio_medians = {
        key: statistics.median(pair[key] for pair in paired_ratios)
        for key in (
            "qps_current_over_reference",
            "p99_current_over_reference",
            "server_cpu_per_request_current_over_reference",
            "qps_current_over_no_logging",
            "p99_current_over_no_logging",
            "server_cpu_per_request_current_over_no_logging",
            "qps_reference_over_no_logging",
            "p99_reference_over_no_logging",
            "server_cpu_per_request_reference_over_no_logging",
        )
    }
    threshold_passed = (
        paired_ratio_medians["qps_current_over_reference"] >= MINIMUM_QPS_RATIO
        and paired_ratio_medians["p99_current_over_reference"] <= MAXIMUM_P99_RATIO
        and paired_ratio_medians[
            "server_cpu_per_request_current_over_reference"
        ]
        <= MAXIMUM_CPU_RATIO
    )
    return {
        "workers": workers,
        "rounds_per_variant": expected_rounds,
        "raw_qps": raw_qps,
        "raw_p99_seconds": raw_p99,
        "raw_server_cpu_seconds_per_request": raw_server_cpu_per_request,
        "paired_ratios": paired_ratios,
        "paired_ratio_medians": paired_ratio_medians,
        "nested_processes": (
            _nested_process_comparison(rounds, expected_rounds)
            if workers == 1
            and all(
                isinstance(run.get("nested_processes"), dict)
                for variant_runs in variants.values()
                for run in variant_runs
            )
            else None
        ),
        "ratio_of_separate_medians_diagnostic": {
            "basis": "ratio_of_separate_variant_medians",
            "gating": False,
            "median_qps": median_qps,
            "median_p99_seconds": median_p99,
            "qps_current_over_reference": legacy_qps_ratio,
            "p99_current_over_reference": legacy_p99_ratio,
        },
        "thresholds": {
            "basis": "median_of_paired_round_ratios",
            "minimum_qps_ratio": MINIMUM_QPS_RATIO,
            "maximum_p99_ratio": MAXIMUM_P99_RATIO,
            "maximum_cpu_ratio": MAXIMUM_CPU_RATIO,
            "enforced": enforce,
        },
        "threshold_passed": threshold_passed,
        "passed": threshold_passed if enforce else True,
    }


def _machine_information(root: Path) -> JsonObject:
    """Record the Linux, Python, CPU, and filesystem identity of this evidence."""
    uname = platform.uname()
    stat = os.statvfs(root)
    affinity_count: int | None
    try:
        affinity_count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity_count = None
    return {
        "kernel": {
            "system": uname.system,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "libraries": {"aiohttp": aiohttp.__version__},
        "cpu": {
            "logical_count": os.cpu_count(),
            "affinity_count": affinity_count,
        },
        "filesystem": {
            "path": str(root),
            "block_size": stat.f_bsize,
            "fragment_size": stat.f_frsize,
        },
    }


def _base_report(config: BenchmarkConfig) -> JsonObject:
    """Create the full JSON report shell before environmental checks run."""
    return {
        "benchmark": "oldman_real_sanic_logging",
        "mode": config.mode,
        "config": {
            "workers": list(config.workers),
            "rounds": config.rounds,
            "warmup_requests": config.warmup_requests,
            "measured_requests": config.measured_requests,
            "concurrency": config.concurrency,
            "ordering": (
                "cyclic current/timed_reference/no_logging order by round"
            ),
            "inject_fault": config.inject_fault,
            "ratios_enforced": config.enforce_ratios,
            "minimum_qps_ratio": MINIMUM_QPS_RATIO,
            "maximum_p99_ratio": MAXIMUM_P99_RATIO,
            "maximum_cpu_ratio": MAXIMUM_CPU_RATIO,
        },
        "machine": None,
        "contracts": {},
        "runs": [],
        "comparisons": [],
        "failures": [],
        "passed": False,
    }


def _execute(config: BenchmarkConfig, report: JsonObject) -> None:
    """Append every result in place, retaining evidence if an exception escapes."""
    retry_contract = _aiohttp_retry_contract()
    report["contracts"]["aiohttp_connection_retry"] = retry_contract
    if not retry_contract["passed"]:
        report["failures"].append(
            f"aiohttp connection retry contract failed: {retry_contract}"
        )
        return
    if platform.system() != "Linux" or not Path("/proc").is_dir():
        report["failures"].append("real Sanic performance gate requires Linux /proc")
        return
    if not FIXTURE.is_file():
        report["failures"].append(f"fixture is missing: {FIXTURE}")
        return

    with tempfile.TemporaryDirectory(prefix="oldman-web-performance-") as directory:
        root = Path(directory)
        report["machine"] = _machine_information(root)
        for workers in config.workers:
            worker_runs: list[JsonObject] = []
            for round_number in range(1, config.rounds + 1):
                for order_index, variant in enumerate(
                    _round_order(round_number),
                    start=1,
                ):
                    run = _run_variant(
                        root,
                        workers,
                        round_number,
                        order_index,
                        variant,
                        config,
                    )
                    report["runs"].append(run)
                    worker_runs.append(run)
                    if config.inject_fault == "after_first_run_exception":
                        raise RuntimeError(
                            "injected exception after preserving the first run"
                        )
                    if not run["passed"]:
                        report["failures"].append(
                            f"workers={workers} round={round_number} "
                            f"variant={variant}: {run['error']}"
                        )
                        return

            comparison = _comparison(
                workers,
                worker_runs,
                config.enforce_ratios,
                expected_rounds=config.rounds,
            )
            report["comparisons"].append(comparison)
            if not comparison["passed"]:
                report["failures"].append(
                    f"workers={workers} ratio gate failed: {comparison}"
                )

    report["passed"] = not report["failures"]


def main() -> int:
    """Print complete JSON evidence and return nonzero if any gate failed."""
    parser = _build_parser()
    try:
        config = _config_from_args(parser, parser.parse_args())
    except BenchmarkFailure as exc:
        parser.error(str(exc))

    report = _base_report(config)
    try:
        _execute(config, report)
    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
