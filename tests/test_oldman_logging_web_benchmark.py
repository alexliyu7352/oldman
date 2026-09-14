from __future__ import annotations

import errno
import json
import os
import statistics
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest import mock

from tests.performance import logging_web_benchmark as benchmark
from tests.performance.logging_web_benchmark import BenchmarkFailure, _comparison

CURRENT_QPS = (
    4626.360265944283,
    4581.916655435213,
    4767.8092770970725,
    4876.943107929552,
    4879.541283798469,
    4700.0,
)
REFERENCE_QPS = (
    4629.60999927903,
    4605.264574050477,
    4669.12483970169,
    4666.55875023422,
    4809.982547731839,
    4700.0,
)
CURRENT_P99 = (
    0.03311823308467865,
    0.034157779067754745,
    0.03368447721004486,
    0.02847879007458687,
    0.02702086791396141,
    0.03,
)
REFERENCE_P99 = (
    0.03403836116194725,
    0.028592154383659363,
    0.029719874262809753,
    0.02942284569144249,
    0.028218183666467667,
    0.03,
)
NO_LOGGING_QPS = (5100.0, 5150.0, 5125.0, 5175.0, 5200.0, 5150.0)
NO_LOGGING_P99 = (0.025, 0.024, 0.026, 0.023, 0.024, 0.025)
CURRENT_SERVER_CPU = (0.00031, 0.00030, 0.00032, 0.00029, 0.00030, 0.00030)
REFERENCE_SERVER_CPU = (0.00033, 0.00032, 0.00034, 0.00031, 0.00032, 0.00030)
NO_LOGGING_SERVER_CPU = (
    0.00020,
    0.00019,
    0.00021,
    0.00020,
    0.00019,
    0.00020,
)
ROOT = Path(__file__).resolve().parents[1]


def _run(
    round_number: int,
    order_index: int,
    variant: str,
    qps: float,
    p99: float,
    server_cpu_per_request: float,
) -> dict[str, Any]:
    return {
        "round": round_number,
        "order_index": order_index,
        "variant": variant,
        "load": {
            "measurement": {
                "qps": qps,
                "latency_seconds": {"p99": p99},
                "server_cpu": {
                    "seconds_per_request": server_cpu_per_request,
                },
            }
        },
    }


def _formal_failed_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for round_number, values in enumerate(
        zip(
            CURRENT_QPS,
            REFERENCE_QPS,
            NO_LOGGING_QPS,
            CURRENT_P99,
            REFERENCE_P99,
            NO_LOGGING_P99,
            CURRENT_SERVER_CPU,
            REFERENCE_SERVER_CPU,
            NO_LOGGING_SERVER_CPU,
            strict=True,
        ),
        start=1,
    ):
        (
            current_qps,
            reference_qps,
            no_logging_qps,
            current_p99,
            reference_p99,
            no_logging_p99,
            current_cpu,
            reference_cpu,
            no_logging_cpu,
        ) = values
        order = benchmark._round_order(round_number)
        runs.extend(
            (
                _run(
                    round_number,
                    order.index("current") + 1,
                    "current",
                    current_qps,
                    current_p99,
                    current_cpu,
                ),
                _run(
                    round_number,
                    order.index("timed_reference") + 1,
                    "timed_reference",
                    reference_qps,
                    reference_p99,
                    reference_cpu,
                ),
                _run(
                    round_number,
                    order.index("no_logging") + 1,
                    "no_logging",
                    no_logging_qps,
                    no_logging_p99,
                    no_logging_cpu,
                ),
            )
        )
    return list(reversed(runs))


def _normal_final_fixture_state() -> dict[str, Any]:
    return {
        "manager_ack_complete": True,
        "shutdown_signal_count": 1,
        "shutdown_signals": [
            {
                "name": "SIGTERM",
                "already_shutting_down": False,
                "original_returned": True,
                "exception": None,
            }
        ],
        "manager_kill_count": 0,
        "manager_kills": [],
        "sanic_serve_returned": True,
        "main_returned": True,
        "unhandled_exception": None,
    }


