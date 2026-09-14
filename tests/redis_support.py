"""Test-owned redis-server processes for the Linux integration gate."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from oldman.conf.schemas import RedisConfig


def require_redis_server(resolver: Callable[[str], str | None] = shutil.which) -> str:
    """Fail the Linux integration gate instead of silently skipping Redis."""
    executable = resolver("redis-server")
    if executable is None:
        raise RuntimeError("redis-server is required for the Linux integration gate")
    return executable


class RedisProcess:
    """Own one redis-server bound only to a temporary Unix socket."""

    def __init__(self, executable: str, directory: Path, name: str) -> None:
        self.socket_path = directory / f"{name}.sock"
        self.process = subprocess.Popen(
            [
                executable,
                "--save",
                "",
                "--appendonly",
                "no",
                "--port",
                "0",
                "--unixsocket",
                str(self.socket_path),
                "--unixsocketperm",
                "700",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while not self.socket_path.exists() and self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.socket_path.exists():
            self.stop()
            raise RuntimeError("redis-server did not create its owned Unix socket")

    def stop(self) -> None:
        """Stop Redis if it is still running."""
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


def owned_redis_config(socket_path: Path, databases: Mapping[str, int]) -> RedisConfig:
    """Point the given aliases at one owned socket, keeping each alias's database number."""
    return RedisConfig.model_validate(
        {alias: {"redis_url": f"unix://{socket_path.as_posix()}?db={database}", "health_check_interval": 0} for alias, database in databases.items()}
    )
