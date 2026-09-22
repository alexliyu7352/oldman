"""Pin the wire contract of UrlSealer: reversible, deterministic, and unforgeable."""

from __future__ import annotations

import re
import unittest

from oldman.utils.crypto import SEAL_TAG_BYTES, UrlSealer

KEY = b"0123456789abcdef0123456789abcdef"
OTHER_KEY = b"fedcba9876543210fedcba9876543210"
URL = "https://cdn-edge-07.example.com/hls/v3/live/channel-0117/1080p/segment_00001.ts?exp=1789600000"
URL_SAFE = re.compile(r"[A-Za-z0-9_-]*")


class UrlSealerTest(unittest.TestCase):
    """The sealer replaces three hand-rolled proxy ciphers, so its contract is pinned here."""

    def setUp(self) -> None:
        """Use one sealer per test so nothing leaks between them."""
        self.sealer = UrlSealer(KEY)

    def test_round_trip_covers_empty_short_and_long_payloads(self) -> None:
        """Every length must survive a round trip, including the empty and byte-boundary cases."""
        for payload in (b"", b"x", b"\x00", b"\xff" * 7, b"a" * 15, b"b" * 16, URL.encode(), b"z" * 4096):
            with self.subTest(size=len(payload)):
                self.assertEqual(payload, self.sealer.unseal(self.sealer.seal(payload)))

    def test_round_trip_preserves_arbitrary_bytes(self) -> None:
        """The payload is bytes, not text: all 256 values must come back unchanged."""
        payload = bytes(range(256))
        self.assertEqual(payload, self.sealer.unseal(self.sealer.seal(payload)))

    def test_sealing_is_deterministic_so_callers_can_cache(self) -> None:
        """Proxies cache both directions and the CDN caches the URL; a random token breaks both."""
        first = self.sealer.seal(URL.encode())
        self.assertEqual(first, self.sealer.seal(URL.encode()))
        self.assertEqual(first, UrlSealer(KEY).seal(URL.encode()))

    def test_token_only_uses_url_safe_characters(self) -> None:
        """The token goes into a path segment unescaped."""
        for payload in (b"", bytes(range(256)), URL.encode()):
            with self.subTest(size=len(payload)):
                token = self.sealer.seal(payload)
                self.assertRegex(token, URL_SAFE)
                self.assertNotIn("=", token)

    def test_overhead_is_constant_regardless_of_length(self) -> None:
        """Growth must not scale with the URL: it is the tag alone, through base64url."""
        overheads = set()
        for size in (48, 120, 300, 900):
            payload = b"u" * size
            plain = (size * 4 + 2) // 3
            overheads.add(len(self.sealer.seal(payload)) - plain)
        self.assertEqual(1, len(overheads), f"overhead drifted with length: {overheads}")
        self.assertEqual({(SEAL_TAG_BYTES * 4 + 2) // 3}, overheads)

    def test_two_payloads_never_share_a_keystream(self) -> None:
        """The fixed keystream was the old defect: identical prefixes produced identical ciphertext."""
        first = self.sealer.seal(b"https://cdn.example.com/live/ch01/seg00001.ts")
        second = self.sealer.seal(b"https://cdn.example.com/live/ch01/seg00002.ts")
        shared = 0
        for left, right in zip(first, second, strict=False):
            if left != right:
                break
            shared += 1
        self.assertEqual(0, shared, "ciphertexts still share a prefix")

    def test_edited_token_is_rejected_at_every_position(self) -> None:
        """A forged path must not reach the upstream fetch, so every byte is covered by the tag."""
        token = self.sealer.seal(URL.encode())
        for index in range(len(token)):
            swapped = "A" if token[index] != "A" else "B"
            with self.subTest(index=index):
                self.assertIsNone(self.sealer.unseal(token[:index] + swapped + token[index + 1:]))

    def test_truncated_and_malformed_tokens_are_rejected(self) -> None:
        """Bad input returns None rather than raising into the request handler."""
        token = self.sealer.seal(URL.encode())
        for broken in ("", "a", token[:SEAL_TAG_BYTES], token[:-4], "!!!not base64!!!", token + "zzzz"):
            with self.subTest(token=broken[:16]):
                self.assertNotEqual(URL.encode(), self.sealer.unseal(broken))

    def test_another_key_cannot_open_the_token(self) -> None:
        """Keys are purpose-separated; a token from one purpose must not open under another."""
        self.assertIsNone(UrlSealer(OTHER_KEY).unseal(self.sealer.seal(URL.encode())))

    def test_short_keys_are_refused(self) -> None:
        """A weak key is a configuration error, not something to paper over."""
        with self.assertRaises(ValueError):
            UrlSealer(b"too short")


if __name__ == "__main__":
    unittest.main()