class LoggingWebBenchmarkComparisonTests(unittest.TestCase):
    def test_gate_uses_median_of_paired_round_ratios(self) -> None:
        result = _comparison(1, _formal_failed_runs(), enforce=True)

        expected_qps_ratio = statistics.median(
            current / reference
            for current, reference in zip(CURRENT_QPS, REFERENCE_QPS, strict=True)
        )
        expected_p99_ratio = statistics.median(
            current / reference
            for current, reference in zip(CURRENT_P99, REFERENCE_P99, strict=True)
        )
        paired_medians = result["paired_ratio_medians"]
        legacy = result["ratio_of_separate_medians_diagnostic"]

        self.assertAlmostEqual(
            paired_medians["qps_current_over_reference"],
            expected_qps_ratio,
        )
        self.assertAlmostEqual(
            paired_medians["p99_current_over_reference"],
            expected_p99_ratio,
        )
        self.assertAlmostEqual(
            paired_medians["server_cpu_per_request_current_over_reference"],
            statistics.median(
                current / reference
                for current, reference in zip(
                    CURRENT_SERVER_CPU,
                    REFERENCE_SERVER_CPU,
                    strict=True,
                )
            ),
        )
        self.assertAlmostEqual(
            paired_medians["server_cpu_per_request_current_over_no_logging"],
            statistics.median(
                current / baseline
                for current, baseline in zip(
                    CURRENT_SERVER_CPU,
                    NO_LOGGING_SERVER_CPU,
                    strict=True,
                )
            ),
        )
        self.assertAlmostEqual(
            legacy["p99_current_over_reference"],
            statistics.median(CURRENT_P99) / statistics.median(REFERENCE_P99),
        )
        self.assertFalse(legacy["gating"])
        self.assertGreater(legacy["p99_current_over_reference"], 1.05)
        self.assertLess(paired_medians["p99_current_over_reference"], 1.05)
        self.assertTrue(result["threshold_passed"])
        self.assertTrue(result["passed"])

        paired = result["paired_ratios"]
        self.assertEqual(
            [item["round"] for item in paired],
            list(range(1, benchmark.RELEASE_ROUNDS + 1)),
        )
        self.assertEqual(
            paired[0]["order"],
            ["current", "timed_reference", "no_logging"],
        )
        self.assertEqual(
            paired[1]["order"],
            ["timed_reference", "no_logging", "current"],
        )
        self.assertEqual(paired[0]["current_qps"], CURRENT_QPS[0])
        self.assertEqual(paired[0]["reference_p99_seconds"], REFERENCE_P99[0])

    def test_missing_variant_fails_closed(self) -> None:
        runs = [
            run
            for run in _formal_failed_runs()
            if not (run["round"] == 3 and run["variant"] == "timed_reference")
        ]

        with self.assertRaisesRegex(BenchmarkFailure, "round 3.*timed_reference"):
            _comparison(1, runs, enforce=True)

    def test_duplicate_variant_fails_closed(self) -> None:
        runs = _formal_failed_runs()
        duplicate = next(
            run
            for run in runs
            if run["round"] == 2 and run["variant"] == "current"
        )
        runs.append(duplicate.copy())

        with self.assertRaisesRegex(BenchmarkFailure, "round 2.*current"):
            _comparison(1, runs, enforce=True)

    def test_wrong_execution_order_fails_closed(self) -> None:
        """Reported order indexes must match the frozen six permutations."""
        runs = _formal_failed_runs()
        current = next(
            run
            for run in runs
            if run["round"] == 1 and run["variant"] == "current"
        )
        current["order_index"] = 3

        with self.assertRaisesRegex(BenchmarkFailure, "round 1.*execution order"):
            _comparison(1, runs, enforce=True)

    def test_wrong_round_count_fails_closed(self) -> None:
        runs = [
            run
            for run in _formal_failed_runs()
            if run["round"] != benchmark.RELEASE_ROUNDS
        ]

        with self.assertRaisesRegex(
            BenchmarkFailure,
            f"exactly {benchmark.RELEASE_ROUNDS} rounds",
        ):
            _comparison(1, runs, enforce=True)

    def test_round_order_rotates_all_three_variants(self) -> None:
        self.assertEqual(
            benchmark._round_order(1),
            ("current", "timed_reference", "no_logging"),
        )
        self.assertEqual(
            benchmark._round_order(2),
            ("timed_reference", "no_logging", "current"),
        )
        self.assertEqual(
            benchmark._round_order(3),
            ("no_logging", "current", "timed_reference"),
        )

    def test_release_rounds_balance_every_variant_position(self) -> None:
        """The release gate must place every variant equally in every position."""
        orders = [
            benchmark._round_order(round_number)
            for round_number in range(1, benchmark.RELEASE_ROUNDS + 1)
        ]
        positions = {
            variant: Counter(
                order.index(variant)
                for order in orders
            )
            for variant in ("current", "timed_reference", "no_logging")
        }

        self.assertEqual(len(set(orders)), 6)
        self.assertEqual(
            positions,
            {
                variant: Counter({0: 2, 1: 2, 2: 2})
                for variant in ("current", "timed_reference", "no_logging")
            },
        )
        for first, second in (
            ("current", "timed_reference"),
            ("current", "no_logging"),
            ("timed_reference", "no_logging"),
        ):
            self.assertEqual(
                Counter(order.index(first) < order.index(second) for order in orders),
                Counter({True: 3, False: 3}),
            )

    def test_cpu_ratio_above_limit_fails_gate(self) -> None:
        """CPU cost is a release boundary rather than diagnostic-only output."""
        runs = _formal_failed_runs()
        for run in runs:
            if run["variant"] == "current":
                run["load"]["measurement"]["server_cpu"][
                    "seconds_per_request"
                ] = 0.001

        result = _comparison(1, runs, enforce=True)

        self.assertGreater(
            result["paired_ratio_medians"][
                "server_cpu_per_request_current_over_reference"
            ],
            benchmark.MAXIMUM_CPU_RATIO,
        )
        self.assertFalse(result["threshold_passed"])
        self.assertFalse(result["passed"])


