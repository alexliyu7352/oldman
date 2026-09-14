"""Independent regression tests for the browser screenshot comparator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

from scripts.compare_browser_visuals import (
    MAX_ALLOWED_CHANGED_PIXEL_RATIO,
    MAX_ALLOWED_MEAN_ABSOLUTE_ERROR,
    MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
    MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR,
    PIXEL_DELTA,
    TILE_SCALES,
    TILE_STRIDE,
    compare_directories,
)


def compare(source: Path, target: Path, *, diff_dir: Path | None = None) -> dict[str, Any]:
    return compare_directories(
        source,
        target,
        source_revision="reviewed-source",
        max_mean_absolute_error=MAX_ALLOWED_MEAN_ABSOLUTE_ERROR,
        max_changed_pixel_ratio=MAX_ALLOWED_CHANGED_PIXEL_RATIO,
        max_tile_mean_absolute_error=MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR,
        max_tile_changed_pixel_ratio=MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
        diff_dir=diff_dir,
    )


class BrowserVisualComparatorTest(unittest.TestCase):
    def test_rejects_same_directory_even_through_path_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            captures = Path(temporary_directory) / "captures"
            captures.mkdir()
            Image.new("RGB", (64, 64), "white").save(captures / "page.png")

            with self.assertRaisesRegex(ValueError, "must be independent"):
                compare(captures, captures / ".." / "captures")

    def test_empty_capture_inventories_never_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()

            result = compare(source, target)

            self.assertFalse(result["ok"])
            self.assertEqual(
                ["source-capture-inventory-empty", "target-capture-inventory-empty"],
                result["inventoryErrors"],
            )
            self.assertEqual(0, result["captureCount"])

    def test_manifest_must_be_closed_on_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            for name in ("common.png", "missing.png"):
                Image.new("RGB", (64, 64), "white").save(source / name)
            for name in ("common.png", "unexpected.png"):
                Image.new("RGB", (64, 64), "white").save(target / name)
            (target / "nested").mkdir()
            Image.new("RGB", (64, 64), "white").save(target / "nested" / "hidden.PNG")

            result = compare(source, target)

            self.assertFalse(result["ok"])
            self.assertEqual(["missing.png"], result["missingTarget"])
            self.assertEqual(["nested/hidden.PNG", "unexpected.png"], result["unexpectedTarget"])
            self.assertEqual(2, result["sourceCaptureCount"])
            self.assertEqual(3, result["targetCaptureCount"])

    def test_multiscale_overlapping_tiles_catch_gray_icon_spanning_fixed_tiles(self) -> None:
        self.assertEqual(16, TILE_STRIDE)
        self.assertEqual(((16, 8), (32, 16)), TILE_SCALES)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            heatmaps = root / "heatmaps"
            source.mkdir()
            target.mkdir()
            source_image = Image.new("RGB", (512, 512), "white")
            target_image = source_image.copy()
            # This 16x16 icon straddles x=32 and y=32.  A non-overlapping grid
            # sees only 8x8 changed pixels in each tile and used to let it pass.
            source_image.paste((120, 120, 120), (24, 24, 40, 40))
            source_image.save(source / "toolbar.png")
            target_image.save(target / "toolbar.png")

            result = compare(source, target, diff_dir=heatmaps)
            comparison = result["comparisons"][0]

            self.assertLess(comparison["changedPixelRatio"], MAX_ALLOWED_CHANGED_PIXEL_RATIO)
            self.assertGreater(
                comparison["maximumTileChangedPixelRatio"],
                MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
            )
            self.assertEqual([24, 24, 40, 40], comparison["worstChangedPixelTile"])
            self.assertEqual(16, comparison["worstChangedPixelTileSize"])
            self.assertFalse(result["ok"])
            with Image.open(heatmaps / "toolbar.png") as heatmap:
                self.assertEqual((512, 512), heatmap.size)

    def test_multiscale_tiles_reject_an_eight_pixel_gray_icon_across_a_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            source_image = Image.new("RGB", (512, 512), "white")
            target_image = source_image.copy()
            source_image.paste((160, 160, 160), (12, 12, 20, 20))
            source_image.save(source / "small-icon.png")
            target_image.save(target / "small-icon.png")

            result = compare(source, target)
            comparison = result["comparisons"][0]

            self.assertLess(comparison["changedPixelRatio"], MAX_ALLOWED_CHANGED_PIXEL_RATIO)
            self.assertEqual(0.25, comparison["maximumTileChangedPixelRatio"])
            self.assertEqual([8, 8, 24, 24], comparison["worstChangedPixelTile"])
            self.assertEqual(16, comparison["worstChangedPixelTileSize"])
            self.assertFalse(result["ok"])

    def test_uniform_low_amplitude_control_token_drift_is_not_treated_as_antialiasing(self) -> None:
        self.assertEqual(4, PIXEL_DELTA)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            source_image = Image.new("RGB", (256, 256), "white")
            target_image = source_image.copy()
            source_image.paste((245, 245, 245), (64, 64, 96, 96))
            target_image.paste((250, 250, 250), (64, 64, 96, 96))
            source_image.save(source / "control-token.png")
            target_image.save(target / "control-token.png")

            result = compare(source, target)
            comparison = result["comparisons"][0]

            self.assertLess(comparison["maximumTileMeanAbsoluteError"], MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR)
            self.assertEqual(1.0, comparison["maximumTileChangedPixelRatio"])
            self.assertFalse(result["ok"])

    def test_sparse_antialiasing_noise_stays_below_local_and_global_ceilings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            source_image = Image.new("RGB", (128, 128), "white")
            target_image = source_image.copy()
            # A few edge pixels moving by one antialiasing step are expected
            # browser rasterization noise, not a missing UI component.
            for coordinate in ((30, 30), (31, 30), (32, 31), (33, 31), (34, 32), (35, 32)):
                target_image.putpixel(coordinate, (239, 239, 239))
            source_image.save(source / "text.png")
            target_image.save(target / "text.png")

            result = compare(source, target)

            self.assertTrue(result["ok"])
            self.assertLessEqual(
                result["maximumTileChangedPixelRatio"],
                MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
            )


if __name__ == "__main__":
    unittest.main()
