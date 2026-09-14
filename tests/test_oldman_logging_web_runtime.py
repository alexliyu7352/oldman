"""Real-process acceptance tests for Sanic direct logging ownership and shutdown."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "logging_web_service.py"


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """Capture one completed fixture run and its observed process topology."""

    state: dict[str, Any]
    worker_states: dict[int, dict[str, Any]]
    reloader_states: dict[int, dict[str, Any]]
    response_states: dict[int, dict[str, Any]]
    matrix: dict[str, Any]
    log_text: str
    active_log_text: str
    archived_log_text: str
    access_text: str
    database_text: str
    stdout: str
    stderr: str


def _reserve_port() -> int:
    """Reserve and release one local TCP port for an isolated Sanic fixture."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _open_log_files(pid: int, log_dir: Path) -> set[Path]:
    """Return log files currently opened by one live Linux process."""
    result: set[Path] = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    if not fd_dir.exists():
        return result
    for descriptor in fd_dir.iterdir():
        try:
            target = Path(os.readlink(descriptor))
        except (FileNotFoundError, OSError):
            continue
        if target.suffix == ".log" and target.parent == log_dir:
            result.add(target)
    return result


def _read_json_response(
    port: int,
    path: str = "/pid",
    *,
    timeout: float = 0.5,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch one fixture route with explicit timeout and optional headers."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers or {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _run_on_worker(
    port: int,
    path: str,
    worker_pid: int,
    token: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Retry a fixture route until Sanic dispatches it to one selected worker."""
    deadline = time.monotonic() + timeout
    headers = {
        "X-Matrix-Target-Pid": str(worker_pid),
        "X-Matrix-Token": token,
    }
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        payload = _read_json_response(
            port,
            path,
            timeout=min(8.0, max(0.01, remaining)),
            headers=headers,
        )
        if time.monotonic() >= deadline:
            break
        if payload.get("executed") is True:
            return payload
        time.sleep(0.02)
    raise TimeoutError(f"route {path} never reached worker {worker_pid}")


def _run_ordinary_request_on_worker(
    port: int,
    worker_pid: int,
    run_id: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Send uniquely tokenized HTTP requests until one selected worker responds."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        suffix = f"{run_id}_{worker_pid}_{attempt}_{uuid.uuid4().hex[:8]}"
        access_token = f"MATRIX_HTTP_ACCESS_{suffix}"
        request_token = f"MATRIX_HTTP_REQREC_{suffix}"
        database_token = f"MATRIX_HTTP_DBREC_{suffix}"
        payload = _read_json_response(
            port,
            f"/matrix/pid/{access_token}",
            timeout=8,
            headers={
                "X-Matrix-Target-Pid": str(worker_pid),
                "X-Matrix-Request-Token": request_token,
                "X-Matrix-Database-Token": database_token,
            },
        )
        if payload.get("executed") is True:
            return payload
        time.sleep(0.02)
    raise TimeoutError(f"ordinary request never reached worker {worker_pid}")


def _read_existing(path: Path) -> str:
    """Read a diagnostic file without masking an earlier service failure."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<missing>"


def _terminate_service(
    process: subprocess.Popen[str],
    *,
    diagnostic_paths: tuple[Path, ...] = (),
    known_pids: set[int] | None = None,
) -> tuple[str, str]:
    """Stop the Sanic primary and forcibly clean its process group on timeout."""
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        return process.communicate(timeout=15)
    except subprocess.TimeoutExpired as exc:
        diagnostics = "\n".join(
            f"{path.name}:\n{_read_existing(path)}"
            for path in diagnostic_paths
        )
        observed_pids = {process.pid, *(known_pids or set())}
        observed_pids.update(
            int(pid) for pid in re.findall(r"MATRIX_CHILD_PID:(\d+)", diagnostics)
        )
        remaining = sorted(
            pid for pid in observed_pids if Path(f"/proc/{pid}").exists()
        )
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            "fixture did not stop after SIGTERM\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}\n"
            f"logs:\n{diagnostics}\nremaining_pids_before_kill:{remaining}"
        ) from exc


