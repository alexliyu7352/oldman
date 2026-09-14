"""Tests for source/target real-browser screenshot comparison."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts.compare_browser_visuals import compare_directories, parse_args


class CompareBrowserVisualsTest(unittest.TestCase):
    def test_identical_capture_sets_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            for directory in (source, target):
                Image.new("RGB", (8, 6), "white").save(directory / "dashboard-desktop.png")

            result = compare_directories(
                source,
                target,
                source_revision="source-commit",
                max_mean_absolute_error=0.0,
                max_changed_pixel_ratio=0.0,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["captureCount"])
            self.assertEqual("source-commit", result["sourceRevision"])

    def test_pixel_drift_and_missing_capture_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            Image.new("RGB", (8, 6), "white").save(source / "dashboard-desktop.png")
            Image.new("RGB", (8, 6), "black").save(target / "dashboard-desktop.png")
            Image.new("RGB", (8, 6), "white").save(source / "users-mobile.png")

            result = compare_directories(
                source,
                target,
                source_revision="source-commit",
                max_mean_absolute_error=0.01,
                max_changed_pixel_ratio=0.01,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(["users-mobile.png"], result["missingTarget"])
            self.assertEqual(["dashboard-desktop.png"], result["failed"])

    def test_size_mismatch_and_unexpected_capture_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            Image.new("RGB", (8, 6), "white").save(source / "dashboard.png")
            Image.new("RGB", (9, 6), "white").save(target / "dashboard.png")
            Image.new("RGB", (8, 6), "white").save(target / "unplanned.png")

            result = compare_directories(
                source,
                target,
                source_revision="source-commit",
                max_mean_absolute_error=0.02,
                max_changed_pixel_ratio=0.06,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(["unplanned.png"], result["unexpectedTarget"])
            self.assertEqual("image-size-mismatch", result["comparisons"][0]["reason"])

    def test_explicit_control_region_preserves_raw_drift_and_normalizes_only_that_box(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            source_image = Image.new("RGB", (64, 64), "white")
            target_image = source_image.copy()
            target_image.paste("black", (8, 8, 16, 16))
            source_image.save(source / "user-form.png")
            target_image.save(target / "user-form.png")

            result = compare_directories(
                source,
                target,
                source_revision="source-commit",
                max_mean_absolute_error=0.0,
                max_changed_pixel_ratio=0.0,
                max_tile_mean_absolute_error=0.0,
                max_tile_changed_pixel_ratio=0.0,
                approved_difference_regions={"user-form.png": [[8, 8, 16, 16]]},
            )

            comparison = result["comparisons"][0]
            self.assertTrue(result["ok"])
            self.assertEqual(0.0, comparison["meanAbsoluteError"])
            self.assertGreater(comparison["rawMeanAbsoluteError"], 0.0)
            self.assertEqual([[8, 8, 16, 16]], comparison["approvedDifferenceRegions"])

            target_image.paste("black", (40, 40, 48, 48))
            target_image.save(target / "user-form.png")
            drifted = compare_directories(
                source,
                target,
                source_revision="source-commit",
                max_mean_absolute_error=0.0,
                max_changed_pixel_ratio=0.0,
                max_tile_mean_absolute_error=0.0,
                max_tile_changed_pixel_ratio=0.0,
                approved_difference_regions={"user-form.png": [[8, 8, 16, 16]]},
            )
            self.assertFalse(drifted["ok"])
            self.assertEqual(["user-form.png"], drifted["failed"])

    def test_cli_rejects_thresholds_looser_than_the_review_boundary(self) -> None:
        with patch(
            "sys.argv",
            [
                "compare_browser_visuals.py",
                "source",
                "target",
                "--source-revision",
                "source-commit",
                "--max-changed-pixel-ratio",
                "0.061",
            ],
        ), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args()


if __name__ == "__main__":
    unittest.main()
