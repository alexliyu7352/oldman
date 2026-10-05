"""A Web or background service's PID file, identity record and stop, through the real CLI.

Running means the PID file is locked; the identity record lets stop verify the process group it
signals, wait for all of it, and kill it at the deadline. These run a SimpleApplication service in a
temporary project; its Redis settings point at a closed port so nothing reaches a real server.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import oldman.processes.subprocess as managed_subprocess
import oldman.runtime._process_group as process_group
from oldman.processes.subprocess import _live_process_group_pids
from oldman.runtime._process_group import GroupIdentity, _process_identity, stop_process_group

ROOT = Path(__file__).resolve().parents[1]

SERVICE = """
import asyncio
import os
import time

from oldman.runtime import SimpleApplication

# A run a failed test left behind ends by itself.
DEADLINE = time.monotonic() + 120


class ProbeApplication(SimpleApplication):
    def prepare(self) -> None:
        pass

    def _setup_signal_handlers(self) -> None:
        super()._setup_signal_handlers()
        if os.environ.get("PROBE_MODE") == "signal-at-handlers":
            import signal

            # A stop request the moment the service can take one.
            os.kill(os.getpid(), signal.SIGTERM)

    async def main(self, *args, **kwargs) -> None:
        # The run's signal handlers are in place by now: until then SIGTERM ends it abruptly.
        open("main.started", "w").close()
        mode = os.environ.get("PROBE_MODE", "run")
        if mode == "fork-child":
            import multiprocessing

            multiprocessing.get_context("fork").Process(target=time.sleep, args=(60,)).start()
        if mode == "straggler":
            # A member from the start of the run that ignores SIGTERM, as a hung worker does.
            import signal

            child = os.fork()
            if child == 0:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(60)
                os._exit(0)
            with open("straggler.pid", "w") as file:
                file.write(str(child))
        if mode == "stop-inside":
            from oldman.logging import logger

            try:
                self.stop()
            except RuntimeError as error:
                logger.warning("refused: %s", error)
            logger.warning("still logging")
        try:
            await asyncio.sleep(max(0, DEADLINE - time.monotonic()))
        except asyncio.CancelledError:
            if mode in ("fork-on-stop", "fork-on-stop-ignoring-sigterm"):
                # A member that appears only once the stop has begun.
                import signal

                child = os.fork()
                if child == 0:
                    ignore = mode == "fork-on-stop-ignoring-sigterm"
                    signal.signal(signal.SIGTERM, signal.SIG_IGN if ignore else signal.SIG_DFL)
                    time.sleep(60)
                    os._exit(0)
                with open("late-member.pid", "w") as file:
                    file.write(str(child))
            if mode == "slow-stop":
                await asyncio.sleep(2)
            while mode == "stubborn" and time.monotonic() < DEADLINE:
                try:
                    await asyncio.sleep(DEADLINE - time.monotonic())
                except asyncio.CancelledError:
                    pass
            raise
"""


# A script in a terminal's foreground that starts the service and waits for it, as `bash run.sh probe
# start` does; like a service, it ignores SIGHUP. stdin "tty" starts the service directly, "devnull"
# is what bash gives a command a script puts in the background with `&`.
LAUNCHER = """
import signal, subprocess, sys, time

