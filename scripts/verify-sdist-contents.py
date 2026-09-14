#!/usr/bin/env python3
"""Verify that the Oldman source distribution contains only publishable sources."""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tarfile
import tomllib
from collections import Counter
from collections.abc import Mapping
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

try:
    from scripts.python_release_inventory import (
        committed_oldman_inventory,
        compare_package_inventories,
        require_clean_oldman_tree,
        sdist_oldman_inventory,
    )
    from scripts.release_artifacts import python_distribution_version
except ModuleNotFoundError:  # pragma: no cover - direct/build-hook execution
    artifacts_path = Path(__file__).resolve().with_name("release_artifacts.py")
    artifacts_spec = importlib.util.spec_from_file_location("oldman_release_artifacts", artifacts_path)
    if artifacts_spec is None or artifacts_spec.loader is None:
        raise RuntimeError(f"Cannot load release artifacts helper: {artifacts_path}") from None
    artifacts_module = importlib.util.module_from_spec(artifacts_spec)
    sys.modules[artifacts_spec.name] = artifacts_module
    artifacts_spec.loader.exec_module(artifacts_module)
    python_distribution_version = artifacts_module.python_distribution_version
    inventory_path = Path(__file__).resolve().with_name("python_release_inventory.py")
    inventory_spec = importlib.util.spec_from_file_location("oldman_python_release_inventory", inventory_path)
    if inventory_spec is None or inventory_spec.loader is None:
        raise RuntimeError(f"Cannot load release inventory helper: {inventory_path}") from None
    inventory_module = importlib.util.module_from_spec(inventory_spec)
    sys.modules[inventory_spec.name] = inventory_module
    inventory_spec.loader.exec_module(inventory_module)
    committed_oldman_inventory = inventory_module.committed_oldman_inventory
    compare_package_inventories = inventory_module.compare_package_inventories
    require_clean_oldman_tree = inventory_module.require_clean_oldman_tree
    sdist_oldman_inventory = inventory_module.sdist_oldman_inventory

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SOURCE_FILES = (
    "LICENSE",
    "LICENSES/aiocache-BSD-3-Clause.txt",
    "LICENSES/flag-icons-LICENSE.txt",
    "LICENSES/nats-py-Apache-2.0.txt",
    "README.md",
    "pyproject.toml",
    "scripts/hatch_sdist_hook.py",
)
SDIST_MTIME = 1_580_601_600

REQUIRED_PATHS = {
    "LICENSE",
    "LICENSES/aiocache-BSD-3-Clause.txt",
    "LICENSES/flag-icons-LICENSE.txt",
    "LICENSES/nats-py-Apache-2.0.txt",
    "PKG-INFO",
    "README.md",
    "oldman/__init__.py",
    "oldman/py.typed",
    "oldman/web/messages/notifications/locales/messages.pot",
    "oldman/web/messages/notifications/locales/zh_Hans/LC_MESSAGES/messages.mo",
    "oldman/web/messages/notifications/locales/zh_Hans/LC_MESSAGES/messages.po",
    "oldman/web/messages/notifications/locales/zh_Hant/LC_MESSAGES/messages.mo",
    "oldman/web/messages/notifications/locales/zh_Hant/LC_MESSAGES/messages.po",
    "oldman/web/messages/notifications/migrations/__init__.py",
    "oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py",
    "oldman/web/templates/oldman/messages/notifications/center_content.html",
    "oldman/web/templates/oldman/messages/notifications/topbar_fragment.html",
    "pyproject.toml",
    "scripts/hatch_sdist_hook.py",
}
FORBIDDEN_PREFIXES = (
    "docs/",
    "examples/",
    "frontend/",
    "scripts/",
    "tests/",
)
FORBIDDEN_ROOT_FILES = {
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "tsconfig.base.json",
    "uv.lock",
}


