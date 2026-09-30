"""run_foreground: a command on the caller's terminal, with subprocess.run's results and errors."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from oldman.processes import run_foreground, run_subprocess_exec

SESSION_AND_GROUP = "import os; print(os.getsid(0), os.getpgid(0))"


class RunForegroundTest(unittest.TestCase):
    def test_the_child_stays_in_the_callers_session_and_process_group(self) -> None:
        # That is what lets it open the terminal (sudo) and receive Ctrl-C with the caller;
        # run_subprocess_exec gives its child a session of its own.
        completed = asyncio.run(run_foreground(sys.executable, "-c", SESSION_AND_GROUP, capture_output=True, text=True))
        self.assertEqual(f"{os.getsid(0)} {os.getpgid(0)}", completed.stdout.strip())
        managed = asyncio.run(run_subprocess_exec(sys.executable, "-c", SESSION_AND_GROUP, capture_output=True))
        self.assertNotEqual(str(os.getsid(0)), (managed.stdout or b"").split()[0].decode())

    def test_input_output_and_a_failing_command(self) -> None:
        script = "import sys; data = sys.stdin.read(); print(data.upper()); print('broke', file=sys.stderr); sys.exit(3)"
        completed = asyncio.run(run_foreground(sys.executable, "-c", script, input="abc", capture_output=True, text=True))
        self.assertEqual((3, "ABC\n", "broke\n"), (completed.returncode, completed.stdout, completed.stderr))
        with self.assertRaises(subprocess.CalledProcessError) as failed:
            asyncio.run(run_foreground(sys.executable, "-c", script, input=b"abc", capture_output=True, check=True))
        self.assertEqual((3, b"broke\n"), (failed.exception.returncode, failed.exception.stderr))

    def test_cwd_env_and_path_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "where.py"
            script.write_text("import os; print(os.getcwd(), os.environ.get('WHERE_TEST'), 'HOME' in os.environ)")
            completed = asyncio.run(
                run_foreground(Path(sys.executable), script, cwd=directory, env={"WHERE_TEST": "yes"}, capture_output=True, text=True)
            )
        self.assertEqual(f"{Path(directory).resolve()} yes False", completed.stdout.strip())

    def test_a_missing_program_and_a_timeout(self) -> None:
        with self.assertRaises(FileNotFoundError):
            asyncio.run(run_foreground("/nonexistent/program"))
        with self.assertRaises(subprocess.TimeoutExpired):
            asyncio.run(run_foreground(sys.executable, "-c", "import time; time.sleep(5)", timeout=0.2))

    def test_the_event_loop_keeps_running_while_it_waits(self) -> None:
        async def scenario() -> int:
            ticks = 0

            async def tick() -> None:
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.02)
                    ticks += 1

            ticker = asyncio.create_task(tick())
            await run_foreground(sys.executable, "-c", "import time; time.sleep(0.4)")
            ticker.cancel()
            return ticks

        self.assertGreater(asyncio.run(scenario()), 5)


if __name__ == "__main__":
    unittest.main()
