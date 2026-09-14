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

    def test_stats_uses_the_migrated_redis_client(self) -> None:
        connection = FakeFingerprintRedis()
        client = SimpleNamespace(async_get_conn=lambda: self._connection(connection))

        with patch.object(fingerprint, "redis_client", client):
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

        client = SimpleNamespace(async_get_conn=lambda: self._connection(InvalidLogRedis()))

        with (
            patch.object(fingerprint, "redis_client", client),
            self.assertRaises(json.JSONDecodeError),
        ):
            asyncio.run(fingerprint.get_stats("fingerprint-1"))

    @staticmethod
    async def _connection(connection: FakeFingerprintRedis) -> FakeFingerprintRedis:
        return connection


if __name__ == "__main__":
    unittest.main()
