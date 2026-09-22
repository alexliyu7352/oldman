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


class JsonSerializerChoiceTest(unittest.TestCase):
    """Where orjson replaced the stdlib, and the three places it must not.

    The swap is worth doing on request-path code - orjson is roughly ten times faster to
    serialize and three to eight times faster to parse - but only where the output is
    byte-identical. It is not universally identical, and two of the differences change
    meaning rather than formatting.
    """

    def test_jwt_timestamps_stay_numbers(self) -> None:
        """orjson serializes datetime natively, which would make exp a string.

        JWT requires exp and iat to be numeric. Without OPT_PASSTHROUGH_DATETIME orjson
        never calls the default hook for a datetime, so the claim silently becomes
        "2030-01-01T00:00:00+00:00" and every verifier rejects it.
        """
        from datetime import UTC, datetime

        from oldman.security.jwt import jwt_decode, jwt_encode

        secret = "x" * 40
        claims = {"sub": "u-1", "exp": datetime(2030, 1, 1, tzinfo=UTC), "iat": datetime(2026, 9, 20, tzinfo=UTC)}
        decoded = jwt_decode(jwt_encode(claims, secret), secret)

        self.assertIsInstance(decoded["exp"], int)
        self.assertIsInstance(decoded["iat"], int)

    def test_the_broker_message_id_is_unchanged_by_the_swap(self) -> None:
        """Changing the serializer here would renumber messages already in flight."""
        import hashlib
        import json

        import orjson

        for identity in (
            ["oldman.q.default", "send_mail", "abc-123", 0],
            ["oldman.q.默认", "发送邮件", "id-中文", 3],
            ["q", 'name "quoted" and\\escaped', "i", 99],
        ):
            with self.subTest(identity=identity):
                previous = json.dumps(identity, separators=(",", ":"), ensure_ascii=False).encode()
                self.assertEqual(previous, orjson.dumps(identity))
                self.assertEqual(
                    hashlib.sha256(previous).hexdigest(),
                    hashlib.sha256(orjson.dumps(identity)).hexdigest(),
                )

    def test_the_nan_guards_keep_the_standard_library(self) -> None:
        """allow_nan=False raises; orjson writes null. That is a silent corruption."""
        import json
        from pathlib import Path

        import orjson

        with self.assertRaises(ValueError):
            json.dumps({"v": float("nan")}, allow_nan=False)
        self.assertEqual(b'{"v":null}', orjson.dumps({"v": float("nan")}))

        root = Path(__file__).resolve().parents[1] / "oldman"
        for relative in ("web/components/forms/fields.py", "db/fixtures.py"):
            with self.subTest(module=relative):
                source = (root / relative).read_text(encoding="utf-8")
                self.assertIn("allow_nan=False", source)
                self.assertIn("json.dumps(", source, "the NaN guard must stay on the standard library")

    def test_the_static_manifest_keeps_the_standard_library(self) -> None:
        """It escapes non-ASCII; orjson has no ensure_ascii and would change the artifact."""
        import json
        from pathlib import Path

        import orjson

        payload = {"名字": "值"}
        self.assertIn(b"\\u540d", json.dumps(payload, indent=2, sort_keys=True).encode())
        self.assertNotIn(b"\\u540d", orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))

        source = (Path(__file__).resolve().parents[1] / "oldman" / "web" / "staticfiles" / "collector.py").read_text(encoding="utf-8")
        self.assertIn("json.dumps(payload, indent=2, sort_keys=True)", source)
