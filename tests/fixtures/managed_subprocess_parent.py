"""Parent process fixture used to prove parent-death cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from oldman.processes import create_subprocess_exec


async def _wait_for_text(path: Path, timeout: float = 5.0) -> str:
    """Wait asynchronously for one child-owned state file."""
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


async def main() -> None:
    """Start a managed command and remain alive until the test kills this parent."""
    state_file = Path(os.environ["OLDMAN_SUBPROCESS_STATE_FILE"])
    descendant_file = state_file.with_suffix(".descendant")
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
    )
    descendant_pid = int(await _wait_for_text(descendant_file))
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "parent_pid": os.getpid(),
                "pid": process.pid,
                "supervisor_pid": process.supervisor_pid,
                "process_group": process.process_group,
                "descendant_pid": descendant_pid,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(state_file)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