def resolve_sdist_args(args: list[str]) -> list[Path]:
    """Resolve explicit source distribution paths in caller-provided order."""
    archives: list[Path] = []
    for value in args:
        if any(character in value for character in "*?[]"):
            raise RuntimeError(f"Source distribution must be an explicit path, not a glob: {value!r}")
        candidate = Path(value).expanduser()
        if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(".tar.gz"):
            raise RuntimeError(f"Source distribution is not a readable regular .tar.gz file: {candidate}")
        archives.append(candidate.resolve())
    return archives


def release_source_files(root: Path) -> dict[str, bytes]:
    """Read release-root inputs from the current worktree for direct/test use."""
    return {name: (root / name).read_bytes() for name in RELEASE_SOURCE_FILES}


def committed_release_source_files(root: Path, revision: str) -> dict[str, bytes]:
    """Read release-root inputs from the same frozen Git revision as ``oldman/**``."""
    files: dict[str, bytes] = {}
    for name in RELEASE_SOURCE_FILES:
        completed = subprocess.run(
            ("git", "-C", str(root), "show", f"{revision}:{name}"),
            check=False,
            capture_output=True,
        )
        if completed.returncode:
            raise RuntimeError(f"Cannot read committed release source {name} at {revision}")
        files[name] = completed.stdout
    return files


