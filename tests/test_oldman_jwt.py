"""JWT regression tests migrated with the foundation security implementation."""

from __future__ import annotations

import base64
import json
import unittest
from datetime import UTC, datetime, timedelta

from oldman.security import ExpiredTokenError, InvalidTokenError, jwt_decode, jwt_encode


class OldmanJwtTest(unittest.TestCase):
    """Verify signing, tamper detection and expiry handling."""

    def test_round_trip_preserves_payload(self) -> None:
        token = jwt_encode({"sub": "user-1", "scope": ["read"]}, "secret")

        payload = jwt_decode(token, "secret")

        self.assertEqual("user-1", payload["sub"])
        self.assertEqual(["read"], payload["scope"])

    def test_decode_rejects_tampered_payload(self) -> None:
        token = jwt_encode({"sub": "user-1"}, "secret")
        header, payload, signature = token.split(".")
        decoded_payload = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        decoded_payload["sub"] = "user-2"
        tampered_payload = base64.urlsafe_b64encode(
            json.dumps(decoded_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")

        with self.assertRaisesRegex(InvalidTokenError, "signature"):
            jwt_decode(".".join((header, tampered_payload, signature)), "secret")

    def test_decode_rejects_expired_token(self) -> None:
        token = jwt_encode({"sub": "user-1", "exp": datetime.now(UTC) - timedelta(seconds=1)}, "secret")

        with self.assertRaises(ExpiredTokenError):
            jwt_decode(token, "secret")

    def test_encode_can_add_expiration_delta(self) -> None:
        token = jwt_encode({"sub": "user-1"}, "secret", expires_delta=timedelta(minutes=5))

        payload = jwt_decode(token, "secret")

        self.assertIsInstance(payload["exp"], int)


if __name__ == "__main__":
    unittest.main()
