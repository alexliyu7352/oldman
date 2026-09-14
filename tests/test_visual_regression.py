"""Tests for the compact visual-regression signature helper."""

from __future__ import annotations

import io
import unittest

from PIL import Image, ImageDraw

from scripts.visual_regression import BASELINE_ALGORITHM, SIGNATURE_WIDTH, build_visual_baseline, compare_visual_baseline


class VisualRegressionTest(unittest.TestCase):
    """Keep the browser gate's pixel comparison honest."""

    def test_identical_capture_passes(self) -> None:
        png = self._capture(accent_left=20)
        baseline = build_visual_baseline(png, viewport_width=320, viewport_height=200, mobile=False)

        comparison = compare_visual_baseline(
            "same",
            png,
            baseline,
            max_mean_absolute_error=0.001,
            max_changed_pixel_ratio=0.001,
        )

        self.assertTrue(comparison.passed)
        self.assertEqual(0.0, comparison.mean_absolute_error)
        self.assertEqual(0.0, comparison.changed_pixel_ratio)
        self.assertEqual(BASELINE_ALGORITHM, baseline["algorithm"])
        signature_size = baseline["signatureSize"]
        self.assertIsInstance(signature_size, list)
        self.assertEqual(SIGNATURE_WIDTH, signature_size[0] if isinstance(signature_size, list) else None)

    def test_material_layout_shift_fails(self) -> None:
        baseline_png = self._capture(accent_left=20)
        shifted_png = self._capture(accent_left=150)
        baseline = build_visual_baseline(baseline_png, viewport_width=320, viewport_height=200, mobile=False)

        comparison = compare_visual_baseline(
            "shifted",
            shifted_png,
            baseline,
            max_mean_absolute_error=0.01,
            max_changed_pixel_ratio=0.05,
        )

        self.assertFalse(comparison.passed)
        self.assertGreater(comparison.changed_pixel_ratio, 0.05)

    def test_unknown_baseline_algorithm_is_rejected(self) -> None:
        png = self._capture(accent_left=20)
        baseline = build_visual_baseline(png, viewport_width=320, viewport_height=200, mobile=False)
        baseline["algorithm"] = "obsolete"

        with self.assertRaisesRegex(ValueError, "unsupported algorithm"):
            compare_visual_baseline(
                "obsolete",
                png,
                baseline,
                max_mean_absolute_error=0.01,
                max_changed_pixel_ratio=0.05,
            )

    @staticmethod
    def _capture(*, accent_left: int) -> bytes:
        image = Image.new("RGB", (320, 200), "#fafafa")
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, 307, 187), fill="#ffffff", outline="#d4d4d8", width=2)
        draw.rectangle((accent_left, 36, accent_left + 90, 82), fill="#2563eb")
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        return encoded.getvalue()


if __name__ == "__main__":
    unittest.main()
