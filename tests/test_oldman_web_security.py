"""Cross-language constraints between the browser fingerprint sender and its server config."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT_TS = ROOT / "frontend/packages/oldman-web/src/core/security/fingerprint.ts"


class FingerprintTtlMarginTest(unittest.TestCase):
    """The browser reuses one encrypted payload for `ttlMs`; the server rejects a timestamp
    further than `timestamp_max_diff` from its own clock.

    Making the two equal leaves no margin: a request sent in the last milliseconds of a
    payload's life arrives after the tolerance has passed and gets a 403, while the client
    still believes the payload is valid and keeps sending the same one. Clock drift widens
    that window. It shows up as rare, unreproducible 403s, and both defaults look reasonable
    on their own.
    """

    def test_the_client_default_leaves_room_under_the_server_default(self) -> None:
        from oldman.conf.schemas import FingerprintSecurityConfig

        source = FINGERPRINT_TS.read_text(encoding="utf-8")
        match = re.search(r"const DEFAULT_TTL_MS = ([\d\s*]+);", source)
        self.assertIsNotNone(match, "DEFAULT_TTL_MS is not in the shape this guard reads")
        assert match is not None
        client_ttl_ms = 1
        for factor in match.group(1).split("*"):
            client_ttl_ms *= int(factor.strip())
        server_tolerance_ms = FingerprintSecurityConfig().timestamp_max_diff

        self.assertLess(
            client_ttl_ms,
            server_tolerance_ms,
            "the browser would still be reusing a payload the server has begun refusing",
        )
        # 余量要够一次慢请求加上两端时钟漂移，不是差一毫秒就算数。
        self.assertGreaterEqual(server_tolerance_ms - client_ttl_ms, 30_000)


if __name__ == "__main__":
    unittest.main()