def _probe_records(log_text: str, token: str) -> dict[int, dict[str, Any]]:
    """Parse JSON process probes emitted with one unique fixture token."""
    records: dict[int, dict[str, Any]] = {}
    pattern = re.compile(rf"{re.escape(token)} (\{{.*\}})$")
    for line in log_text.splitlines():
        match = pattern.search(line)
        if match is None:
            continue
        payload = json.loads(match.group(1))
        records[int(payload["pid"])] = payload
    return records


class RunOnWorkerTest(unittest.TestCase):
    """Verify worker routing never exceeds its caller's timeout budget."""

    def test_request_timeout_uses_remaining_outer_budget(self) -> None:
        """One response read receives only the deadline's remaining duration."""
        with (
            patch(
                "tests.test_oldman_logging_web_runtime.time.monotonic",
                side_effect=(10.0, 10.25, 10.3),
            ),
            patch(
                "tests.test_oldman_logging_web_runtime._read_json_response",
                return_value={"executed": True},
            ) as read_response,
        ):
            result = _run_on_worker(8000, "/matrix/write", 123, "token", timeout=0.5)

        self.assertTrue(result["executed"])
        self.assertAlmostEqual(0.25, read_response.call_args.kwargs["timeout"])

    def test_response_after_outer_deadline_is_rejected(self) -> None:
        """A nominally successful response cannot escape a spent outer deadline."""
        with (
            patch(
                "tests.test_oldman_logging_web_runtime.time.monotonic",
                side_effect=(10.0, 10.25, 10.6),
            ),
            patch(
                "tests.test_oldman_logging_web_runtime._read_json_response",
                return_value={"executed": True},
            ) as read_response,
        ):
            with self.assertRaisesRegex(TimeoutError, "never reached worker 123"):
                _run_on_worker(8000, "/matrix/write", 123, "token", timeout=0.5)

        read_response.assert_called_once()


