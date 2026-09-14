"""Real-process tests for Oldman's managed asyncio subprocess boundary."""

from __future__ import annotations

import asyncio
import json
import os
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
from pathlib import Path
from typing import Any

from oldman.processes.subprocess import (
    SubprocessError,
    SubprocessStartError,
    SubprocessTimeoutError,
    create_subprocess_exec,
    run_subprocess_exec,
)

ROOT = Path(__file__).resolve().parents[1]
PARENT_FIXTURE = ROOT / "tests" / "fixtures" / "managed_subprocess_parent.py"
WEB_FIXTURE = ROOT / "tests" / "fixtures" / "managed_subprocess_web_service.py"


def _process_state(pid: int) -> str | None:
    """Return one Linux process state, or None after complete removal."""
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, IndexError, OSError):
        return None


def _pid_is_live(pid: int) -> bool:
    """Treat a zombie as already stopped for process-lifecycle assertions."""
    state = _process_state(pid)
    return state is not None and state != "Z"


def _process_group_pids(process_group: int) -> list[int]:
    """Return live non-zombie PIDs still owned by one process group."""
    pids: list[int] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            state = fields[0]
            group = int(fields[2])
        except (FileNotFoundError, IndexError, OSError, ValueError):
            continue
        if group == process_group and state != "Z":
            pids.append(int(stat_path.parent.name))
    return sorted(pids)


def _wait_for_pids_gone(pids: set[int], timeout: float = 5.0) -> bool:
    """Wait synchronously until every selected process has stopped."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_pid_is_live(pid) for pid in pids):
            return True
        time.sleep(0.02)
    return not any(_pid_is_live(pid) for pid in pids)


async def _wait_for_file(path: Path, timeout: float = 5.0) -> str:
    """Wait asynchronously for a non-empty state file."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            await asyncio.sleep(0.02)
            continue
        if value:
            return value
        await asyncio.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {path}")


def _wait_for_json(path: Path, timeout: float = 10.0) -> dict[str, Any]:
    """Wait synchronously for one atomically published JSON object."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.02)
            continue
        if isinstance(value, dict):
            return value
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {path}")


def _reserve_port() -> int:
    """Reserve and release one loopback port for the Sanic fixture."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    """Wait until the real server worker accepts TCP connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.02)
    raise TimeoutError(f"port {port} did not become ready")


