"""Deterministic contracts for the explicit Storage benchmark harness."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import tracemalloc
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from oldman.storage.backends.filesystem import FileSystemStorage
from oldman.storage.backends.memory import InMemoryStorage
from tests.performance import storage_benchmark as benchmark
from tests.performance.storage_benchmark import (
    BACKENDS,
    SCENARIO_VARIANTS,
    SCENARIOS,
    _comparison_records,
    _configuration_record,
    _Counters,
    _environment_record,
    _execution_order,
    _isolated_sample,
    _median_records,
    _prepare_operation,
    _sample,
    _sizes,
    _validate_resource_budget,
    _write_records,
    run,
)


def _comparison_sample(
    variant: str,
    implementation: str,
    *,
    round_number: int,
    elapsed: float,
) -> dict[str, Any]:
    return {
        "record": "sample",
        "variant": variant,
        "backend": "filesystem",
        "implementation": implementation,
        "size_bytes": 1024,
        "scenario": "bytes_save",
        "round": round_number,
        "elapsed_seconds": elapsed,
        "mib_per_second": 0.0 if elapsed <= 0 else 1.0 / elapsed,
        "user_cpu_seconds": elapsed / 2,
        "system_cpu_seconds": elapsed / 2,
        "cpu_seconds": elapsed,
        "cpu_to_wall_ratio": 1.0,
        "process_rss_before_bytes": 100,
        "peak_process_rss_bytes": 200,
        "peak_process_rss_delta_bytes": 100,
        "executor_call_count": 3,
        "data_io_call_count": 1,
        "data_chunk_count": 1,
        "peak_python_allocation_bytes": 50,
        "worker_pid": round_number,
    }


class StorageBenchmarkTest(unittest.IsolatedAsyncioTestCase):
    def test_sizes_reject_duplicates(self) -> None:
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "duplicate"):
            _sizes("1024,1024")

    def test_resource_budget_accepts_approved_profiles(self) -> None:
        _validate_resource_budget((1024, 1_048_576, 16_777_216), 4)
        _validate_resource_budget((104_857_600,), 1)

    def test_resource_budget_rejects_unsafe_concurrent_sample(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds the 256 MiB sample limit"):
            _validate_resource_budget((104_857_600,), 8)

    def test_environment_record_identifies_benchmark_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = _environment_record(Path(directory))

        self.assertEqual("environment", record["record"])
        self.assertEqual(4, record["schema_version"])
        self.assertIn("python_version", record)
        self.assertIn("platform", record)
        self.assertIn("cpu_count", record)
        self.assertIn("filesystem_block_size", record)
        self.assertIn("git_revision", record)
        self.assertIn("git_tracked_dirty", record)

    def test_git_dirty_ignores_generated_benchmark_artifacts(self) -> None:
        tracked_dirty = getattr(benchmark, "_git_tracked_dirty", None)
        self.assertTrue(callable(tracked_dirty))
        if not callable(tracked_dirty):
            return

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            artifact = repository / "docs/internal/benchmarks/result.ndjson"
            source = repository / "source.py"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("old\n", encoding="utf-8")
            source.write_text("old\n", encoding="utf-8")
            subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
            subprocess.run(("git", "add", "."), cwd=repository, check=True)
            subprocess.run(
                (
                    "git",
                    "-c",
                    "user.name=Benchmark Test",
                    "-c",
                    "user.email=benchmark@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ),
                cwd=repository,
                check=True,
            )

            artifact.write_text("new\n", encoding="utf-8")
            self.assertFalse(tracked_dirty(repository))

            source.write_text("new\n", encoding="utf-8")
            self.assertTrue(tracked_dirty(repository))

    def test_configuration_record_contains_complete_matrix(self) -> None:
        record = _configuration_record((1024,), 64, 4, 5)

        self.assertEqual("configuration", record["record"])
        self.assertEqual([1024], record["sizes_bytes"])
        self.assertEqual(65_536, record["chunk_size_bytes"])
        self.assertEqual(list(BACKENDS), record["backends"])
        self.assertEqual(list(SCENARIOS), record["scenarios"])
        self.assertEqual("subprocess", record.get("sample_isolation"))
        self.assertTrue(record["filesystem_location_prepared_before_timing"])

    def test_same_name_has_no_false_direct_baseline(self) -> None:
        self.assertEqual(
            ("filesystem_storage", "memory_storage"),
            SCENARIO_VARIANTS["same_name_concurrent"],
        )

    def test_execution_order_counterbalances_variants(self) -> None:
        first = _execution_order(1)
        second = _execution_order(2)
        self.assertEqual(
            (
                "filesystem_storage",
                "filesystem_direct",
                "filesystem_atomic_reference",
                "memory_storage",
            ),
            tuple(variant for scenario, variant in first if scenario == "bytes_save"),
        )
        self.assertEqual(
            (
                "memory_storage",
                "filesystem_atomic_reference",
                "filesystem_direct",
                "filesystem_storage",
            ),
            tuple(variant for scenario, variant in second if scenario == "bytes_save"),
        )

    def test_write_records_publishes_complete_ndjson_atomically(self) -> None:
        records = [{"record": "environment"}, {"record": "configuration"}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.ndjson"

            _write_records(output, records)

            decoded = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(records, decoded)
            self.assertEqual([output], list(Path(directory).iterdir()))

    def test_comparison_records_measure_storage_against_direct(self) -> None:
        storage = _comparison_sample(
            "filesystem_storage",
            "storage",
            round_number=1,
            elapsed=2.0,
        )
        storage["peak_process_rss_delta_bytes"] = 30
        direct = _comparison_sample(
            "filesystem_direct",
            "direct",
            round_number=1,
            elapsed=1.0,
        )
        direct["peak_process_rss_delta_bytes"] = 20
        samples = [storage, direct]

        comparison = _comparison_records(samples, _median_records(samples))[0]

        self.assertEqual("filesystem_direct", comparison["baseline_variant"])
        self.assertEqual(2.0, comparison["wall_time_ratio"])
        self.assertEqual(0.5, comparison["throughput_ratio"])
        self.assertEqual(2.0, comparison["cpu_time_ratio"])
        self.assertEqual(10, comparison["peak_process_rss_delta_bytes_delta"])

    def test_comparison_uses_paired_round_ratios_and_quartiles(self) -> None:
        samples: list[dict[str, Any]] = []
        for round_number, storage_elapsed, baseline_elapsed in (
            (1, 1.0, 1.0),
            (2, 2.0, 1.0),
            (3, 30.0, 10.0),
            (4, 40.0, 10.0),
        ):
            samples.extend(
                (
                    _comparison_sample(
                        "filesystem_storage",
                        "storage",
                        round_number=round_number,
                        elapsed=storage_elapsed,
                    ),
                    _comparison_sample(
                        "filesystem_atomic_reference",
                        "atomic_reference",
                        round_number=round_number,
                        elapsed=baseline_elapsed,
                    ),
                )
            )

        comparison = _comparison_records(samples, _median_records(samples))[0]

        self.assertEqual(
            "median_of_paired_round_ratios",
            comparison["comparison_method"],
        )
        self.assertEqual(4, comparison["paired_rounds"])
        self.assertEqual(2.5, comparison["wall_time_ratio"])
        self.assertEqual(1.75, comparison["wall_time_ratio_p25"])
        self.assertEqual(3.25, comparison["wall_time_ratio_p75"])
        self.assertEqual(2.5, comparison["cpu_time_ratio"])
        self.assertNotEqual(16.0 / 5.5, comparison["wall_time_ratio"])

    def test_percentile_uses_linear_interpolation_and_accepts_one_sample(self) -> None:
        percentile = getattr(benchmark, "_percentile", None)
        self.assertTrue(callable(percentile))
        if not callable(percentile):
            return

        self.assertEqual(1.75, percentile([4.0, 1.0, 3.0, 2.0], 0.25))
        self.assertEqual(3.25, percentile([4.0, 1.0, 3.0, 2.0], 0.75))
        self.assertEqual(7.0, percentile([7.0], 0.25))
        self.assertEqual(7.0, percentile([7.0], 0.75))

    def test_comparison_rejects_missing_paired_round(self) -> None:
        samples = [
            _comparison_sample(
                "filesystem_storage",
                "storage",
                round_number=1,
                elapsed=2.0,
            ),
            _comparison_sample(
                "filesystem_storage",
                "storage",
                round_number=2,
                elapsed=2.0,
            ),
            _comparison_sample(
                "filesystem_direct",
                "direct",
                round_number=1,
                elapsed=1.0,
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "paired rounds differ"):
            _comparison_records(samples, _median_records(samples))

    def test_comparison_rejects_duplicate_sample_round(self) -> None:
        storage = _comparison_sample(
            "filesystem_storage",
            "storage",
            round_number=1,
            elapsed=2.0,
        )
        samples = [
            storage,
            dict(storage),
            _comparison_sample(
                "filesystem_direct",
                "direct",
                round_number=1,
                elapsed=1.0,
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "duplicate benchmark sample"):
            _comparison_records(samples, _median_records(samples))

    def test_comparison_rejects_non_positive_paired_baseline(self) -> None:
        samples = [
            _comparison_sample(
                "filesystem_storage",
                "storage",
                round_number=1,
                elapsed=2.0,
            ),
            _comparison_sample(
                "filesystem_direct",
                "direct",
                round_number=1,
                elapsed=0.0,
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "non-positive paired baseline"):
            _comparison_records(samples, _median_records(samples))

    def test_comparison_records_include_raw_and_atomic_baselines(self) -> None:
        samples = [
            _comparison_sample(
                "filesystem_storage",
                "storage",
                round_number=1,
                elapsed=2.0,
            ),
            _comparison_sample(
                "filesystem_direct",
                "direct",
                round_number=1,
                elapsed=1.0,
            ),
            _comparison_sample(
                "filesystem_atomic_reference",
                "atomic_reference",
                round_number=1,
                elapsed=1.5,
            ),
        ]

        comparisons = _comparison_records(samples, _median_records(samples))

        self.assertEqual(
            ["filesystem_direct", "filesystem_atomic_reference"],
            [record.get("baseline_variant") for record in comparisons],
        )
        ratios = {record["baseline_variant"]: record["wall_time_ratio"] for record in comparisons}
        self.assertEqual(2.0, ratios["filesystem_direct"])
        self.assertEqual(2.0 / 1.5, ratios["filesystem_atomic_reference"])

    async def test_run_returns_complete_ordered_record_set(self) -> None:
        with redirect_stdout(StringIO()):
            records = await run((1,), 1, 1, 1, isolate_samples=False)

        self.assertEqual(
            ["environment", "configuration"],
            [row["record"] for row in records[:2]],
        )
        self.assertEqual(
            21,
            sum(row["record"] == "sample" for row in records),
        )
        self.assertEqual(
            21,
            sum(row["record"] == "median" for row in records),
        )
        self.assertEqual(
            9,
            sum(row["record"] == "comparison" for row in records),
        )

    async def test_run_isolates_samples_by_default(self) -> None:
        with redirect_stdout(StringIO()):
            records = await run((1,), 256, 1, 1)

        samples = [row for row in records if row["record"] == "sample"]
        self.assertEqual(21, len(samples))
        self.assertTrue(all(row["worker_pid"] != os.getpid() for row in samples))

    async def test_overwrite_verifier_rejects_stale_equal_length_content(self) -> None:
        storage = InMemoryStorage(chunk_size=2)
        counters = _Counters()
        _operation, verify = await _prepare_operation(
            storage,
            "overwrite",
            size=3,
            chunk_size=2,
            concurrency=1,
            payload=b"new",
            counters=counters,
        )

        with self.assertRaisesRegex(RuntimeError, "wrong stored content"):
            await verify()

    async def test_sample_removes_filesystem_data_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            await _sample(
                "filesystem_storage",
                "bytes_save",
                size=1024,
                chunk_size=64,
                concurrency=1,
                round_number=1,
                root=root,
            )

            self.assertEqual([], list(root.iterdir()))

    async def test_sample_prepares_storage_location_before_operation_setup(self) -> None:
        observed: list[bool] = []
        real_prepare = benchmark._prepare_operation

        async def recorded_prepare(storage: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(storage, FileSystemStorage):
                observed.append(storage.location.is_dir())
            return await real_prepare(storage, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                benchmark,
                "_prepare_operation",
                side_effect=recorded_prepare,
            ),
        ):
            await _sample(
                "filesystem_storage",
                "bytes_save",
                size=8,
                chunk_size=4,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        self.assertEqual([True], observed)

    async def test_direct_aiofiles_scenarios_validate_results(self) -> None:
        scenarios = (
            "bytes_save",
            "stream_save",
            "stream_read",
            "overwrite",
            "different_name_concurrent",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    result = await _sample(
                        "filesystem_direct",
                        scenario,
                        size=1024,
                        chunk_size=256,
                        concurrency=2,
                        round_number=1,
                        root=root,
                    )

                    self.assertEqual("filesystem_direct", result.get("variant"))

    async def test_isolated_sample_runs_in_a_fresh_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = await _isolated_sample(
                "memory_storage",
                "bytes_save",
                size=1,
                chunk_size=262_144,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        self.assertNotEqual(os.getpid(), result["worker_pid"])
        self.assertGreater(result["peak_process_rss_bytes"], 0)

    async def test_sample_peak_includes_prepared_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = await _sample(
                "memory_storage",
                "stream_read",
                size=65_536,
                chunk_size=1024,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        self.assertGreaterEqual(result["peak_python_allocation_bytes"], 65_536)

    async def test_sample_records_cpu_and_process_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = await _sample(
                "memory_storage",
                "bytes_save",
                size=1,
                chunk_size=262_144,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        self.assertIn("user_cpu_seconds", result)
        self.assertGreaterEqual(result["user_cpu_seconds"], 0)
        self.assertGreaterEqual(result["system_cpu_seconds"], 0)
        self.assertEqual(
            result["user_cpu_seconds"] + result["system_cpu_seconds"],
            result["cpu_seconds"],
        )
        self.assertGreaterEqual(result["cpu_to_wall_ratio"], 0)
        self.assertGreater(result["process_rss_before_bytes"], 0)
        self.assertGreater(result["peak_process_rss_bytes"], 0)
        self.assertGreaterEqual(result["peak_process_rss_delta_bytes"], 0)
        self.assertEqual(os.getpid(), result["worker_pid"])

    async def test_median_preserves_cpu_and_process_memory_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sample = await _sample(
                "memory_storage",
                "bytes_save",
                size=1,
                chunk_size=262_144,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        median = _median_records([sample])[0]

        self.assertIn("cpu_seconds", median)
        self.assertEqual(sample["cpu_seconds"], median["cpu_seconds"])
        self.assertEqual(sample["cpu_to_wall_ratio"], median["cpu_to_wall_ratio"])
        self.assertEqual(sample["peak_process_rss_bytes"], median["peak_process_rss_bytes"])
        self.assertEqual(
            sample["peak_process_rss_delta_bytes"],
            median["peak_process_rss_delta_bytes"],
        )

    async def test_stream_save_does_not_allocate_unused_input_payload(self) -> None:
        size = 1_048_576
        with tempfile.TemporaryDirectory() as directory:
            result = await _sample(
                "memory_storage",
                "stream_save",
                size=size,
                chunk_size=65_536,
                concurrency=1,
                round_number=1,
                root=Path(directory),
            )

        self.assertLess(result["peak_python_allocation_bytes"], size * 5 / 2)

    async def test_sample_stops_tracing_when_preparation_fails(self) -> None:
        async def failing_prepare(*args: object, **kwargs: object) -> object:
            self.assertTrue(tracemalloc.is_tracing())
            raise RuntimeError("prepare failed")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(benchmark, "_prepare_operation", new=failing_prepare),
                self.assertRaisesRegex(RuntimeError, "prepare failed"),
            ):
                await _sample(
                    "memory_storage",
                    "stream_read",
                    size=1,
                    chunk_size=1,
                    concurrency=1,
                    round_number=1,
                    root=Path(directory),
                )

        self.assertFalse(tracemalloc.is_tracing())
