"""Strict, dependency-free validation for retained browser PNG evidence."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}


class PngEvidenceError(RuntimeError):
    """Raised when browser evidence is not one complete, safe PNG."""


@dataclass(frozen=True)
class PngEvidence:
    """Content identity and decoded dimensions of one retained PNG."""

    bytes: int
    height: int
    sha256: str
    width: int


def require_png(path: Path, *, min_width: int = 300, min_height: int = 200) -> PngEvidence:
    """Parse chunks, CRCs and scanlines; reject headers or corrupt image lookalikes."""
    if path.is_symlink() or not path.is_file():
        raise PngEvidenceError(f"PNG evidence is missing or not a regular file: {path}")
    payload = path.read_bytes()
    if not payload.startswith(PNG_SIGNATURE):
        raise PngEvidenceError(f"PNG evidence has an invalid signature: {path}")

    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise PngEvidenceError(f"PNG evidence has a truncated chunk: {path}")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            raise PngEvidenceError(f"PNG evidence has a truncated chunk payload: {path}")
        data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            raise PngEvidenceError(f"PNG evidence has an invalid chunk CRC: {path}")
        chunks.append((chunk_type, data))
        offset = end
        if chunk_type == b"IEND":
            break
    if offset != len(payload) or not chunks or chunks[0][0] != b"IHDR" or chunks[-1] != (b"IEND", b""):
        raise PngEvidenceError(f"PNG evidence has an invalid chunk boundary: {path}")
    if sum(chunk_type == b"IHDR" for chunk_type, _data in chunks) != 1:
        raise PngEvidenceError(f"PNG evidence must contain exactly one IHDR: {path}")

    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise PngEvidenceError(f"PNG evidence has an invalid IHDR: {path}")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if width < min_width or height < min_height or width > 10_000 or height > 10_000:
        raise PngEvidenceError(f"PNG evidence dimensions are outside the browser contract: {width}x{height}: {path}")
    if color_type not in CHANNELS or bit_depth not in BIT_DEPTHS[color_type]:
        raise PngEvidenceError(f"PNG evidence has an unsupported color format: {path}")
    if (compression, filter_method, interlace) != (0, 0, 0):
        raise PngEvidenceError(f"PNG evidence uses unsupported compression/filter/interlace metadata: {path}")

    idat = b"".join(data for chunk_type, data in chunks if chunk_type == b"IDAT")
    if not idat:
        raise PngEvidenceError(f"PNG evidence contains no image data: {path}")
    row_bytes = (width * CHANNELS[color_type] * bit_depth + 7) // 8
    expected_decoded = height * (row_bytes + 1)
    if expected_decoded > 100 * 1024 * 1024:
        raise PngEvidenceError(f"PNG evidence decoded image is unreasonably large: {path}")
    inflater = zlib.decompressobj()
    try:
        decoded = inflater.decompress(idat, expected_decoded + 1)
        if inflater.unconsumed_tail:
            raise PngEvidenceError(f"PNG evidence exceeds its declared scanline size: {path}")
        decoded += inflater.flush()
    except zlib.error as exc:
        raise PngEvidenceError(f"PNG evidence image data cannot be decompressed: {path}: {exc}") from exc
    if (
        len(decoded) != expected_decoded
        or not inflater.eof
        or inflater.unused_data
        or any(decoded[row * (row_bytes + 1)] > 4 for row in range(height))
    ):
        raise PngEvidenceError(f"PNG evidence has invalid decoded scanlines: {path}")
    return PngEvidence(
        bytes=len(payload),
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
        width=width,
    )
