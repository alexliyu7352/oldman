from __future__ import annotations

import unittest
from collections import Counter
from typing import Any

from tests.performance import logging_process_benchmark as benchmark


def _measurement(records: int, throughput: float, cpu_per_unit: float) -> dict[str, Any]:
    """Build one child measurement with the requested normalized values."""
    return {
        "records": records,
        "elapsed_seconds": records / throughput,
        "cpu": {"total_seconds": records * cpu_per_unit},
    }


def _run(
    round_number: int,
    variant: str,
    throughput: float,
    cpu_per_unit: float,
) -> dict[str, Any]:
    """Build one complete synthetic run for comparison-only tests."""
    child = _measurement(1, throughput, cpu_per_unit)
    return {
        "round": round_number,
        "order_index": benchmark._round_order(round_number).index(variant) + 1,
        "variant": variant,
        "result": {
            "simple_application": {
                "records_per_second": throughput,
                "cpu": {"seconds_per_record": cpu_per_unit},
            },
            "base_manager": {
                "first": child,
                "replacement": child,
            },
            "async_manager": {
                "runs": [child],
                "recovery": child,
            },
            "subprocess": {
                "output": {
                    "pipe_stdout_bytes": 1,
                    "pipe_stderr_bytes": 1,
                    "pipe_elapsed_seconds": 2 / throughput,
                    "child_cpu": {"seconds_per_unit": cpu_per_unit},
                }
            },
        },
    }


def _comparison_runs(
    current_throughput: float,
    current_cpu: float,
) -> list[dict[str, Any]]:
    """Build six balanced rounds with fixed standard-library baselines."""
    runs: list[dict[str, Any]] = []
    values = {
        "current": (current_throughput, current_cpu),
        "stdlib": (1_000.0, 0.001),
        "no_logging": (1_100.0, 0.0009),
    }
    for round_number in range(1, benchmark.RELEASE_ROUNDS + 1):
        for variant, (throughput, cpu_per_unit) in values.items():
            runs.append(
                _run(
                    round_number,
                    variant,
                    throughput,
                    cpu_per_unit,
                )
            )
    return runs


