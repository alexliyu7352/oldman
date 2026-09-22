"""Behavior tests for the migrated fingerprint security helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oldman.web.security import AESGcmDecrypt, fingerprint, get_stats


class FakeFingerprintRedis:
    async def smembers(self, key: str) -> set[str]:
        self.last_members_key = key
        return {"127.0.0.1"}

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        del start, end
        return [json.dumps({"key": key})]

    async def exists(self, key: str) -> int:
        self.last_exists_key = key
        return 1


class FingerprintSecurityTest(unittest.TestCase):
    def test_web_crypto_decryptor_preserves_json_and_invalid_json_results(self) -> None:
        """The moved decryptor must retain the fixed JSON error distinction."""
        key = bytes(range(32))
        encoded_key = base64.b64encode(key).decode("ascii")

        def encrypt(payload: bytes, nonce_byte: int) -> str:
            nonce = bytes([nonce_byte]) * 12
            encrypted = nonce + AESGCM(key).encrypt(nonce, payload, None)
            return base64.b64encode(encrypted).decode("ascii")

        self.assertEqual(
            (True, "success", {"vid": "visitor-identifier-123"}),
            AESGcmDecrypt.decrypt(
                encrypt(b'{"vid":"visitor-identifier-123"}', 1),
                encoded_key,
            ),
        )
        self.assertEqual(
            (False, "invalid_json", {}),
            AESGcmDecrypt.decrypt(encrypt(b"not-json", 2), encoded_key),
        )

    def test_web_security_exports_the_migrated_fingerprint_implementation(self) -> None:
        self.assertIs(get_stats, fingerprint.get_stats)

    def test_payload_validation_rejects_stale_and_short_identifiers(self) -> None:
        now = int(time.time() * 1000)

        self.assertEqual((False, "invalid_visitor_id", ""), fingerprint.validate_payload({"vid": "short", "ts": now}, 1_000))
        self.assertEqual(
            (False, "timestamp_expired", ""),
            fingerprint.validate_payload({"vid": "visitor-identifier-123", "ts": now - 5_000}, 1_000),
        )
        self.assertEqual(
            (True, "valid", "visitor-identifier-123"),
            fingerprint.validate_payload({"vid": "visitor-identifier-123", "ts": now}, 1_000),
        )

    def test_stats_uses_the_shared_security_connection(self) -> None:
        connection = FakeFingerprintRedis()

        with patch.object(fingerprint, "security_redis_connection", lambda: self._connection(connection)):
            response = asyncio.run(fingerprint.get_stats("fingerprint-1"))

        body = response.body
        assert body is not None
        payload = json.loads(body)
        self.assertEqual(0, payload["error_code"])
        self.assertEqual(["127.0.0.1"], payload["data"]["associated_ips"])
        self.assertTrue(payload["data"]["is_blocked"])
        self.assertEqual("relation:fp_ip:fingerprint-1", connection.last_members_key)
        self.assertEqual("application/json", response.content_type)

    def test_stats_preserves_standard_json_decode_errors(self) -> None:
        class InvalidLogRedis(FakeFingerprintRedis):
            async def lrange(self, key: str, start: int, end: int) -> list[str]:
                del key, start, end
                return ["not-json"]

        invalid = InvalidLogRedis()

        with (
            patch.object(fingerprint, "security_redis_connection", lambda: self._connection(invalid)),
            self.assertRaises(json.JSONDecodeError),
        ):
            asyncio.run(fingerprint.get_stats("fingerprint-1"))

    @staticmethod
    async def _connection(connection: FakeFingerprintRedis) -> FakeFingerprintRedis:
        return connection


if __name__ == "__main__":
    unittest.main()


class SecurityStateConnectionTest(unittest.TestCase):
    """Every Web security subsystem must read and write one Redis database.

    The fingerprint blacklist used to be written on the DEFAULT alias while the rate
    limiter's Lua read it on the session alias. On the shipped demo configuration those
    are different databases (3 and 5), so the blacklist never took effect and nothing
    reported a failure. These guard the single owner that now answers the question.
    """

    def test_the_alias_follows_the_session_connection(self) -> None:
        import oldman.conf as conf
        from oldman.web.security.store import security_redis_alias

        configured = SimpleNamespace(web=SimpleNamespace(session=SimpleNamespace(redis_alias="SESSION")))
        with patch.dict(conf.__dict__, {"settings": configured}):
            self.assertEqual("SESSION", security_redis_alias())

        moved = SimpleNamespace(web=SimpleNamespace(session=SimpleNamespace(redis_alias="OTHER")))
        with patch.dict(conf.__dict__, {"settings": moved}):
            self.assertEqual("OTHER", security_redis_alias(), "the alias must be read at call time, not captured")

    def test_no_security_module_resolves_a_connection_on_its_own(self) -> None:
        """A second answer to "which Redis" is how the writer and reader drifted apart."""
        import inspect

        from oldman.web.security import fingerprint as fingerprint_module
        from oldman.web.security import guard
        from oldman.web.security.rate_limiter import fixed_window

        for module in (fingerprint_module, guard, fixed_window):
            source = inspect.getsource(module)
            self.assertNotIn(
                "redis_client.async_get_conn()",
                source,
                f"{module.__name__} takes the default connection instead of the security one",
            )
            self.assertNotIn(
                "settings.web.session.redis_alias",
                source,
                f"{module.__name__} names the alias itself instead of asking security_redis_alias()",
            )

    def test_the_blacklist_writer_uses_the_shared_connection(self) -> None:
        """log_fake_fingerprint_attempt writes the key the rate limiter's Lua reads."""

        class RecordingRedis:
            def __init__(self) -> None:
                self.keys: list[str] = []

            async def lpush(self, key: str, value: object) -> int:
                self.keys.append(key)
                return 1

            async def ltrim(self, key: str, start: int, end: int) -> None:
                del key, start, end

            async def expire(self, key: str, ttl: int) -> None:
                del key, ttl

            async def llen(self, key: str) -> int:
                del key
                return 11  # past the threshold, so the blacklist write happens

            async def setex(self, key: str, ttl: int, value: str) -> None:
                del ttl, value
                self.keys.append(key)

        recording = RecordingRedis()

        async def shared() -> RecordingRedis:
            return recording

        with patch.object(fingerprint, "security_redis_connection", shared):
            asyncio.run(fingerprint.log_fake_fingerprint_attempt("10.0.0.1", "forged"))

        self.assertIn("blacklist:ip:10.0.0.1", recording.keys)