def project_table(source_files: Mapping[str, bytes]) -> dict[str, Any]:
    """Parse the frozen PEP 621 project table and its bound root files."""
    missing = set(RELEASE_SOURCE_FILES) - set(source_files)
    if missing:
        raise RuntimeError(f"Release source metadata is missing: {', '.join(sorted(missing))}")
    try:
        document = tomllib.loads(source_files["pyproject.toml"].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Frozen pyproject.toml cannot be parsed: {exc}") from exc
    project = document.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("Frozen pyproject.toml has no project table")
    if project.get("readme") != "README.md" or project.get("license") != {"file": "LICENSE"}:
        raise RuntimeError("Frozen project readme/license files drifted from the release-root contract")
    return project


def _one_header(message: Any, name: str, errors: list[str], label: str) -> str | None:
    values = message.get_all(name, [])
    if len(values) != 1:
        errors.append(f"{label} must contain exactly one {name} header")
        return None
    return str(values[0])


def core_metadata_errors(payload: bytes, source_files: Mapping[str, bytes], *, label: str) -> list[str]:
    """Bind generated core metadata to frozen PEP 621 fields and root-file bytes."""
    errors: list[str] = []
    try:
        project = project_table(source_files)
        message = BytesParser(policy=default).parsebytes(payload)
    except (OSError, RuntimeError) as exc:
        return [f"{label} cannot be bound to frozen project metadata: {exc}"]

    scalar_headers = {
        "Metadata-Version": "2.4",
        "Name": project.get("name"),
        "Version": python_distribution_version(project["version"]),
        "Summary": project.get("description"),
        "Description-Content-Type": "text/markdown",
        "License-File": "LICENSE",
    }
    expected_header_counts = Counter(
        {
            "metadata-version": 1,
            "name": 1,
            "version": 1,
            "summary": 1,
            "project-url": len(project.get("urls", {})),
            "license": 1,
            "license-file": 1,
            "requires-python": 1,
            "requires-dist": len(project.get("dependencies", [])),
            "description-content-type": 1,
        }
    )
    actual_header_counts = Counter(name.lower() for name in message.keys())
    if actual_header_counts != expected_header_counts:
        errors.append(f"{label} header inventory does not match frozen pyproject.toml")
    for header, expected in scalar_headers.items():
        actual = _one_header(message, header, errors, label)
        if not isinstance(expected, str) or actual != expected:
            errors.append(f"{label} {header} does not match frozen pyproject.toml")

    actual_python = _one_header(message, "Requires-Python", errors, label)
    expected_python = project.get("requires-python")
    try:
        if not isinstance(expected_python, str) or actual_python is None or SpecifierSet(actual_python) != SpecifierSet(expected_python):
            errors.append(f"{label} Requires-Python does not match frozen pyproject.toml")
    except InvalidSpecifier:
        errors.append(f"{label} contains invalid Requires-Python metadata")

    expected_dependencies = project.get("dependencies")
    actual_dependencies = message.get_all("Requires-Dist", [])
    try:
        expected_requirements = Counter(Requirement(value) for value in expected_dependencies or [])
        actual_requirements = Counter(Requirement(str(value)) for value in actual_dependencies)
    except (InvalidRequirement, TypeError) as exc:
        errors.append(f"{label} dependency metadata cannot be parsed: {exc}")
    else:
        if expected_requirements != actual_requirements:
            errors.append(f"{label} Requires-Dist does not match frozen pyproject.toml")

    expected_urls = project.get("urls")
    actual_urls: dict[str, str] = {}
    for value in message.get_all("Project-URL", []):
        label_and_url = str(value).split(",", 1)
        if len(label_and_url) != 2 or label_and_url[0].strip() in actual_urls:
            errors.append(f"{label} contains malformed or duplicate Project-URL metadata")
            continue
        actual_urls[label_and_url[0].strip()] = label_and_url[1].strip()
    if not isinstance(expected_urls, dict) or actual_urls != expected_urls:
        errors.append(f"{label} Project-URL values do not match frozen pyproject.toml")

    license_header = _one_header(message, "License", errors, label)
    try:
        expected_license = source_files["LICENSE"].decode("utf-8")
    except UnicodeDecodeError:
        errors.append("Frozen LICENSE is not UTF-8")
    else:
        normalized_license = re.sub(r"\s+", " ", expected_license).strip()
        if license_header is None or re.sub(r"\s+", " ", license_header).strip() != normalized_license:
            errors.append(f"{label} License does not match frozen LICENSE")

    if message.get_payload(decode=True) != source_files["README.md"]:
        errors.append(f"{label} description payload does not match frozen README.md")
    return errors


def sdist_metadata_errors(
    archive: tarfile.TarFile,
    root: str,
    source_files: Mapping[str, bytes],
) -> list[str]:
    """Bind root files and PKG-INFO to frozen release inputs."""
    errors: list[str] = []
    try:
        project = project_table(source_files)
        expected_root = f"{project['name']}-{python_distribution_version(project['version'])}"
    except (KeyError, RuntimeError) as exc:
        return [f"Source distribution metadata cannot be bound to frozen project metadata: {exc}"]
    if root != expected_root:
        errors.append(f"Source distribution root does not match frozen project identity: {root}")
    for name in RELEASE_SOURCE_FILES:
        member_name = f"{root}/{name}"
        try:
            extracted = archive.extractfile(member_name)
        except KeyError:
            continue
        if extracted is not None and extracted.read() != source_files[name]:
            errors.append(f"Source distribution {name} does not match frozen source")
    pkg_info_name = f"{root}/PKG-INFO"
    try:
        pkg_info = archive.extractfile(pkg_info_name)
    except KeyError:
        pkg_info = None
    if pkg_info is not None:
        errors.extend(core_metadata_errors(pkg_info.read(), source_files, label="Source distribution PKG-INFO"))
    return errors


def archive_relative_path(name: str) -> str:
    """Strip the standard distribution root directory from a member name."""
    parts = PurePosixPath(name).parts
    return PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else ""


def expected_sdist_root(path: Path) -> str:
    """Return the one archive root implied by an ``.tar.gz`` filename."""
    return path.name.removesuffix(".tar.gz")


def safe_sdist_member_errors(member: tarfile.TarInfo, root: str) -> list[str]:
    """Reject traversal, links, devices, directories, and non-canonical names."""
    name = member.name
    parts = PurePosixPath(name).parts
    errors: list[str] = []
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(*parts).as_posix() != name
        or parts[0] != root
        or len(parts) < 2
    ):
        errors.append(f"Source distribution contains unsafe member path: {name!r}")
    if member.type != tarfile.REGTYPE:
        errors.append(f"Source distribution contains unsafe member type: {name}")
    if member.mode != 0o644:
        errors.append(f"Source distribution member mode is not the release-file mode 0644: {name}")
    if member.uid != 0 or member.gid != 0 or member.uname != "" or member.gname != "":
        errors.append(f"Source distribution member has non-canonical ownership metadata: {name}")
    if member.mtime != SDIST_MTIME:
        errors.append(f"Source distribution member has non-canonical mtime: {name}")
    if member.pax_headers:
        # tarfile emits a PAX header once a member path exceeds the 100-byte ustar name field;
        # that header may carry the path and nothing else (no mtime, uid, or other overrides).
        if set(member.pax_headers) != {"path"} or len(name) <= 100 or member.pax_headers["path"] != name:
            errors.append(f"Source distribution member has unexpected PAX metadata: {name}")
    if member.linkname or member.devmajor != 0 or member.devminor != 0 or member.sparse is not None:
        errors.append(f"Source distribution member has unexpected link/device metadata: {name}")
    return errors


