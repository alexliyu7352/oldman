"""Adversarial tests for retained browser PNG validation."""

from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.png_evidence import PngEvidenceError, require_png


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, *, width: int = 320, height: int = 200) -> None:
    rows = b"".join(b"\0" + (b"\x7f\x7f\x7f" * width) for _row in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(rows))
        + png_chunk(b"IEND", b"")
    )


class PngEvidenceTest(unittest.TestCase):
    def test_complete_png_passes_with_decoded_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "browser.png"
            write_png(path)

            evidence = require_png(path)

        self.assertEqual((320, 200), (evidence.width, evidence.height))
        self.assertGreater(evidence.bytes, 100)

    def test_header_only_tiny_corrupt_and_symlink_images_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            header = root / "header.png"
            header.write_bytes(b"\x89PNG\r\n\x1a\nreviewed")
            tiny = root / "tiny.png"
            write_png(tiny, width=1, height=1)
            corrupt = root / "corrupt.png"
            write_png(corrupt)
            corrupt.write_bytes(corrupt.read_bytes()[:-1] + b"x")
            linked = root / "linked.png"
            linked.symlink_to(tiny)

            for path in (header, tiny, corrupt, linked):
                with self.subTest(path=path), self.assertRaises(PngEvidenceError):
                    require_png(path)


if __name__ == "__main__":
    unittest.main()
