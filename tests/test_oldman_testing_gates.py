"""The shared browser-gate machinery: owned resources, and proof they are released."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from oldman.testing.gates import (
    BrowserGateError,
    FirstUseInteraction,
    find_free_port,
    gate_settings,
    minimal_environment,
    owned_redis_server,
    owned_service,
    port_is_open,
    process_group_exists,
    redis_database_url,
    run_browser_child,
    service_command,
    wait_for_service,
)

ROOT = Path(__file__).resolve().parents[1]
# The shape gate_settings rewrites; a project's own example file carries far more than this.
EXAMPLE_SETTINGS = """
core:
  app_name: probe
  data_dir: ./data
logging:
  dir: ./logs
process:
  pid_dir: ./pids
database:
  url: sqlite+aiosqlite:///./data/probe.sqlite3
redis:
  CACHE:
    redis_url: redis://localhost:6379/2
  SESSION:
    redis_url: redis://127.0.0.1:6379/5
  SSE:
    redis_url: redis://127.0.0.1:6379/6
  TASKIQ:
    redis_url: redis://127.0.0.1:6379/7
web:
  listen_host: '::'
  listen_port: 17998
  workers: 4
  access_log: true
  security:
    secret_key: example-only
    fingerprint:
      aes_secret_key: example-only
  session:
    prefix: "probe_session:"
    user_prefix: "probe_user:"
    cookie_name: probe_sid
  sse:
    heartbeat_interval: 15
    session_check_interval: 30
  static:
    dir: ./frontend
    root: ./static
  template:
    dir: ./templates
storages:
  default:
    options:
      location: ./media