signal.signal(signal.SIGHUP, signal.SIG_IGN)
stdin_mode, result = sys.argv[1:3]
service = subprocess.Popen(
    [sys.executable, "-m", "oldman.cli", "probe", "start"],
    stdin=None if stdin_mode == "tty" else subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
code = service.wait()
with open(result, "w") as file:
    file.write(str(code))
time.sleep(120)  # kept for the test to read its terminal; killed by the cleanup, or ends by itself
"""


class ServiceProject:
    """A temporary project with one background service named `probe`."""

    def __init__(self, root: Path, *, stop_timeout: float) -> None:
        self.root = root
        files = {
            "pyproject.toml": "[project]\nname = 'pid-lifecycle-fixture'\nversion = '0'\n",
            "config/__init__.py": "",
            "config/schemas.py": "from oldman.conf import DefaultSettings\n\n\nclass Settings(DefaultSettings):\n    pass\n",
            "services/__init__.py": "",
            "services/probe.py": SERVICE,
            "data/probe_settings.yaml": textwrap.dedent(
                f"""
                apps: []
                process:
                  stop_timeout: {stop_timeout}
                redis:
                  DEFAULT:
                    redis_url: redis://127.0.0.1:1/0
                  CACHE:
                    redis_url: redis://127.0.0.1:1/1
                  SESSION:
                    redis_url: redis://127.0.0.1:1/2
                """
            ),
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.pid_file = root / "pids" / "probe.pid"
        self.identity_file = root / "pids" / "probe.identity.json"
        self.main_started = root / "main.started"
        self.processes: list[subprocess.Popen[str]] = []
        self.others: list[tuple[int, int]] = []

    def environment(self, mode: str) -> dict[str, str]:
        return {**os.environ, "PYTHONPATH": str(ROOT), "OLDMAN_CLI_LANGUAGE": "en", "PROBE_MODE": mode}

    def launch(self, action: str, *, mode: str = "run") -> subprocess.Popen[str]:
        """Run `probe <action>` in its own session, as a shell job or a service manager would."""
        process = subprocess.Popen(
            [sys.executable, "-m", "oldman.cli", "probe", action],
            cwd=self.root,
            env=self.environment(mode),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.processes.append(process)
        return process

    def start(self, *, mode: str = "run") -> subprocess.Popen[str]:
        """Start the service and return once it runs its main(), where a stop signal ends it normally."""
        self.main_started.unlink(missing_ok=True)
        process = self.launch("start", mode=mode)
        self.wait_running(process)
        wait_until(self.main_started.exists, "the service did not reach its main()")
        return process

    def wait_running(self, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 30
        while not (self.pid_file.exists() and self.pid_file.read_text().strip() == str(process.pid)):
            if process.poll() is not None or time.monotonic() > deadline:
                output = process.stdout.read() if process.poll() is not None and process.stdout else ""
                raise AssertionError(f"the service did not start (exit {process.poll()}): {output}")
            time.sleep(0.05)

    def run(self, action: str, *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "oldman.cli", "probe", action],
            cwd=self.root,
            env=self.environment("run"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def track(self, pid: int) -> None:
        """Have close() kill `pid`, a process that is not this test's child, if it is still the same process."""
        identity = _process_identity(pid)
        if identity is not None:
            self.others.append((pid, identity[1]))

    def close(self) -> None:
        """Kill what a test left running, and only that: a number a process gave up may name another process now.

        A child not yet collected keeps its number, so its group can be killed; one collected is left
        alone. Other processes are killed only while their start time still matches.
        """
        for process in self.processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        for pid, start_ticks in self.others:
            kill_if_unchanged(pid, start_ticks)


def kill_if_unchanged(pid: int, start_ticks: int) -> None:
    """SIGKILL `pid` (and its group when it leads one) only while it is still the process that started at `start_ticks`."""
    identity = _process_identity(pid)
    if identity is None or identity[1] != start_ticks:
        return
    try:
        if identity[0] == pid:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def terminal_foreground_group(pid: int) -> int:
    """The foreground process group of the terminal `pid` belongs to (tpgid in /proc/<pid>/stat)."""
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[5])


