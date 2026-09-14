"""Service-scoped Web security settings and key contracts."""

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from typing import Literal
from unittest.mock import patch

from pydantic import ValidationError

from oldman.apps.admin.settings import AdminSettings
from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import (
    DefaultSettings,
    FingerprintRateLimitConfig,
    FingerprintSecurityConfig,
    WebSecurityConfig,
)
from oldman.runtime import ServiceDefinition
from oldman.web.security import WebSecurityPurpose, derive_web_security_key


def _manager(
    root: Path,
    name: str,
    kind: Literal["web", "simple"],
) -> SettingsManager:
    """Build a manager whose Web scope comes only from the service definition."""
    definition = ServiceDefinition(
        name,
        root / "services" / f"{name}.py",
        kind,
    )
    return SettingsManager(
        DefaultSettings,
        definition,
        root / f"{name}_settings.yaml",
    )


class WebSecuritySettingsTest(unittest.TestCase):
    """Verify explicit generation, YAML-only loading, and key separation."""

    def test_web_init_generates_independent_secrets_and_private_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_manager = _manager(root, "first_web", "web")
            second_manager = _manager(root, "second_web", "web")

            first_manager.init_config()
            second_manager.init_config()
            first = first_manager.read_config()["web"]["security"]
            second = second_manager.read_config()["web"]["security"]

            self.assertGreaterEqual(len(first["secret_key"]), 32)
            self.assertEqual(
                32,
                len(base64.b64decode(first["fingerprint"]["aes_secret_key"], validate=True)),
            )
            self.assertNotEqual(first["secret_key"], second["secret_key"])
            self.assertNotEqual(
                first["fingerprint"]["aes_secret_key"],
                second["fingerprint"]["aes_secret_key"],
            )
            self.assertEqual(0o600, first_manager.config_file.stat().st_mode & 0o777)

    def test_simple_service_does_not_generate_web_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = _manager(Path(temporary_directory), "worker", "simple")

            manager.init_config()

            self.assertNotIn("web", manager.read_config())

    def test_sync_preserves_root_and_mode_while_filling_blank_aes(self) -> None:
        root_secret = "existing-web-security-root-secret-value"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = _manager(root, "web", "web")
            manager.config_file.write_text(
                f"web:\n  security:\n    secret_key: {root_secret}\n    fingerprint:\n      aes_secret_key:\n",
                encoding="utf-8",
            )
            manager.config_file.chmod(0o640)

            manager.sync_config()
            security = manager.read_config()["web"]["security"]

            self.assertEqual(root_secret, security["secret_key"])
            self.assertEqual(
                32,
                len(base64.b64decode(security["fingerprint"]["aes_secret_key"], validate=True)),
            )
            self.assertEqual(0o640, manager.config_file.stat().st_mode & 0o777)

    def test_runtime_requires_secrets_in_yaml_and_ignores_environment(self) -> None:
        aes_secret = base64.b64encode(bytes(range(32))).decode("ascii")
        root_secret = "yaml-web-security-root-secret-value"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manager = _manager(root, "web", "web")
            manager.config_file.write_text("web: {}\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "WEB__SECURITY__SECRET_KEY": "environment-web-security-root-secret-value",
                    "WEB__SECURITY__FINGERPRINT__AES_SECRET_KEY": aes_secret,
                },
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "settings.web.security.secret_key is empty"):
                    manager.load()

            manager.config_file.write_text(
                f"web:\n  security:\n    secret_key: {root_secret}\n    fingerprint:\n      aes_secret_key: {aes_secret}\n",
                encoding="utf-8",
            )
            loaded = manager.load()

        self.assertEqual(root_secret, loaded.web.security.secret_key)
        self.assertEqual(aes_secret, loaded.web.security.fingerprint.aes_secret_key)

    def test_security_models_reject_weak_or_incomplete_values(self) -> None:
        with self.assertRaisesRegex(ValidationError, "at least 32 characters"):
            WebSecurityConfig(secret_key="too-short")
        with self.assertRaisesRegex(ValidationError, "valid base64"):
            FingerprintSecurityConfig(aes_secret_key="not-base64")
        with self.assertRaisesRegex(ValidationError, "exactly 32 bytes"):
            FingerprintSecurityConfig(aes_secret_key=base64.b64encode(b"short").decode("ascii"))
        with self.assertRaisesRegex(ValidationError, "must define 'default'"):
            FingerprintSecurityConfig(
                rate_limits={
                    "/api/login": FingerprintRateLimitConfig(
                        window=1,
                        fp_max=1,
                        ip_max=1,
                    )
                }
            )

    def test_protocol_keys_are_stable_and_separated(self) -> None:
        root_secret = "purpose-separated-web-security-root-secret"
        derived = {purpose: derive_web_security_key(root_secret, purpose) for purpose in WebSecurityPurpose}

        self.assertEqual(len(WebSecurityPurpose), len(set(derived.values())))
        self.assertEqual(
            derived[WebSecurityPurpose.CSRF],
            derive_web_security_key(root_secret, WebSecurityPurpose.CSRF),
        )
        with self.assertRaises(TypeError):
            derive_web_security_key(root_secret, "oldman.web.csrf.v1")  # type: ignore[arg-type]

    def test_admin_app_settings_do_not_own_web_csrf_secrets(self) -> None:
        self.assertNotIn("csrf_secret_key", AdminSettings.model_fields)


if __name__ == "__main__":
    unittest.main()