class LoggingWebBenchmarkLifecycleTests(unittest.TestCase):
    def _validation_errors(self, state: object) -> list[str]:
        validator = cast(
            Callable[[object], list[str]],
            getattr(benchmark, "_final_fixture_state_errors", None),
        )
        self.assertIsNotNone(
            validator,
            "runner must define _final_fixture_state_errors",
        )
        return validator(state)

    def test_normal_final_state_passes(self) -> None:
        self.assertEqual(
            self._validation_errors(_normal_final_fixture_state()),
            [],
        )

    def test_second_shutdown_signal_fails_closed(self) -> None:
        state = _normal_final_fixture_state()
        state["shutdown_signal_count"] = 2
        state["shutdown_signals"].append(
            {
                "name": "SIGTERM",
                "already_shutting_down": True,
                "original_returned": True,
                "exception": None,
            }
        )

        errors = "\n".join(self._validation_errors(state))

        self.assertIn("shutdown_signal_count must be 1", errors)
        self.assertIn("already_shutting_down", errors)

    def test_manager_kill_fails_closed(self) -> None:
        state = _normal_final_fixture_state()
        state["manager_kill_count"] = 1
        state["manager_kills"] = [
            {
                "workers": [
                    {
                        "name": "Sanic-Srv-0-0",
                        "pid": 1234,
                        "state": "TERMINATED",
                        "exit_code": None,
                        "alive": True,
                    }
                ],
                "original_returned": False,
                "exception": {
                    "type": "ServerKilled",
                    "message": "",
                },
            }
        ]

        errors = "\n".join(self._validation_errors(state))

        self.assertIn("manager_kill_count must be 0", errors)

    def test_unhandled_exception_without_returns_fails_closed(self) -> None:
        state = _normal_final_fixture_state()
        state["sanic_serve_returned"] = False
        state["main_returned"] = False
        state["unhandled_exception"] = {
            "type": "RuntimeError",
            "message": "serve failed",
            "traceback": "Traceback (most recent call last): ...",
        }

        errors = "\n".join(self._validation_errors(state))

        self.assertIn("sanic_serve_returned must be true", errors)
        self.assertIn("main_returned must be true", errors)
        self.assertIn("unhandled_exception must be null", errors)


