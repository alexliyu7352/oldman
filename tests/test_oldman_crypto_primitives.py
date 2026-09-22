"""The cryptographic primitives, and the boundary between them and their callers."""

from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from oldman.utils.crypto import (
    AES_GCM_IV_BYTES,
    AES_GCM_TAG_BYTES,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    generate_secure_token,
)

ROOT = Path(__file__).resolve().parents[1]


class AesGcmPrimitiveTest(unittest.TestCase):
    """One AES-GCM implementation, and it says why it failed.

    There used to be two: this module's, which returned an empty string for every
    failure - so "wrong key" and "successfully decrypted nothing" were the same answer -
    and the one behind the fingerprint decryptor, which classified the reason. The dead
    one was the exported one, so anyone reaching for it got the worse contract.
    """

    def setUp(self) -> None:
        self.key = os.urandom(32)

    def test_a_round_trip_returns_the_plaintext(self) -> None:
        payload = aes_gcm_encrypt(b'{"vid":"abc"}', self.key)
        self.assertEqual((True, "success", b'{"vid":"abc"}'), aes_gcm_decrypt(payload, self.key))

    def test_every_call_uses_a_fresh_iv(self) -> None:
        """Reusing an IV with one key destroys GCM outright, so this is not cosmetic."""
        ivs = {aes_gcm_encrypt(b"same", self.key)[:AES_GCM_IV_BYTES] for _ in range(200)}
        self.assertEqual(200, len(ivs))

    def test_a_truncated_payload_is_named_as_such(self) -> None:
        ok, reason, plaintext = aes_gcm_decrypt(b"x" * (AES_GCM_IV_BYTES + AES_GCM_TAG_BYTES - 1), self.key)
        self.assertFalse(ok)
        self.assertEqual("data_too_short", reason)
        self.assertEqual(b"", plaintext)

    def test_a_wrong_key_is_distinguishable_from_a_malformed_payload(self) -> None:
        payload = aes_gcm_encrypt(b"secret", self.key)
        ok, reason, _ = aes_gcm_decrypt(payload, os.urandom(32))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("authentication_failed:"), reason)
        self.assertNotEqual("authentication_failed:", reason, "InvalidTag stringifies empty; the type name must fill in")

    def test_an_empty_plaintext_is_a_success_not_a_failure(self) -> None:
        """The old contract could not express this: empty result meant error."""
        self.assertEqual((True, "success", b""), aes_gcm_decrypt(aes_gcm_encrypt(b"", self.key), self.key))


class SecureTokenTest(unittest.TestCase):
    """`length` now means the length.

    The old implementation encoded random bytes, truncated to ten characters and then
    filtered, so `length` controlled neither the output size nor the retry threshold
    consistently: generate_secure_token(20) asked for eighteen characters out of ten and
    looped forever.
    """

    CONFUSABLE = {"I", "L", "O", "0", "1"}

    def test_the_requested_length_is_the_produced_length(self) -> None:
        for length in (1, 8, 10, 20, 32, 64):
            with self.subTest(length=length):
                self.assertEqual(length, len(generate_secure_token(length)))

    def test_look_alike_characters_never_appear(self) -> None:
        produced = "".join(generate_secure_token(32) for _ in range(200))
        self.assertFalse(self.CONFUSABLE & set(produced))

    def test_a_meaningless_length_is_refused_rather_than_looping(self) -> None:
        with self.assertRaises(ValueError):
            generate_secure_token(0)

    def test_tokens_do_not_repeat(self) -> None:
        self.assertEqual(500, len({generate_secure_token(16) for _ in range(500)}))


class DecryptorBoundaryTest(unittest.TestCase):
    """The browser decryptor keeps the wire format; the crypto lives in utils."""

    def test_the_decryptor_no_longer_implements_aes(self) -> None:
        source = (ROOT / "oldman" / "web" / "security" / "decryptors.py").read_text(encoding="utf-8")
        self.assertIn("from oldman.utils.crypto import aes_gcm_decrypt", source)
        self.assertNotIn("AESGCM(", source, "the business layer should not be constructing ciphers")

    def test_failure_reasons_survive_the_split(self) -> None:
        from oldman.web.security.decryptors import AESGcmDecrypt

        key = os.urandom(32)
        encoded_key = base64.b64encode(key).decode()
        iv = os.urandom(AES_GCM_IV_BYTES)

        good = base64.b64encode(aes_gcm_encrypt(b'{"vid":"abc"}', key)).decode()
        self.assertEqual((True, "success"), AESGcmDecrypt.decrypt(good, encoded_key)[:2])

        short = base64.b64encode(b"short").decode()
        self.assertEqual("data_too_short", AESGcmDecrypt.decrypt(short, encoded_key)[1])

        not_json = base64.b64encode(iv + AESGCM(key).encrypt(iv, b"not-json", None)).decode()
        self.assertEqual("invalid_json", AESGcmDecrypt.decrypt(not_json, encoded_key)[1])

        wrong_key = base64.b64encode(os.urandom(32)).decode()
        self.assertTrue(AESGcmDecrypt.decrypt(good, wrong_key)[1].startswith("authentication_failed:"))

        self.assertTrue(AESGcmDecrypt.decrypt("!!!not-base64!!!", encoded_key)[1].startswith("invalid_encoding:"))


if __name__ == "__main__":
    unittest.main()
