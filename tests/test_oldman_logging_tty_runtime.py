"""Real-terminal acceptance tests for Simple and Web application logging."""

from __future__ import annotations

import errno
import json
import os
import pty
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_FIXTURE = ROOT / "tests" / "fixtures" / "logging_tty_simple_service.py"
WEB_FIXTURE = ROOT / "tests" / "fixtures" / "logging_tty_web_service.py"
ANSI_PREFIX = "\x1b["
CaptureMode = Literal["pty", "pipe"]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """Capture one fixture process and every artifact used for diagnostics."""

    mode: CaptureMode
    pid: int
    returncode: int | None
    output: str
    file_text: dict[str, str]
    decode_errors: dict[str, str]
    process_group_gone: bool
    state: dict[str, Any]

    @property
    def diagnostics(self) -> str:
        """Render complete bounded-run evidence for any failed assertion."""
        files = "\n".join(
            f"{name}:\n{text}" for name, text in sorted(self.file_text.items())
        )
        return (
            f"mode={self.mode} pid={self.pid} exit_code={self.returncode} "
            f"process_group_gone={self.process_group_gone}\n"
            f"output:\n{self.output}\n"
            f"decode_errors={self.decode_errors}\n"
            f"state={self.state}\n"
            f"active_and_archived_files:\n{files}"
        )


class _PtyReader:
    """Drain one PTY master concurrently and stop within a fixed deadline."""

    def __init__(self, master_fd: int) -> None:
        self._master_fd = master_fd
        self._chunks: list[bytes] = []
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._read_until_eof,
            name="oldman-tty-test-reader",
            daemon=True,
        )
        self._thread.start()

    def _read_until_eof(self) -> None:
        """Read until the slave side closes; Linux reports PTY EOF as EIO."""
        try:
            while True:
                try:
                    chunk = os.read(self._master_fd, 65536)
                except OSError as exc:
                    if exc.errno in {errno.EIO, errno.EBADF}:
                        return
                    raise
                if not chunk:
                    return
                self._chunks.append(chunk)
        except BaseException as exc:
            self._failure = exc

    @property
    def partial_output(self) -> str:
        """Return a read-only UTF-8 snapshot without waiting for EOF."""
        return b"".join(tuple(self._chunks)).decode("utf-8", errors="replace")

    def finish(self, timeout: float = 5.0) -> str:
        """Join the reader with a deadline and return UTF-8 diagnostic output."""
        self._thread.join(timeout)
        if self._thread.is_alive():
            os.close(self._master_fd)
            self._thread.join(1.0)
            raise TimeoutError("PTY reader did not reach EOF within 5 seconds")
        os.close(self._master_fd)
        if self._failure is not None:
            raise RuntimeError("PTY reader failed") from self._failure
        return self.partial_output


def _reserve_port() -> int:
    """Reserve and release a loopback port for one isolated Web fixture."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _token_count(text: str, token: str) -> int:
    """Count every token occurrence so same-line duplicates remain visible."""
    return text.count(token)


def _token_line(text: str, token: str) -> str:
    """Return the unique token-bearing line, or a diagnostic placeholder."""
    lines = [line for line in text.splitlines() if token in line]
    return lines[0] if len(lines) == 1 else f"<found {len(lines)} token lines>"


def _process_group_exists(process_group: int) -> bool:
    """Probe a dedicated fixture process group without changing it."""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_process_group_exit(process_group: int, timeout: float = 3.0) -> bool:
    """Bound how long successful fixture cleanup may retain descendants."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_group_exists(process_group):
            return True
        time.sleep(0.02)
    return not _process_group_exists(process_group)


def _kill_process_group(process: subprocess.Popen[bytes]) -> bool:
    """Kill a fixture group, reap its primary, and report bounded disappearance."""
    if _process_group_exists(process.pid):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"unable to reap killed fixture pid={process.pid} "
            f"exit_code={process.returncode}"
        ) from exc
    return _wait_for_process_group_exit(process.pid)


def _capture_log_files(log_dir: Path, app_name: str) -> tuple[dict[str, str], dict[str, str]]:
    """Strictly decode expected active logs and any timestamped archives."""
    active_names = (
        f"{app_name}.log",
        f"{app_name}_database.log",
        f"{app_name}_access.log",
    )
    paths = {log_dir / name for name in active_names}
    for active_name in active_names:
        paths.update(log_dir.glob(f"{active_name}.*"))

    texts: dict[str, str] = {}
    decode_errors: dict[str, str] = {}
    for path in sorted(paths):
        name = path.name
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            texts[name] = "<missing>"
            continue
        try:
            texts[name] = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            decode_errors[name] = str(exc)
            texts[name] = repr(payload)
    return texts, decode_errors