class Terminal:
    """A service started by LAUNCHER in a new terminal of its own."""

    def __init__(self, test: unittest.TestCase, project: ServiceProject, stdin_mode: str) -> None:
        self.result = project.root / f"launcher-{stdin_mode}.result"
        project.main_started.unlink(missing_ok=True)
        self.launcher, master = pty.fork()
        if self.launcher == 0:
            try:
                os.chdir(project.root)
                os.execve(sys.executable, [sys.executable, "-c", LAUNCHER, stdin_mode, str(self.result)], project.environment("run"))
            finally:
                os._exit(127)
        self.master: int | None = master
        self.service_identity: tuple[int, int] | None = None
        test.addCleanup(self.close)
        deadline = time.monotonic() + 30
        while not (project.pid_file.exists() and project.pid_file.read_text().isdigit() and project.identity_file.exists()):
            test.assertLess(time.monotonic(), deadline, "the service did not start in the terminal")
            time.sleep(0.05)
        self.service = int(project.pid_file.read_text())
        identity = _process_identity(self.service)
        if identity is not None:
            self.service_identity = (self.service, identity[1])
        # A stop signal before the service's main() ends it abruptly (exit -15) instead of normally.
        wait_until(project.main_started.exists, "the service did not reach its main()")

    def foreground(self) -> int:
        return terminal_foreground_group(self.launcher)

    def exit_code(self) -> str:
        deadline = time.monotonic() + 10
        while not (self.result.exists() and self.result.read_text()):
            if time.monotonic() > deadline:
                return "the service did not exit"
            time.sleep(0.05)
        return self.result.read_text()

    def hang_up(self) -> None:
        """Close the terminal, as closing a terminal window does; once, the number may be reused after."""
        if self.master is not None:
            os.close(self.master)
            self.master = None

    def close(self) -> None:
        # The service is the launcher's child, collected by it: kill it only while it is the same process.
        if self.service_identity is not None:
            kill_if_unchanged(*self.service_identity)
        # The launcher is this test's child and keeps its number until it is collected here.
        if os.waitpid(self.launcher, os.WNOHANG) == (0, 0):
            os.kill(self.launcher, signal.SIGKILL)
            os.waitpid(self.launcher, 0)
        self.hang_up()


def wait_until(condition, message: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.05)


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def dead_pid() -> int:
    """The pid of a process that has exited and been collected."""
    finished = subprocess.Popen(["true"])
    finished.wait()
    return finished.pid


