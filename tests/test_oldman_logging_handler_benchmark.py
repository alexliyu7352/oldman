from __future__ import annotations

import unittest
from typing import Any

from tests.performance import logging_handler_benchmark as benchmark


class LoggingHandlerBenchmarkCpuTests(unittest.TestCase):
    """Verify CPU accounting used by the direct-handler performance evidence."""

    def test_cpu_delta_reports_cost_per_record_and_average_cores(self) -> None:
        """A usage delta must preserve user/system cost and normalized values."""
        result = benchmark._cpu_usage_delta(
            {"user_seconds": 1.0, "system_seconds": 2.0},
            {"user_seconds": 1.4, "system_seconds": 2.1},
            record_count=100,
            elapsed_seconds=0.5,
        )

        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["user_seconds"], 0.4)
        self.assertAlmostEqual(result["system_seconds"], 0.1)
        self.assertAlmostEqual(result["total_seconds"], 0.5)
        self.assertAlmostEqual(result["seconds_per_record"], 0.005)
        self.assertAlmostEqual(result["average_cores"], 1.0)

    def test_worker_cpu_aggregation_sums_all_children(self) -> None:
        """Four-process CPU must be the sum of child CPU, never parent CPU."""
        reports: list[dict[str, Any]] = [
            {
                "ok": True,
                "cpu": {
                    "passed": True,
                    "user_seconds": 0.20,
                    "system_seconds": 0.05,
                },
            },
            {
                "ok": True,
                "cpu": {
                    "passed": True,
                    "user_seconds": 0.30,
                    "system_seconds": 0.05,
                },
            },
        ]

        result = benchmark._aggregate_worker_cpu(
            reports,
            record_count=200,
            elapsed_seconds=0.4,
        )

        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["user_seconds"], 0.5)
        self.assertAlmostEqual(result["system_seconds"], 0.1)
        self.assertAlmostEqual(result["total_seconds"], 0.6)
        self.assertAlmostEqual(result["seconds_per_record"], 0.003)
        self.assertAlmostEqual(result["average_cores"], 1.5)

    def test_scenario_summary_includes_cpu_ratio_without_gating_on_it(self) -> None:
        """Existing throughput threshold stays the gate while CPU remains evidence."""
        runs: list[dict[str, Any]] = []
        for variant, rate, cpu_per_record in (
            ("current", 110.0, 0.003),
            ("reference", 100.0, 0.004),
        ):
            for _ in range(benchmark.ROUNDS):
                runs.append(
                    {
                        "variant": variant,
                        "elapsed_seconds": 1.0,
                        "records_per_second": rate,
                        "cpu": {
                            "seconds_per_record": cpu_per_record,
                            "average_cores": 0.5,
                        },
                    }
                )

        result = benchmark._scenario_summary(runs)

        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["current_to_reference_ratio"], 1.1)
        self.assertAlmostEqual(result["cpu"]["current_to_reference_ratio"], 0.75)
        self.assertFalse(result["cpu"]["gating"])


if __name__ == "__main__":
    unittest.main()
