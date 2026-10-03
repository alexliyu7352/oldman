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
        tampered_payload = (
            base64.urlsafe_b64encode(json.dumps(decoded_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).rstrip(b"=").decode("ascii")
        )

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

    def test_a_token_is_refused_before_its_nbf(self) -> None:
        """RFC 7519 4.1.5: a token must not be accepted before its not-before time."""
        later = int(datetime.now(UTC).timestamp()) + 60
        token = jwt_encode({"sub": "user-1", "nbf": later}, "secret")

        with self.assertRaisesRegex(InvalidTokenError, "not valid yet"):
            jwt_decode(token, "secret")
        self.assertEqual("user-1", jwt_decode(token, "secret", leeway=120)["sub"])

    def test_nbf_must_be_a_number(self) -> None:
        for bad in ("soon", True):
            with self.subTest(nbf=bad), self.assertRaisesRegex(InvalidTokenError, "nbf"):
                jwt_decode(jwt_encode({"sub": "user-1", "nbf": bad}, "secret"), "secret")

    def test_audience_is_checked_both_ways(self) -> None:
        """A token for one audience must not pass where another, or none, is expected."""
        for_billing = jwt_encode({"sub": "user-1", "aud": "billing"}, "secret")
        for_several = jwt_encode({"sub": "user-1", "aud": ["billing", "reports"]}, "secret")
        for_anyone = jwt_encode({"sub": "user-1"}, "secret")

        self.assertEqual("user-1", jwt_decode(for_billing, "secret", audience="billing")["sub"])
        self.assertEqual("user-1", jwt_decode(for_several, "secret", audience="reports")["sub"])
        for token, audience in ((for_billing, "reports"), (for_anyone, "billing"), (for_billing, None)):
            with self.subTest(audience=audience), self.assertRaisesRegex(InvalidTokenError, "audience"):
                jwt_decode(token, "secret", audience=audience)

    def test_issuer_is_checked_when_one_is_expected(self) -> None:
        from_auth = jwt_encode({"sub": "user-1", "iss": "auth"}, "secret")
        unsigned_by_anyone = jwt_encode({"sub": "user-1"}, "secret")

        self.assertEqual("user-1", jwt_decode(from_auth, "secret", issuer="auth")["sub"])
        self.assertEqual("user-1", jwt_decode(from_auth, "secret")["sub"])
        for token in (from_auth, unsigned_by_anyone):
            with self.assertRaisesRegex(InvalidTokenError, "issuer"):
                jwt_decode(token, "secret", issuer="gateway")


if __name__ == "__main__":
    unittest.main()
