"""AsyncConfigDict concurrency tests migrated from the foundation source."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from oldman.conf.base import yaml
from oldman.conf.containers import AsyncConfigDict


class CountingConfigDict(AsyncConfigDict):
    """Config dictionary that exposes load/change counts for concurrency assertions."""

    def __init__(self, config_path: Path, check_interval: float = 5.0) -> None:
        super().__init__(config_path, check_interval=check_interval)
        self.load_count = 0
        self.changed_count = 0

    async def _load_file_content(self) -> str:
        self.load_count += 1
        await asyncio.sleep(0.02)
        return await super()._load_file_content()

    def get_empty_data(self) -> dict:
        return {"streams": {}}

    def on_file_changed(self, old_data: dict, new_data: dict) -> None:
        del old_data, new_data
        self.changed_count += 1


def write_yaml(path: Path, data: dict) -> None:
    """Write a small YAML fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        yaml.dump(data, file_handle)


class OldmanAsyncConfigDictTest(unittest.TestCase):
    """Verify first-load, hot-path, reload and write serialization."""

    def test_concurrent_initial_reads_wait_for_one_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streams.yaml"
            write_yaml(path, {"streams": {"one": {"name": "One"}}})
            config = CountingConfigDict(path)

            async def run_case() -> list[dict]:
                return await asyncio.gather(*(config.get_data() for _ in range(12)))

            results = asyncio.run(run_case())

        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(1, config.load_count)
        self.assertEqual(1, config.changed_count)

    def test_hot_path_uses_cache_within_check_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streams.yaml"
            write_yaml(path, {"streams": {"one": {"name": "One"}}})
            config = CountingConfigDict(path, check_interval=60)

            async def run_case() -> list[dict]:
                first = await config.get_data()
                results = [first]
                for _ in range(10):
                    results.append(await config.get_data())
                return results

            results = asyncio.run(run_case())

        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(1, config.load_count)

    def test_concurrent_reload_reads_changed_file_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "streams.yaml"
            write_yaml(path, {"streams": {"one": {"name": "One"}}})
            config = CountingConfigDict(path, check_interval=0)

            async def run_case() -> list[dict]:
                await config.get_data()
                await asyncio.sleep(0.01)
                write_yaml(path, {"streams": {"two": {"name": "Two"}}})
                return await asyncio.gather(*(config.get_data() for _ in range(12)))

            results = asyncio.run(run_case())

        self.assertTrue(all(result["streams"] == {"two": {"name": "Two"}} for result in results))
        self.assertEqual(2, config.load_count)
        self.assertEqual(2, config.changed_count)

    def test_save_marks_cache_loaded_and_missing_file_is_created_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved_path = Path(tmp) / "saved.yaml"
            saved = CountingConfigDict(saved_path, check_interval=60)
            missing_path = Path(tmp) / "missing.yaml"
            missing = CountingConfigDict(missing_path)

            async def run_case() -> tuple[dict, list[dict], bool]:
                await saved.save_data({"streams": {"saved": {"name": "Saved"}}})
                saved_data = await saved.get_data()
                missing_results = await asyncio.gather(*(missing.get_data() for _ in range(8)))
                return saved_data, missing_results, missing_path.exists()

            saved_data, missing_results, missing_exists = asyncio.run(run_case())

        self.assertEqual({"saved": {"name": "Saved"}}, saved_data["streams"])
        self.assertEqual(0, saved.load_count)
        self.assertTrue(all(result == {"streams": {}} for result in missing_results))
        self.assertTrue(missing_exists)


if __name__ == "__main__":
    unittest.main()
