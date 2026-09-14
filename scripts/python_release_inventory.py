"""Committed and archived ``oldman/**`` release inventories."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PACKAGE_PREFIX = "oldman/"


@dataclass(frozen=True)
class CommittedPackageInventory:
    """Exact package files and contents frozen in one Git commit."""

    revision: str
    files: dict[str, str]

    @property
    def digest(self) -> str:
        return inventory_digest(self.files)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inventory_digest(files: dict[str, str]) -> str:
    """Hash a path-and-content inventory without depending on JSON whitespace."""
    encoded = b"".join(
        path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n"
        for path, digest in sorted(files.items())
    )
    return sha256_bytes(encoded)


def _git(root: Path, *args: str, text: bool = False) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", "-C", str(root), *args),
        check=False,
        capture_output=True,
        text=text,
    )
    if completed.returncode:
        stderr = completed.stderr if isinstance(completed.stderr, str) else completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Git command failed ({completed.returncode}): {' '.join(args)}\n{stderr.strip()}")
    return completed


def require_clean_oldman_tree(root: Path) -> None:
    """Reject package builds that are not sourced from committed ``oldman/**`` files."""
    completed = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
        "--",
        "oldman",
        text=True,
    )
    status = str(completed.stdout).splitlines()
    if status:
        preview = ", ".join(status[:8])
        raise RuntimeError(f"oldman package tree must match a clean commit before release verification: {preview}")


def committed_oldman_inventory(root: Path, revision: str = "HEAD") -> CommittedPackageInventory:
    """Read every committed package blob through ``git archive``."""
    root = root.resolve()
    resolved_revision = str(_git(root, "rev-parse", f"{revision}^{{commit}}", text=True).stdout).strip()
    archive = _git(root, "archive", "--format=tar", resolved_revision, "oldman")
    if not isinstance(archive.stdout, bytes):  # pragma: no cover - guarded by the binary subprocess call
        raise RuntimeError("Git archive unexpectedly returned text output")
    archive_bytes = archive.stdout
    files: dict[str, str] = {}
    unsupported: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as package_archive:
        for member in package_archive.getmembers():
            if member.isdir():
                continue
            path = safe_package_path(member.name)
            if path is None:
                unsupported.append(member.name)
                continue
            if not member.isfile():
                unsupported.append(member.name)
                continue
            extracted = package_archive.extractfile(member)
            if extracted is None:
                unsupported.append(member.name)
                continue
            if path in files:
                raise RuntimeError(f"Committed oldman inventory contains a duplicate path: {path}")
            files[path] = sha256_bytes(extracted.read())
    if unsupported:
        raise RuntimeError(f"Committed oldman inventory contains unsupported entries: {', '.join(sorted(unsupported))}")
    if not files or "oldman/__init__.py" not in files:
        raise RuntimeError("Committed oldman inventory is empty or missing oldman/__init__.py")
    return CommittedPackageInventory(revision=resolved_revision, files=files)


def safe_package_path(value: str) -> str | None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.startswith(PACKAGE_PREFIX):
        return None
    normalized = path.as_posix()
    return normalized if normalized != "oldman" else None


def wheel_oldman_inventory(path: Path) -> dict[str, str]:
    """Read exact package file hashes from a wheel."""
    files: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(PACKAGE_PREFIX):
                continue
            package_path = safe_package_path(info.filename)
            if package_path is None:
                raise RuntimeError(f"Wheel contains an unsafe oldman package path: {info.filename}")
            if package_path in files:
                raise RuntimeError(f"Wheel contains a duplicate oldman package path: {package_path}")
            files[package_path] = sha256_bytes(archive.read(info))
    return files


def sdist_oldman_inventory(path: Path) -> dict[str, str]:
    """Read exact package file hashes below one sdist root directory."""
    files: dict[str, str] = {}
    roots: set[str] = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = PurePosixPath(member.name)
            if len(member_path.parts) < 2:
                continue
            roots.add(member_path.parts[0])
            relative = PurePosixPath(*member_path.parts[1:]).as_posix()
            if not relative.startswith(PACKAGE_PREFIX):
                continue
            if member.isdir():
                continue
            package_path = safe_package_path(relative)
            if package_path is None or not member.isfile():
                raise RuntimeError(f"Source distribution contains an unsupported oldman package entry: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"Cannot read source distribution package entry: {member.name}")
            if package_path in files:
                raise RuntimeError(f"Source distribution contains a duplicate oldman package path: {package_path}")
            files[package_path] = sha256_bytes(extracted.read())
    if len(roots) != 1:
        raise RuntimeError(f"Source distribution must contain exactly one root directory, found {len(roots)}")
    return files


def compare_package_inventories(
    expected: dict[str, str],
    actual: dict[str, str],
    *,
    expected_label: str,
    actual_label: str,
) -> list[str]:
    """Return complete file-set and content differences."""
    errors = [
        f"{actual_label} is missing {expected_label} package file: {path}"
        for path in sorted(expected.keys() - actual.keys())
    ]
    errors.extend(
        f"{actual_label} contains unexpected package file absent from {expected_label}: {path}"
        for path in sorted(actual.keys() - expected.keys())
    )
    errors.extend(
        f"{actual_label} package content differs from {expected_label}: {path}"
        for path in sorted(expected.keys() & actual.keys())
        if expected[path] != actual[path]
    )
    return errors


def inventory_json(inventory: CommittedPackageInventory) -> dict[str, object]:
    """Return persistent evidence for an independently inspectable source inventory."""
    return {
        "fileCount": len(inventory.files),
        "files": dict(sorted(inventory.files.items())),
        "inventorySha256": inventory.digest,
        "revision": inventory.revision,
        "scope": "committed-oldman-package-files-and-content",
    }


def inventory_json_text(inventory: CommittedPackageInventory) -> str:
    return json.dumps(inventory_json(inventory), indent=2, sort_keys=True) + "\n"
