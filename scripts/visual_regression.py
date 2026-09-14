"""Small PNG signature helpers for deterministic browser visual gates."""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageEnhance

BASELINE_ALGORITHM = "rgb-lanczos-v2"
SIGNATURE_WIDTH = 480
PIXEL_DELTA = 18


@dataclass(frozen=True)
class VisualComparison:
    """Result of comparing a browser capture with a committed visual signature."""

    changed_pixel_ratio: float
    current_image_size: tuple[int, int]
    mean_absolute_error: float
    name: str
    passed: bool
    signature_size: tuple[int, int]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly gate result."""
        return asdict(self)


def build_visual_baseline(
    png: bytes,
    *,
    viewport_width: int,
    viewport_height: int,
    mobile: bool,
    signature_width: int = SIGNATURE_WIDTH,
) -> dict[str, object]:
    """Build a compact, reviewable baseline entry from a full browser PNG."""
    image = _open_rgb(png)
    signature = _signature(image, signature_width=signature_width)
    encoded = io.BytesIO()
    signature.save(encoded, format="PNG", optimize=True)
    return {
        "algorithm": BASELINE_ALGORITHM,
        "viewport": {"width": viewport_width, "height": viewport_height, "mobile": mobile},
        "imageSize": list(image.size),
        "signatureSize": list(signature.size),
        "signaturePng": base64.b64encode(encoded.getvalue()).decode("ascii"),
        "sourcePngSha256": hashlib.sha256(png).hexdigest(),
    }


def compare_visual_baseline(
    name: str,
    png: bytes,
    baseline: dict[str, Any],
    *,
    max_mean_absolute_error: float,
    max_changed_pixel_ratio: float,
    diff_path: str | Path | None = None,
) -> VisualComparison:
    """Compare a capture with its baseline and optionally write an amplified diff."""
    current = _open_rgb(png)
    expected = _decode_signature(baseline)
    normalized = current.resize(expected.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(normalized, expected)
    histogram = difference.histogram()
    channel_total = sum((index % 256) * count for index, count in enumerate(histogram))
    mean_absolute_error = channel_total / (expected.width * expected.height * 3 * 255)
    red, green, blue = difference.split()
    maximum_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed_pixels = sum(maximum_channel.histogram()[PIXEL_DELTA:])
    changed_pixel_ratio = changed_pixels / (expected.width * expected.height)
    passed = mean_absolute_error <= max_mean_absolute_error and changed_pixel_ratio <= max_changed_pixel_ratio

    if not passed and diff_path is not None:
        amplified = ImageEnhance.Contrast(difference).enhance(4)
        Path(diff_path).parent.mkdir(parents=True, exist_ok=True)
        amplified.save(diff_path, format="PNG")

    return VisualComparison(
        changed_pixel_ratio=round(changed_pixel_ratio, 6),
        current_image_size=current.size,
        mean_absolute_error=round(mean_absolute_error, 6),
        name=name,
        passed=passed,
        signature_size=expected.size,
    )


def _open_rgb(png: bytes) -> Image.Image:
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGB")


def _signature(image: Image.Image, *, signature_width: int) -> Image.Image:
    if signature_width <= 0:
        raise ValueError("signature_width must be positive")
    signature_height = max(1, round(image.height * signature_width / image.width))
    return image.resize((signature_width, signature_height), Image.Resampling.LANCZOS)


def _decode_signature(baseline: dict[str, Any]) -> Image.Image:
    if baseline.get("algorithm") != BASELINE_ALGORITHM:
        raise ValueError("visual baseline uses an unsupported algorithm")
    encoded = baseline.get("signaturePng")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("visual baseline is missing signaturePng")
    return _open_rgb(base64.b64decode(encoded))


__all__ = ["BASELINE_ALGORITHM", "SIGNATURE_WIDTH", "VisualComparison", "build_visual_baseline", "compare_visual_baseline"]