class FingerprintPayloadTypeTest(unittest.TestCase):
    """The decrypted payload is attacker-shaped input and must be type-checked.

    guard.py says so itself: the AES key is handed to the browser, so anyone who opens
    devtools can sign a payload of their choosing. `vid` was checked; `ts` was not, and a
    string or null reached `abs(current_time - timestamp)`, raised TypeError, escaped the
    decorator and became a 500 - a one-line request that takes a handler down.
    """

    VISITOR = "a" * 20

    def test_a_forged_timestamp_type_is_refused_not_raised(self) -> None:
        for value in ("1700000000000", None, 1.5, [1], {"a": 1}):
            with self.subTest(timestamp=value):
                valid, reason, visitor = fingerprint.validate_payload({"vid": self.VISITOR, "ts": value}, 300_000)
                self.assertFalse(valid)
                self.assertEqual("invalid_timestamp", reason)
                self.assertEqual("", visitor)

    def test_a_boolean_timestamp_is_refused(self) -> None:
        """bool passes isinstance(x, int) and would quietly compare as 0 or 1."""
        valid, reason, _ = fingerprint.validate_payload({"vid": self.VISITOR, "ts": True}, 300_000)
        self.assertFalse(valid)
        self.assertEqual("invalid_timestamp", reason)

    def test_a_real_timestamp_still_validates(self) -> None:
        valid, reason, visitor = fingerprint.validate_payload(
            {"vid": self.VISITOR, "ts": int(time.time() * 1000)},
            300_000,
        )
        self.assertTrue(valid)
        self.assertEqual("valid", reason)
        self.assertEqual(self.VISITOR, visitor)
