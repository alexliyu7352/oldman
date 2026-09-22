"""Task configuration validation and YAML persistence without opening facilities."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings, NATSConnectionConfig, TaskiqConfig
from oldman.runtime import ServiceDefinition


class TaskiqConfigTest(unittest.TestCase):
    """Check operator-facing failures rather than only valid default construction."""

    def test_disabled_defaults_and_explicit_connections(self) -> None:
        """Root configuration is offline, including when credentials files are absent."""
        with patch("socket.socket", side_effect=AssertionError("configuration must not connect")):
            default = DefaultSettings()
            settings = DefaultSettings.model_validate({
                "nats": {"jobs": {"nats_url": "tls://localhost:4222", "tls_ca_file": "/missing/ca.pem"}},
                "redis": {"jobs": {"redis_url": "redis://localhost:6379/8"}},
                "taskiq": {"enabled": True, "namespace": "EPG-dev_1", "nats_alias": "jobs", "redis_alias": "jobs"},
            })
        self.assertFalse(default.taskiq.enabled)
        self.assertIsNone(default.taskiq.namespace)
        self.assertEqual("nats://localhost:4222", default.nats["DEFAULT"].nats_url)
        self.assertEqual("redis://localhost:6379/3", default.redis["DEFAULT"].redis_url)
        self.assertEqual("EPG-dev_1", settings.taskiq.namespace)
        self.assertEqual(["DEFAULT", "jobs"], list(settings.nats))
        self.assertEqual(2, len(settings.nats))
        with self.assertRaises(KeyError):
            _ = settings.nats["JOBS"]

    def test_invalid_task_configurations_are_rejected(self) -> None:
        """Subject injection, absent dependencies and unbounded waits fail early."""
        for value in (
            {"enabled": True}, {"namespace": " padded "}, {"namespace": "中文"},
            {"namespace": "a.b"}, {"consume_queues": []}, {"consume_queues": ["default", "default"]},
            {"consume_queues": [">", "x"]}, {"workers": 0}, {"max_async_tasks": -1},
            {"max_prefetch": -1}, {"startup_attempts": 0}, {"result_ex_time": 0},
            {"schedule_update_interval": 0}, {"stream_max_bytes": 0}, {"stream_max_bytes": -2},
            {"stream_replicas": 2}, {"max_ack_pending": 0}, {"duplicate_window": 9},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TaskiqConfig.model_validate(value)
        for field in ("startup_timeout", "shutdown_timeout", "stop_timeout", "ack_wait", "publish_timeout", "ack_timeout", "duplicate_window"):
            for value in (0, -1, float("inf"), float("nan")):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    TaskiqConfig.model_validate({field: value})
        for field in ("nats_alias", "redis_alias"):
            with self.subTest(field=field), self.assertRaisesRegex(ValidationError, field):
                DefaultSettings.model_validate({"taskiq": {"enabled": True, "namespace": "demo", field: "absent"}})

    def test_nats_authentication_validation_does_not_expose_credentials(self) -> None:
        """Conflicting credentials and malformed endpoints never become anonymous."""
        for values in (
            {"nats_url": "https://secret@localhost"},
            {"nats_url": "nats://secret@localhost:bad"},
            {"nats_url": "nats://secret@localhost?token=x"},
            {"nats_url": " nats://secret@localhost"},
            {"nats_url": "nats://secret@localhost", "credentials_file": "/missing/user.creds"},
            {"nats_url": "tls://secret@localhost", "tls_cert_file": "/missing/cert.pem"},
            {"nats_url": "nats://secret@localhost", "connect_timeout": float("inf")},
        ):
            with self.subTest(fields=list(values)):
                for build in (NATSConnectionConfig.model_validate, lambda v: DefaultSettings.model_validate({"nats": {"DEFAULT": v}})):
                    with self.assertRaises(ValidationError) as caught:
                        build(values)
                    self.assertNotIn("secret", str(caught.exception))
        self.assertEqual("nats://localhost:4222", DefaultSettings.model_validate({"nats": {"DEFAULT": {"connect_timeout": 4}}}).nats["DEFAULT"].nats_url)

    def test_init_and_sync_preserve_explicit_task_settings(self) -> None:
        """Existing service rules generate defaults but never enable or overwrite jobs."""
        with tempfile.TemporaryDirectory(prefix="oldman-taskiq-config-", dir="/tmp") as directory:
            root = Path(directory)
            path = root / "data" / "worker_settings.yaml"
            service = ServiceDefinition("worker", root / "services" / "worker.py", "simple")
            manager = SettingsManager(DefaultSettings, service, path)
            manager.init_config()
            raw = manager.read_config()
            self.assertFalse(raw["taskiq"]["enabled"])
            self.assertNotIn("web", raw)
            path.write_text("taskiq:\n  enabled: true\n  namespace: Custom_1\n  workers: 4\nnats:\n  DEFAULT:\n    connect_timeout: 7\n", encoding="utf-8")
            manager.sync_config()
            loaded = manager.load()
            self.assertTrue(loaded.taskiq.enabled)
            self.assertEqual("Custom_1", loaded.taskiq.namespace)
            self.assertEqual(4, loaded.taskiq.workers)
            self.assertEqual(7, loaded.nats["DEFAULT"].connect_timeout)
            self.assertEqual("nats://localhost:4222", loaded.nats["DEFAULT"].nats_url)


if __name__ == "__main__":
    unittest.main()
