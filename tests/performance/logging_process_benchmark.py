"""Benchmark SimpleApplication and its supported child-process models.

The no-argument release run compares Oldman's current logging, the Python
standard-library timed file handler, and logging disabled.  ``--smoke`` keeps the
same topology with smaller record counts.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

type HandlerVariant = Literal["current", "stdlib", "no_logging"]
type JsonObject = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "logging_process_performance_service.py"

RELEASE_ROUNDS = 6
RELEASE_MAIN_RECORDS = 20_000
RELEASE_BASE_RECORDS = 10_000
RELEASE_ASYNC_RECORDS = 2_000
RELEASE_ASYNC_RUNS = 4
RELEASE_SUBPROCESS_BYTES = 1_048_576
MINIMUM_THROUGHPUT_RATIO = 0.98
MAXIMUM_CPU_RATIO = 1.05

SMOKE_ROUNDS = 1
SMOKE_MAIN_RECORDS = 200
SMOKE_BASE_RECORDS = 100
SMOKE_ASYNC_RECORDS = 50
SMOKE_ASYNC_RUNS = 2
SMOKE_SUBPROCESS_BYTES = 65_536

RUN_TIMEOUT_SECONDS = 90.0
GROUP_EXIT_TIMEOUT_SECONDS = 5.0
ANSI_ESCAPE = b"\x1b"


class BenchmarkFailure(RuntimeError):
    """Signal invalid evidence or incomplete process cleanup."""


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Hold immutable release values or the fixed smoke profile."""

    mode: Literal["release", "smoke"]
    rounds: int
    main_records: int
    base_records: int
    async_records: int
    async_runs: int
    subprocess_bytes: int


def _build_parser() -> argparse.ArgumentParser:
    """Build the intentionally small release/smoke command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    return parser


def _config(smoke: bool) -> BenchmarkConfig:
    """Return one frozen workload without ad-hoc count overrides."""
    if smoke:
        return BenchmarkConfig(
            mode="smoke",
            rounds=SMOKE_ROUNDS,
            main_records=SMOKE_MAIN_RECORDS,
            base_records=SMOKE_BASE_RECORDS,
            async_records=SMOKE_ASYNC_RECORDS,
            async_runs=SMOKE_ASYNC_RUNS,
            subprocess_bytes=SMOKE_SUBPROCESS_BYTES,
        )
    return BenchmarkConfig(
        mode="release",
        rounds=RELEASE_ROUNDS,
        main_records=RELEASE_MAIN_RECORDS,
        base_records=RELEASE_BASE_RECORDS,
        async_records=RELEASE_ASYNC_RECORDS,
        async_runs=RELEASE_ASYNC_RUNS,
        subprocess_bytes=RELEASE_SUBPROCESS_BYTES,
    )


def _round_order(
    round_number: int,
) -> tuple[HandlerVariant, HandlerVariant, HandlerVariant]:
    """Balance every position and pairwise before/after order over six rounds."""
    orders: tuple[
        tuple[HandlerVariant, HandlerVariant, HandlerVariant],
        ...,
    ] = (
        ("current", "stdlib", "no_logging"),
        ("stdlib", "no_logging", "current"),
        ("no_logging", "current", "stdlib"),
        ("no_logging", "stdlib", "current"),
        ("current", "no_logging", "stdlib"),
        ("stdlib", "current", "no_logging"),
    )
    return orders[(round_number - 1) % len(orders)]


def _process_group_pids(process_group: int) -> list[int]:
    """List live non-zombie Linux processes in one fixture group."""
    pids: list[int] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            suffix = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            state = suffix[0]
            group = int(suffix[2])
        except (IndexError, OSError, ValueError):
            continue
        if group == process_group and state != "Z":
            pids.append(int(stat_path.parent.name))
    return sorted(pids)


def _wait_for_group_exit(process_group: int, timeout: float) -> list[int]:
    """Wait within one deadline and return any remaining process IDs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = _process_group_pids(process_group)
        if not remaining:
            return []
        time.sleep(0.02)
    return _process_group_pids(process_group)


