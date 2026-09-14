"""Benchmark Oldman's direct file handler against an equivalent stdlib writer.

Run the release gate explicitly with::

    .venv/bin/python -m tests.performance.logging_handler_benchmark

The optional ``--candidate-source`` argument exists only for read-only regression
diagnostics.  It loads ``AtomicAppendFileHandler`` from a standalone source file,
which lets reviewers exercise a historical ``git show`` snapshot without changing
the checkout or presenting historical numbers as a current gate result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import multiprocessing
import os
import platform
import re
import resource
import statistics
import sys
import tempfile
import time
import traceback
from collections import Counter
from collections.abc import Callable
from logging.handlers import TimedRotatingFileHandler
from multiprocessing.connection import Connection, wait
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from oldman.logging.formatters import PlainTextFormatter

type HandlerFactory = Callable[..., logging.Handler]
type JsonObject = dict[str, Any]

ROUNDS = 5
SINGLE_RECORDS = 100_000
WORKER_COUNT = 4
RECORDS_PER_WORKER = 50_000
SINGLE_WARMUP_RECORDS = 2_000
WORKER_WARMUP_RECORDS = 1_000
MINIMUM_RATIO = 0.95
REFERENCE_ROLLOVER_AT = 2**63 - 1
# Supported Linux systems provide ``PIPE_BUF`` of at least 4096 bytes.  Connection's
# four-byte frame header plus this payload therefore fits one atomic pipe write.
MAX_WORKER_REPORT_BYTES = 4000
REPORT_DRAIN_TIMEOUT_SECONDS = 0.25
STARTUP_TIMEOUT_SECONDS = 60.0
EXIT_TIMEOUT_SECONDS = 120.0
TERMINATE_TIMEOUT_SECONDS = 5.0

LOGGER_NAME = "oldman.handler.performance"
FORMAT = "%(message)s"
PAYLOAD = (
    "HANDLER_BENCHMARK producer=%d sequence=%06d "
    "payload=Oldman-中文-café-\x1b[31mplain\x1b[0m"
)
EXPECTED_LINE = re.compile(
    r"HANDLER_BENCHMARK producer=(\d+) sequence=(\d{6}) "
    r"payload=Oldman-中文-café-plain"
)

# Fail closed: only filesystems with local append semantics admitted by the
# release-gate design may contribute performance evidence.
LOCAL_FILESYSTEMS = {
    "btrfs",
    "ext2",
    "ext3",
    "ext4",
    "overlay",
    "tmpfs",
    "xfs",
    "zfs",
}


class BenchmarkFailure(RuntimeError):
    """Signal a correctness, environment, child-lifecycle, or ratio failure."""


def _build_parser() -> argparse.ArgumentParser:
    """Build the small command-line surface for the release and diagnostic runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-source",
        type=Path,
        help=(
            "load AtomicAppendFileHandler from this standalone source file; "
            "intended for a git-show historical diagnostic only"
        ),
    )
    return parser


def _load_standalone_module(source: Path) -> ModuleType:
    """Load one historical handler module without copying it into the repository."""
    resolved = source.resolve(strict=True)
    module_name = f"_oldman_handler_benchmark_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise BenchmarkFailure(f"cannot load candidate handler source: {resolved}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses inspect ``sys.modules`` while the historical source is executing.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _candidate_handler_class(candidate_source: str | None) -> HandlerFactory:
    """Resolve the current candidate or a standalone historical diagnostic class."""
    if candidate_source is None:
        from oldman.logging.handlers import AtomicAppendFileHandler

        return cast(HandlerFactory, AtomicAppendFileHandler)

    module = _load_standalone_module(Path(candidate_source))
    handler_class = getattr(module, "AtomicAppendFileHandler", None)
    if not isinstance(handler_class, type) or not issubclass(handler_class, logging.Handler):
        raise BenchmarkFailure(
            "candidate source does not define an AtomicAppendFileHandler subclass"
        )
    return cast(HandlerFactory, handler_class)


def _make_handler(
    variant: str,
    path: Path,
    candidate_source: str | None,
) -> logging.Handler:
    """Create either writer with the exact same formatter and UTF-8 configuration."""
    if variant == "current":
        handler = _candidate_handler_class(candidate_source)(path, encoding="utf-8")
    elif variant == "reference":
        reference = TimedRotatingFileHandler(
            path,
            when="midnight",
            interval=1,
            backupCount=0,
            encoding="utf-8",
            delay=True,
        )
        # The stdlib handler remains a formatting/write-speed reference only;
        # pinning the deadline prevents a midnight boundary from rotating a round.
        reference.rolloverAt = REFERENCE_ROLLOVER_AT
        handler = reference
    else:
        raise BenchmarkFailure(f"unknown handler variant: {variant}")
    handler.setFormatter(PlainTextFormatter(FORMAT))
    return handler