def canonical_gzip_header_errors(path: Path) -> list[str]:
    """Require Hatchling's deterministic gzip wrapper metadata."""
    header = path.read_bytes()[:10]
    expected = b"\x1f\x8b\x08\x00" + SDIST_MTIME.to_bytes(4, "little") + b"\x02\xff"
    return [] if header == expected else ["Source distribution has non-canonical gzip header metadata"]


def verify_sdist(
    path: Path,
    *,
    expected_inventory: dict[str, str] | None = None,
    expected_source_files: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Verify a single source distribution archive."""
    if not path.exists():
        return [f"Source distribution does not exist: {path}"]
    if expected_source_files is None:
        expected_source_files = release_source_files(ROOT)

    errors: list[str] = canonical_gzip_header_errors(path)
    if expected_inventory is not None:
        try:
            artifact_inventory = sdist_oldman_inventory(path)
        except (OSError, RuntimeError, tarfile.TarError) as exc:
            errors.append(f"Cannot read source distribution oldman package inventory: {exc}")
        else:
            errors.extend(
                compare_package_inventories(
                    expected_inventory,
                    artifact_inventory,
                    expected_label="committed source",
                    actual_label="source distribution",
                )
            )

    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        raw_names = [member.name for member in members]
        if len(raw_names) != len(set(raw_names)):
            errors.append("Source distribution contains duplicate archive members")
        root = expected_sdist_root(path)
        for member in members:
            errors.extend(safe_sdist_member_errors(member, root))
        names = {archive_relative_path(member.name) for member in members if member.isfile()}
        errors.extend(sdist_metadata_errors(archive, root, expected_source_files))

    package_names = set(expected_inventory) if expected_inventory is not None else {
        name for name in names if name.startswith("oldman/")
    }
    allowed_names = package_names | set(RELEASE_SOURCE_FILES) | {"PKG-INFO"}
    errors.extend(f"Source distribution contains unexpected member: {name}" for name in sorted(names - allowed_names))
    errors.extend(f"Source distribution is missing expected member: {name}" for name in sorted(allowed_names - names))

    errors.extend(f"Source distribution missing required file: {name}" for name in sorted(REQUIRED_PATHS - names))
    for name in sorted(names):
        if name in FORBIDDEN_ROOT_FILES:
            errors.append(f"Source distribution contains repository-only file: {name}")
        if name.startswith(FORBIDDEN_PREFIXES) and name != "scripts/hatch_sdist_hook.py":
            errors.append(f"Source distribution contains non-package tree: {name}")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--source-revision", default="HEAD", help=argparse.SUPPRESS)
    parser.add_argument("archives", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run source distribution verification."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source_root = args.source_root.expanduser().resolve()
    try:
        require_clean_oldman_tree(source_root)
        source_inventory = committed_oldman_inventory(source_root, args.source_revision)
        expected_inventory = source_inventory.files
        expected_source_files = committed_release_source_files(source_root, source_inventory.revision)
        archives = resolve_sdist_args(args.archives)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors: list[str] = []
    for archive in archives:
        errors.extend(
            verify_sdist(
                archive,
                expected_inventory=expected_inventory,
                expected_source_files=expected_source_files,
            )
        )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Oldman source distribution contents are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