def _stop_process(process: subprocess.Popen[bytes]) -> JsonObject:
    """Bound fixture completion and forcibly clean its group only on failure."""
    action = "natural_exit"
    try:
        process.wait(timeout=RUN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        action = "sigkill"
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    remaining = _wait_for_group_exit(process.pid, GROUP_EXIT_TIMEOUT_SECONDS)
    if remaining:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        remaining = _wait_for_group_exit(process.pid, 5)
    return {
        "action": action,
        "exit_code": process.returncode,
        "remaining_group_pids": remaining,
        "passed": action == "natural_exit" and process.returncode == 0 and not remaining,
    }


def _read_result(path: Path) -> JsonObject:
    """Read one fixture result as a JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BenchmarkFailure(f"fixture result is not an object: {value!r}")
    return cast(JsonObject, value)


def _sequence_counts(text: str, token: str) -> dict[str, Counter[int]]:
    """Parse every performance label and sequence for one unique run token."""
    pattern = re.compile(
        rf"PROCESS_PERF token={re.escape(token)} label=([^ ]+) sequence=(\d{{8}})"
    )
    observed: dict[str, Counter[int]] = {}
    for label, sequence in pattern.findall(text):
        observed.setdefault(label, Counter())[int(sequence)] += 1
    return observed


def _expected_labels(result: JsonObject, config: BenchmarkConfig) -> dict[str, int]:
    """Build exact dynamic label counts from the PIDs returned by real children."""
    base = cast(JsonObject, result["base_manager"])
    async_result = cast(JsonObject, result["async_manager"])
    labels = {"simple_application": config.main_records}
    for generation in ("first", "replacement"):
        child = cast(JsonObject, base[generation])
        labels[str(child["label"])] = config.base_records
    for child in cast(list[JsonObject], async_result["runs"]):
        labels[str(child["label"])] = config.async_records
    recovery = cast(JsonObject, async_result["recovery"])
    labels[str(recovery["label"])] = config.async_records
    return labels


def _validate_log_output(
    log_dir: Path,
    app_name: str,
    token: str,
    variant: HandlerVariant,
    result: JsonObject,
    config: BenchmarkConfig,
) -> JsonObject:
    """Verify exact structured records, disabled output, UTF-8 and no ANSI bytes."""
    prefix = app_name.lower().strip().replace(" ", "_")
    path = log_dir / f"{prefix}.log"
    payload = path.read_bytes() if path.exists() else b""
    errors: list[str] = []
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        text = ""
        errors.append(f"main log is not UTF-8: {exc}")
    if ANSI_ESCAPE in payload:
        errors.append("main log contains ANSI escapes")

    observed = _sequence_counts(text, token)
    expected = _expected_labels(result, config)
    if variant == "no_logging":
        if observed:
            errors.append(f"disabled logging emitted structured records: {observed}")
        if f"PROCESS_PERF_TIMEOUT token={token}" in text:
            errors.append("disabled logging emitted the timeout marker")
        if f"PROCESS_PERF_SIGKILL token={token}" in text:
            errors.append("disabled logging emitted the SIGKILL marker")
    else:
        if set(observed) != set(expected):
            errors.append(
                f"structured labels mismatch: expected={sorted(expected)} "
                f"observed={sorted(observed)}"
            )
        for label, count in expected.items():
            expected_sequences = Counter(range(count))
            if observed.get(label, Counter()) != expected_sequences:
                errors.append(f"label {label} sequence multiset mismatch")
        if text.count(f"PROCESS_PERF_TIMEOUT token={token}") != 1:
            errors.append("timeout marker count is not exactly one")
        if text.count(f"PROCESS_PERF_SIGKILL token={token}") != 1:
            errors.append("SIGKILL marker count is not exactly one")

    sidecars = sorted(candidate.name for candidate in log_dir.glob(f"{path.name}.*"))
    if sidecars:
        errors.append(f"unexpected rotation sidecars: {sidecars}")
    return {
        "file": path.name,
        "bytes": len(payload),
        "expected_labels": expected,
        "observed_labels": {label: sum(counts.values()) for label, counts in observed.items()},
        "sidecars": sidecars,
        "errors": errors,
        "passed": not errors,
    }


def _result_pids(result: JsonObject) -> set[int]:
    """Collect every application, manager, temporary and subprocess PID."""
    base = cast(JsonObject, result["base_manager"])
    async_result = cast(JsonObject, result["async_manager"])
    subprocess_result = cast(JsonObject, result["subprocess"])
    output = cast(JsonObject, subprocess_result["output"])
    cleanup = cast(JsonObject, subprocess_result["cleanup"])
    pids = {
        int(result["pid"]),
        int(cast(JsonObject, base["first"])["pid"]),
        int(cast(JsonObject, base["replacement"])["pid"]),
        int(cast(JsonObject, async_result["recovery"])["pid"]),
        int(output["inherited_pid"]),
        int(output["pipe_pid"]),
        int(cleanup["timeout_pid"]),
        int(cleanup["cancelled_pid"]),
    }
    pids.update(int(child["pid"]) for child in cast(list[JsonObject], async_result["runs"]))
    return pids


def _validate_result(
    result: JsonObject,
    variant: HandlerVariant,
    config: BenchmarkConfig,
) -> list[str]:
    """Return every semantic, CPU, recovery and cleanup failure from one run."""
    errors: list[str] = []
    if result.get("variant") != variant:
        errors.append(f"variant mismatch: {result.get('variant')!r}")
    simple = result.get("simple_application")
    if not isinstance(simple, dict) or simple.get("records") != config.main_records:
        errors.append("SimpleApplication result is incomplete")
    base = result.get("base_manager")
    if not isinstance(base, dict) or base.get("restart_completed") is not True:
        errors.append("BaseManager restart did not complete")
    elif cast(JsonObject, base["first"]).get("pid") == cast(
        JsonObject, base["replacement"]
    ).get("pid"):
        errors.append("BaseManager replacement reused the first PID")
    async_result = result.get("async_manager")
    if not isinstance(async_result, dict):
        errors.append("AsyncProcessManager result is missing")
    else:
        if len(cast(list[Any], async_result.get("runs", []))) != config.async_runs:
            errors.append("AsyncProcessManager repeated run count is wrong")
        if async_result.get("timed_out") is not True:
            errors.append("AsyncProcessManager timeout did not propagate")
        if async_result.get("sigkill_result") is not None:
            errors.append("AsyncProcessManager abrupt child returned a fake result")
        recovery = async_result.get("recovery")
        if not isinstance(recovery, dict) or recovery.get("label") != "async_recovery":
            errors.append("AsyncProcessManager did not recover after timeout/SIGKILL")
    subprocess_result = result.get("subprocess")
    if not isinstance(subprocess_result, dict):
        errors.append("subprocess result is missing")
    else:
        output = cast(JsonObject, subprocess_result["output"])
        cleanup = cast(JsonObject, subprocess_result["cleanup"])
        if output.get("inherited_returncode") != 0 or output.get("pipe_returncode") != 0:
            errors.append("normal subprocess returned nonzero")
        if output.get("pipe_stdout_bytes") != config.subprocess_bytes:
            errors.append("PIPE stdout byte count is wrong")
        if output.get("pipe_stderr_bytes") != config.subprocess_bytes:
            errors.append("PIPE stderr byte count is wrong")
        if not isinstance(output.get("event_loop_ticks"), int) or output["event_loop_ticks"] <= 0:
            errors.append("PIPE subprocess blocked the event loop")
        for key in (
            "timed_out",
            "timeout_group_gone",
            "cancelled",
            "cancelled_group_gone",
        ):
            if cleanup.get(key) is not True:
                errors.append(f"subprocess cleanup flag {key} is not true")
        for key in (
            "timeout_group_pids_before_cleanup",
            "cancelled_group_pids_before_cleanup",
        ):
            observed = cleanup.get(key)
            if not isinstance(observed, list) or len(observed) < 2:
                errors.append(f"subprocess cleanup did not observe a descendant: {key}={observed!r}")
    live_pids = sorted(pid for pid in _result_pids(result) if Path(f"/proc/{pid}").exists())
    if live_pids:
        errors.append(f"owned child PIDs remain after application exit: {live_pids}")
    return errors


def _run_variant(
    root: Path,
    round_number: int,
    order_index: int,
    variant: HandlerVariant,
    config: BenchmarkConfig,
) -> JsonObject:
    """Run one fresh SimpleApplication and retain all correctness evidence."""
    run_id = uuid.uuid4().hex
    token = f"PROCESSPERF_{run_id.upper()}"
    app_name = f"process_perf_{round_number}_{order_index}_{run_id[:8]}"
    run_dir = root / f"r{round_number}-o{order_index}-{variant}"
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True)
    result_file = run_dir / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "OLDMAN_PROCESS_PERF_LOG_DIR": str(log_dir),
            "OLDMAN_PROCESS_PERF_RESULT_FILE": str(result_file),
            "OLDMAN_PROCESS_PERF_APP_NAME": app_name,
            "OLDMAN_PROCESS_PERF_TOKEN": token,
            "OLDMAN_PROCESS_PERF_VARIANT": variant,
            "OLDMAN_PROCESS_PERF_MAIN_RECORDS": str(config.main_records),
            "OLDMAN_PROCESS_PERF_BASE_RECORDS": str(config.base_records),
            "OLDMAN_PROCESS_PERF_ASYNC_RECORDS": str(config.async_records),
            "OLDMAN_PROCESS_PERF_ASYNC_RUNS": str(config.async_runs),
            "OLDMAN_PROCESS_PERF_SUBPROCESS_BYTES": str(config.subprocess_bytes),
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
    started_at = time.perf_counter()
    shutdown = _stop_process(process)
    elapsed = time.perf_counter() - started_at
    errors: list[str] = []
    result: JsonObject | None = None
    if not shutdown["passed"]:
        errors.append(f"fixture lifecycle failed: {shutdown}")
    try:
        result = _read_result(result_file)
    except BaseException as exc:
        errors.append(f"result read failed: {type(exc).__name__}: {exc}")
    validation: JsonObject | None = None
    log_validation: JsonObject | None = None
    if result is not None:
        semantic_errors = _validate_result(result, variant, config)
        validation = {"errors": semantic_errors, "passed": not semantic_errors}
        errors.extend(semantic_errors)
        log_validation = _validate_log_output(
            log_dir,
            app_name,
            token,
            variant,
            result,
            config,
        )
        if not log_validation["passed"]:
            errors.extend(cast(list[str], log_validation["errors"]))
    return {
        "round": round_number,
        "order_index": order_index,
        "variant": variant,
        "elapsed_seconds": elapsed,
        "fixture_pid": process.pid,
        "shutdown": shutdown,
        "result": result,
        "validation": validation,
        "log_validation": log_validation,
        "errors": errors,
        "passed": not errors,
    }


def _aggregate_child_sequences(children: list[JsonObject]) -> JsonObject:
    """Combine sequential child logger measurements without hiding CPU totals."""
    records = sum(int(child["records"]) for child in children)
    elapsed = sum(float(child["elapsed_seconds"]) for child in children)
    cpu_seconds = sum(float(cast(JsonObject, child["cpu"])["total_seconds"]) for child in children)
    return {
        "throughput": records / elapsed,
        "cpu_per_unit": cpu_seconds / records,
    }


def _scenario_metrics(run: JsonObject) -> dict[str, JsonObject]:
    """Extract comparable Simple, BaseManager, async and subprocess measurements."""
    result = cast(JsonObject, run["result"])
    simple = cast(JsonObject, result["simple_application"])
    base = cast(JsonObject, result["base_manager"])
    async_result = cast(JsonObject, result["async_manager"])
    output = cast(JsonObject, cast(JsonObject, result["subprocess"])["output"])
    base_children = [cast(JsonObject, base["first"]), cast(JsonObject, base["replacement"])]
    async_children = [*cast(list[JsonObject], async_result["runs"]), cast(JsonObject, async_result["recovery"])]
    return {
        "simple_application": {
            "throughput": float(simple["records_per_second"]),
            "cpu_per_unit": float(cast(JsonObject, simple["cpu"])["seconds_per_record"]),
        },
        "base_manager": _aggregate_child_sequences(base_children),
        "async_process_manager": _aggregate_child_sequences(async_children),
        "subprocess_pipe": {
            "throughput": (
                (int(output["pipe_stdout_bytes"]) + int(output["pipe_stderr_bytes"]))
                / float(output["pipe_elapsed_seconds"])
            ),
            "cpu_per_unit": float(cast(JsonObject, output["child_cpu"])["seconds_per_unit"]),
        },
    }


def _comparison(
    runs: list[JsonObject],
    expected_rounds: int,
    *,
    enforce: bool,
) -> JsonObject:
    """Summarize paired performance and enforce release-only logging thresholds."""
    by_round: dict[int, dict[HandlerVariant, JsonObject]] = {}
    for run in runs:
        raw_round = run.get("round")
        if not isinstance(raw_round, int) or isinstance(raw_round, bool):
            raise BenchmarkFailure(f"run has an invalid round number: {run}")
        raw_variant = run.get("variant")
        if raw_variant not in ("current", "stdlib", "no_logging"):
            raise BenchmarkFailure(f"run has an invalid variant: {run}")
        variant = cast(HandlerVariant, raw_variant)
        round_variants = by_round.setdefault(raw_round, {})
        if variant in round_variants:
            raise BenchmarkFailure(
                f"round {raw_round} has duplicate {variant} variant"
            )
        round_variants[variant] = run
    expected = set(range(1, expected_rounds + 1))
    if set(by_round) != expected:
        raise BenchmarkFailure(f"comparison rounds mismatch: {sorted(by_round)}")
    scenario_names = (
        "simple_application",
        "base_manager",
        "async_process_manager",
        "subprocess_pipe",
    )
    summaries: JsonObject = {}
    for scenario in scenario_names:
        values: dict[HandlerVariant, dict[str, list[float]]] = {
            variant: {"throughput": [], "cpu_per_unit": []}
            for variant in ("current", "stdlib", "no_logging")
        }
        paired: list[JsonObject] = []
        for round_number in range(1, expected_rounds + 1):
            variants = by_round[round_number]
            if set(variants) != {"current", "stdlib", "no_logging"}:
                raise BenchmarkFailure(
                    f"round {round_number} does not contain all three variants"
                )
            order_indexes = {
                variant: run.get("order_index")
                for variant, run in variants.items()
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
            order = tuple(
                cast(HandlerVariant, run["variant"])
                for run in sorted(
                    variants.values(),
                    key=lambda item: cast(int, item["order_index"]),
                )
            )
            if order != _round_order(round_number):
                raise BenchmarkFailure(
                    f"round {round_number} execution order {order} does not match "
                    f"{_round_order(round_number)}"
                )
            metrics: dict[HandlerVariant, JsonObject] = {
                variant: _scenario_metrics(run)[scenario]
                for variant, run in variants.items()
            }
            if any(
                float(measurement[metric]) <= 0
                for measurement in metrics.values()
                for metric in ("throughput", "cpu_per_unit")
            ):
                raise BenchmarkFailure(
                    f"round {round_number} {scenario} measurements must be positive"
                )
            for variant, measurement in metrics.items():
                values[variant]["throughput"].append(float(measurement["throughput"]))
                values[variant]["cpu_per_unit"].append(float(measurement["cpu_per_unit"]))
            paired.append(
                {
                    "round": round_number,
                    "order": list(order),
                    "throughput_current_over_stdlib": (
                        metrics["current"]["throughput"]
                        / metrics["stdlib"]["throughput"]
                    ),
                    "cpu_current_over_stdlib": (
                        metrics["current"]["cpu_per_unit"]
                        / metrics["stdlib"]["cpu_per_unit"]
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
        paired_ratio_medians = {
            key: statistics.median(item[key] for item in paired)
            for key in (
                "throughput_current_over_stdlib",
                "cpu_current_over_stdlib",
                "throughput_current_over_no_logging",
                "cpu_current_over_no_logging",
            )
        }
        threshold_passed = (
            paired_ratio_medians["throughput_current_over_stdlib"]
            >= MINIMUM_THROUGHPUT_RATIO
            and paired_ratio_medians["cpu_current_over_stdlib"]
            <= MAXIMUM_CPU_RATIO
            if scenario != "subprocess_pipe"
            else None
        )
        summaries[scenario] = {
            "medians": {
                variant: {
                    metric: statistics.median(measurements)
                    for metric, measurements in metrics.items()
                }
                for variant, metrics in values.items()
            },
            "paired_ratio_medians": paired_ratio_medians,
            "paired_rounds": paired,
            "threshold_passed": threshold_passed,
        }
    threshold_passed = all(
        cast(bool, cast(JsonObject, summaries[scenario])["threshold_passed"])
        for scenario in (
            "simple_application",
            "base_manager",
            "async_process_manager",
        )
    )
    return {
        "scenarios": summaries,
        "thresholds": {
            "basis": "median_of_paired_round_ratios",
            "minimum_throughput_ratio": MINIMUM_THROUGHPUT_RATIO,
            "maximum_cpu_ratio": MAXIMUM_CPU_RATIO,
            "gated_scenarios": [
                "simple_application",
                "base_manager",
                "async_process_manager",
            ],
            "subprocess_pipe_is_diagnostic_only": True,
            "enforced": enforce,
        },
        "threshold_passed": threshold_passed,
        "gating": enforce,
        "passed": threshold_passed if enforce else True,
    }


def _machine_information() -> JsonObject:
    """Record the Linux/Python/CPU identity of one benchmark report."""
    affinity: int | None
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = None
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "affinity_cpu_count": affinity,
    }


def _execute(config: BenchmarkConfig) -> JsonObject:
    """Run every round and retain complete evidence even after one failure."""
    report: JsonObject = {
        "benchmark": "oldman_application_process_logging",
        "mode": config.mode,
        "config": {
            "rounds": config.rounds,
            "main_records": config.main_records,
            "base_records_per_generation": config.base_records,
            "async_records_per_child": config.async_records,
            "async_repeated_children": config.async_runs,
            "subprocess_bytes_per_stream": config.subprocess_bytes,
            "minimum_throughput_ratio": MINIMUM_THROUGHPUT_RATIO,
            "maximum_cpu_ratio": MAXIMUM_CPU_RATIO,
        },
        "machine": _machine_information(),
        "runs": [],
        "comparison": None,
        "failures": [],
        "passed": False,
    }
    if platform.system() != "Linux" or not Path("/proc").is_dir():
        report["failures"].append("process benchmark requires Linux /proc")
        return report
    with tempfile.TemporaryDirectory(prefix="oldman-process-performance-") as directory:
        root = Path(directory)
        for round_number in range(1, config.rounds + 1):
            for order_index, variant in enumerate(_round_order(round_number), start=1):
                run = _run_variant(
                    root,
                    round_number,
                    order_index,
                    variant,
                    config,
                )
                report["runs"].append(run)
                if not run["passed"]:
                    report["failures"].append(
                        f"round={round_number} variant={variant}: {run['errors']}"
                    )
        if not report["failures"]:
            try:
                report["comparison"] = _comparison(
                    report["runs"],
                    config.rounds,
                    enforce=config.mode == "release",
                )
                if not cast(JsonObject, report["comparison"])["passed"]:
                    report["failures"].append(
                        f"release ratio gate failed: {report['comparison']}"
                    )
            except BaseException as exc:
                report["failures"].append(
                    f"comparison failed: {type(exc).__name__}: {exc}"
                )
    report["passed"] = not report["failures"]
    return report


def main() -> int:
    """Print one complete JSON report and return nonzero on correctness failure."""
    args = _build_parser().parse_args()
    try:
        report = _execute(_config(args.smoke))
    except BaseException as exc:
        report = {
            "benchmark": "oldman_application_process_logging",
            "passed": False,
            "failures": [f"{type(exc).__name__}: {exc}"],
            "traceback": traceback.format_exc(),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
