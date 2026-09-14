"""Shared release-version validation and deterministic artifact paths."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

from packaging.utils import canonicalize_version
from packaging.version import InvalidVersion, Version

SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def artifact_sha256(path: Path) -> str:
    """Hash one exact release artifact without discovering alternatives."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_expected_artifact_sha256(path: Path, expected: str | None, *, label: str) -> str:
    """Bind an existing-artifact consumer to its parent gate's reviewed hash."""
    if expected is None or SHA256_PATTERN.fullmatch(expected) is None:
        raise RuntimeError(f"Existing-artifact {label} requires one lowercase SHA-256 digest")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Current-release {label} was not created at its exact path: {path}")
    actual = artifact_sha256(path)
    if actual != expected:
        raise RuntimeError(f"Existing-artifact {label} SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def validate_release_version(version: object) -> str:
    """Require the shared version to preserve release semantics in npm and Python."""
    if not isinstance(version, str):
        raise RuntimeError("Root pyproject.toml project.version must be a string")
    match = SEMVER_PATTERN.fullmatch(version)
    if match is None:
        raise RuntimeError("Root pyproject.toml project.version must be one exact valid SemVer value")
    if "+" in version:
        raise RuntimeError(
            "Root pyproject.toml project.version build metadata is unsupported because generated Oldman dependencies use >="
        )
    try:
        python_version = Version(version)
    except InvalidVersion as exc:
        raise RuntimeError(
            "Root pyproject.toml project.version must also be a valid Python distribution version"
        ) from exc
    if match.group("prerelease") is not None and not python_version.is_prerelease:
        raise RuntimeError(
            "Root pyproject.toml project.version prerelease semantics must agree between npm and Python"
        )
    return version


def authoritative_version(root: Path) -> str:
    """Read and validate the sole release-version authority."""
    path = root / "pyproject.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Cannot read release metadata at {path}: {exc}") from exc
    project = document.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    return validate_release_version(version)


def python_distribution_version(version: str) -> str:
    """Return the normalized version Hatchling writes into wheel names and metadata."""
    validated = validate_release_version(version)
    return canonicalize_version(Version(validated), strip_trailing_zero=False)


def python_release_artifact_paths(root: Path, version: str) -> tuple[Path, Path]:
    """Construct the exact wheel and sdist paths produced for one Python release."""
    python_version = python_distribution_version(version)
    dist = root / "dist"
    wheel = (dist / f"oldman-{python_version}-py3-none-any.whl").resolve()
    sdist = (dist / f"oldman-{python_version}.tar.gz").resolve()
    return wheel, sdist


def release_artifact_paths(root: Path, version: str) -> tuple[Path, Path]:
    """Construct exact Python and npm artifacts without glob or mtime discovery."""
    wheel, _sdist = python_release_artifact_paths(root, version)
    npm_tarball = (root / "frontend" / "packages" / "oldman-web" / f"oldman-web-{version}.tgz").resolve()
    return wheel, npm_tarball
