#!/usr/bin/env python3
"""Compare matching real-browser PNG captures from source and migration runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypedDict

from PIL import Image, ImageChops

# These are noise ceilings, not values calibrated from a source/target diff.
# Both sides run in isolated trees on the same Chrome binary, locale, timezone,
# viewport and deterministic fixtures.  A larger delta therefore represents a
# real rendering change that must be reviewed instead of silently allowlisted.
# Ignore only subpixel-scale raster noise. A uniform 5/255 token shift across
# one control or surface must still count as changed even when its MAE is low.
PIXEL_DELTA = 4
MAX_ALLOWED_MEAN_ABSOLUTE_ERROR = 0.005
MAX_ALLOWED_CHANGED_PIXEL_RATIO = 0.015
# Original-resolution 16px and 32px tiles ensure a missing icon, button,
# pagination control or field cannot be diluted by a tall full-page screenshot.
# Each half-tile stride is intentional: a small control spanning a fixed grid
# boundary must be measured whole by at least one overlapping window.
TILE_SIZE = 32
TILE_STRIDE = TILE_SIZE // 2
TILE_SCALES = ((16, 8), (TILE_SIZE, TILE_STRIDE))
MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR = 0.04
MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO = 0.12


class TileMetric(TypedDict):
    box: list[int]
    meanAbsoluteError: float
    changedPixelRatio: float
    tileSize: int
    tileStride: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="reference browser screenshot directory")
    parser.add_argument("target", type=Path, help="oldman_framwork browser screenshot directory")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--diff-dir", type=Path, help="Write one full-resolution heatmap per matching capture")
    parser.add_argument(
        "--max-mean-absolute-error",
        type=float,
        default=MAX_ALLOWED_MEAN_ABSOLUTE_ERROR,
    )
    parser.add_argument(
        "--max-changed-pixel-ratio",
        type=float,
        default=MAX_ALLOWED_CHANGED_PIXEL_RATIO,
    )
    parser.add_argument(
        "--max-tile-mean-absolute-error",
        type=float,
        default=MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR,
    )
    parser.add_argument(
        "--max-tile-changed-pixel-ratio",
        type=float,
        default=MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
    )
    args = parser.parse_args()
    if not 0 <= args.max_mean_absolute_error <= MAX_ALLOWED_MEAN_ABSOLUTE_ERROR:
        parser.error(f"--max-mean-absolute-error must be between 0 and {MAX_ALLOWED_MEAN_ABSOLUTE_ERROR}")
    if not 0 <= args.max_changed_pixel_ratio <= MAX_ALLOWED_CHANGED_PIXEL_RATIO:
        parser.error(f"--max-changed-pixel-ratio must be between 0 and {MAX_ALLOWED_CHANGED_PIXEL_RATIO}")
    if not 0 <= args.max_tile_mean_absolute_error <= MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR:
        parser.error(f"--max-tile-mean-absolute-error must be between 0 and {MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR}")
    if not 0 <= args.max_tile_changed_pixel_ratio <= MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO:
        parser.error(
            f"--max-tile-changed-pixel-ratio must be between 0 and {MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO}"
        )
    return args


def compare_directories(
    source_dir: Path,
    target_dir: Path,
    *,
    source_revision: str,
    max_mean_absolute_error: float,
    max_changed_pixel_ratio: float,
    max_tile_mean_absolute_error: float = MAX_ALLOWED_TILE_MEAN_ABSOLUTE_ERROR,
    max_tile_changed_pixel_ratio: float = MAX_ALLOWED_TILE_CHANGED_PIXEL_RATIO,
    diff_dir: Path | None = None,
    approved_difference_regions: dict[str, list[list[int]]] | None = None,
) -> dict[str, Any]:
    """Return a complete comparison; missing or differently sized captures fail."""
    if source_dir.resolve() == target_dir.resolve():
        raise ValueError(f"source and target directories must be independent: {source_dir.resolve()}")

    source_files = _capture_manifest(source_dir)
    target_files = _capture_manifest(target_dir)
    approved_regions = _validate_approved_difference_regions(
        approved_difference_regions or {},
        source_files=source_files,
        target_files=target_files,
    )
    missing_target = sorted(source_files.keys() - target_files.keys())
    unexpected_target = sorted(target_files.keys() - source_files.keys())
    inventory_errors = []
    if not source_files:
        inventory_errors.append("source-capture-inventory-empty")
    if not target_files:
        inventory_errors.append("target-capture-inventory-empty")
    comparisons: list[dict[str, Any]] = []

    if diff_dir is not None:
        if diff_dir.exists() and any(diff_dir.iterdir()):
            raise ValueError(f"diff directory is not empty: {diff_dir}")
        diff_dir.mkdir(parents=True, exist_ok=True)

    for name in sorted(source_files.keys() & target_files.keys()):
        source = _open_rgb(source_files[name])
        target = _open_rgb(target_files[name])
        if source.size != target.size:
            comparisons.append(
                {
                    "name": name,
                    "passed": False,
                    "sourceSize": list(source.size),
                    "targetSize": list(target.size),
                    "reason": "image-size-mismatch",
                }
            )
            continue
        heatmap_path = None
        if diff_dir is not None:
            heatmap_path = diff_dir / name
            _write_difference_heatmap(source, target, heatmap_path)
        raw_mean_absolute_error, raw_changed_pixel_ratio = _difference_metrics(source, target)
        raw_tile_metrics = maximum_tile_metrics(source, target)
        regions = approved_regions.get(name, [])
        compared_target = _mask_approved_regions(source, target, regions)
        mean_absolute_error, changed_pixel_ratio = _difference_metrics(source, compared_target)
        tile_metrics = maximum_tile_metrics(source, compared_target)
        comparisons.append(
            {
                "name": name,
                "passed": mean_absolute_error <= max_mean_absolute_error
                and changed_pixel_ratio <= max_changed_pixel_ratio
                and tile_metrics["meanAbsoluteError"] <= max_tile_mean_absolute_error
                and tile_metrics["changedPixelRatio"] <= max_tile_changed_pixel_ratio,
                "meanAbsoluteError": round(mean_absolute_error, 6),
                "changedPixelRatio": round(changed_pixel_ratio, 6),
                "maximumTileMeanAbsoluteError": round(tile_metrics["meanAbsoluteError"], 6),
                "maximumTileChangedPixelRatio": round(tile_metrics["changedPixelRatio"], 6),
                "worstMeanAbsoluteErrorTile": tile_metrics["meanAbsoluteErrorTile"],
                "worstMeanAbsoluteErrorTileSize": tile_metrics["meanAbsoluteErrorTileSize"],
                "worstChangedPixelTile": tile_metrics["changedPixelTile"],
                "worstChangedPixelTileSize": tile_metrics["changedPixelTileSize"],
                "rawMeanAbsoluteError": round(raw_mean_absolute_error, 6),
                "rawChangedPixelRatio": round(raw_changed_pixel_ratio, 6),
                "rawMaximumTileMeanAbsoluteError": round(raw_tile_metrics["meanAbsoluteError"], 6),
                "rawMaximumTileChangedPixelRatio": round(raw_tile_metrics["changedPixelRatio"], 6),
                "rawWorstMeanAbsoluteErrorTile": raw_tile_metrics["meanAbsoluteErrorTile"],
                "rawWorstMeanAbsoluteErrorTileSize": raw_tile_metrics["meanAbsoluteErrorTileSize"],
                "rawWorstChangedPixelTile": raw_tile_metrics["changedPixelTile"],
                "rawWorstChangedPixelTileSize": raw_tile_metrics["changedPixelTileSize"],
                "approvedDifferenceRegions": regions,
                "sourceSize": list(source.size),
                "targetSize": list(target.size),
                "differenceHeatmap": str(heatmap_path.resolve()) if heatmap_path is not None else None,
            }
        )

    failed = [item["name"] for item in comparisons if not item["passed"]]
    metric_rows = [item for item in comparisons if "meanAbsoluteError" in item]
    return {
        "ok": not inventory_errors and not missing_target and not unexpected_target and not failed,
        "sourceRevision": source_revision,
        "sourceDirectory": str(source_dir.resolve()),
        "targetDirectory": str(target_dir.resolve()),
        "thresholds": {
            "maxMeanAbsoluteError": max_mean_absolute_error,
            "maxChangedPixelRatio": max_changed_pixel_ratio,
            "maxTileMeanAbsoluteError": max_tile_mean_absolute_error,
            "maxTileChangedPixelRatio": max_tile_changed_pixel_ratio,
            "tileSize": TILE_SIZE,
            "tileStride": TILE_STRIDE,
            "tileScales": [{"size": size, "stride": stride} for size, stride in TILE_SCALES],
            "pixelDelta": PIXEL_DELTA,
        },
        "sourceCaptureCount": len(source_files),
        "targetCaptureCount": len(target_files),
        "captureCount": len(comparisons),
        "inventoryErrors": inventory_errors,
        "missingTarget": missing_target,
        "unexpectedTarget": unexpected_target,
        "failed": failed,
        "maximumMeanAbsoluteError": max((item["meanAbsoluteError"] for item in metric_rows), default=0.0),
        "maximumChangedPixelRatio": max((item["changedPixelRatio"] for item in metric_rows), default=0.0),
        "maximumTileMeanAbsoluteError": max(
            (item["maximumTileMeanAbsoluteError"] for item in metric_rows),
            default=0.0,
        ),
        "maximumTileChangedPixelRatio": max(
            (item["maximumTileChangedPixelRatio"] for item in metric_rows),
            default=0.0,
        ),
        "rawMaximumMeanAbsoluteError": max((item["rawMeanAbsoluteError"] for item in metric_rows), default=0.0),
        "rawMaximumChangedPixelRatio": max((item["rawChangedPixelRatio"] for item in metric_rows), default=0.0),
        "rawMaximumTileMeanAbsoluteError": max(
            (item["rawMaximumTileMeanAbsoluteError"] for item in metric_rows),
            default=0.0,
        ),
        "rawMaximumTileChangedPixelRatio": max(
            (item["rawMaximumTileChangedPixelRatio"] for item in metric_rows),
            default=0.0,
        ),
        "approvedDifferenceCaptureCount": sum(bool(item["approvedDifferenceRegions"]) for item in metric_rows),
        "comparisons": comparisons,
    }


def _validate_approved_difference_regions(
    regions: dict[str, list[list[int]]],
    *,
    source_files: dict[str, Path],
    target_files: dict[str, Path],
) -> dict[str, list[list[int]]]:
    """Validate explicit, screenshot-scoped pixel boxes before any normalization."""
    unknown = sorted(set(regions) - (set(source_files) & set(target_files)))
    if unknown:
        raise ValueError(f"approved difference regions reference unknown captures: {unknown}")

    validated: dict[str, list[list[int]]] = {}
    for name, boxes in regions.items():
        if not isinstance(boxes, list) or not boxes:
            raise ValueError(f"approved difference regions must be a non-empty list: {name}")
        width, height = _open_rgb(source_files[name]).size
        validated_boxes: list[list[int]] = []
        for box in boxes:
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(value) is not int for value in box)
            ):
                raise ValueError(f"approved difference region must contain four integers: {name}={box!r}")
            left, top, right, bottom = box
            if left < 0 or top < 0 or right <= left or bottom <= top or right > width or bottom > height:
                raise ValueError(f"approved difference region is outside the capture: {name}={box!r}, size={(width, height)}")
            validated_boxes.append([left, top, right, bottom])
        validated[name] = validated_boxes
    return validated


def _mask_approved_regions(
    source: Image.Image,
    target: Image.Image,
    regions: list[list[int]],
) -> Image.Image:
    """Normalize only reviewed target-only control pixels while retaining raw metrics."""
    if not regions:
        return target
    normalized = target.copy()
    for left, top, right, bottom in regions:
        box = (left, top, right, bottom)
        normalized.paste(source.crop(box), box)
    return normalized


def _write_difference_heatmap(source: Image.Image, target: Image.Image, destination: Path) -> None:
    """Persist an amplified, full-resolution RGB diff for independent review."""
    difference = ImageChops.difference(source, target)
    amplified = difference.point([min(255, value * 4) for value in range(256)] * len(difference.getbands()))
    red, green, blue = amplified.split()
    intensity = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    quarter = [value // 4 for value in range(256)]
    heatmap = Image.merge("RGB", (intensity, green.point(quarter), blue.point(quarter)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    heatmap.save(destination)


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def _capture_manifest(directory: Path) -> dict[str, Path]:
    """Inventory every PNG below a capture root using stable relative names."""
    return {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() == ".png"
    }


def _difference_metrics(source: Image.Image, target: Image.Image) -> tuple[float, float]:
    """Return normalized MAE and thresholded changed-pixel ratio."""
    difference = ImageChops.difference(source, target)
    histogram = difference.histogram()
    channel_total = sum((index % 256) * count for index, count in enumerate(histogram))
    mean_absolute_error = channel_total / (source.width * source.height * 3 * 255)
    red, green, blue = difference.split()
    maximum_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed_pixels = sum(maximum_channel.histogram()[PIXEL_DELTA:])
    return mean_absolute_error, changed_pixels / (source.width * source.height)


def maximum_tile_metrics(source: Image.Image, target: Image.Image) -> dict[str, Any]:
    """Return worst original-resolution overlapping-tile metrics for two images."""
    maximum_mae = -1.0
    maximum_changed = -1.0
    maximum_mae_tile: list[int] = []
    maximum_changed_tile: list[int] = []
    maximum_mae_tile_size = 0
    maximum_changed_tile_size = 0
    for tile_size, tile_stride in TILE_SCALES:
        for tile in iter_tile_metrics(source, target, tile_size=tile_size, tile_stride=tile_stride):
            tile_mae = tile["meanAbsoluteError"]
            tile_changed = tile["changedPixelRatio"]
            left, top, right, bottom = tile["box"]
            if tile_mae > maximum_mae:
                maximum_mae = tile_mae
                maximum_mae_tile = [left, top, right, bottom]
                maximum_mae_tile_size = tile_size
            if tile_changed > maximum_changed:
                maximum_changed = tile_changed
                maximum_changed_tile = [left, top, right, bottom]
                maximum_changed_tile_size = tile_size
    return {
        "meanAbsoluteError": maximum_mae,
        "changedPixelRatio": maximum_changed,
        "meanAbsoluteErrorTile": maximum_mae_tile,
        "meanAbsoluteErrorTileSize": maximum_mae_tile_size,
        "changedPixelTile": maximum_changed_tile,
        "changedPixelTileSize": maximum_changed_tile_size,
    }


def iter_tile_metrics(
    source: Image.Image,
    target: Image.Image,
    *,
    tile_size: int = TILE_SIZE,
    tile_stride: int = TILE_STRIDE,
) -> Iterator[TileMetric]:
    """Yield every overlapping original-resolution tile and both normalized metrics."""
    if source.size != target.size:
        raise ValueError(f"tile metric images must have equal sizes: {source.size} != {target.size}")
    if tile_size <= 0 or tile_stride <= 0 or tile_stride > tile_size:
        raise ValueError(f"invalid tile geometry: size={tile_size}, stride={tile_stride}")
    if source.mode != "RGB":
        source = source.convert("RGB")
    if target.mode != "RGB":
        target = target.convert("RGB")
    for top in _tile_starts(source.height, tile_size=tile_size, tile_stride=tile_stride):
        bottom = min(top + tile_size, source.height)
        for left in _tile_starts(source.width, tile_size=tile_size, tile_stride=tile_stride):
            right = min(left + tile_size, source.width)
            box = (left, top, right, bottom)
            tile_mae, tile_changed = _difference_metrics(source.crop(box), target.crop(box))
            yield {
                "box": [left, top, right, bottom],
                "meanAbsoluteError": tile_mae,
                "changedPixelRatio": tile_changed,
                "tileSize": tile_size,
                "tileStride": tile_stride,
            }


def _tile_starts(length: int, *, tile_size: int, tile_stride: int) -> list[int]:
    """Return half-tile-phase starts while keeping edge windows full-sized."""
    if length <= tile_size:
        return [0]
    final_start = length - tile_size
    starts = set(range(0, final_start + 1, tile_stride))
    starts.add(final_start)
    return sorted(starts)


def main() -> int:
    args = parse_args()
    result = compare_directories(
        args.source,
        args.target,
        source_revision=args.source_revision,
        max_mean_absolute_error=args.max_mean_absolute_error,
        max_changed_pixel_ratio=args.max_changed_pixel_ratio,
        max_tile_mean_absolute_error=args.max_tile_mean_absolute_error,
        max_tile_changed_pixel_ratio=args.max_tile_changed_pixel_ratio,
        diff_dir=args.diff_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