class LoggingProcessBenchmarkTests(unittest.TestCase):
    """Verify the small calculation surface of the process benchmark."""

    def test_round_order_rotates_all_three_logging_modes(self) -> None:
        """Every mode must occupy every order position across three rounds."""
        self.assertEqual(
            benchmark._round_order(1),
            ("current", "stdlib", "no_logging"),
        )
        self.assertEqual(
            benchmark._round_order(2),
            ("stdlib", "no_logging", "current"),
        )
        self.assertEqual(
            benchmark._round_order(3),
            ("no_logging", "current", "stdlib"),
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
            for variant in ("current", "stdlib", "no_logging")
        }

        self.assertEqual(len(set(orders)), 6)
        self.assertEqual(
            positions,
            {
                variant: Counter({0: 2, 1: 2, 2: 2})
                for variant in ("current", "stdlib", "no_logging")
            },
        )
        for first, second in (
            ("current", "stdlib"),
            ("current", "no_logging"),
            ("stdlib", "no_logging"),
        ):
            self.assertEqual(
                Counter(order.index(first) < order.index(second) for order in orders),
                Counter({True: 3, False: 3}),
            )

    def test_release_comparison_enforces_throughput_and_cpu(self) -> None:
        """A release comparison must fail either frozen performance boundary."""
        throughput_failure = benchmark._comparison(
            _comparison_runs(current_throughput=970.0, current_cpu=0.001),
            benchmark.RELEASE_ROUNDS,
            enforce=True,
        )
        cpu_failure = benchmark._comparison(
            _comparison_runs(current_throughput=1_000.0, current_cpu=0.00106),
            benchmark.RELEASE_ROUNDS,
            enforce=True,
        )

        self.assertFalse(throughput_failure["threshold_passed"])
        self.assertFalse(throughput_failure["passed"])
        self.assertFalse(cpu_failure["threshold_passed"])
        self.assertFalse(cpu_failure["passed"])

    def test_duplicate_variant_fails_closed(self) -> None:
        """One repeated variant must not silently replace its first measurement."""
        runs = _comparison_runs(current_throughput=1_000.0, current_cpu=0.001)
        duplicate = next(
            run
            for run in runs
            if run["round"] == 2 and run["variant"] == "current"
        )
        runs.append(duplicate.copy())

        with self.assertRaisesRegex(
            benchmark.BenchmarkFailure,
            "round 2.*duplicate current",
        ):
            benchmark._comparison(
                runs,
                benchmark.RELEASE_ROUNDS,
                enforce=True,
            )

    def test_wrong_execution_order_fails_closed(self) -> None:
        """Reported order indexes must match the frozen six permutations."""
        runs = _comparison_runs(current_throughput=1_000.0, current_cpu=0.001)
        current = next(
            run
            for run in runs
            if run["round"] == 1 and run["variant"] == "current"
        )
        current["order_index"] = 3

        with self.assertRaisesRegex(
            benchmark.BenchmarkFailure,
            "round 1.*execution order",
        ):
            benchmark._comparison(
                runs,
                benchmark.RELEASE_ROUNDS,
                enforce=True,
            )

    def test_smoke_comparison_reports_but_does_not_enforce_ratios(self) -> None:
        """Smoke mode remains a correctness diagnostic rather than a timer gate."""
        result = benchmark._comparison(
            _comparison_runs(current_throughput=1.0, current_cpu=1.0),
            benchmark.RELEASE_ROUNDS,
            enforce=False,
        )

        self.assertFalse(result["threshold_passed"])
        self.assertTrue(result["passed"])
        self.assertFalse(result["gating"])

    def test_child_sequence_aggregation_sums_cpu_and_elapsed(self) -> None:
        """Sequential child cost must be normalized after summing every child."""
        children: list[dict[str, Any]] = [
            {
                "records": 100,
                "elapsed_seconds": 0.2,
                "cpu": {"total_seconds": 0.15},
            },
            {
                "records": 100,
                "elapsed_seconds": 0.3,
                "cpu": {"total_seconds": 0.20},
            },
        ]

        result = benchmark._aggregate_child_sequences(children)

        self.assertAlmostEqual(result["throughput"], 400.0)
        self.assertAlmostEqual(result["cpu_per_unit"], 0.00175)

    def test_process_result_validation_rejects_incomplete_cleanup(self) -> None:
        """Missing subprocess cleanup proof must fail instead of being ignored."""
        config = benchmark._config(smoke=True)
        result: dict[str, Any] = {
            "variant": "current",
            "pid": 999_999_991,
            "simple_application": {"records": config.main_records},
            "base_manager": {
                "restart_completed": True,
                "first": {"pid": 999_999_992},
                "replacement": {"pid": 999_999_993},
            },
            "async_manager": {
                "runs": [
                    {"pid": 999_999_994 + index}
                    for index in range(config.async_runs)
                ],
                "timed_out": True,
                "sigkill_result": None,
                "recovery": {
                    "pid": 999_999_996,
                    "label": "async_recovery",
                },
            },
            "subprocess": {
                "output": {
                    "inherited_pid": 999_999_997,
                    "pipe_pid": 999_999_998,
                    "inherited_returncode": 0,
                    "pipe_returncode": 0,
                    "pipe_stdout_bytes": config.subprocess_bytes,
                    "pipe_stderr_bytes": config.subprocess_bytes,
                    "event_loop_ticks": 1,
                },
                "cleanup": {
                    "timeout_pid": 999_999_999,
                    "cancelled_pid": 999_999_990,
                    "timed_out": True,
                    "timeout_group_gone": False,
                    "cancelled": True,
                    "cancelled_group_gone": True,
                    "timeout_group_pids_before_cleanup": [1, 2],
                    "cancelled_group_pids_before_cleanup": [3, 4],
                },
            },
        }

        errors = benchmark._validate_result(result, "current", config)

        self.assertTrue(
            any("timeout_group_gone" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