def _read_state(state_file: Path) -> dict[str, Any]:
    """Read fixture state without hiding a process or logging failure."""
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"state_error": repr(exc)}


def _series_text(result: ScenarioResult, active_name: str) -> str:
    """Combine one active log and its archives for exact token accounting."""
    return "".join(
        text
        for name, text in sorted(result.file_text.items())
        if name == active_name or name.startswith(f"{active_name}.")
    )


def _spawn_fixture(
    fixture: Path,
    env: dict[str, str],
    mode: CaptureMode,
) -> tuple[subprocess.Popen[bytes], _PtyReader | None]:
    """Start one fixture in its own session with real PTY or PIPE streams."""
    if mode == "pty":
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                [sys.executable, str(fixture)],
                cwd=ROOT,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        return process, _PtyReader(master_fd)

    process = subprocess.Popen(
        [sys.executable, str(fixture)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    return process, None


def _finish_process(
    process: subprocess.Popen[bytes],
    reader: _PtyReader | None,
    *,
    timeout: float,
) -> tuple[str, bool]:
    """Capture output, killing the entire process group on any timeout."""
    try:
        if reader is None:
            stdout, stderr = process.communicate(timeout=timeout)
            output = (stdout or b"").decode("utf-8", errors="replace")
            output += (stderr or b"").decode("utf-8", errors="replace")
        else:
            process.wait(timeout=timeout)
            try:
                output = reader.finish()
            except Exception as reader_error:
                partial_output = reader.partial_output
                group_gone = _kill_process_group(process)
                raise AssertionError(
                    f"PTY reader failed pid={process.pid} "
                    f"exit_code={process.returncode} "
                    f"process_group_gone={group_gone}\n"
                    f"partial_output:\n{partial_output}\n"
                    f"reader_error={reader_error!r}"
                ) from reader_error
    except subprocess.TimeoutExpired as exc:
        group_gone = _kill_process_group(process)
        if reader is None:
            stdout, stderr = process.communicate(timeout=5)
            output = (stdout or b"").decode("utf-8", errors="replace")
            output += (stderr or b"").decode("utf-8", errors="replace")
        else:
            try:
                output = reader.finish()
            except Exception as reader_error:
                partial_output = reader.partial_output
                group_gone = _kill_process_group(process)
                raise AssertionError(
                    f"PTY reader failed after process timeout pid={process.pid} "
                    f"exit_code={process.returncode} "
                    f"process_group_gone={group_gone}\n"
                    f"partial_output:\n{partial_output}\n"
                    f"reader_error={reader_error!r}\n"
                    f"process_error={exc!r}"
                ) from reader_error
        raise AssertionError(
            f"fixture timed out pid={process.pid} exit_code={process.returncode} "
            f"process_group_gone={group_gone}\n"
            f"output:\n{output}"
        ) from exc

    group_gone = _wait_for_process_group_exit(process.pid)
    if not group_gone:
        group_gone = _kill_process_group(process)
    return output, group_gone


def _wait_for_http_ready(
    process: subprocess.Popen[bytes],
    port: int,
    timeout: float = 15.0,
) -> None:
    """Poll HTTP readiness without invoking the uniquely tokenized route."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Web fixture exited before readiness pid={process.pid} "
                f"exit_code={process.returncode}"
            )
        remaining = deadline - time.monotonic()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/__oldman_tty_ready__",
                timeout=min(0.5, max(0.01, remaining)),
            ):
                return
        except urllib.error.HTTPError as exc:
            # A bounded HTTP 404 proves the server can complete a request while
            # keeping the single tokenized acceptance request untouched.
            exc.close()
            return
        except (TimeoutError, urllib.error.URLError):
            time.sleep(0.05)
    raise TimeoutError(f"Web fixture pid={process.pid} was not ready within 15 seconds")


def _wait_for_manager_ack_complete(
    process: subprocess.Popen[bytes],
    state_file: Path,
    timeout: float = 5.0,
) -> None:
    """Wait until Sanic's primary has left its worker-ack startup loop."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Web fixture exited before manager ACK completion pid={process.pid} "
                f"exit_code={process.returncode}"
            )
        if _read_state(state_file).get("manager_ack_complete") is True:
            return
        time.sleep(0.02)
    raise TimeoutError(
        f"Web fixture pid={process.pid} did not publish manager ACK completion "
        "within 5 seconds"
    )


class TtyRuntimeHelperTest(unittest.TestCase):
    """Keep exact-count and bounded-cleanup helpers deterministic."""

    def test_token_count_counts_repeats_within_one_line(self) -> None:
        """Duplicate tokens on one line must remain visible to exact-count gates."""
        self.assertEqual(2, _token_count("TOKEN TOKEN\n", "TOKEN"))

    def test_web_fixture_publishes_manager_ack_after_original_wait(self) -> None:
        """The shutdown gate must follow Sanic's successful worker-ack wait."""
        source = WEB_FIXTURE.read_text(encoding="utf-8")
        original_call = source.find("_ORIGINAL_MANAGER_WAIT_FOR_ACK(self)")
        publish = source.find("manager_ack_complete=True", original_call)
        preserved_return = source.find("return result", publish)

        self.assertNotEqual(-1, original_call)
        self.assertGreater(publish, original_call)
        self.assertGreater(preserved_return, publish)

    def test_pty_reader_timeout_keeps_partial_output(self) -> None:
        """Reader shutdown errors must not discard bytes already captured."""
        master_fd, slave_fd = pty.openpty()
        reader = _PtyReader(master_fd)
        try:
            os.write(slave_fd, b"partial-reader-token\n")
            deadline = time.monotonic() + 1
            while not reader._chunks and time.monotonic() < deadline:
                time.sleep(0.01)
            with self.assertRaises(TimeoutError):
                reader.finish(timeout=0.01)
            self.assertIn(
                "partial-reader-token",
                getattr(reader, "partial_output", ""),
            )
        finally:
            os.close(slave_fd)

    def test_finish_process_wraps_reader_failure_and_cleans_group(self) -> None:
        """A PTY drain failure reports partial bytes and kills descendants."""

        class FailingReader:
            partial_output = "partial-reader-token\n"

            @staticmethod
            def finish() -> str:
                raise TimeoutError("reader-stalled")

        source = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", source],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        caught: BaseException | None = None
        try:
            process.wait(timeout=5)
            try:
                _finish_process(process, FailingReader(), timeout=1)  # type: ignore[arg-type]
            except BaseException as exc:
                caught = exc

            self.assertIsInstance(caught, AssertionError)
            message = str(caught)
            self.assertIn("partial-reader-token", message)
            self.assertIn("reader-stalled", message)
            self.assertIn(f"pid={process.pid}", message)
            self.assertIn("exit_code=0", message)
            self.assertFalse(_process_group_exists(process.pid))
        finally:
            if _process_group_exists(process.pid):
                os.killpg(process.pid, signal.SIGKILL)
            _wait_for_process_group_exit(process.pid)

    def test_finish_process_returns_post_kill_group_cleanup_result(self) -> None:
        """A successful second cleanup check must replace the stale false state."""
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        with patch(
            f"{__name__}._wait_for_process_group_exit",
            side_effect=(False, True),
        ) as wait_for_exit:
            _, group_gone = _finish_process(process, None, timeout=5)

        self.assertTrue(group_gone)
        self.assertEqual(2, wait_for_exit.call_count)


@unittest.skipUnless(sys.platform == "linux", "real PTY logging gate is Linux-only")
class OldmanLoggingTtyRuntimeTest(unittest.TestCase):
    """Verify color=auto against real application streams and plain files."""

    maxDiff = None

    def _run_simple(self, mode: CaptureMode) -> tuple[ScenarioResult, dict[str, str]]:
        """Run one naturally exiting SimpleApplication scenario."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "logs"
            state_file = root / "state.json"
            log_dir.mkdir()
            suffix = uuid.uuid4().hex
            app_name = f"tty_simple_{suffix[:8]}"
            tokens = {
                "main": f"TTY_SIMPLE_MAIN_{suffix}",
                "error": f"TTY_SIMPLE_ERROR_{suffix}",
                "database": f"TTY_SIMPLE_DATABASE_{suffix}",
            }
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_TEST_LOG_DIR": str(log_dir),
                    "OLDMAN_TEST_STATE_FILE": str(state_file),
                    "OLDMAN_TEST_APP_NAME": app_name,
                    "OLDMAN_TEST_MAIN_TOKEN": tokens["main"],
                    "OLDMAN_TEST_ERROR_TOKEN": tokens["error"],
                    "OLDMAN_TEST_DATABASE_TOKEN": tokens["database"],
                }
            )
            process, reader = _spawn_fixture(SIMPLE_FIXTURE, env, mode)
            try:
                output, group_gone = _finish_process(process, reader, timeout=15)
            except BaseException as exc:
                cleanup_gone = not _process_group_exists(process.pid)
                if _process_group_exists(process.pid):
                    cleanup_gone = _kill_process_group(process)
                file_text, decode_errors = _capture_log_files(log_dir, app_name)
                raise AssertionError(
                    f"{exc}\n"
                    f"pid={process.pid} exit_code={process.returncode} "
                    f"process_group_gone_after_failure={cleanup_gone}\n"
                    f"decode_errors={decode_errors}\n"
                    f"state={_read_state(state_file)}\n"
                    "active_and_archived_files:\n"
                    + "\n".join(
                        f"{name}:\n{text}"
                        for name, text in sorted(file_text.items())
                    )
                ) from exc
            file_text, decode_errors = _capture_log_files(log_dir, app_name)
            result = ScenarioResult(
                mode=mode,
                pid=process.pid,
                returncode=process.returncode,
                output=output,
                file_text=file_text,
                decode_errors=decode_errors,
                process_group_gone=group_gone,
                state=_read_state(state_file),
            )
            return result, tokens

    def _run_web(self, mode: CaptureMode) -> tuple[ScenarioResult, dict[str, str]]:
        """Run one single-worker WebApplication request and normal shutdown."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "logs"
            state_file = root / "state.json"
            log_dir.mkdir()
            suffix = uuid.uuid4().hex
            app_name = f"tty_web_{suffix[:8]}"
            port = _reserve_port()
            tokens = {
                "main": f"TTY_WEB_MAIN_{suffix}",
                "error": f"TTY_WEB_ERROR_{suffix}",
                "database": f"TTY_WEB_DATABASE_{suffix}",
                "access": f"TTY_WEB_ACCESS_{suffix}",
            }
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_TEST_LOG_DIR": str(log_dir),
                    "OLDMAN_TEST_STATE_FILE": str(state_file),
                    "OLDMAN_TEST_APP_NAME": app_name,
                    "OLDMAN_TEST_MAIN_TOKEN": tokens["main"],
                    "OLDMAN_TEST_ERROR_TOKEN": tokens["error"],
                    "OLDMAN_TEST_DATABASE_TOKEN": tokens["database"],
                    "OLDMAN_TEST_PORT": str(port),
                }
            )
            process, reader = _spawn_fixture(WEB_FIXTURE, env, mode)
            response_state: dict[str, Any] = {}
            startup_error: BaseException | None = None
            try:
                _wait_for_http_ready(process, port)
                url = f"http://127.0.0.1:{port}/tty/{tokens['access']}"
                with urllib.request.urlopen(url, timeout=5) as response:
                    response_state = json.loads(response.read())
                _wait_for_manager_ack_complete(process, state_file)
            except BaseException as exc:
                startup_error = exc
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)

            try:
                output, group_gone = _finish_process(process, reader, timeout=15)
            except BaseException as exc:
                cleanup_gone = not _process_group_exists(process.pid)
                if _process_group_exists(process.pid):
                    cleanup_gone = _kill_process_group(process)
                file_text, decode_errors = _capture_log_files(
                    log_dir,
                    WEB_FIXTURE.stem,
                )
                raise AssertionError(
                    f"{exc}\n"
                    f"pid={process.pid} exit_code={process.returncode} "
                    f"process_group_gone_after_failure={cleanup_gone}\n"
                    f"decode_errors={decode_errors}\n"
                    f"state={_read_state(state_file)}\n"
                    "active_and_archived_files:\n"
                    + "\n".join(
                        f"{name}:\n{text}"
                        for name, text in sorted(file_text.items())
                    )
                ) from exc
            file_text, decode_errors = _capture_log_files(
                log_dir,
                WEB_FIXTURE.stem,
            )
            state = _read_state(state_file)
            state["response"] = response_state
            if startup_error is not None:
                state["request_error"] = repr(startup_error)
            result = ScenarioResult(
                mode=mode,
                pid=process.pid,
                returncode=process.returncode,
                output=output,
                file_text=file_text,
                decode_errors=decode_errors,
                process_group_gone=group_gone,
                state=state,
            )
            return result, tokens

    def _assert_console_policy(
        self,
        result: ScenarioResult,
        tokens: dict[str, str],
        color_tokens: tuple[str, ...],
    ) -> None:
        """Check exact console routing and the real stream's color boundary."""
        message = result.diagnostics
        for token in tokens.values():
            self.assertEqual(1, _token_count(result.output, token), message)
        for token_name in color_tokens:
            line = _token_line(result.output, tokens[token_name])
            if result.mode == "pty":
                self.assertIn(ANSI_PREFIX, line, message)
            else:
                self.assertNotIn(ANSI_PREFIX, line, message)

    def _assert_common_success(self, result: ScenarioResult) -> None:
        """Check bounded process, group, status and UTF-8 cleanup contracts."""
        message = result.diagnostics
        self.assertEqual(0, result.returncode, message)
        self.assertTrue(result.process_group_gone, message)
        self.assertEqual({}, result.decode_errors, message)
        self.assertEqual(result.pid, result.state.get("pid"), message)
        self.assertTrue(result.state.get("finished"), message)

    def test_simple_application_auto_color_uses_real_tty(self) -> None:
        """Simple console color follows a PTY while its two files stay plain."""
        for mode in ("pty", "pipe"):
            with self.subTest(mode=mode):
                result, tokens = self._run_simple(mode)
                self._assert_common_success(result)
                self._assert_console_policy(result, tokens, ("main", "error"))
                message = result.diagnostics
                main = _series_text(result, f"{result.state.get('app_name')}.log")
                database = _series_text(
                    result,
                    f"{result.state.get('app_name')}_database.log",
                )
                self.assertNotEqual("", main, message)
                self.assertNotEqual("", database, message)
                self.assertNotIn(ANSI_PREFIX, main + database, message)
                self.assertEqual(1, _token_count(main, tokens["main"]), message)
                self.assertEqual(1, _token_count(main, tokens["error"]), message)
                self.assertEqual(0, _token_count(main, tokens["database"]), message)
                self.assertEqual(1, _token_count(database, tokens["database"]), message)
                self.assertEqual(0, _token_count(database, tokens["main"]), message)
                self.assertEqual(0, _token_count(database, tokens["error"]), message)

    def test_web_application_auto_color_uses_real_tty(self) -> None:
        """Web main, error and access colors follow real PTY and PIPE streams."""
        for mode in ("pty", "pipe"):
            with self.subTest(mode=mode):
                result, tokens = self._run_web(mode)
                self._assert_common_success(result)
                self.assertIs(
                    result.state.get("main_process_ready"),
                    True,
                    result.diagnostics,
                )
                self.assertIs(
                    result.state.get("manager_ack_complete"),
                    True,
                    result.diagnostics,
                )
                self._assert_console_policy(
                    result,
                    tokens,
                    ("main", "error", "access"),
                )
                message = result.diagnostics
                worker_pid = result.state.get("response", {}).get("pid")
                self.assertIsInstance(worker_pid, int, message)
                self.assertFalse(Path(f"/proc/{worker_pid}").exists(), message)
                log_prefix = WEB_FIXTURE.stem
                main = _series_text(result, f"{log_prefix}.log")
                database = _series_text(result, f"{log_prefix}_database.log")
                access = _series_text(result, f"{log_prefix}_access.log")
                self.assertNotEqual("", main, message)
                self.assertNotEqual("", database, message)
                self.assertNotEqual("", access, message)
                self.assertNotIn(ANSI_PREFIX, main + database + access, message)
                self.assertEqual(1, _token_count(main, tokens["main"]), message)
                self.assertEqual(1, _token_count(main, tokens["error"]), message)
                self.assertEqual(0, _token_count(main, tokens["database"]), message)
                self.assertEqual(0, _token_count(main, tokens["access"]), message)
                self.assertEqual(1, _token_count(database, tokens["database"]), message)
                self.assertEqual(0, _token_count(database, tokens["main"]), message)
                self.assertEqual(0, _token_count(database, tokens["error"]), message)
                self.assertEqual(0, _token_count(database, tokens["access"]), message)
                self.assertEqual(1, _token_count(access, tokens["access"]), message)
                self.assertEqual(0, _token_count(access, tokens["main"]), message)
                self.assertEqual(0, _token_count(access, tokens["error"]), message)
                self.assertEqual(0, _token_count(access, tokens["database"]), message)


if __name__ == "__main__":
    unittest.main()