class LoggingWebBenchmarkFixtureWrapperTests(unittest.TestCase):
    def _run_fixture_script(self, body: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="oldman-fixture-contract-") as directory:
            root = Path(directory)
            log_dir = root / "logs"
            log_dir.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_WEB_BENCH_LOG_DIR": str(log_dir),
                    "OLDMAN_WEB_BENCH_STATE_FILE": str(root / "state.json"),
                    "OLDMAN_WEB_BENCH_APP_NAME": "fixture_contract",
                    "OLDMAN_WEB_BENCH_VARIANT": "current",
                    "OLDMAN_WEB_BENCH_WORKERS": "1",
                    "OLDMAN_WEB_BENCH_PORT": "1",
                    "OLDMAN_WEB_BENCH_FAULT": "none",
                }
            )
            completed = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(body)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            output_lines = completed.stdout.strip().splitlines()
            self.assertTrue(output_lines, "fixture contract emitted no JSON")
            return cast(dict[str, Any], json.loads(output_lines[-1]))

    def test_nested_shutdown_update_preserves_both_actual_events(self) -> None:
        result = self._run_fixture_script(
            """
            import json
            import signal

            from tests.fixtures import logging_web_performance_service as fixture

            fixture._PRIMARY_STATE = {
                "shutdown_signal_count": 0,
                "shutdown_signals": [],
                "manager_kill_count": 0,
                "manager_kills": [],
            }
            fixture._PRIMARY_STATE_VERSION = 0
            fixture._publish_primary_state()

            class Manager:
                _shutting_down = False

            manager = Manager()
            original_error = RuntimeError("outer shutdown failed")
            original_calls = 0

            def original(manager, signal_number, frame):
                global original_calls
                del signal_number, frame
                original_calls += 1
                manager._shutting_down = True
                if original_calls == 1:
                    raise original_error
                return "nested-return"

            fixture._ORIGINAL_MANAGER_SHUTDOWN_SIGNAL = original
            real_exception_summary = fixture._exception_summary
            nested_triggered = False

            def exception_summary(exc, *, with_traceback):
                global nested_triggered
                if not nested_triggered:
                    nested_triggered = True
                    fixture._shutdown_signal_and_publish(
                        manager,
                        signal.SIGTERM,
                        None,
                    )
                return real_exception_summary(
                    exc,
                    with_traceback=with_traceback,
                )

            fixture._exception_summary = exception_summary
            caught_original = False
            try:
                fixture._shutdown_signal_and_publish(
                    manager,
                    signal.SIGTERM,
                    None,
                )
            except BaseException as exc:
                caught_original = exc is original_error

            print(json.dumps({
                "caught_original": caught_original,
                "original_calls": original_calls,
                "state": fixture._PRIMARY_STATE,
            }, sort_keys=True))
            """
        )

        state = result["state"]
        self.assertTrue(result["caught_original"])
        self.assertEqual(result["original_calls"], 2)
        self.assertEqual(state["shutdown_signal_count"], 2)
        self.assertEqual(len(state["shutdown_signals"]), 2)
        self.assertFalse(state["shutdown_signals"][0]["original_returned"])
        self.assertTrue(state["shutdown_signals"][1]["original_returned"])

    def test_ack_diagnostic_write_failure_does_not_change_return(self) -> None:
        result = self._run_fixture_script(
            """
            import errno
            import json

            from tests.fixtures import logging_web_performance_service as fixture

            marker = object()
            fixture._PRIMARY_STATE = {"manager_ack_complete": False}
            fixture._PRIMARY_STATE_VERSION = 0
            fixture._ORIGINAL_MANAGER_WAIT_FOR_ACK = lambda manager: marker

            def fail_publish():
                raise OSError(errno.ENOSPC, "diagnostic disk full")

            fixture._publish_primary_state = fail_publish
            escaped = None
            returned_original = False
            try:
                result = fixture._wait_for_ack_and_publish(object())
                returned_original = result is marker
            except BaseException as exc:
                escaped = type(exc).__name__

            print(json.dumps({
                "escaped": escaped,
                "returned_original": returned_original,
            }, sort_keys=True))
            """
        )

        self.assertIsNone(result["escaped"])
        self.assertTrue(result["returned_original"])

    def test_ack_wrapper_reraises_original_exception_unchanged(self) -> None:
        result = self._run_fixture_script(
            """
            import json

            from tests.fixtures import logging_web_performance_service as fixture

            original_error = RuntimeError("original ACK failure")

            def fail_original(manager):
                raise original_error

            fixture._ORIGINAL_MANAGER_WAIT_FOR_ACK = fail_original
            caught_original = False
            try:
                fixture._wait_for_ack_and_publish(object())
            except BaseException as exc:
                caught_original = exc is original_error

            print(json.dumps({"caught_original": caught_original}))
            """
        )

        self.assertTrue(result["caught_original"])