"""


class MinimalEnvironmentTest(unittest.TestCase):
    def test_it_keeps_only_allowlisted_values_and_fixes_the_clock(self) -> None:
        environment = minimal_environment(
            {"PATH": "/usr/bin", "SECRET_TOKEN": "leak", "LANG": "zh_TW.UTF-8", "LANGUAGE": "zh_TW:zh", "TZ": "Asia/Shanghai"}
        )

        self.assertEqual("/usr/bin", environment["PATH"])
        self.assertNotIn("SECRET_TOKEN", environment)
        # 时钟、hash 种子和语言都由门禁决定：开发机的 LANG 会改变浏览器请求的 Accept-Language，
        # 也就改变了被断言的那套界面文案。
        self.assertEqual(("C.UTF-8", "C.UTF-8", "en_US:en"), (environment["LANG"], environment["LC_ALL"], environment["LANGUAGE"]))
        self.assertEqual("UTC", environment["TZ"])
        self.assertEqual("0", environment["PYTHONHASHSEED"])


class RedisUrlTest(unittest.TestCase):
    def test_it_selects_a_logical_database_and_rejects_a_non_redis_url(self) -> None:
        self.assertEqual("redis://127.0.0.1:6380/2", redis_database_url("redis://127.0.0.1:6380", 2))
        self.assertEqual("rediss://host:6379/0", redis_database_url("rediss://host:6379/9", 0))
        with self.assertRaisesRegex(BrowserGateError, "concrete Redis URL"):
            redis_database_url("unix:///run/redis.sock", 0)


class PortAndProcessTest(unittest.TestCase):
    def test_a_reserved_port_is_free_and_this_process_group_exists(self) -> None:
        self.assertFalse(port_is_open(find_free_port()))
        self.assertTrue(process_group_exists(os.getpgid(0)))

    def test_waiting_fails_fast_when_the_service_exits_first(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"], start_new_session=True)
        process.wait(timeout=10)

        with self.assertRaisesRegex(BrowserGateError, "exited before listening: 3"):
            wait_for_service(process, find_free_port(), timeout=1, name="probe")


class GateSettingsTest(unittest.TestCase):
    def test_every_path_points_into_the_gate_state_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="oldman-gate-settings-") as directory:
            state_root = Path(directory)
            example = state_root / "web_settings.example.yaml"
            example.write_text(EXAMPLE_SETTINGS, encoding="utf-8")
            seen: list[str] = []

            config_file = gate_settings(
                example,
                state_root,
                service_port=18999,
                redis_url="redis://127.0.0.1:6399",
                namespace="oldman_probe_gate",
                database_name="probe.sqlite3",
                customize=lambda payload: seen.append(str(payload["core"]["data_dir"])),
            )

            from ruamel.yaml import YAML

            payload = YAML(typ="safe", pure=True).load(config_file.read_text(encoding="utf-8"))
            self.assertEqual(str(state_root / "data"), payload["core"]["data_dir"])
            self.assertEqual(f"sqlite+aiosqlite:///{state_root / 'probe.sqlite3'}", payload["database"]["url"])
            # 每一个别名都要落到门禁自己那台 Redis 的一个独立 database：漏掉一个就会写开发机的真实 Redis。
            self.assertEqual(
                {
                    "CACHE": "redis://127.0.0.1:6399/0",
                    "SESSION": "redis://127.0.0.1:6399/1",
                    "SSE": "redis://127.0.0.1:6399/2",
                    "TASKIQ": "redis://127.0.0.1:6399/3",
                },
                {alias: entry["redis_url"] for alias, entry in payload["redis"].items()},
            )
            self.assertEqual(18999, payload["web"]["listen_port"])
            self.assertEqual(1, payload["web"]["workers"])
            self.assertEqual("oldman_probe_gate_sid", payload["web"]["session"]["cookie_name"])
            self.assertEqual(str(state_root / "media"), payload["storages"]["default"]["options"]["location"])
            self.assertEqual("127.0.0.1", payload["web"]["listen_host"])
            self.assertNotEqual("example-only", payload["web"]["security"]["fingerprint"]["aes_secret_key"])
            # The secret key is generated per gate run instead of copied from the example file.
            self.assertGreaterEqual(len(payload["web"]["security"]["secret_key"]), 32)
            self.assertEqual([str(state_root / "data")], seen)


class ProcessGroupCleanupTest(unittest.TestCase):
    """清理必须针对整个进程组：领导进程先退出是常见情况，不是"已经干净了"。"""

    def test_it_signals_the_group_after_the_leader_has_exited(self) -> None:
        import subprocess
        import time

        from oldman.testing.gates import _terminate_group, process_group_exists

        child = subprocess.Popen(["sh", "-c", "sleep 60 & exit 0"], start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and child.poll() is None:
                time.sleep(0.05)
            self.assertIsNotNone(child.poll(), "领导进程应该已经退出")
            self.assertTrue(process_group_exists(child.pid), "同组的 sleep 应该还活着")

            _terminate_group(child, grace=3, kill_wait=3)

            self.assertFalse(process_group_exists(child.pid))
        finally:
            if process_group_exists(child.pid):
                _terminate_group(child, grace=1, kill_wait=1)


class FirstUseInteractionTest(unittest.TestCase):
    def test_it_answers_first_use_and_refuses_everything_else(self) -> None:
        interaction = FirstUseInteraction()

        self.assertEqual("first use", interaction.choose("internal migration state", ("first use", "adopt")))
        with self.assertRaises(BrowserGateError):
            interaction.choose("something else", ("first use",))
        with self.assertRaises(BrowserGateError):
            interaction.confirm("drop the table?")
        with self.assertRaises(BrowserGateError):
            interaction.text("migration name", default="auto")


class BrowserChildTest(unittest.TestCase):
    def test_a_clean_payload_passes_and_a_dirty_one_fails(self) -> None:
        clean = '{"ok": true, "browser": "chrome", "consoleErrors": [], "pageErrors": [], "badResponses": []}'
        dirty = '{"ok": true, "browser": "chrome", "consoleErrors": ["boom"], "pageErrors": [], "badResponses": []}'
        environment = minimal_environment({})

        result = run_browser_child(
            [sys.executable, "-c", f"print({clean!r})"],
            environment=environment,
            project_root=ROOT,
            browser="chrome",
        )
        self.assertIs(True, result["ok"])

        with self.assertRaisesRegex(BrowserGateError, "was not clean"):
            run_browser_child(
                [sys.executable, "-c", f"print({dirty!r})"],
                environment=environment,
                project_root=ROOT,
                browser="chrome",
            )
        with self.assertRaisesRegex(BrowserGateError, "invalid JSON"):
            run_browser_child(
                [sys.executable, "-c", "print('not json')"],
                environment=environment,
                project_root=ROOT,
                browser="chrome",
            )


class OwnedResourceTest(unittest.TestCase):
    def test_an_owned_redis_starts_and_leaves_nothing_behind(self) -> None:
        environment = minimal_environment()
        if shutil.which("redis-server", path=environment.get("PATH")) is None:
            self.skipTest("redis-server is required for this gate")
        with tempfile.TemporaryDirectory(prefix="oldman-gate-redis-") as directory:
            state_root = Path(directory)
            with owned_redis_server(state_root, environment=environment) as redis_url:
                port = int(redis_url.rsplit(":", 1)[1])
                self.assertTrue(port_is_open(port))
            self.assertFalse(port_is_open(port))

    def test_service_command_boots_through_the_public_entry_points(self) -> None:
        command = service_command(Path("/tmp/web_settings.yaml"), service="web")

        self.assertEqual(sys.executable, command[0])
        self.assertIn("bootstrap_service('web'", command[2])
        self.assertIn("get_service_definition('web'", command[2])
        self.assertIn("execute_command('start')", command[2])

    def test_an_owned_service_group_is_reaped_at_the_end(self) -> None:
        environment = minimal_environment()
        with tempfile.TemporaryDirectory(prefix="oldman-gate-service-") as directory:
            config_file = Path(directory) / "web_settings.yaml"
            config_file.write_text("", encoding="utf-8")
            with owned_service(config_file, environment=environment, project_root=ROOT, name="probe") as process:
                pid = process.pid
            self.assertFalse(process_group_exists(pid))
            self.assertTrue((Path(directory) / "probe.log").exists())


if __name__ == "__main__":
    unittest.main()
