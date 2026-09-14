"""Real-process matrix for SimpleApplication logging and child lifecycles."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "logging_simple_service.py"


def _token_count(text: str, token: str) -> int:
    """Count matching log lines so duplicate records cannot hide in a set."""
    return sum(token in line for line in text.splitlines())


def _owned_pids(payload: dict[str, Any], combined_log: str) -> set[int]:
    """Collect every application, manager, temporary and subprocess PID."""
    base_manager = payload["base_manager"]
    async_manager = payload["async_manager"]
    subprocess_result = payload["subprocess"]
    pids = {
        int(payload["main"]["pid"]),
        int(base_manager["first_pid"]),
        int(base_manager["second_pid"]),
        int(async_manager["first"]["pid"]),
        int(async_manager["final"]["pid"]),
        int(subprocess_result["inherited_pid"]),
        int(subprocess_result["pipe_pid"]),
    }
    pids.update(int(value) for value in re.findall(r"MATRIX_CHILD_PID:(\d+)", combined_log))
    return pids


def _read_existing(path: Path) -> str:
    """Read a diagnostic file without masking the original timeout."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<missing>"


@unittest.skipUnless(sys.platform == "linux", "logging process matrix is Linux-only")
class OldmanLoggingSimpleRuntimeTest(unittest.TestCase):
    """Exercise S1-S6, R1 and C1 through one real SimpleApplication."""

    maxDiff = None

    def test_simple_application_process_logging_matrix(self) -> None:
        """All supported Simple child types keep the direct logging contract."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "logs"
            log_dir.mkdir()
            result_file = root / "result.json"
            run_id = uuid.uuid4().hex
            app_name = f"simple_matrix_{run_id[:8]}"
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_TEST_LOG_DIR": str(log_dir),
                    "OLDMAN_TEST_RESULT_FILE": str(result_file),
                    "OLDMAN_TEST_APP_NAME": app_name,
                    "OLDMAN_TEST_MATRIX_TOKEN": run_id,
                }
            )
            process = subprocess.Popen(
                [sys.executable, str(FIXTURE)],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=40)
            except subprocess.TimeoutExpired:
                diagnostic_paths = (
                    log_dir / f"{app_name}.log",
                    log_dir / f"{app_name}.log.matrix",
                    log_dir / f"{app_name}_database.log",
                )
                diagnostics = "\n".join(
                    f"{path.name}:\n{_read_existing(path)}"
                    for path in diagnostic_paths
                )
                observed_pids = {
                    process.pid,
                    *(
                        int(pid)
                        for pid in re.findall(r"(?:MATRIX_CHILD_PID:|MATRIX_BASE_TICK:.*:)(\d+)", diagnostics)
                    ),
                }
                remaining = sorted(
                    pid for pid in observed_pids if Path(f"/proc/{pid}").exists()
                )
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
                self.fail(
                    "Simple fixture hung\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}\n"
                    f"logs:\n{diagnostics}\nremaining_pids_before_kill:{remaining}"
                )

            self.assertEqual(0, process.returncode, f"stdout:\n{stdout}\nstderr:\n{stderr}")
            self.assertTrue(result_file.is_file(), f"missing result\nstdout:\n{stdout}\nstderr:\n{stderr}")

            payload = json.loads(result_file.read_text(encoding="utf-8"))
            active = (log_dir / f"{app_name}.log").read_text(encoding="utf-8")
            archived = (log_dir / f"{app_name}.log.matrix").read_text(encoding="utf-8")
            database = (log_dir / f"{app_name}_database.log").read_text(encoding="utf-8")
            combined = archived + active

            with self.subTest(matrix="S1"):
                self.assertTrue(payload["main"]["owns_rotation"])
                self.assertEqual(
                    ["oldman-log-rotation"],
                    payload["main"]["rotation_threads"],
                )
                self.assertIn("AtomicAppendFileHandler", payload["main"]["handlers"])
                self.assertEqual(1, _token_count(combined, f"SIMPLE_MAIN:{run_id}"))
                self.assertEqual(1, _token_count(database, f"SIMPLE_DATABASE:{run_id}"))
                self.assertNotIn(f"SIMPLE_DATABASE:{run_id}", combined)
                self.assertNotIn(f"SIMPLE_MAIN:{run_id}", database)
                self.assertIn(f"SIMPLE_MAIN:{run_id}", stdout)

            with self.subTest(matrix="S2-S3-R1"):
                base = payload["base_manager"]
                self.assertNotEqual(base["first_pid"], base["second_pid"])
                self.assertFalse(base["first_probe"]["owns_rotation"])
                self.assertFalse(base["second_probe"]["owns_rotation"])
                self.assertEqual([], base["first_probe"]["rotation_threads"])
                self.assertEqual([], base["second_probe"]["rotation_threads"])
                self.assertEqual("spawn", base["first_probe"]["start_method"])
                self.assertEqual("spawn", base["second_probe"]["start_method"])
                self.assertIn("AtomicAppendFileHandler", base["first_probe"]["handlers"])
                self.assertIn("AtomicAppendFileHandler", base["second_probe"]["handlers"])
                first_tick = f"MATRIX_BASE_TICK:{run_id}:{base['first_pid']}"
                second_tick = f"MATRIX_BASE_TICK:{run_id}:{base['second_pid']}"
                self.assertEqual(2, _token_count(combined, f"MATRIX_BASE_STATE:{run_id}:"))
                self.assertIn(first_tick, archived)
                self.assertIn(first_tick, active)
                self.assertIn(second_tick, active)
                self.assertNotIn(second_tick, archived)
                self.assertIn(f"MATRIX_BASE_STATE:{run_id}", stdout)

            with self.subTest(matrix="S4"):
                async_result = payload["async_manager"]
                self.assertTrue(async_result["timed_out"])
                self.assertIsNone(async_result["killed"])
                self.assertEqual("first", async_result["first"]["label"])
                self.assertEqual("final", async_result["final"]["label"])
                for label in ("first", "final"):
                    probe = async_result[label]
                    self.assertEqual("spawn", probe["billiard_start_method"])
                    self.assertFalse(probe["owns_rotation"])
                    self.assertEqual([], probe["rotation_threads"])
                    self.assertIn("AtomicAppendFileHandler", probe["handlers"])
                    structured = f"MATRIX_ASYNC:{run_id}:{label}"
                    raw_stdout = f"MATRIX_RAW_STDOUT:{run_id}:{label}"
                    raw_stderr = f"MATRIX_RAW_STDERR:{run_id}:{label}"
                    self.assertEqual(1, _token_count(combined, structured))
                    self.assertIn(raw_stdout, stdout)
                    self.assertIn(raw_stderr, stdout)
                self.assertEqual(1, _token_count(combined, f"MATRIX_TIMEOUT:{run_id}"))
                self.assertEqual(1, _token_count(combined, f"MATRIX_SIGKILL:{run_id}"))
                self.assertNotIn("MATRIX_RAW_STDOUT", combined)
                self.assertNotIn("MATRIX_RAW_STDERR", combined)

            with self.subTest(matrix="S5-S6"):
                subprocess_result = payload["subprocess"]
                self.assertEqual(0, subprocess_result["inherited_returncode"])
                self.assertEqual(0, subprocess_result["pipe_returncode"])
                self.assertGreater(subprocess_result["event_loop_ticks"], 0)
                self.assertIn(f"INHERITED_STDOUT:{run_id}", stdout)
                self.assertIn(f"INHERITED_STDERR:{run_id}", stderr)
                self.assertEqual(f"PIPE_STDOUT:{run_id}\n", subprocess_result["pipe_stdout"])
                self.assertEqual(f"PIPE_STDERR:{run_id}\n", subprocess_result["pipe_stderr"])
                self.assertNotIn(f"INHERITED_STDOUT:{run_id}", combined + database)
                self.assertNotIn(f"INHERITED_STDERR:{run_id}", combined + database)
                all_automatic_outputs = stdout + stderr + combined + database
                self.assertNotIn(f"PIPE_STDOUT:{run_id}", all_automatic_outputs)
                self.assertNotIn(f"PIPE_STDERR:{run_id}", all_automatic_outputs)

            with self.subTest(matrix="C1"):
                self.assertEqual([], payload["after_run"]["rotation_threads"])
                self.assertEqual([], payload["after_run"]["pipe_reader_threads"])
                remaining = {
                    pid
                    for pid in _owned_pids(payload, combined)
                    if Path(f"/proc/{pid}").exists()
                }
                self.assertFalse(remaining)

            self.assertNotIn("\x1b[", combined + database)


if __name__ == "__main__":
    unittest.main()
