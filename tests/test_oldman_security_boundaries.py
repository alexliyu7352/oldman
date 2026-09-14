"""Verify that generic and Web-specific security APIs do not cross layers."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from oldman.conf.schemas import FingerprintSecurityConfig
from oldman.security import jwt_decode
from oldman.security.jwt import jwt_decode as module_jwt_decode
from oldman.security.rate_limiter import TokenBucketRateLimiter
from oldman.security.rate_limiter.token_bucket import (
    TokenBucketRateLimiter as ModuleTokenBucketRateLimiter,
)
from oldman.web.security import (
    AESGcmDecrypt,
    WebSecurityPurpose,
    derive_web_security_key,
)
from oldman.web.security.decryptors import AESGcmDecrypt as ModuleAESGcmDecrypt
from oldman.web.security.keys import (
    WebSecurityPurpose as ModuleWebSecurityPurpose,
)
from oldman.web.security.keys import (
    derive_web_security_key as module_derive_web_security_key,
)

ROOT = Path(__file__).resolve().parents[1]


class OldmanSecurityBoundaryTest(unittest.TestCase):
    """Keep browser and HTTP policy outside the generic security package."""

    def test_public_aggregates_export_canonical_objects(self) -> None:
        """Aggregates must expose implementations without wrapper classes."""
        self.assertIs(jwt_decode, module_jwt_decode)
        self.assertIs(TokenBucketRateLimiter, ModuleTokenBucketRateLimiter)
        self.assertIs(AESGcmDecrypt, ModuleAESGcmDecrypt)
        self.assertIs(WebSecurityPurpose, ModuleWebSecurityPurpose)
        self.assertIs(derive_web_security_key, module_derive_web_security_key)
        self.assertEqual(
            60,
            FingerprintSecurityConfig().rate_limits["default"].window,
        )

    def test_removed_web_security_paths_have_no_compatibility_shims(self) -> None:
        """Web-specific modules must not survive under oldman.security."""
        removed = (
            "oldman.security.config",
            "oldman.security.decryptors",
            "oldman.security.rate_limiter.base",
            "oldman.security.rate_limiter.fingerprint",
            "oldman.security.rate_limiter.fixed_window",
            "oldman.security.rate_limiter.lua",
            "oldman.web.security.config",
        )
        for module_name in removed:
            with self.subTest(module_name=module_name):
                self.assertIsNone(importlib.util.find_spec(module_name))

    def test_generic_security_does_not_import_web_or_provider_layers(self) -> None:
        """The generic package must remain usable without reverse dependencies."""
        forbidden = ("oldman.web", "oldman.providers", "sanic")
        offenders: list[str] = []
        for path in (ROOT / "oldman" / "security").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(value in source for value in forbidden):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], offenders)

    def test_security_files_do_not_reference_the_removed_redis_module(self) -> None:
        """The Web fingerprint helper must use the current Redis registry."""
        offenders: list[str] = []
        for root in (ROOT / "oldman" / "security", ROOT / "oldman" / "web" / "security"):
            for path in root.rglob("*.py"):
                if "oldman.providers.redis.async_redis" in path.read_text(encoding="utf-8"):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
