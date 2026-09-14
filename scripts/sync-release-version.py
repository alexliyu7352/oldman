#!/usr/bin/env python3
"""Synchronize release-version copies from the root Python metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

try:
    from scripts.release_artifacts import (
        authoritative_version as read_authoritative_version,
    )
    from scripts.release_artifacts import (
        python_distribution_version,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_artifacts import authoritative_version as read_authoritative_version
    from release_artifacts import python_distribution_version

ROOT = Path(__file__).resolve().parents[1]
JSON_TARGETS = (
    Path("package.json"),
    Path("frontend/apps/admin/package.json"),
    Path("frontend/packages/oldman-web/package.json"),
)
TEXT_TARGETS = (
    (
        Path("oldman/version.py"),
        re.compile(r'^__VERSION__ = "(?P<version>[^"]+)"$', re.MULTILINE),
        '__VERSION__ = "{version}"',
    ),
    (
        Path("frontend/packages/oldman-web/src/core/index.ts"),
        re.compile(r'^export const OLDMAN_WEB_VERSION = "(?P<version>[^"]+)";$', re.MULTILINE),
        'export const OLDMAN_WEB_VERSION = "{version}";',
    ),
)


class VersionSyncError(RuntimeError):
    """Raised when release metadata cannot be inspected safely."""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--write", action="store_true", help="rewrite generated version copies")
    return parser.parse_args()


def load_toml(path: Path) -> dict[str, Any]:
    """Load one TOML document with a concise error."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise VersionSyncError(f"Cannot read TOML metadata at {path}: {exc}") from exc


def authoritative_version(root: Path) -> str:
    """Read the one release version authority from the root pyproject."""
    try:
        return read_authoritative_version(root)
    except RuntimeError as exc:
        raise VersionSyncError(str(exc)) from exc


def editable_lock_version(root: Path) -> str:
    """Read the locked version of the editable root Oldman distribution."""
    document = load_toml(root / "uv.lock")
    packages = document.get("package")
    if not isinstance(packages, list):
        raise VersionSyncError("uv.lock has no package inventory")

    matches: list[str] = []
    for package in packages:
        if not isinstance(package, dict) or package.get("name") != "oldman":
            continue
        source = package.get("source")
        if not isinstance(source, dict) or source.get("editable") != ".":
            continue
        version = package.get("version")
        if isinstance(version, str):
            matches.append(version)
    if len(matches) != 1:
        raise VersionSyncError(f"Expected one editable oldman entry in uv.lock, found {len(matches)}")
    return matches[0]


def synchronize_json(path: Path, version: str, *, write: bool) -> str | None:
    """Check or rewrite a package.json version field."""
    try:
        source = path.read_text(encoding="utf-8")
        document = json.loads(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise VersionSyncError(f"Cannot read JSON metadata at {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("version"), str):
        raise VersionSyncError(f"JSON metadata has no string version field: {path}")

    current = document["version"]
    if current == version:
        return None
    if not write:
        return f"{path}: expected version {version}, found {current}"

    document["version"] = version
    rendered = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if rendered != source:
        path.write_text(rendered, encoding="utf-8")
    return None


def synchronize_text(
    path: Path,
    pattern: re.Pattern[str],
    replacement: str,
    version: str,
    *,
    write: bool,
) -> str | None:
    """Check or rewrite one named runtime version constant."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VersionSyncError(f"Cannot read runtime metadata at {path}: {exc}") from exc
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise VersionSyncError(f"Expected one release-version constant in {path}, found {len(matches)}")

    current = matches[0].group("version")
    if current == version:
        return None
    if not write:
        return f"{path}: expected version {version}, found {current}"

    rendered, count = pattern.subn(replacement.format(version=version), source, count=1)
    if count != 1:
        raise VersionSyncError(f"Could not rewrite release-version constant in {path}")
    path.write_text(rendered, encoding="utf-8")
    return None


def synchronize(root: Path, *, write: bool) -> list[str]:
    """Synchronize generated copies and return all remaining drift."""
    root = root.resolve()
    version = authoritative_version(root)
    failures: list[str] = []
    for relative in JSON_TARGETS:
        failure = synchronize_json(root / relative, version, write=write)
        if failure is not None:
            failures.append(failure)
    for relative, pattern, replacement in TEXT_TARGETS:
        failure = synchronize_text(root / relative, pattern, replacement, version, write=write)
        if failure is not None:
            failures.append(failure)

    locked_version = editable_lock_version(root)
    expected_locked_version = python_distribution_version(version)
    if locked_version != expected_locked_version:
        failures.append(
            f"{root / 'uv.lock'}: expected editable oldman version {expected_locked_version}, found {locked_version}"
        )
    return failures


def main() -> int:
    """Check or rewrite all generated release-version copies."""
    args = parse_args()
    try:
        failures = synchronize(args.root, write=args.write)
        version = authoritative_version(args.root.resolve())
    except VersionSyncError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    action = "synchronized" if args.write else "verified"
    print(f"Oldman release version {version} {action} from pyproject.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