class ServicePidLifecycleTest(unittest.TestCase):
    def project(self, *, stop_timeout: float = 10) -> ServiceProject:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        project = ServiceProject(Path(directory.name), stop_timeout=stop_timeout)
        self.addCleanup(project.close)
        return project

    def group_of_its_own(self) -> subprocess.Popen[bytes]:
        """An unrelated process leading a group of its own, as another program's service does."""
        process = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def unrelated_process(self) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(["sleep", "60"])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def test_stop_returns_once_the_service_has_exited(self) -> None:
        # It used to send SIGTERM and return at once, while the service was still shutting down.
        project = self.project()
        service = project.start(mode="slow-stop")
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertIn(f"Stopped probe (main process {service.pid}).", stopped.stdout)
        self.assertIsNotNone(service.poll(), "stop returned while the service still ran")
        self.assertFalse(project.pid_file.exists())
        self.assertFalse(project.identity_file.exists())

    def test_a_service_that_never_finishes_stopping_is_killed_at_the_deadline(self) -> None:
        project = self.project(stop_timeout=1)
        service = project.start(mode="stubborn")
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertEqual(-signal.SIGKILL, service.wait(timeout=5))
        self.assertEqual((), _live_process_group_pids(service.pid))
        self.assertFalse(project.pid_file.exists())
        self.assertFalse(project.identity_file.exists())

    def test_a_leftover_pid_file_does_not_block_start_when_its_pid_is_reused(self) -> None:
        # The PID file of a killed run survives; its number may now belong to any process.
        project = self.project()
        other = self.unrelated_process()
        project.pid_file.parent.mkdir(parents=True)
        project.pid_file.write_text(str(other.pid))
        project.start()
        self.assertIsNone(other.poll())
        self.assertEqual(0, project.run("stop").returncode)

    def test_stop_does_not_signal_a_pid_it_cannot_verify(self) -> None:
        project = self.project()
        other = self.unrelated_process()
        project.pid_file.parent.mkdir(parents=True)
        project.pid_file.write_text(str(other.pid))
        stopped = project.run("stop")
        self.assertNotEqual(0, stopped.returncode)
        self.assertIn("no identity record", stopped.stdout + stopped.stderr)
        time.sleep(0.2)
        self.assertIsNone(other.poll(), "stop signalled a process it could not verify")

    def test_a_second_start_is_refused_while_the_service_runs(self) -> None:
        project = self.project()
        service = project.start()
        second = project.run("start")
        self.assertNotEqual(0, second.returncode)
        self.assertIn(f"already running, pid: {service.pid}", second.stdout + second.stderr)
        self.assertEqual(0, project.run("stop").returncode)

    def killed_run_with_a_survivor(self, project: ServiceProject, *, pid_file: bool) -> tuple[int, tuple[int, ...]]:
        """The records of a run whose main process is gone while a process it started lives on."""
        # A primary killed with SIGKILL leaves its children (Sanic workers) in its group, on its port.
        leader = subprocess.Popen(
            [sys.executable, "-c", "import subprocess, sys; subprocess.Popen(['sleep', '60']); sys.stdin.readline()"],
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        project.processes.append(leader)
        deadline = time.monotonic() + 10
        while len(_live_process_group_pids(leader.pid)) < 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        pgid, start_ticks = _process_identity(leader.pid) or (0, 0)
        project.pid_file.parent.mkdir(parents=True)
        if pid_file:
            project.pid_file.write_text(str(leader.pid))
        project.identity_file.write_text(json.dumps({"pid": leader.pid, "pgid": pgid, "start_ticks": start_ticks, "boot_id": boot_id()}))
        assert leader.stdin is not None
        leader.stdin.write("\n")
        leader.stdin.flush()
        leader.wait(timeout=10)
        survivor = _live_process_group_pids(leader.pid)
        self.assertEqual(1, len(survivor))
        project.track(survivor[0])
        return leader.pid, survivor

    def test_start_and_stop_refuse_while_processes_of_a_killed_run_survive(self) -> None:
        project = self.project()
        leader, survivor = self.killed_run_with_a_survivor(project, pid_file=True)

        started = project.run("start")
        self.assertNotEqual(0, started.returncode)
        self.assertIn(f"process group {leader}: {survivor[0]}", started.stdout + started.stderr)
        stopped = project.run("stop")
        self.assertNotEqual(0, stopped.returncode)
        self.assertIn(f"process group {leader}: {survivor[0]}", stopped.stdout + stopped.stderr)
        self.assertEqual(survivor, _live_process_group_pids(leader), "stop signalled a group it could not verify")

    def test_start_says_the_service_still_runs_when_only_its_pid_file_was_removed(self) -> None:
        # start told the operator to kill the group it listed, and that group was the running service.
        project = self.project()
        service = project.start()
        project.pid_file.unlink()
        started = project.run("start")
        self.assertNotEqual(0, started.returncode)
        self.assertIn(f"is still running (main process {service.pid})", started.stdout + started.stderr)
        self.assertNotIn("kill -TERM -", started.stdout + started.stderr)
        self.assertIsNone(service.poll())
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertIsNotNone(service.poll(), "stop did not find the service by its identity record")

    def test_a_refused_start_leaves_no_pid_file_behind(self) -> None:
        # Its lock created an empty PID file, and every stop after it refused: "written by an earlier version".
        project = self.project()
        self.killed_run_with_a_survivor(project, pid_file=False)
        self.assertNotEqual(0, project.run("start").returncode)
        self.assertFalse(project.pid_file.exists())

    def test_an_empty_pid_file_is_not_a_running_service(self) -> None:
        # A start writes its identity before its pid: an empty file is a start on its way, or one killed early.
        project = self.project()
        project.pid_file.parent.mkdir(parents=True)
        project.pid_file.write_text("")
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertIn("probe is not running.", stopped.stdout)

    def test_an_unreadable_identity_with_nothing_running_is_cleared(self) -> None:
        # A record cut short by a power loss made every stop fail, and restart with it.
        project = self.project()
        project.pid_file.parent.mkdir(parents=True)
        project.pid_file.write_text(str(dead_pid()))
        project.identity_file.write_text("")
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertFalse(project.identity_file.exists())
        self.assertFalse(project.pid_file.exists())
        project.start()
        self.assertEqual(0, project.run("stop").returncode)

    def test_an_unreadable_identity_of_a_running_service_is_refused(self) -> None:
        project = self.project()
        service = project.start()
        project.identity_file.write_text("{broken")
        stopped = project.run("stop")
        self.assertNotEqual(0, stopped.returncode)
        self.assertIn("cannot be read", stopped.stdout + stopped.stderr)
        self.assertIn(f"(pid {service.pid}) with `kill -TERM <pid>`", stopped.stdout + stopped.stderr)
        self.assertIsNone(service.poll())
        self.assertEqual("{broken", project.identity_file.read_text())

    def test_stop_leaves_the_records_alone_when_a_new_instance_holds_the_lock(self) -> None:
        # The records of a run that is gone, while a new run has just locked the PID file and not yet
        # replaced them: they are about to be the new run's, and stop removed them under its feet.
        project = self.project()
        project.pid_file.parent.mkdir(parents=True)
        gone = dead_pid()
        recorded = json.dumps({"pid": gone, "pgid": gone, "start_ticks": 12345, "boot_id": boot_id()})
        project.identity_file.write_text(recorded)
        holder = os.open(project.pid_file, os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, holder)
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(holder, str(os.getpid()).encode())
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertEqual(recorded, project.identity_file.read_text())
        self.assertEqual(str(os.getpid()), project.pid_file.read_text())

    def test_a_forked_child_does_not_keep_a_killed_service_running(self) -> None:
        # multiprocessing forks by default on Linux before Python 3.14; the child inherited the
        # locked PID file and kept it locked, so start blamed the dead main process as running.
        project = self.project()
        service = project.start(mode="fork-child")
        deadline = time.monotonic() + 10
        while len(_live_process_group_pids(service.pid)) < 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        os.kill(service.pid, signal.SIGKILL)
        service.wait(timeout=10)
        (child,) = _live_process_group_pids(service.pid)
        project.track(child)

        started = project.run("start")
        self.assertNotEqual(0, started.returncode)
        self.assertNotIn("already running", started.stdout + started.stderr)
        self.assertIn(f"process group {service.pid}: {child}", started.stdout + started.stderr)

    def test_stop_called_inside_the_service_is_refused_and_its_logging_goes_on(self) -> None:
        # The refusal closed the service's logging: neither the reason nor anything after it reached the log.
        project = self.project()
        project.start(mode="stop-inside")
        log = project.root / "logs" / "probe.log"
        deadline = time.monotonic() + 10
        while "still logging" not in (log.read_text() if log.exists() else ""):
            self.assertLess(time.monotonic(), deadline, log.read_text() if log.exists() else "no log file")
            time.sleep(0.05)
        self.assertIn("refused: ProbeApplication: stop cannot be called from inside the running service", log.read_text())
        self.assertEqual(0, project.run("stop").returncode)

    def test_a_service_started_directly_by_a_foreground_script_takes_and_returns_the_terminal(self) -> None:
        # Ctrl-C in that terminal must reach the service; when it ends, the script gets the terminal back.
        project = self.project()
        terminal = Terminal(self, project, "tty")
        wait_until(lambda: terminal.foreground() == terminal.service, "the service did not take the terminal")
        self.assertEqual(0, project.run("stop").returncode)
        self.assertEqual("0", terminal.exit_code())
        self.assertEqual(terminal.launcher, terminal.foreground())

    def test_a_service_put_in_the_background_by_a_script_leaves_the_terminal_alone(self) -> None:
        # It took the terminal from the script still in the foreground: Ctrl-C then reached only the service.
        project = self.project()
        terminal = Terminal(self, project, "devnull")
        for _ in range(10):
            self.assertEqual(terminal.launcher, terminal.foreground())
            time.sleep(0.05)
        self.assertEqual(0, project.run("stop").returncode)
        self.assertEqual("0", terminal.exit_code())

    def test_a_hung_up_terminal_does_not_fail_the_service_on_exit(self) -> None:
        # Giving the terminal back raised EIO, and the service that had stopped normally exited 1.
        project = self.project()
        terminal = Terminal(self, project, "tty")
        wait_until(lambda: terminal.foreground() == terminal.service, "the service did not take the terminal")
        terminal.hang_up()
        self.assertEqual(0, project.run("stop").returncode)
        self.assertEqual("0", terminal.exit_code())

    def stop_a_run_that_forks_as_it_stops(self, mode: str, *, stop_timeout: float) -> tuple[subprocess.CompletedProcess[str], int, float]:
        """Stop a run whose service forks a member as it stops, then exits: the stop's result, the member, the seconds taken."""
        project = self.project(stop_timeout=stop_timeout)
        project.start(mode=mode)
        started = time.monotonic()
        stopped = project.run("stop")
        seconds = time.monotonic() - started
        late = project.root / "late-member.pid"
        wait_until(lambda: late.exists() and late.read_text().isdigit(), "the service forked no member as it stopped")
        member = int(late.read_text())
        project.track(member)
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertIsNone(_process_identity(member), "the member forked while stopping was left running")
        self.assertFalse(project.pid_file.exists())
        self.assertFalse(project.identity_file.exists())
        return stopped, member, seconds

    def test_a_member_forked_while_the_service_stops_is_stopped_with_it(self) -> None:
        # None of the processes stop had verified lived on, so it refused and left the member running;
        # the service had removed its records as it exited, so nothing pointed at the member again.
        stopped, _, seconds = self.stop_a_run_that_forks_as_it_stops("fork-on-stop", stop_timeout=10)
        self.assertNotIn("after the stop deadline", stopped.stdout + stopped.stderr)
        self.assertLess(seconds, 8, "the member was not asked to stop: only the deadline ended it")

    def test_a_member_forked_while_stopping_that_ignores_sigterm_is_killed_at_the_deadline(self) -> None:
        stopped, _, _ = self.stop_a_run_that_forks_as_it_stops("fork-on-stop-ignoring-sigterm", stop_timeout=2)
        self.assertIn("after the stop deadline", stopped.stdout + stopped.stderr)

    def test_a_member_that_outlives_the_deadline_is_killed_with_the_group(self) -> None:
        # The main process exits on SIGTERM; a member it started ignores it, as a hung worker does.
        project = self.project(stop_timeout=1)
        service = project.start(mode="straggler")
        straggler_file = project.root / "straggler.pid"
        wait_until(lambda: straggler_file.exists() and straggler_file.read_text().isdigit(), "the service forked no member")
        straggler = int(straggler_file.read_text())
        project.track(straggler)
        stopped = project.run("stop")
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        self.assertIn("after the stop deadline", stopped.stdout + stopped.stderr)
        self.assertIsNone(_process_identity(straggler), "the member was left running")
        self.assertEqual((), _live_process_group_pids(service.pid))

    def test_a_service_ended_without_stop_removes_its_own_records(self) -> None:
        # Ctrl-C, systemd or docker stop end it with a signal; nothing else would clean up after it.
        project = self.project()
        service = project.start()
        os.kill(service.pid, signal.SIGTERM)
        self.assertEqual(0, service.wait(timeout=10))
        self.assertFalse(project.pid_file.exists())
        self.assertFalse(project.identity_file.exists())

    def test_an_identity_from_another_boot_neither_blocks_start_nor_gets_signalled(self) -> None:
        # Its numbers describe processes of a boot that is over; a live group under them now is another program's.
        project = self.project()
        other = self.group_of_its_own()
        pgid, start_ticks = _process_identity(other.pid) or (0, 0)
        project.pid_file.parent.mkdir(parents=True)
        project.identity_file.write_text(json.dumps({"pid": other.pid, "pgid": pgid, "start_ticks": start_ticks, "boot_id": "an-earlier-boot"}))
        project.start()
        self.assertEqual(0, project.run("stop").returncode)
        self.assertIsNone(other.poll(), "a group named by an earlier boot's record was signalled")

    def test_an_identity_whose_main_process_number_is_reused_neither_blocks_start_nor_gets_signalled(self) -> None:
        # The recorded main process is gone and its number leads another program's group now.
        project = self.project()
        other = self.group_of_its_own()
        pgid, start_ticks = _process_identity(other.pid) or (0, 0)
        project.pid_file.parent.mkdir(parents=True)
        project.identity_file.write_text(json.dumps({"pid": other.pid, "pgid": pgid, "start_ticks": start_ticks + 1, "boot_id": boot_id()}))
        project.start()
        self.assertEqual(0, project.run("stop").returncode)
        self.assertIsNone(other.poll(), "a group whose leader's number was reused was signalled")

    def test_a_stop_signal_arriving_as_the_handlers_are_installed_ends_the_service(self) -> None:
        # uvloop drops a signal that arrives once add_signal_handler has run but before the loop does;
        # the handlers were installed before the loop ran, so the service ignored it and ran on.
        project = self.project()
        service = project.launch("start", mode="signal-at-handlers")
        self.assertEqual(0, service.wait(timeout=20))
        self.assertFalse(project.pid_file.exists())
        self.assertFalse(project.identity_file.exists())

    def test_restart_starts_the_new_run_after_the_old_one_has_exited(self) -> None:
        project = self.project()
        old = project.start(mode="slow-stop")
        restart = project.launch("restart")
        project.wait_running(restart)
        self.assertIsNotNone(old.poll(), "the new run started before the old one exited")
        self.assertEqual(0, project.run("stop").returncode)


class StopWaitTest(unittest.TestCase):
    def test_stop_does_not_scan_proc_at_every_poll(self) -> None:
        # A scan of /proc takes about 45 ms on a host with 600 processes; scanning at every 0.1 s poll kept
        # a third of a core busy for as long as stop waited.
        stubborn = subprocess.Popen(
            [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(flush=True); time.sleep(60)"],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(stubborn.stdout.close)  # type: ignore[union-attr]
        self.addCleanup(stubborn.wait)
        self.addCleanup(lambda: stubborn.poll() is None and os.killpg(stubborn.pid, signal.SIGKILL))
        assert stubborn.stdout is not None
        stubborn.stdout.readline()
        pgid, start_ticks = _process_identity(stubborn.pid) or (0, 0)
        scans = 0
        scan = managed_subprocess._live_process_group_pids

        def counted_scan(group: int) -> tuple[int, ...]:
            nonlocal scans
            scans += 1
            return scan(group)

        with (
            patch.object(managed_subprocess, "_live_process_group_pids", counted_scan),
            patch.object(process_group, "_live_process_group_pids", counted_scan),
        ):
            self.assertTrue(stop_process_group(GroupIdentity(stubborn.pid, pgid, start_ticks, boot_id()), 0.5))
        self.assertEqual(-signal.SIGKILL, stubborn.wait(timeout=5))
        # One scan to learn the members, one once the killed one is a zombie.
        self.assertLessEqual(scans, 3)


# exit(2), unlike exit_group(2), ends only the calling thread.
SYS_EXIT = {"x86_64": 60, "aarch64": 93}.get(os.uname().machine)

# The main thread leaves first, as it may when a multi-threaded service is killed: /proc then shows the
# process as a zombie while another thread still runs and holds its files, the PID file lock among them.
LEADER_LEAVES_FIRST = """
import ctypes, fcntl, os, signal, sys, threading, time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
threading.Thread(target=time.sleep, args=(60,), daemon=True).start()
print(flush=True)
ctypes.CDLL(None).syscall(int(sys.argv[2]), 0)
"""


def lock_is_free(path: Path) -> bool:
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


@unittest.skipUnless(SYS_EXIT, "needs the exit(2) syscall number of this architecture")
class ExitingThreadsTest(unittest.TestCase):
    """A process has not finished exiting while any of its threads runs, though its main thread is a zombie."""

    def leader_leaves_first(self) -> tuple[subprocess.Popen[str], Path]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        lock = Path(directory.name) / "probe.pid"
        process = subprocess.Popen(
            [sys.executable, "-c", LEADER_LEAVES_FIRST, str(lock), str(SYS_EXIT)],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(process.stdout.close)  # type: ignore[union-attr]
        self.addCleanup(process.wait)
        self.addCleanup(lambda: process.poll() is None and os.killpg(process.pid, signal.SIGKILL))
        assert process.stdout is not None
        process.stdout.readline()
        wait_until(lambda: self.stat(process.pid)[0] == "Z", "the main thread did not exit on its own")
        self.assertFalse(lock_is_free(lock))
        return process, lock

    def stat(self, pid: int) -> list[str]:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()

    def test_a_zombie_main_thread_with_a_running_thread_is_still_live(self) -> None:
        process, lock = self.leader_leaves_first()
        self.assertEqual((process.pid,), _live_process_group_pids(process.pid))
        self.assertIsNotNone(_process_identity(process.pid))

        os.killpg(process.pid, signal.SIGKILL)
        wait_until(lambda: lock_is_free(lock), "the killed process kept its lock")
        wait_until(lambda: not _live_process_group_pids(process.pid), "a process with no thread left still counts as live")
        self.assertIsNone(_process_identity(process.pid))

    def test_stop_returns_once_the_last_thread_has_released_the_pid_file_lock(self) -> None:
        # The CI failure: stop killed the service, saw only a zombie and returned while another thread still held
        # the PID file lock, so the records stayed behind.
        process, lock = self.leader_leaves_first()
        fields = self.stat(process.pid)
        identity = GroupIdentity(process.pid, int(fields[2]), int(fields[19]), boot_id())
        self.assertTrue(stop_process_group(identity, 0.5))
        self.assertTrue(lock_is_free(lock))
        self.assertEqual(-signal.SIGKILL, process.wait(timeout=5))


class GroupOneTest(unittest.TestCase):
    """killpg(1, sig) is kill(-1, sig): every process the caller may signal. Nothing may target group 1."""

    def test_an_identity_naming_process_1_is_refused(self) -> None:
        pgid, start_ticks = _process_identity(1) or (1, 0)
        record = json.dumps({"pid": 1, "pgid": pgid, "start_ticks": start_ticks, "boot_id": boot_id()})
        with self.assertRaises(ValueError):
            GroupIdentity.from_json(record)

    def test_stop_refuses_group_1_without_sending_a_signal(self) -> None:
        # Group 1's real start time, so that nothing but the refusal stands between it and the signals.
        # They are intercepted through the os module; a name bound straight from os would bypass that,
        # and this test would then send kill(-1) itself if the refusal broke.
        self.assertNotIn("kill", vars(process_group))
        self.assertNotIn("killpg", vars(process_group))
        pgid, start_ticks = _process_identity(1) or (1, 0)
        with (
            patch.object(process_group.os, "kill") as kill,
            patch.object(process_group.os, "killpg") as killpg,
            self.assertRaises(RuntimeError),
        ):
            stop_process_group(GroupIdentity(1, pgid, start_ticks, boot_id()), 1)
        kill.assert_not_called()
        killpg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