@unittest.skipUnless(sys.platform == "linux", "managed subprocess is Linux-only")
class ManagedSubprocessAsyncTest(unittest.IsolatedAsyncioTestCase):
    """Verify public async execution, output and group-cleanup semantics."""

    async def test_run_captures_output_without_blocking_the_event_loop(self) -> None:
        """PIPE draining must preserve bytes while other coroutines keep running."""
        ticks = 0
        ticking = True

        async def ticker() -> None:
            """Count scheduler turns until the command completes."""
            nonlocal ticks
            while ticking:
                ticks += 1
                await asyncio.sleep(0)

        ticker_task = asyncio.create_task(ticker())
        try:
            result = await run_subprocess_exec(
                sys.executable,
                "-c",
                "import sys,time; print('out'); print('err', file=sys.stderr); time.sleep(0.1)",
                capture_output=True,
                check=True,
            )
        finally:
            ticking = False
            await ticker_task

        self.assertEqual(0, result.returncode)
        self.assertEqual(b"out\n", result.stdout)
        self.assertEqual(b"err\n", result.stderr)
        self.assertGreater(ticks, 0)
        self.assertNotEqual(result.pid, result.supervisor_pid)

    async def test_communicate_supports_interactive_stdin(self) -> None:
        """The private supervisor must not consume or rewrite command stdio."""
        process = await create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(b"oldman")

        self.assertEqual(0, process.returncode)
        self.assertEqual(b"OLDMAN", stdout)
        self.assertEqual(b"", stderr)

    async def test_check_error_retains_command_output(self) -> None:
        """A non-zero result must preserve both output streams for diagnosis."""
        with self.assertRaises(SubprocessError) as caught:
            await run_subprocess_exec(
                sys.executable,
                "-c",
                "import sys; print('bad-out'); print('bad-err', file=sys.stderr); raise SystemExit(7)",
                capture_output=True,
                check=True,
            )

        self.assertEqual(7, caught.exception.result.returncode)
        self.assertEqual(b"bad-out\n", caught.exception.result.stdout)
        self.assertEqual(b"bad-err\n", caught.exception.result.stderr)

    async def test_start_error_names_the_requested_command(self) -> None:
        """An exec failure must arrive through the private startup handshake."""
        missing = f"/definitely-missing-oldman-command-{uuid.uuid4().hex}"
        with self.assertRaises(SubprocessStartError) as caught:
            await create_subprocess_exec(missing)

        self.assertEqual((missing,), caught.exception.command)
        self.assertIn(missing, caught.exception.message)

    async def test_cwd_and_environment_reach_the_actual_command(self) -> None:
        """Supervisor isolation must not change caller-selected cwd or env."""
        with tempfile.TemporaryDirectory() as directory:
            result = await run_subprocess_exec(
                sys.executable,
                "-c",
                "import os; print(os.getcwd()); print(os.environ['OLDMAN_CHILD_VALUE'])",
                cwd=directory,
                env={**os.environ, "OLDMAN_CHILD_VALUE": "kept"},
                capture_output=True,
                check=True,
            )

        self.assertEqual(
            f"{directory}\nkept\n".encode(),
            result.stdout,
        )

    async def test_timeout_kills_the_command_and_its_descendant(self) -> None:
        """Timeout cleanup must target the owned group rather than one PID."""
        with tempfile.TemporaryDirectory() as directory:
            descendant_file = Path(directory) / "descendant.txt"
            source = (
                "import pathlib,signal,subprocess,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
                "time.sleep(60)"
            )
            with self.assertRaises(SubprocessTimeoutError) as caught:
                await run_subprocess_exec(
                    sys.executable,
                    "-c",
                    source,
                    str(descendant_file),
                    timeout=0.2,
                    terminate_grace_period=0.1,
                )

            descendant_pid = int(await _wait_for_file(descendant_file))
            error = caught.exception
            self.assertFalse(_pid_is_live(error.pid))
            self.assertFalse(_pid_is_live(descendant_pid))
            self.assertEqual([], _process_group_pids(error.process_group))

    async def test_cancellation_cleans_the_complete_process_group(self) -> None:
        """Caller cancellation must propagate only after child cleanup completes."""
        with tempfile.TemporaryDirectory() as directory:
            descendant_file = Path(directory) / "descendant.txt"
            source = (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
                "time.sleep(60)"
            )
            process = await create_subprocess_exec(
                sys.executable,
                "-c",
                source,
                str(descendant_file),
                terminate_grace_period=0.1,
            )
            descendant_pid = int(await _wait_for_file(descendant_file))
            waiter = asyncio.create_task(process.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter

            self.assertFalse(_pid_is_live(process.pid))
            self.assertFalse(_pid_is_live(descendant_pid))
            self.assertEqual([], _process_group_pids(process.process_group))

    async def test_normal_exit_cleans_lingering_same_group_descendants(self) -> None:
        """A command cannot leave daemon-like same-group children behind."""
        with tempfile.TemporaryDirectory() as directory:
            descendant_file = Path(directory) / "descendant.txt"
            source = (
                "import pathlib,subprocess,sys; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')"
            )
            result = await run_subprocess_exec(
                sys.executable,
                "-c",
                source,
                str(descendant_file),
                terminate_grace_period=0.1,
            )
            descendant_pid = int(await _wait_for_file(descendant_file))

            self.assertEqual(0, result.returncode)
            self.assertFalse(_pid_is_live(descendant_pid))
            self.assertEqual([], _process_group_pids(result.process_group))

    async def test_supervisor_cleans_descendants_before_the_handle_is_awaited(self) -> None:
        """An un-awaited completed command must not outlive its safety supervisor."""
        with tempfile.TemporaryDirectory() as directory:
            descendant_file = Path(directory) / "descendant.txt"
            source = (
                "import pathlib,subprocess,sys; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')"
            )
            process = await create_subprocess_exec(
                sys.executable,
                "-c",
                source,
                str(descendant_file),
                terminate_grace_period=0.1,
            )
            descendant_pid = int(await _wait_for_file(descendant_file))
            try:
                supervisor_gone = await asyncio.to_thread(
                    _wait_for_pids_gone,
                    {process.supervisor_pid},
                )
                self.assertTrue(supervisor_gone)
                self.assertFalse(_pid_is_live(descendant_pid))
                self.assertEqual([], _process_group_pids(process.process_group))
                self.assertEqual(0, await process.wait())
            finally:
                await process.kill()

    async def test_kill_mirrors_sigkill_and_removes_the_owned_group(self) -> None:
        """The explicit hard-stop API must return the actual signal status."""
        process = await create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        )

        returncode = await process.kill()

        self.assertEqual(-signal.SIGKILL, returncode)
        self.assertEqual(returncode, process.returncode)
        self.assertEqual([], _process_group_pids(process.process_group))

    async def test_repeated_timeout_cancel_and_recovery_do_not_poison_later_runs(self) -> None:
        """Failure cleanup must not leave shared state that blocks a later command."""
        for _ in range(2):
            with self.assertRaises(SubprocessTimeoutError):
                await run_subprocess_exec(
                    sys.executable,
                    "-c",
                    "import time; time.sleep(60)",
                    timeout=0.05,
                    terminate_grace_period=0.05,
                )

            process = await create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                terminate_grace_period=0.05,
            )
            waiter = asyncio.create_task(process.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter

        result = await run_subprocess_exec(
            sys.executable,
            "-c",
            "print('recovered')",
            capture_output=True,
            check=True,
        )
        self.assertEqual(b"recovered\n", result.stdout)


@unittest.skipUnless(sys.platform == "linux", "managed subprocess is Linux-only")
class ManagedSubprocessParentDeathTest(unittest.TestCase):
    """Verify kernel-assisted cleanup when the owner cannot run finally blocks."""

    def test_plain_parent_sigkill_removes_command_and_descendant(self) -> None:
        """A killed ordinary parent must not leave its managed process group."""
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_SUBPROCESS_STATE_FILE": str(state_file),
                }
            )
            parent = subprocess.Popen(
                [sys.executable, str(PARENT_FIXTURE)],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            state: dict[str, Any] = {}
            try:
                state = _wait_for_json(state_file)
                os.kill(parent.pid, signal.SIGKILL)
                parent.communicate(timeout=5)
                owned_pids = {
                    int(state["pid"]),
                    int(state["supervisor_pid"]),
                    int(state["descendant_pid"]),
                }
                self.assertTrue(_wait_for_pids_gone(owned_pids))
                self.assertEqual([], _process_group_pids(int(state["process_group"])))
            finally:
                if parent.poll() is None:
                    os.killpg(parent.pid, signal.SIGKILL)
                    parent.communicate(timeout=5)
                if state and _process_group_pids(int(state["process_group"])):
                    os.killpg(int(state["process_group"]), signal.SIGKILL)

    def test_sanic_worker_sigkill_removes_command_and_descendant(self) -> None:
        """The same parent-death contract must hold inside a real Sanic worker."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "logs"
            state_dir = root / "state"
            log_dir.mkdir()
            state_dir.mkdir()
            port = _reserve_port()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(ROOT),
                    "OLDMAN_SUBPROCESS_LOG_DIR": str(log_dir),
                    "OLDMAN_SUBPROCESS_STATE_DIR": str(state_dir),
                    "OLDMAN_SUBPROCESS_APP_NAME": f"subprocess_web_{uuid.uuid4().hex[:8]}",
                    "OLDMAN_SUBPROCESS_PORT": str(port),
                }
            )
            service = subprocess.Popen(
                [sys.executable, str(WEB_FIXTURE)],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            state: dict[str, Any] = {}
            try:
                _wait_for_port(port)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/start", timeout=10) as response:
                    state = json.loads(response.read())
                worker_pid = int(state["worker_pid"])
                os.kill(worker_pid, signal.SIGKILL)
                owned_pids = {
                    int(state["pid"]),
                    int(state["supervisor_pid"]),
                    int(state["descendant_pid"]),
                }
                self.assertTrue(_wait_for_pids_gone(owned_pids))
                self.assertEqual([], _process_group_pids(int(state["process_group"])))
            except urllib.error.URLError as exc:
                stdout, stderr = service.communicate(timeout=5)
                self.fail(f"Web fixture request failed: {exc!r}\nstdout:\n{stdout}\nstderr:\n{stderr}")
            finally:
                if service.poll() is None:
                    os.killpg(service.pid, signal.SIGKILL)
                    service.communicate(timeout=5)
                if state and _process_group_pids(int(state["process_group"])):
                    os.killpg(int(state["process_group"]), signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