class OldmanLoggingWebRuntimeTest(unittest.TestCase):
    """Exercise the single direct topology through real Sanic workers."""

    maxDiff = None

    def _run_service(self, workers: int, *, auto_reload: bool = False) -> ServiceResult:
        """Run one fixture, inspect live ownership, then verify bounded shutdown."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "logs"
            log_dir.mkdir()
            state_file = root / "state.json"
            port = _reserve_port()
            run_id = uuid.uuid4().hex
            app_name = f"web_direct_{workers}_{run_id[:8]}"
            main_token = f"MAIN_{run_id}"
            worker_token = f"WORKER_{run_id}"
            request_token = f"REQUEST_{run_id}"
            database_token = f"DATABASE_{run_id}"
            reloader_token = f"RELOADER_{run_id}"
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_TEST_LOG_DIR": str(log_dir),
                    "OLDMAN_TEST_STATE_FILE": str(state_file),
                    "OLDMAN_TEST_APP_NAME": app_name,
                    "OLDMAN_TEST_MAIN_TOKEN": main_token,
                    "OLDMAN_TEST_WORKER_TOKEN": worker_token,
                    "OLDMAN_TEST_REQUEST_TOKEN": request_token,
                    "OLDMAN_TEST_DATABASE_TOKEN": database_token,
                    "OLDMAN_TEST_RELOADER_TOKEN": reloader_token,
                    "OLDMAN_TEST_WORKERS": str(workers),
                    "OLDMAN_TEST_PORT": str(port),
                    "OLDMAN_TEST_AUTO_RELOAD": "1" if auto_reload else "0",
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
            state: dict[str, Any] = {}
            response_states: dict[int, dict[str, Any]] = {}
            worker_states: dict[int, dict[str, Any]] = {}
            reloader_states: dict[int, dict[str, Any]] = {}
            matrix: dict[str, Any] = {
                "ordinary_by_worker": {},
                "async_by_worker": {},
                "rotation": {
                    "pre_tokens": [],
                    "reopen_probes": [],
                    "active_reopen_probes": {},
                    "post_tokens": [],
                },
            }
            log_prefix = FIXTURE.stem
            log_file = log_dir / f"{log_prefix}.log"
            archived_log_file = log_dir / f"{log_prefix}.log.matrix"
            access_file = log_dir / f"{log_prefix}_access.log"
            database_file = log_dir / f"{log_prefix}_database.log"
            deadline = time.monotonic() + 20
            try:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(
                            f"fixture exited during startup\nstdout:\n{stdout}\nstderr:\n{stderr}"
                        )
                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8"))
                        except json.JSONDecodeError:
                            pass
                    try:
                        response = _read_json_response(port)
                        response_states[int(response["pid"])] = response
                    except (ConnectionError, TimeoutError, urllib.error.URLError):
                        pass

                    if log_file.exists():
                        live_text = log_file.read_text(encoding="utf-8")
                        worker_states = _probe_records(live_text, worker_token)
                        reloader_states = _probe_records(live_text, reloader_token)
                    workers_ready = len(worker_states) == workers
                    responses_ready = len(response_states) == workers
                    reloader_ready = not auto_reload or len(reloader_states) == 1
                    if state and responses_ready and workers_ready and reloader_ready:
                        break
                    time.sleep(0.05)
                else:
                    diagnostics = "\n".join(
                        f"{path.name}:\n{_read_existing(path)}"
                        for path in (
                            archived_log_file,
                            log_file,
                            access_file,
                            database_file,
                        )
                    )
                    observed_pids = {
                        process.pid,
                        *worker_states,
                        *reloader_states,
                        *response_states,
                    }
                    if "pid" in state:
                        observed_pids.add(int(state["pid"]))
                    observed_pids.update(
                        int(pid)
                        for pid in re.findall(r"MATRIX_CHILD_PID:(\d+)", diagnostics)
                    )
                    live_pids = sorted(
                        pid for pid in observed_pids if Path(f"/proc/{pid}").exists()
                    )
                    stdout, stderr = _terminate_service(
                        process,
                        diagnostic_paths=(
                            archived_log_file,
                            log_file,
                            access_file,
                            database_file,
                        ),
                        known_pids=observed_pids,
                    )
                    self.fail(
                        "fixture did not become ready before timeout\n"
                        f"stdout:\n{stdout}\nstderr:\n{stderr}\n"
                        f"logs:\n{diagnostics}\nlive_pids_before_stop:{live_pids}"
                    )

                time.sleep(0.5)
                all_live_pids = {
                    int(state["pid"]),
                    *worker_states,
                    *reloader_states,
                }
                for pid in all_live_pids:
                    self.assertTrue(_open_log_files(pid, log_dir), f"PID {pid} has no log files")

                for worker_pid in worker_states:
                    matrix["ordinary_by_worker"][str(worker_pid)] = (
                        _run_ordinary_request_on_worker(port, worker_pid, run_id)
                    )

                for worker_pid in worker_states:
                    token = f"ASYNC_{run_id}_{worker_pid}"
                    matrix["async_by_worker"][str(worker_pid)] = _run_on_worker(
                        port,
                        "/matrix/async",
                        worker_pid,
                        token,
                    )

                if workers == 1:
                    only_worker_pid = next(iter(worker_states))
                    inherited_token = f"INHERITED_{run_id}"
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        inherited_future = executor.submit(
                            _run_on_worker,
                            port,
                            "/matrix/subprocess/inherited",
                            only_worker_pid,
                            inherited_token,
                        )
                        ready_token = f"WEB_INHERITED_READY:{inherited_token}"
                        deadline = time.monotonic() + 5
                        while (
                            ready_token not in _read_existing(log_file)
                            and time.monotonic() < deadline
                        ):
                            time.sleep(0.02)
                        self.assertIn(ready_token, _read_existing(log_file))
                        started = time.monotonic()
                        _read_json_response(port, "/pid", timeout=0.5)
                        probe_latency = time.monotonic() - started
                        inherited_result = inherited_future.result(timeout=5)
                    inherited_result["probe_latency"] = probe_latency
                    inherited_result["ready_token"] = ready_token
                    matrix["inherited"] = inherited_result

                    pipe_token = f"PIPE_{run_id}"
                    pipe_result = _run_on_worker(
                        port,
                        "/matrix/subprocess/pipe",
                        only_worker_pid,
                        pipe_token,
                    )
                    pipe_result["token"] = pipe_token
                    matrix["pipe"] = pipe_result

                if workers == 2:
                    pre_tokens = [f"WEB_PRE_{run_id}_{pid}" for pid in worker_states]
                    for worker_pid, token in zip(worker_states, pre_tokens, strict=True):
                        _run_on_worker(port, "/matrix/write", worker_pid, token)
                    deadline = time.monotonic() + 5
                    while (
                        not all(token in log_file.read_text(encoding="utf-8") for token in pre_tokens)
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.02)
                    self.assertTrue(
                        all(token in log_file.read_text(encoding="utf-8") for token in pre_tokens)
                    )
                    log_file.replace(archived_log_file)
                    log_file.touch()

                    reopen_probes: list[str] = []
                    active_reopen_probes: dict[str, str] = {}
                    for worker_pid in worker_states:
                        deadline = time.monotonic() + 2.5
                        while time.monotonic() < deadline:
                            reopen_probe = (
                                f"WEB_REOPEN_{run_id}_{worker_pid}_{uuid.uuid4().hex}"
                            )
                            _run_on_worker(
                                port,
                                "/matrix/write",
                                worker_pid,
                                reopen_probe,
                                timeout=max(0.01, deadline - time.monotonic()),
                            )
                            reopen_probes.append(reopen_probe)
                            if reopen_probe in log_file.read_text(encoding="utf-8"):
                                active_reopen_probes[str(worker_pid)] = reopen_probe
                                break
                            time.sleep(0.02)
                        else:
                            self.fail(
                                f"worker {worker_pid} did not reopen within 2.5 seconds"
                            )

                    post_tokens = [f"WEB_POST_{run_id}_{pid}" for pid in worker_states]
                    for worker_pid, token in zip(worker_states, post_tokens, strict=True):
                        _run_on_worker(port, "/matrix/write", worker_pid, token)
                    deadline = time.monotonic() + 2.5
                    while (
                        not all(token in log_file.read_text(encoding="utf-8") for token in post_tokens)
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.02)
                    self.assertTrue(
                        all(token in log_file.read_text(encoding="utf-8") for token in post_tokens)
                    )
                    matrix["rotation"] = {
                        "pre_tokens": pre_tokens,
                        "reopen_probes": reopen_probes,
                        "active_reopen_probes": active_reopen_probes,
                        "post_tokens": post_tokens,
                    }

                shutdown_pids = set(all_live_pids)
                for payload in matrix["async_by_worker"].values():
                    shutdown_pids.add(int(payload["first"]["pid"]))
                    shutdown_pids.add(int(payload["final"]["pid"]))
                if workers == 1:
                    shutdown_pids.add(int(matrix["inherited"]["pid"]))
                    shutdown_pids.add(int(matrix["pipe"]["pid"]))
                shutdown_log_text = _read_existing(archived_log_file) + _read_existing(log_file)
                shutdown_pids.update(
                    int(pid)
                    for pid in re.findall(r"MATRIX_CHILD_PID:(\d+)", shutdown_log_text)
                )
                stdout, stderr = _terminate_service(
                    process,
                    diagnostic_paths=(
                        archived_log_file,
                        log_file,
                        access_file,
                        database_file,
                    ),
                    known_pids=shutdown_pids,
                )
                self.assertEqual(0, process.returncode, stderr)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)

            active_log_text = log_file.read_text(encoding="utf-8")
            archived_log_text = (
                archived_log_file.read_text(encoding="utf-8")
                if archived_log_file.exists()
                else ""
            )
            log_text = archived_log_text + active_log_text
            access_text = access_file.read_text(encoding="utf-8")
            database_text = database_file.read_text(encoding="utf-8")
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual([], state["after_run"]["rotation_threads"])
            self.assertEqual([], state["after_run"]["pipe_reader_threads"])
            self.assertEqual(1, log_text.count(main_token))
            self.assertEqual(workers, log_text.count(worker_token))
            request_count = log_text.count(request_token)
            database_count = database_text.count(database_token)
            self.assertGreater(request_count, 0)
            self.assertEqual(request_count, database_count)
            self.assertIn(main_token, stdout)
            self.assertIn(worker_token, stdout)
            self.assertNotIn("\x1b[", log_text)
            self.assertNotIn("\x1b[", access_text)
            self.assertNotIn("\x1b[", database_text)
            self.assertIn("/pid", access_text)
            self.assertNotIn(main_token, access_text + database_text)
            self.assertNotIn(worker_token, access_text + database_text)
            self.assertNotIn(request_token, access_text)
            self.assertNotIn(database_token, log_text)
            self.assertNotIn(database_token, access_text)
            self.assertNotIn(request_token, database_text)
            for worker_pid, payload in matrix["ordinary_by_worker"].items():
                self.assertEqual(int(worker_pid), payload["worker"]["pid"])
                ordinary_request_token = payload["request_token"]
                ordinary_database_token = payload["database_token"]
                ordinary_access_token = payload["access_token"]
                self.assertEqual(1, log_text.count(ordinary_request_token))
                self.assertNotIn(ordinary_request_token, access_text + database_text)
                self.assertEqual(1, database_text.count(ordinary_database_token))
                self.assertNotIn(ordinary_database_token, log_text + access_text)
                self.assertEqual(1, access_text.count(ordinary_access_token))
                self.assertNotIn(ordinary_access_token, log_text + database_text)
            for worker_pid in worker_states:
                self.assertIn(f"Worker complete [{worker_pid}]", log_text)

            for payload in matrix["async_by_worker"].values():
                token = payload["token"]
                for label in ("first", "final"):
                    self.assertIn(f"MATRIX_RAW_STDOUT:{token}:{label}", stdout)
                    self.assertIn(f"MATRIX_RAW_STDERR:{token}:{label}", stdout)
                    file_outputs = log_text + access_text + database_text
                    self.assertNotIn(f"MATRIX_RAW_STDOUT:{token}:{label}", file_outputs)
                    self.assertNotIn(f"MATRIX_RAW_STDERR:{token}:{label}", file_outputs)

            related_pids = {
                *shutdown_pids,
                *(int(pid) for pid in re.findall(r"MATRIX_CHILD_PID:(\d+)", log_text)),
            }
            for payload in matrix["async_by_worker"].values():
                related_pids.add(int(payload["first"]["pid"]))
                related_pids.add(int(payload["final"]["pid"]))
            if workers == 1:
                related_pids.add(int(matrix["inherited"]["pid"]))
                related_pids.add(int(matrix["pipe"]["pid"]))
            deadline = time.monotonic() + 5
            while (
                any(Path(f"/proc/{pid}").exists() for pid in related_pids)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            self.assertFalse({pid for pid in related_pids if Path(f"/proc/{pid}").exists()})

            return ServiceResult(
                state=state,
                worker_states=worker_states,
                reloader_states=reloader_states,
                response_states=response_states,
                matrix=matrix,
                log_text=log_text,
                active_log_text=active_log_text,
                archived_log_text=archived_log_text,
                access_text=access_text,
                database_text=database_text,
                stdout=stdout,
                stderr=stderr,
            )

    def test_primary_workers_and_nested_processes_follow_the_logging_matrix(self) -> None:
        """Primary, workers and nested children follow the complete matrix."""
        for workers in (1, 2):
            with self.subTest(workers=workers):
                result = self._run_service(workers)
                self.assertTrue(result.state["owns_rotation"])
                self.assertEqual(["oldman-log-rotation"], result.state["rotation_threads"])
                self.assertIn("AtomicAppendFileHandler", result.state["handlers"])
                self.assertNotEqual({int(result.state["pid"])}, set(result.response_states))
                self.assertEqual(set(result.worker_states), set(result.response_states))
                for child_state in result.worker_states.values():
                    self.assertFalse(child_state["owns_rotation"])
                    self.assertEqual([], child_state["rotation_threads"])
                    self.assertIn("AtomicAppendFileHandler", child_state["handlers"])
                for response_state in result.response_states.values():
                    self.assertFalse(response_state["owns_rotation"])

                for worker_pid, payload in result.matrix["async_by_worker"].items():
                    self.assertEqual(int(worker_pid), payload["worker"]["pid"])
                    self.assertTrue(payload["timed_out"])
                    self.assertIsNone(payload["killed"])
                    self.assertEqual("first", payload["first"]["label"])
                    self.assertEqual("final", payload["final"]["label"])
                    for label in ("first", "final"):
                        probe = payload[label]
                        self.assertEqual("spawn", probe["billiard_start_method"])
                        self.assertFalse(probe["owns_rotation"])
                        self.assertEqual([], probe["rotation_threads"])
                        self.assertIn("AtomicAppendFileHandler", probe["handlers"])
                    self.assertEqual([], payload["pipe_reader_threads"])
                    token = payload["token"]
                    self.assertEqual(1, result.log_text.count(f"MATRIX_ASYNC:{token}:first"))
                    self.assertEqual(1, result.log_text.count(f"MATRIX_TIMEOUT:{token}"))
                    self.assertEqual(1, result.log_text.count(f"MATRIX_SIGKILL:{token}"))
                    self.assertEqual(1, result.log_text.count(f"MATRIX_ASYNC:{token}:final"))

                if workers == 1:
                    inherited = result.matrix["inherited"]
                    piped = result.matrix["pipe"]
                    self.assertLess(inherited["probe_latency"], 0.40)
                    self.assertEqual(1, result.log_text.count(inherited["ready_token"]))
                    self.assertIn(inherited["stdout_token"], result.stdout)
                    self.assertIn(inherited["stderr_token"], result.stderr)
                    self.assertNotIn(inherited["stdout_token"], result.log_text)
                    self.assertNotIn(inherited["stderr_token"], result.log_text)
                    pipe_token = piped["token"]
                    self.assertEqual(f"WEB_PIPE_STDOUT:{pipe_token}\n", piped["stdout"])
                    self.assertEqual(f"WEB_PIPE_STDERR:{pipe_token}\n", piped["stderr"])
                    automatic_output = (
                        result.stdout
                        + result.stderr
                        + result.log_text
                        + result.access_text
                        + result.database_text
                    )
                    self.assertNotIn(piped["stdout"].strip(), automatic_output)
                    self.assertNotIn(piped["stderr"].strip(), automatic_output)

                if workers == 2:
                    for token in result.matrix["rotation"]["pre_tokens"]:
                        self.assertEqual(1, result.archived_log_text.count(token))
                        self.assertNotIn(token, result.active_log_text)
                        self.assertEqual(1, result.log_text.count(token))
                    for token in result.matrix["rotation"]["reopen_probes"]:
                        self.assertEqual(1, result.log_text.count(token))
                    for token in result.matrix["rotation"][
                        "active_reopen_probes"
                    ].values():
                        self.assertEqual(1, result.active_log_text.count(token))
                        self.assertNotIn(token, result.archived_log_text)
                    for token in result.matrix["rotation"]["post_tokens"]:
                        self.assertEqual(1, result.active_log_text.count(token))
                        self.assertNotIn(token, result.archived_log_text)
                        self.assertEqual(1, result.log_text.count(token))

    def test_auto_reloader_uses_the_same_writer_only_context(self) -> None:
        """The Sanic reloader writes directly but never owns another coordinator."""
        result = self._run_service(1, auto_reload=True)

        self.assertEqual(1, len(result.reloader_states))
        self.assertTrue(result.state["owns_rotation"])
        self.assertEqual(["oldman-log-rotation"], result.state["rotation_threads"])
        for child_state in result.worker_states.values():
            self.assertFalse(child_state["owns_rotation"])
            self.assertEqual([], child_state["rotation_threads"])
            self.assertIn("AtomicAppendFileHandler", child_state["handlers"])
        for child_state in result.reloader_states.values():
            self.assertFalse(child_state["owns_rotation"])
            self.assertEqual([], child_state["rotation_threads"])
            self.assertIn("AtomicAppendFileHandler", child_state["handlers"])


if __name__ == "__main__":
    unittest.main()