def _write_records(
    handler: logging.Handler,
    producer: int,
    record_count: int,
) -> JsonObject:
    """Write one sequence and measure wall time plus this process's CPU cost."""
    cpu_before = _cpu_usage_snapshot()
    started_at = time.perf_counter()
    for sequence in range(record_count):
        record = logging.LogRecord(
            LOGGER_NAME,
            logging.INFO,
            __file__,
            0,
            PAYLOAD,
            (producer, sequence),
            None,
        )
        handler.handle(record)
    elapsed = time.perf_counter() - started_at
    cpu_after = _cpu_usage_snapshot()
    return {
        "elapsed_seconds": elapsed,
        "cpu": _cpu_usage_delta(
            cpu_before,
            cpu_after,
            record_count=record_count,
            elapsed_seconds=elapsed,
        ),
    }


def _cpu_usage_snapshot() -> JsonObject:
    """Capture cumulative user and system CPU for the current process."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
    }


def _cpu_usage_delta(
    before: JsonObject,
    after: JsonObject,
    *,
    record_count: int,
    elapsed_seconds: float,
) -> JsonObject:
    """Normalize a process CPU delta by records and the measured wall window."""
    user_seconds = float(after["user_seconds"]) - float(before["user_seconds"])
    system_seconds = float(after["system_seconds"]) - float(
        before["system_seconds"]
    )
    total_seconds = user_seconds + system_seconds
    errors: list[str] = []
    if user_seconds < 0 or system_seconds < 0:
        errors.append("CPU counters moved backwards")
    if record_count <= 0 or elapsed_seconds <= 0:
        errors.append(
            f"invalid CPU denominators: records={record_count} elapsed={elapsed_seconds}"
        )
    if total_seconds <= 0:
        errors.append("CPU delta is zero")
    return {
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_record": (
            total_seconds / record_count if record_count > 0 else None
        ),
        "average_cores": (
            total_seconds / elapsed_seconds if elapsed_seconds > 0 else None
        ),
        "errors": errors,
        "passed": not errors,
    }


def _run_private_sequence(
    variant: str,
    path: Path,
    candidate_source: str | None,
    producer: int,
    record_count: int,
) -> JsonObject:
    """Open, write, and close one single-process sequence without leaking handlers."""
    handler = _make_handler(variant, path, candidate_source)
    try:
        return _write_records(handler, producer, record_count)
    finally:
        handler.close()


def _decode_mount_field(value: str) -> str:
    """Decode the octal escapes used for paths and sources in mountinfo."""
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _filesystem_information(path: Path) -> JsonObject:
    """Find the longest Linux mountinfo entry containing the benchmark directory."""
    resolved = path.resolve()
    best_match: JsonObject | None = None
    best_length = -1
    try:
        mount_lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BenchmarkFailure(f"cannot read Linux mount information: {exc}") from exc

    for line in mount_lines:
        left, separator, right = line.partition(" - ")
        left_fields = left.split()
        right_fields = right.split()
        if not separator or len(left_fields) < 6 or len(right_fields) < 2:
            continue
        mount_point = Path(_decode_mount_field(left_fields[4])).resolve()
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        if len(str(mount_point)) <= best_length:
            continue
        filesystem_type = right_fields[0]
        best_length = len(str(mount_point))
        best_match = {
            "mount_point": str(mount_point),
            "type": filesystem_type,
            "source": _decode_mount_field(right_fields[1]),
            "device": left_fields[2],
            "local": filesystem_type.lower() in LOCAL_FILESYSTEMS,
        }

    if best_match is None:
        raise BenchmarkFailure(f"no Linux mountinfo entry contains {resolved}")
    return best_match


def _cpu_information() -> JsonObject:
    """Record CPU identity plus the logical and scheduler-visible processor counts."""
    models: set[str] = set()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Hardware", "Processor"}:
                models.add(value.strip())
    except OSError:
        pass
    affinity_count: int | None
    try:
        affinity_count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity_count = None
    return {
        "models": sorted(model for model in models if model),
        "logical_count": os.cpu_count(),
        "affinity_count": affinity_count,
    }


def _machine_information(path: Path) -> JsonObject:
    """Describe the exact Linux, Python, filesystem, and CPU benchmark environment."""
    uname = platform.uname()
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
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
        },
        "filesystem": _filesystem_information(path),
        "cpu": _cpu_information(),
    }


def _validate_environment(machine: JsonObject) -> None:
    """Reject platforms outside the explicit Linux local-filesystem gate contract."""
    kernel = machine["kernel"]
    filesystem = machine["filesystem"]
    if kernel["system"] != "Linux":
        raise BenchmarkFailure("handler performance gate requires Linux")
    if not filesystem["local"]:
        raise BenchmarkFailure(
            f"handler performance gate requires a local filesystem, got {filesystem['type']}"
        )


def _validate_output(
    path: Path,
    producer_count: int,
    records_per_producer: int,
) -> JsonObject:
    """Check complete unique records and prove that no timed sidecar was created."""
    rotation_files = sorted(
        candidate.name for candidate in path.parent.glob(f"{path.name}.*")
    )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        checks = {
            "output_readable": False,
            "utf8_valid": False,
            "newline_terminated": False,
            "ansi_free": False,
            "exact_line_count": False,
            "all_lines_well_formed": False,
            "unique_producer_sequence": False,
            "exact_producer_sequence_set": False,
            "no_rotation_files": not rotation_files,
        }
        return {
            "passed": False,
            "checks": checks,
            "error": f"{type(exc).__name__}: {exc}",
            "expected_records": producer_count * records_per_producer,
            "observed_lines": 0,
            "observed_unique_pairs": 0,
            "duplicate_pairs": 0,
            "missing_pairs": producer_count * records_per_producer,
            "unexpected_pairs": 0,
            "malformed_samples": [],
            "rotation_files": rotation_files,
            "bytes": 0,
        }
    utf8_valid = True
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        utf8_valid = False
        text = ""

    newline_terminated = bool(payload) and payload.endswith(b"\n")
    ansi_free = b"\x1b" not in payload
    lines = text.splitlines() if utf8_valid else []
    observed: Counter[tuple[int, int]] = Counter()
    malformed_samples: list[str] = []
    for line in lines:
        match = EXPECTED_LINE.fullmatch(line)
        if match is None:
            if len(malformed_samples) < 5:
                malformed_samples.append(line[:240])
            continue
        observed[(int(match.group(1)), int(match.group(2)))] += 1

    expected = {
        (producer, sequence)
        for producer in range(producer_count)
        for sequence in range(records_per_producer)
    }
    observed_pairs = set(observed)
    duplicate_count = sum(count - 1 for count in observed.values() if count > 1)
    missing = expected - observed_pairs
    unexpected = observed_pairs - expected
    expected_count = producer_count * records_per_producer
    checks = {
        "output_readable": True,
        "utf8_valid": utf8_valid,
        "newline_terminated": newline_terminated,
        "ansi_free": ansi_free,
        "exact_line_count": len(lines) == expected_count,
        "all_lines_well_formed": not malformed_samples and len(observed) == len(lines),
        "unique_producer_sequence": duplicate_count == 0,
        "exact_producer_sequence_set": not missing and not unexpected,
        "no_rotation_files": not rotation_files,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "expected_records": expected_count,
        "observed_lines": len(lines),
        "observed_unique_pairs": len(observed_pairs),
        "duplicate_pairs": duplicate_count,
        "missing_pairs": len(missing),
        "unexpected_pairs": len(unexpected),
        "malformed_samples": malformed_samples,
        "rotation_files": rotation_files,
        "bytes": len(payload),
    }


def _base_run_result(variant: str, path: Path, records: int) -> JsonObject:
    """Create a JSON-safe run shell before any operation that could fail."""
    return {
        "variant": variant,
        "file": path.name,
        "records": records,
        "elapsed_seconds": None,
        "records_per_second": None,
        "cpu": None,
        "correctness": None,
        "error": None,
    }


def _single_sequence_run(
    variant: str,
    path: Path,
    candidate_source: str | None,
    record_count: int,
) -> JsonObject:
    """Run one sequence while retaining timing and validation details on failure."""
    result = _base_run_result(variant, path, record_count)
    try:
        measurement = _run_private_sequence(
            variant,
            path,
            candidate_source,
            producer=0,
            record_count=record_count,
        )
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    else:
        elapsed = float(measurement["elapsed_seconds"])
        result["elapsed_seconds"] = elapsed
        result["records_per_second"] = record_count / elapsed
        result["cpu"] = measurement["cpu"]
        if not measurement["cpu"]["passed"]:
            result["error"] = f"CPU measurement failed: {measurement['cpu']}"

    correctness = _validate_output(path, 1, record_count)
    result["correctness"] = correctness
    if not correctness["passed"] and result["error"] is None:
        result["error"] = f"correctness failed: {correctness}"
    return result


def _single_run(
    variant: str,
    path: Path,
    candidate_source: str | None,
) -> JsonObject:
    """Measure and validate exactly 100,000 records from one process."""
    return _single_sequence_run(
        variant,
        path,
        candidate_source,
        SINGLE_RECORDS,
    )


def _multiprocess_worker(
    variant: str,
    candidate_source: str | None,
    measured_path: str,
    warmup_path: str,
    producer: int,
    ready_barrier: Any,
    start_barrier: Any,
    result_connection: Connection,
) -> None:
    """Warm one spawned child, synchronize its start, and report bounded results."""
    try:
        _run_private_sequence(
            variant,
            Path(warmup_path),
            candidate_source,
            producer,
            WORKER_WARMUP_RECORDS,
        )
        handler = _make_handler(variant, Path(measured_path), candidate_source)
        try:
            ready_barrier.wait(timeout=STARTUP_TIMEOUT_SECONDS)
            start_barrier.wait(timeout=STARTUP_TIMEOUT_SECONDS)
            measurement = _write_records(handler, producer, RECORDS_PER_WORKER)
        finally:
            handler.close()
        _send_worker_report(
            result_connection,
            {
                "ok": True,
                "pid": os.getpid(),
                "producer": producer,
                "elapsed_seconds": measurement["elapsed_seconds"],
                "records_per_second": (
                    RECORDS_PER_WORKER / measurement["elapsed_seconds"]
                ),
                "cpu": measurement["cpu"],
            },
        )
    except BaseException as exc:
        try:
            _send_worker_report(
                result_connection,
                {
                    "ok": False,
                    "pid": os.getpid(),
                    "producer": producer,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
            )
        finally:
            result_connection.close()
        raise
    else:
        result_connection.close()


def _serialize_worker_report(report: JsonObject) -> bytes:
    """Serialize one report deterministically without mutating the source object."""
    return json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _encode_worker_report(report: JsonObject) -> bytes:
    """Encode one atomic-size report, preserving bounded failure evidence if truncated."""
    original_payload = _serialize_worker_report(report)
    if len(original_payload) <= MAX_WORKER_REPORT_BYTES:
        return original_payload

    error_text = str(report.get("error", ""))
    traceback_text = str(report.get("traceback", ""))
    error_type = error_text.partition(":")[0][:128]
    truncated: JsonObject = {
        "ok": bool(report.get("ok", False)),
        "pid": report.get("pid") if isinstance(report.get("pid"), int) else None,
        "producer": (
            report.get("producer")
            if isinstance(report.get("producer"), int)
            else None
        ),
        "error_type": error_type,
        "error": error_text[:512],
        "traceback_head": traceback_text[:1200],
        "traceback_tail": traceback_text[-1200:],
        "report_truncated": True,
        "original_size_bytes": len(original_payload),
    }
    # JSON escaping can expand control-heavy text, so shrink the three variable
    # fields until the encoded frame—not merely the Python character count—fits.
    for _ in range(16):
        payload = _serialize_worker_report(truncated)
        if len(payload) <= MAX_WORKER_REPORT_BYTES:
            return payload
        for field_name in ("error", "traceback_head", "traceback_tail"):
            value = str(truncated[field_name])
            reduced_length = len(value) // 2
            truncated[field_name] = (
                value[-reduced_length:]
                if field_name == "traceback_tail" and reduced_length
                else value[:reduced_length]
            )

    fallback: JsonObject = {
        "ok": bool(report.get("ok", False)),
        "pid": report.get("pid") if isinstance(report.get("pid"), int) else None,
        "producer": (
            report.get("producer")
            if isinstance(report.get("producer"), int)
            else None
        ),
        "error_type": error_type[:64],
        "error": error_text[:64],
        "traceback_head": traceback_text[:128],
        "traceback_tail": traceback_text[-128:],
        "report_truncated": True,
        "report_fallback": True,
        "original_size_bytes": len(original_payload),
    }
    fallback_payload = _serialize_worker_report(fallback)
    if len(fallback_payload) > MAX_WORKER_REPORT_BYTES:
        raise BenchmarkFailure("minimal worker failure report exceeds atomic frame limit")
    return fallback_payload


def _send_worker_report(connection: Connection, report: JsonObject) -> None:
    """Send one atomically writable UTF-8 JSON frame through the public protocol."""
    connection.send_bytes(_encode_worker_report(report))


def _decode_worker_report(payload: bytes) -> JsonObject:
    """Decode one bounded JSON frame and reject non-object worker messages."""
    try:
        report = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkFailure(
            f"multiprocess worker returned invalid JSON: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(report, dict):
        raise BenchmarkFailure("multiprocess worker returned a non-object report")
    return report


def _worker_report_key(report: JsonObject) -> str:
    """Build the stable producer/PID identity used to reject duplicate reports."""
    pid = report.get("pid")
    producer = report.get("producer")
    if not isinstance(pid, int) or not isinstance(producer, int):
        raise BenchmarkFailure(
            "multiprocess worker report lacks integer pid/producer identity"
        )
    return f"pid={pid}:producer={producer}"


def _append_worker_report(
    report: JsonObject,
    reports: list[JsonObject],
    report_keys: set[str],
    duplicate_reports: list[JsonObject],
) -> None:
    """Retain the first report for one key and record duplicates without overwrite."""
    report_key = _worker_report_key(report)
    retained_report = {"report_key": report_key, **report}
    if report_key in report_keys:
        duplicate_reports.append(retained_report)
        return
    report_keys.add(report_key)
    reports.append(retained_report)


def _drain_worker_reports(
    connections: list[Connection],
    deadline: float,
    reports: list[JsonObject],
    report_keys: set[str],
    duplicate_reports: list[JsonObject],
) -> list[str]:
    """Drain every ready pipe within one strict global deadline before closing it."""
    pending = list(connections)
    errors: list[str] = []
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            ready = cast(list[Connection], wait(pending, timeout=remaining))
        except (OSError, ValueError) as exc:
            errors.append(f"report drain wait failed: {type(exc).__name__}: {exc}")
            break
        if not ready:
            break
        for connection in ready:
            try:
                payload = connection.recv_bytes(maxlength=MAX_WORKER_REPORT_BYTES)
            except EOFError:
                pending.remove(connection)
                continue
            except (OSError, ValueError) as exc:
                pending.remove(connection)
                errors.append(
                    f"report drain receive failed: {type(exc).__name__}: {exc}"
                )
                continue
            try:
                report = _decode_worker_report(payload)
            except BenchmarkFailure as exc:
                errors.append(f"report drain rejected worker report: {exc}")
                continue
            try:
                _append_worker_report(
                    report,
                    reports,
                    report_keys,
                    duplicate_reports,
                )
            except BenchmarkFailure as exc:
                errors.append(f"report drain rejected worker report: {exc}")
    return errors


def _bounded_process_cleanup(processes: list[Any]) -> list[JsonObject]:
    """Join every PID, escalating through terminate and kill within fixed timeouts."""
    cleanup: list[JsonObject] = []
    deadline = time.monotonic() + EXIT_TIMEOUT_SECONDS
    for process in processes:
        process.join(max(0.0, deadline - time.monotonic()))

    for process in processes:
        action = "joined"
        if process.is_alive():
            action = "terminated"
            process.terminate()
            process.join(TERMINATE_TIMEOUT_SECONDS)
        if process.is_alive():
            action = "killed"
            process.kill()
            process.join(TERMINATE_TIMEOUT_SECONDS)
        cleanup.append(
            {
                "pid": process.pid,
                "exit_code": process.exitcode,
                "action": action,
                "alive_after_cleanup": process.is_alive(),
            }
        )
    return cleanup


def _unsafe_report_drain_reason(
    processes: list[Any],
    connections: list[Connection],
    cleanup: list[JsonObject],
    cleanup_error: BaseException | None,
) -> str | None:
    """Explain why receiving framed bytes is unsafe until every writer is reaped."""
    reasons: list[str] = []
    if cleanup_error is not None:
        reasons.append(
            f"cleanup raised {type(cleanup_error).__name__}: {cleanup_error}"
        )
    if len(cleanup) != len(processes):
        reasons.append(
            f"cleanup entries {len(cleanup)} do not match processes {len(processes)}"
        )
    if len(connections) != len(processes):
        reasons.append(
            f"connections {len(connections)} do not match processes {len(processes)}"
        )
    alive_pids = [
        item.get("pid") for item in cleanup if item.get("alive_after_cleanup") is not False
    ]
    if alive_pids:
        reasons.append(f"writers remain or are unverified: {alive_pids}")
    if not reasons:
        return None
    return "unsafe to drain because writers remain/unverified: " + "; ".join(reasons)


def _aggregate_worker_cpu(
    reports: list[JsonObject],
    *,
    record_count: int,
    elapsed_seconds: float,
) -> JsonObject:
    """Sum measured child CPU without including parent orchestration overhead."""
    errors: list[str] = []
    user_seconds = 0.0
    system_seconds = 0.0
    for index, report in enumerate(reports):
        cpu = report.get("cpu")
        if not isinstance(cpu, dict) or cpu.get("passed") is not True:
            errors.append(f"worker report {index} has invalid CPU evidence: {cpu!r}")
            continue
        try:
            user_seconds += float(cpu["user_seconds"])
            system_seconds += float(cpu["system_seconds"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"worker report {index} has invalid CPU values: {cpu!r}")
    if record_count <= 0 or elapsed_seconds <= 0:
        errors.append(
            f"invalid CPU denominators: records={record_count} elapsed={elapsed_seconds}"
        )
    total_seconds = user_seconds + system_seconds
    if total_seconds <= 0:
        errors.append("aggregate worker CPU delta is zero")
    return {
        "worker_reports": len(reports),
        "user_seconds": user_seconds,
        "system_seconds": system_seconds,
        "total_seconds": total_seconds,
        "seconds_per_record": (
            total_seconds / record_count if record_count > 0 else None
        ),
        "average_cores": (
            total_seconds / elapsed_seconds if elapsed_seconds > 0 else None
        ),
        "errors": errors,
        "passed": not errors,
    }


def _multiprocess_run(
    variant: str,
    path: Path,
    candidate_source: str | None,
) -> JsonObject:
    """Measure four spawn writers and retain proof that every child PID was reaped."""
    total_records = WORKER_COUNT * RECORDS_PER_WORKER
    result = _base_run_result(variant, path, total_records)
    reports: list[JsonObject] = []
    report_keys: set[str] = set()
    duplicate_reports: list[JsonObject] = []
    result["workers"] = reports
    result["duplicate_worker_reports"] = duplicate_reports
    result["pid_cleanup"] = []
    result["report_drain_errors"] = []
    context: Any = multiprocessing.get_context("spawn")
    ready_barrier = context.Barrier(WORKER_COUNT + 1)
    start_barrier = context.Barrier(WORKER_COUNT + 1)
    processes: list[Any] = []
    receive_connections: list[Connection] = []
    elapsed: float | None = None
    started_at: float | None = None
    cleanup: list[JsonObject] = []
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    drain_errors: list[str] = []

    try:
        for producer in range(WORKER_COUNT):
            receive_connection, send_connection = context.Pipe(duplex=False)
            process = context.Process(
                target=_multiprocess_worker,
                args=(
                    variant,
                    candidate_source,
                    str(path),
                    str(path.with_name(f"{path.stem}-warmup-{producer}.log")),
                    producer,
                    ready_barrier,
                    start_barrier,
                    send_connection,
                ),
            )
            try:
                process.start()
            except BaseException:
                receive_connection.close()
                send_connection.close()
                raise
            processes.append(process)
            receive_connections.append(receive_connection)
            # The spawned child owns its duplicate; the parent must not keep a writer open.
            send_connection.close()

        ready_barrier.wait(timeout=STARTUP_TIMEOUT_SECONDS)
        started_at = time.perf_counter()
        start_barrier.wait(timeout=STARTUP_TIMEOUT_SECONDS)
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            cleanup = _bounded_process_cleanup(processes)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            if started_at is not None:
                elapsed = time.perf_counter() - started_at
            unsafe_drain_reason = _unsafe_report_drain_reason(
                processes,
                receive_connections,
                cleanup,
                cleanup_error,
            )
            if unsafe_drain_reason is None:
                # With every sender reaped, a partial frame reaches EOF instead of
                # blocking recv_bytes while the 0.25s deadline bounds readiness.
                drain_errors = _drain_worker_reports(
                    receive_connections,
                    time.monotonic() + REPORT_DRAIN_TIMEOUT_SECONDS,
                    reports,
                    report_keys,
                    duplicate_reports,
                )
            else:
                drain_errors = [unsafe_drain_reason]
            for connection in receive_connections:
                try:
                    connection.close()
                except OSError as exc:
                    drain_errors.append(
                        f"report connection close failed: {type(exc).__name__}: {exc}"
                    )

    result["pid_cleanup"] = cleanup
    result["report_drain_errors"] = drain_errors
    if elapsed is not None and elapsed > 0:
        result["elapsed_seconds"] = elapsed
        result["records_per_second"] = total_records / elapsed
        result["cpu"] = _aggregate_worker_cpu(
            reports,
            record_count=total_records,
            elapsed_seconds=elapsed,
        )

    errors: list[str] = []
    child_failures = [report for report in reports if not report.get("ok")]
    lifecycle_failed = any(
        item["alive_after_cleanup"]
        or item["exit_code"] != 0
        or item["action"] != "joined"
        for item in cleanup
    )
    if primary_error is not None:
        errors.append(
            f"multiprocess run failed: {type(primary_error).__name__}: {primary_error}; "
            f"cleanup={cleanup}"
        )
    if cleanup_error is not None:
        errors.append(
            f"multiprocess cleanup failed: {type(cleanup_error).__name__}: "
            f"{cleanup_error}"
        )
    if drain_errors:
        errors.append(f"multiprocess report drain failed: {drain_errors}")
    if duplicate_reports:
        errors.append(
            "multiprocess duplicate worker reports: "
            f"{[report['report_key'] for report in duplicate_reports]}"
        )
    if child_failures:
        errors.append(f"multiprocess child failure: {child_failures}")
    if len(reports) != WORKER_COUNT:
        errors.append(
            f"expected {WORKER_COUNT} worker reports, got {len(reports)}"
        )
    if lifecycle_failed:
        errors.append(f"multiprocess PID cleanup failed: {cleanup}")
    cpu = result.get("cpu")
    if not isinstance(cpu, dict) or not cpu.get("passed"):
        errors.append(f"multiprocess CPU measurement failed: {cpu!r}")

    correctness = _validate_output(
        path,
        WORKER_COUNT,
        RECORDS_PER_WORKER,
    )
    result["correctness"] = correctness
    if not correctness["passed"]:
        errors.append(f"correctness failed: {correctness}")
    result["error"] = "; ".join(errors) if errors else None
    return result


def _exception_run_result(
    variant: str,
    path: Path,
    records: int,
    producer_count: int,
    records_per_producer: int,
    exc: BaseException,
    *,
    multiprocess_run: bool,
) -> JsonObject:
    """Preserve an unexpected run exception in the same raw-result shape."""
    result = _base_run_result(variant, path, records)
    result["correctness"] = _validate_output(
        path,
        producer_count,
        records_per_producer,
    )
    result["error"] = f"{type(exc).__name__}: {exc}"
    if multiprocess_run:
        result["workers"] = []
        result["duplicate_worker_reports"] = []
        result["pid_cleanup"] = []
        result["report_drain_errors"] = []
    return result


def _warmup_run(
    scenario: str,
    variant: str,
    root: Path,
    candidate_source: str | None,
) -> JsonObject:
    """Warm one variant and return its complete raw result before measurement."""
    path = root / f"warmup-{scenario}-{variant}.log"
    if scenario == "single_process":
        run = _single_sequence_run(
            variant,
            path,
            candidate_source,
            SINGLE_WARMUP_RECORDS,
        )
    elif scenario == "four_process":
        # A multiprocess run performs an additional private warmup in every child.
        run = _multiprocess_run(variant, path, candidate_source)
    else:
        raise BenchmarkFailure(f"unknown benchmark scenario: {scenario}")
    run["warmup"] = True
    return run


def _empty_scenario_result(scenario: str) -> JsonObject:
    """Register a scenario before warmup so partial work always remains in JSON."""
    return {
        "scenario": scenario,
        "status": "pending",
        "passed": False,
        "failure_kind": None,
        "errors": [],
        "warmup": [],
        "rounds": [],
        "summary": None,
    }


def _record_run_failure(
    scenario_result: JsonObject,
    run: JsonObject,
    label: str,
) -> bool:
    """Mark a retained raw run as fatal after its details are already appended."""
    correctness = run.get("correctness")
    correctness_failed = (
        isinstance(correctness, dict) and not correctness.get("passed", False)
    )
    error = run.get("error")
    if error is None and correctness_failed:
        error = f"correctness failed: {correctness}"
        run["error"] = error
    if error is None:
        return False
    scenario_result["status"] = "failed"
    scenario_result["failure_kind"] = (
        "correctness" if correctness_failed else "execution"
    )
    scenario_result["errors"].append(f"{label}: {error}")
    return True


def _scenario_summary(runs: list[JsonObject]) -> JsonObject:
    """Summarize throughput gate and diagnostic CPU cost across five rounds."""
    current_runs = [run for run in runs if run["variant"] == "current"]
    reference_runs = [run for run in runs if run["variant"] == "reference"]
    if len(current_runs) != ROUNDS or len(reference_runs) != ROUNDS:
        raise BenchmarkFailure("scenario did not produce exactly five A/B rounds")
    current_elapsed = statistics.median(run["elapsed_seconds"] for run in current_runs)
    reference_elapsed = statistics.median(
        run["elapsed_seconds"] for run in reference_runs
    )
    current_rate = statistics.median(
        run["records_per_second"] for run in current_runs
    )
    reference_rate = statistics.median(
        run["records_per_second"] for run in reference_runs
    )
    current_cpu_per_record = statistics.median(
        run["cpu"]["seconds_per_record"] for run in current_runs
    )
    reference_cpu_per_record = statistics.median(
        run["cpu"]["seconds_per_record"] for run in reference_runs
    )
    current_average_cores = statistics.median(
        run["cpu"]["average_cores"] for run in current_runs
    )
    reference_average_cores = statistics.median(
        run["cpu"]["average_cores"] for run in reference_runs
    )
    ratio = current_rate / reference_rate
    return {
        "current": {
            "median_elapsed_seconds": current_elapsed,
            "median_records_per_second": current_rate,
        },
        "reference": {
            "median_elapsed_seconds": reference_elapsed,
            "median_records_per_second": reference_rate,
        },
        "current_to_reference_ratio": ratio,
        "cpu": {
            "current_median_seconds_per_record": current_cpu_per_record,
            "reference_median_seconds_per_record": reference_cpu_per_record,
            "current_median_average_cores": current_average_cores,
            "reference_median_average_cores": reference_average_cores,
            "current_to_reference_ratio": (
                current_cpu_per_record / reference_cpu_per_record
            ),
            "lower_is_better": True,
            "gating": False,
        },
        "minimum_ratio": MINIMUM_RATIO,
        "passed": ratio >= MINIMUM_RATIO,
    }


def _run_scenario(
    scenario: str,
    root: Path,
    candidate_source: str | None,
    scenario_result: JsonObject,
) -> JsonObject:
    """Populate one pre-registered scenario, retaining any partial or failed run."""
    for variant in ("current", "reference"):
        path = root / f"warmup-{scenario}-{variant}.log"
        try:
            run = _warmup_run(scenario, variant, root, candidate_source)
        except BaseException as exc:
            producer_count = 1 if scenario == "single_process" else WORKER_COUNT
            records_per_producer = (
                SINGLE_WARMUP_RECORDS
                if scenario == "single_process"
                else RECORDS_PER_WORKER
            )
            run = _exception_run_result(
                variant,
                path,
                producer_count * records_per_producer,
                producer_count,
                records_per_producer,
                exc,
                multiprocess_run=scenario == "four_process",
            )
            run["warmup"] = True
        scenario_result["warmup"].append(run)
        if _record_run_failure(
            scenario_result,
            run,
            f"{scenario} warmup {variant}",
        ):
            return scenario_result

    flat_runs: list[JsonObject] = []
    for round_index in range(ROUNDS):
        order = (
            ["current", "reference"]
            if round_index % 2 == 0
            else ["reference", "current"]
        )
        round_result: JsonObject = {
            "round": round_index + 1,
            "order": order,
            "runs": [],
        }
        # Append the round before running either side so an exception cannot erase it.
        scenario_result["rounds"].append(round_result)
        for order_index, variant in enumerate(order):
            path = root / (
                f"measured-{scenario}-round-{round_index + 1}-"
                f"order-{order_index + 1}-{variant}.log"
            )
            try:
                if scenario == "single_process":
                    run = _single_run(variant, path, candidate_source)
                elif scenario == "four_process":
                    run = _multiprocess_run(variant, path, candidate_source)
                else:
                    raise BenchmarkFailure(f"unknown benchmark scenario: {scenario}")
            except BaseException as exc:
                producer_count = 1 if scenario == "single_process" else WORKER_COUNT
                records_per_producer = (
                    SINGLE_RECORDS
                    if scenario == "single_process"
                    else RECORDS_PER_WORKER
                )
                run = _exception_run_result(
                    variant,
                    path,
                    producer_count * records_per_producer,
                    producer_count,
                    records_per_producer,
                    exc,
                    multiprocess_run=scenario == "four_process",
                )
            round_result["runs"].append(run)
            flat_runs.append(run)
            if _record_run_failure(
                scenario_result,
                run,
                f"{scenario} round {round_index + 1} {variant}",
            ):
                return scenario_result

    summary = _scenario_summary(flat_runs)
    scenario_result["summary"] = summary
    if summary["passed"]:
        scenario_result["status"] = "passed"
        scenario_result["passed"] = True
    else:
        ratio = summary["current_to_reference_ratio"]
        scenario_result["status"] = "failed"
        scenario_result["failure_kind"] = "threshold"
        scenario_result["errors"].append(
            f"current/reference ratio {ratio:.6f} is below {MINIMUM_RATIO:.2f}"
        )
    return scenario_result


def _configuration(candidate_source: Path | None) -> JsonObject:
    """Expose every fixed benchmark parameter and candidate provenance in JSON."""
    return {
        "candidate": (
            {
                "kind": "standalone_source_diagnostic",
                "source": str(candidate_source.resolve()),
            }
            if candidate_source is not None
            else {
                "kind": "current_checkout",
                "module": "oldman.logging.handlers",
            }
        ),
        "formatter": "oldman.logging.formatters.PlainTextFormatter",
        "format": FORMAT,
        "payload": PAYLOAD,
        "rounds": ROUNDS,
        "order": "A/B on odd rounds, B/A on even rounds",
        "single_process_records": SINGLE_RECORDS,
        "four_process_workers": WORKER_COUNT,
        "records_per_worker": RECORDS_PER_WORKER,
        "four_process_records": WORKER_COUNT * RECORDS_PER_WORKER,
        "single_warmup_records": SINGLE_WARMUP_RECORDS,
        "worker_private_warmup_records": WORKER_WARMUP_RECORDS,
        "reference_rollover_at": REFERENCE_ROLLOVER_AT,
        "max_worker_report_bytes": MAX_WORKER_REPORT_BYTES,
        "report_drain_timeout_seconds": REPORT_DRAIN_TIMEOUT_SECONDS,
        "allowed_local_filesystems": sorted(LOCAL_FILESYSTEMS),
        "multiprocessing_start_method": "spawn",
        "startup_timeout_seconds": STARTUP_TIMEOUT_SECONDS,
        "exit_timeout_seconds": EXIT_TIMEOUT_SECONDS,
        "minimum_current_to_reference_ratio": MINIMUM_RATIO,
    }


def _execute(candidate_source: Path | None) -> tuple[JsonObject, int]:
    """Run the complete gate once and return its JSON document and exit status."""
    single = _empty_scenario_result("single_process")
    four = _empty_scenario_result("four_process")
    result: JsonObject = {
        "schema_version": 1,
        "gate": "oldman_logging_handler_performance",
        "configuration": _configuration(candidate_source),
        "machine": None,
        # Register both scenarios before environment setup or execution can fail.
        "scenarios": {
            "single_process": single,
            "four_process": four,
        },
        "passed": False,
        "errors": [],
    }
    try:
        candidate_source_text = (
            str(candidate_source.resolve(strict=True))
            if candidate_source is not None
            else None
        )
        with tempfile.TemporaryDirectory(
            prefix=".logging-handler-benchmark-",
            dir=Path.cwd(),
        ) as temporary_directory:
            root = Path(temporary_directory)
            machine = _machine_information(root)
            result["machine"] = machine
            _validate_environment(machine)

            _run_scenario(
                "single_process",
                root,
                candidate_source_text,
                single,
            )
            if single["failure_kind"] in {"correctness", "execution"}:
                four["status"] = "not_run"
                four["failure_kind"] = "dependency"
                four["errors"].append(
                    "not run after fatal single-process correctness/execution failure"
                )
            else:
                _run_scenario(
                    "four_process",
                    root,
                    candidate_source_text,
                    four,
                )
    except BaseException as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        # Preserve completed data and explicitly account for scenarios not reached.
        for scenario_result in result["scenarios"].values():
            if scenario_result["status"] == "pending":
                scenario_result["status"] = "not_run"
                scenario_result["failure_kind"] = "execution"
                scenario_result["errors"].append(
                    "not run because benchmark execution raised an exception"
                )

    for scenario_name, scenario_result in result["scenarios"].items():
        result["errors"].extend(
            f"{scenario_name}: {error}" for error in scenario_result["errors"]
        )
    result["passed"] = not result["errors"] and all(
        scenario_result["passed"]
        for scenario_result in result["scenarios"].values()
    )
    return result, 0 if result["passed"] else 1


def main() -> int:
    """Parse arguments, print one complete machine-readable JSON result, and exit."""
    arguments = _build_parser().parse_args()
    result, exit_code = _execute(arguments.candidate_source)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