class LoggingWebBenchmarkEvidenceTests(unittest.TestCase):
    def _runner_callable(self, name: str) -> Callable[..., Any]:
        function = getattr(benchmark, name, None)
        self.assertTrue(callable(function), f"runner must define {name}")
        return cast(Callable[..., Any], function)

    def test_proc_stat_parser_retains_process_identity(self) -> None:
        parser = self._runner_callable("_parse_process_stat")
        suffix = ["S", "123", "4321", *(["0"] * 16), "987654"]
        suffix[11] = "120"
        suffix[12] = "30"

        result = parser(4321, f"4321 (worker name) {' '.join(suffix)}")

        self.assertEqual(
            result,
            {
                "pid": 4321,
                "ppid": 123,
                "process_group": 4321,
                "state": "S",
                "user_time_ticks": 120,
                "system_time_ticks": 30,
                "start_time_ticks": 987654,
                "read_error": None,
            },
        )

    def test_process_group_cpu_delta_sums_stable_processes(self) -> None:
        calculate = self._runner_callable("_process_group_cpu_delta")
        before = {
            "process_group": 4321,
            "ticks_per_second": 100,
            "processes": [
                {
                    "pid": 4321,
                    "process_group": 4321,
                    "start_time_ticks": 1000,
                    "user_time_ticks": 20,
                    "system_time_ticks": 5,
                    "read_error": None,
                },
                {
                    "pid": 4322,
                    "process_group": 4321,
                    "start_time_ticks": 1001,
                    "user_time_ticks": 30,
                    "system_time_ticks": 10,
                    "read_error": None,
                },
            ],
            "passed": True,
            "errors": [],
        }
        after = {
            **before,
            "processes": [
                {
                    **before["processes"][0],
                    "user_time_ticks": 50,
                    "system_time_ticks": 15,
                },
                {
                    **before["processes"][1],
                    "user_time_ticks": 50,
                    "system_time_ticks": 20,
                },
            ],
        }

        result = calculate(before, after, request_count=1000, elapsed_seconds=0.5)

        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["user_seconds"], 0.5)
        self.assertAlmostEqual(result["system_seconds"], 0.2)
        self.assertAlmostEqual(result["total_seconds"], 0.7)
        self.assertAlmostEqual(result["seconds_per_request"], 0.0007)
        self.assertAlmostEqual(result["average_cores"], 1.4)

    def test_process_group_cpu_delta_rejects_pid_churn(self) -> None:
        calculate = self._runner_callable("_process_group_cpu_delta")
        process = {
            "pid": 4321,
            "process_group": 4321,
            "start_time_ticks": 1000,
            "user_time_ticks": 20,
            "system_time_ticks": 5,
            "read_error": None,
        }
        before = {
            "process_group": 4321,
            "ticks_per_second": 100,
            "processes": [process],
            "passed": True,
            "errors": [],
        }
        after = {
            **before,
            "processes": [{**process, "pid": 4322}],
        }

        result = calculate(before, after, request_count=1000, elapsed_seconds=0.5)

        self.assertFalse(result["passed"])
        self.assertTrue(any("PID set changed" in error for error in result["errors"]))

    def test_no_logging_validation_accepts_absent_log_files(self) -> None:
        validate = self._runner_callable("_validate_log_files")
        config = benchmark.BenchmarkConfig(
            mode="smoke",
            workers=(1,),
            rounds=1,
            warmup_requests=1,
            measured_requests=1,
            concurrency=1,
            inject_fault="none",
            enforce_ratios=False,
        )
        with tempfile.TemporaryDirectory(prefix="oldman-no-logging-") as directory:
            result = validate(
                Path(directory),
                "no_logging_app",
                "TOKEN",
                config,
                1,
                "no_logging",
            )

        self.assertTrue(result["passed"])
        self.assertTrue(result["logging_disabled"])

    def test_storage_probe_records_success_and_fsync_failure(self) -> None:
        probe = self._runner_callable("_storage_probe")
        with tempfile.TemporaryDirectory(prefix="oldman-storage-probe-") as directory:
            root = Path(directory)

            success = probe(root)
            with mock.patch.object(
                benchmark.os,
                "fsync",
                side_effect=OSError(errno.ENOSPC, "probe disk full"),
            ):
                failure = probe(root)

        self.assertTrue(success["passed"])
        self.assertEqual(success["step"], "complete")
        self.assertIsNone(success["error"])
        self.assertFalse(failure["passed"])
        self.assertEqual(failure["step"], "fsync")
        self.assertEqual(failure["error"]["type"], "OSError")
        self.assertEqual(failure["error"]["errno"], errno.ENOSPC)
        self.assertIn("probe disk full", failure["error"]["message"])

    def test_pre_shutdown_evidence_retains_all_required_boundaries(self) -> None:
        capture = self._runner_callable("_pre_shutdown_evidence")
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        process_state = {
            "pid": 4321,
            "ppid": 123,
            "process_group": 4321,
            "state": "S",
            "start_time_ticks": 987654,
            "read_error": None,
        }
        with tempfile.TemporaryDirectory(prefix="oldman-pre-shutdown-") as directory:
            root = Path(directory)
            with (
                mock.patch.object(
                    benchmark,
                    "_process_group_pids",
                    return_value=[4321],
                ),
                mock.patch.object(
                    benchmark,
                    "_read_process_stat",
                    return_value=process_state,
                ),
            ):
                result = capture(process, root)

        self.assertTrue(result["passed"])
        self.assertIsNone(result["primary_poll"])
        self.assertIsNone(result["final_primary_poll"])
        self.assertEqual(
            result["processes"],
            [
                {
                    **process_state,
                    "expected_process_group": 4321,
                    "process_group_matches": True,
                    "identity_error": None,
                }
            ],
        )
        self.assertGreater(result["filesystem"]["capacity_bytes"], 0)
        self.assertIn("free_bytes", result["filesystem"])
        self.assertIn("free_inodes", result["filesystem"])
        self.assertTrue(result["storage_probe"]["passed"])

    def test_pre_shutdown_evidence_retains_primary_stat_read_failure(self) -> None:
        capture = self._runner_callable("_pre_shutdown_evidence")
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        process_state = {
            "pid": 4321,
            "ppid": None,
            "process_group": None,
            "state": None,
            "start_time_ticks": None,
            "read_error": {
                "type": "FileNotFoundError",
                "errno": errno.ENOENT,
                "message": "process stat raced with exit",
            },
        }
        with tempfile.TemporaryDirectory(prefix="oldman-pre-shutdown-") as directory:
            with (
                mock.patch.object(
                    benchmark,
                    "_process_group_pids",
                    return_value=[],
                ),
                mock.patch.object(
                    benchmark,
                    "_read_process_stat",
                    return_value=process_state,
                ) as read_stat,
            ):
                result = capture(process, Path(directory))

        read_stat.assert_called_once_with(4321)
        self.assertEqual(
            result["processes"],
            [
                {
                    **process_state,
                    "expected_process_group": 4321,
                    "process_group_matches": None,
                    "identity_error": None,
                }
            ],
        )
        self.assertFalse(result["passed"])
        self.assertIn("stat failed", result["errors"][0])

    def test_pre_shutdown_evidence_fails_if_primary_already_exited(self) -> None:
        capture = self._runner_callable("_pre_shutdown_evidence")
        process = mock.Mock(pid=4321)
        process.poll.return_value = 23
        with tempfile.TemporaryDirectory(prefix="oldman-pre-shutdown-") as directory:
            with mock.patch.object(
                benchmark,
                "_process_group_pids",
                return_value=[],
            ):
                result = capture(process, Path(directory))

        self.assertEqual(result["primary_poll"], 23)
        self.assertFalse(result["passed"])
        self.assertIn("exit code 23", result["errors"][0])

    def test_pre_shutdown_evidence_fails_if_primary_exits_during_probe(self) -> None:
        capture = self._runner_callable("_pre_shutdown_evidence")
        process = mock.Mock(pid=4321)
        exit_code: list[int | None] = [None]
        process.poll.side_effect = lambda: exit_code[0]
        process_state = {
            "pid": 4321,
            "ppid": 123,
            "process_group": 4321,
            "state": "S",
            "start_time_ticks": 987654,
            "read_error": None,
        }

        def probe_after_exit(directory: Path) -> dict[str, Any]:
            del directory
            exit_code[0] = 23
            return {
                "passed": True,
                "step": "complete",
                "bytes": 4096,
                "error": None,
                "cleanup_errors": [],
            }

        with tempfile.TemporaryDirectory(prefix="oldman-pre-shutdown-") as directory:
            with (
                mock.patch.object(
                    benchmark,
                    "_process_group_pids",
                    return_value=[4321],
                ),
                mock.patch.object(
                    benchmark,
                    "_read_process_stat",
                    return_value=process_state,
                ),
                mock.patch.object(
                    benchmark,
                    "_storage_probe",
                    side_effect=probe_after_exit,
                ),
            ):
                result = capture(process, Path(directory))

        self.assertIsNone(result["primary_poll"])
        self.assertEqual(result.get("final_primary_poll"), 23)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("exit code 23" in error for error in result["errors"]),
            result["errors"],
        )

    def test_pre_shutdown_evidence_fails_on_process_group_mismatch(self) -> None:
        capture = self._runner_callable("_pre_shutdown_evidence")
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        mismatched_state = {
            "pid": 4321,
            "ppid": 123,
            "process_group": 9999,
            "state": "S",
            "start_time_ticks": 987654,
            "read_error": None,
        }
        with tempfile.TemporaryDirectory(prefix="oldman-pre-shutdown-") as directory:
            with (
                mock.patch.object(
                    benchmark,
                    "_process_group_pids",
                    return_value=[4321],
                ),
                mock.patch.object(
                    benchmark,
                    "_read_process_stat",
                    return_value=mismatched_state,
                ),
            ):
                result = capture(process, Path(directory))

        snapshot = result["processes"][0]
        self.assertEqual(snapshot.get("expected_process_group"), 4321)
        self.assertIs(snapshot.get("process_group_matches"), False)
        self.assertEqual(
            snapshot.get("identity_error", {}).get("type"),
            "ProcessGroupMismatch",
        )
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("identity mismatch" in error for error in result["errors"]),
            result["errors"],
        )

    def test_successful_run_cleanup_deletes_artifacts(self) -> None:
        cleanup = self._runner_callable("_cleanup_run_directory")
        with tempfile.TemporaryDirectory(prefix="oldman-cleanup-parent-") as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            (run_dir / "artifact.log").write_bytes(b"evidence")

            result = cleanup(run_dir, successful=True)

            self.assertFalse(run_dir.exists())

        self.assertTrue(result["passed"])
        self.assertTrue(result["attempted"])
        self.assertTrue(result["removed"])

    def test_failed_run_cleanup_retains_artifacts(self) -> None:
        cleanup = self._runner_callable("_cleanup_run_directory")
        with tempfile.TemporaryDirectory(prefix="oldman-cleanup-parent-") as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()

            result = cleanup(run_dir, successful=False)

            self.assertTrue(run_dir.exists())

        self.assertTrue(result["passed"])
        self.assertFalse(result["attempted"])
        self.assertTrue(result["retained"])

    def test_cleanup_failure_is_structured_and_fails_closed(self) -> None:
        cleanup = self._runner_callable("_cleanup_run_directory")
        shutil_module = getattr(benchmark, "shutil", None)
        self.assertIsNotNone(shutil_module, "runner must import shutil")
        with tempfile.TemporaryDirectory(prefix="oldman-cleanup-parent-") as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            with mock.patch.object(
                shutil_module,
                "rmtree",
                side_effect=OSError(errno.EIO, "cleanup failed"),
            ):
                result = cleanup(run_dir, successful=True)

        self.assertFalse(result["passed"])
        self.assertTrue(result["attempted"])
        self.assertFalse(result["removed"])
        self.assertEqual(result["error"]["type"], "OSError")
        self.assertEqual(result["error"]["errno"], errno.EIO)


if __name__ == "__main__":
    unittest.main()
