"""The real-server checks fail the gate when their servers are missing; they never skip."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.nats_support import require_nats_server
from tests.redis_support import require_redis_server


def fake_redis_server(directory: Path, version: str) -> str:
    """An executable that answers --version as redis-server does."""
    path = directory / f"redis-server-{version}"
    path.write_text(f"#!/bin/sh\necho 'Redis server v={version} sha=00000000:0 malloc=libc bits=64 build=0'\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


class IntegrationServerRequirementTest(unittest.TestCase):
    def test_missing_redis_server_is_a_gate_failure_not_a_skip(self) -> None:
        """The integration requirement itself cannot be converted into a green skip."""
        with self.assertRaisesRegex(RuntimeError, "redis-server is required"):
            require_redis_server(lambda _name: None, environ={})

    def test_a_redis_server_older_than_6_2_is_refused(self) -> None:
        """taskiq-redis reads results and schedules with GETDEL, which Redis 5 does not have."""
        with tempfile.TemporaryDirectory() as directory:
            old = fake_redis_server(Path(directory), "5.0.7")
            with self.assertRaisesRegex(RuntimeError, "5.0.7 .* older than 6.2"):
                require_redis_server(lambda _name: old, environ={})
            new = fake_redis_server(Path(directory), "6.2.0")
            self.assertEqual(new, require_redis_server(lambda _name: None, environ={"REDIS_SERVER": new}))

    def test_redis_server_from_the_environment_comes_before_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chosen = fake_redis_server(Path(directory), "8.0.6")
            on_path = fake_redis_server(Path(directory), "7.0.15")
            self.assertEqual(chosen, require_redis_server(lambda _name: on_path, environ={"REDIS_SERVER": chosen}))

    def test_missing_nats_server_is_a_gate_failure_not_a_skip(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "nats-server is required"):
            require_nats_server(lambda _name: None, environ={})

    def test_nats_server_from_the_environment_comes_before_path(self) -> None:
        self.assertEqual("/opt/nats", require_nats_server(lambda _name: "/usr/bin/nats-server", environ={"NATS_SERVER": "/opt/nats"}))
        self.assertEqual("/usr/bin/nats-server", require_nats_server(lambda _name: "/usr/bin/nats-server", environ={}))


if __name__ == "__main__":
    unittest.main()
