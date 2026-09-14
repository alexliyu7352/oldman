#!/usr/bin/env python3
"""Verify Oldman wheel package data and public package boundaries."""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tomllib
import zipfile
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
        wheel_oldman_inventory,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from python_release_inventory import (
        committed_oldman_inventory,
        compare_package_inventories,
        require_clean_oldman_tree,
        wheel_oldman_inventory,
    )

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIR_PREFIXES = (
    "oldman/apps/admin/static/oldman/admin/",
    "oldman/apps/admin/templates/",
    "oldman/scaffolds/",
    "oldman/web/static/oldman/",
    "oldman/web/templates/",
    "oldman/web/templates/oldman/forms/default/",
)
REQUIRED_FILES = (
    "oldman/py.typed",
    "oldman/web/messages/notifications/locales/zh_Hans/LC_MESSAGES/messages.mo",
    "oldman/web/messages/notifications/locales/zh_Hant/LC_MESSAGES/messages.mo",
    "oldman/web/messages/notifications/migrations/__init__.py",
    "oldman/web/messages/notifications/migrations/4858aab957ee_create_oldman_notification.py",
    "oldman/web/templates/oldman/messages/notifications/center_content.html",
    "oldman/web/templates/oldman/messages/notifications/topbar_fragment.html",
)
REQUIRED_SCAFFOLD_PREFIXES = (
    "oldman/scaffolds/project/cli_app/",
    "oldman/scaffolds/project/app_service/",
    "oldman/scaffolds/project/api_service/",
    "oldman/scaffolds/project/web_service/",
    "oldman/scaffolds/project/dashboard/",
    "oldman/scaffolds/app/service_app/",
    "oldman/scaffolds/app/api_app/",
    "oldman/scaffolds/app/web_app/",
    "oldman/scaffolds/app/dashboard_app/",
)
FORBIDDEN_ADMIN_ASSET_TOKENS = (
    "epg",
    "channels",
    "catalog",
    "logo",
    "match-decisions",
    "component-coverage",
    "apex-chart",
)
REQUIRED_ADMIN_DYNAMIC_ENTRIES = ("date-time-picker", "dropdown", "modal", "table-filter-form")
DIST_INFO_FILES = ("METADATA", "WHEEL", "entry_points.txt", "licenses/LICENSE", "RECORD")
RELEASE_SOURCE_FILES = ("LICENSE", "README.md", "pyproject.toml")
WHEEL_DATE_TIME = (2020, 2, 2, 0, 0, 0)
ADMIN_STATIC_PREFIX = "oldman/apps/admin/static/oldman/admin/"
NOTIFICATION_LOCALE_PREFIX = "oldman/web/messages/notifications/locales/"


class CaseSensitiveConfigParser(configparser.ConfigParser):
    """Preserve entry-point names exactly while parsing INI metadata."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def resolve_wheel_args(args: list[str]) -> list[Path]:
    """Resolve explicit wheel paths in caller-provided order."""
    wheels: list[Path] = []
    for value in args:
        if any(character in value for character in "*?[]"):
            raise RuntimeError(f"Wheel must be an explicit path, not a glob: {value!r}")
        candidate = Path(value).expanduser()
        if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(".whl"):
            raise RuntimeError(f"Wheel is not a readable regular .whl file: {candidate}")
        wheels.append(candidate.resolve())
    return wheels


def load_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    """Read JSON from a wheel archive."""
    return json.loads(archive.read(name).decode("utf-8"))


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


def expected_hatchling_generator(source_files: Mapping[str, bytes]) -> str:
    """Read the exactly pinned build backend version from frozen pyproject.toml."""
    try:
        document = tomllib.loads(source_files["pyproject.toml"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Frozen pyproject.toml cannot be parsed: {exc}") from exc
    build_system = document.get("build-system")
    requirements = build_system.get("requires") if isinstance(build_system, dict) else None
    if not isinstance(requirements, list):
        raise RuntimeError("Frozen build-system.requires is missing")
    hatchling = [Requirement(value) for value in requirements if Requirement(value).name == "hatchling"]
    if len(hatchling) != 1:
        raise RuntimeError("Frozen build-system must contain exactly one Hatchling requirement")
    specifiers = list(hatchling[0].specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==" or specifiers[0].version.endswith(".*"):
        raise RuntimeError("Frozen Hatchling build backend must use one exact version pin")
    return f"hatchling {specifiers[0].version}"


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
        "Version": project.get("version"),
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
        normalize = lambda value: re.sub(r"\s+", " ", value).strip()  # noqa: E731
        if license_header is None or normalize(license_header) != normalize(expected_license):
            errors.append(f"{label} License does not match frozen LICENSE")

    if message.get_payload(decode=True) != source_files["README.md"]:
        errors.append(f"{label} description payload does not match frozen README.md")
    return errors


def wheel_metadata_errors(
    archive: zipfile.ZipFile,
    dist_info_root: str,
    source_files: Mapping[str, bytes],
) -> list[str]:
    """Bind every non-RECORD dist-info member to frozen project inputs."""
    errors: list[str] = []
    try:
        project = project_table(source_files)
        expected_root = f"{project['name']}-{project['version']}.dist-info"
    except (KeyError, RuntimeError) as exc:
        return [f"Wheel metadata cannot be bound to frozen project metadata: {exc}"]
    if dist_info_root != expected_root:
        errors.append(f"Wheel dist-info root does not match frozen project identity: {dist_info_root}")

    metadata_name = f"{dist_info_root}/METADATA"
    if metadata_name in archive.namelist():
        errors.extend(core_metadata_errors(archive.read(metadata_name), source_files, label="Wheel METADATA"))
    license_name = f"{dist_info_root}/licenses/LICENSE"
    if license_name in archive.namelist() and archive.read(license_name) != source_files["LICENSE"]:
        errors.append("Wheel license file does not match frozen LICENSE")

    wheel_name = f"{dist_info_root}/WHEEL"
    if wheel_name in archive.namelist():
        wheel = BytesParser(policy=default).parsebytes(archive.read(wheel_name))
        expected_wheel = {"Wheel-Version": "1.0", "Root-Is-Purelib": "true", "Tag": "py3-none-any"}
        if Counter(name.lower() for name in wheel.keys()) != Counter(
            {"wheel-version": 1, "generator": 1, "root-is-purelib": 1, "tag": 1}
        ):
            errors.append("Wheel WHEEL metadata has an unexpected header inventory")
        for header, expected in expected_wheel.items():
            if wheel.get_all(header, []) != [expected]:
                errors.append(f"Wheel WHEEL metadata has invalid {header}")
        generator = wheel.get_all("Generator", [])
        try:
            expected_generator = expected_hatchling_generator(source_files)
        except RuntimeError as exc:
            errors.append(f"Wheel Generator cannot be bound to frozen build-system: {exc}")
            expected_generator = None
        if expected_generator is None or generator != [expected_generator]:
            errors.append("Wheel WHEEL metadata has an invalid Generator")

    entry_points_name = f"{dist_info_root}/entry_points.txt"
    if entry_points_name in archive.namelist():
        parser = CaseSensitiveConfigParser(interpolation=None)
        try:
            parser.read_string(archive.read(entry_points_name).decode("utf-8"))
        except (UnicodeDecodeError, configparser.Error) as exc:
            errors.append(f"Wheel entry_points.txt cannot be parsed: {exc}")
        else:
            scripts = project.get("scripts")
            actual_scripts = dict(parser.items("console_scripts")) if parser.sections() == ["console_scripts"] else None
            if not isinstance(scripts, dict) or actual_scripts != scripts:
                errors.append("Wheel entry_points.txt does not match frozen project.scripts")
    return errors


def safe_wheel_member_errors(info: zipfile.ZipInfo) -> list[str]:
    """Reject archive member names and types that cannot be release files."""
    name = info.filename
    parts = PurePosixPath(name).parts
    errors: list[str] = []
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(*parts).as_posix() != name
    ):
        errors.append(f"Wheel contains unsafe member path: {name!r}")
    if info.is_dir():
        errors.append(f"Wheel contains a non-file member: {name}")
    file_type = stat.S_IFMT(info.external_attr >> 16)
    expected_file_type = stat.S_IFREG if name.startswith("oldman/") else 0
    if file_type != expected_file_type:
        errors.append(f"Wheel contains an unsafe member type: {name}")
    expected_external_attr = (expected_file_type | 0o644) << 16
    if info.external_attr != expected_external_attr:
        errors.append(f"Wheel member has non-canonical external attributes: {name}")
    if info.flag_bits & 0x1:
        errors.append(f"Wheel contains an encrypted member: {name}")
    if stat.S_IMODE(info.external_attr >> 16) != 0o644:
        errors.append(f"Wheel member mode is not the release-file mode 0644: {name}")
    if info.create_system != 3 or info.create_version != 20 or info.extract_version != 20:
        errors.append(f"Wheel member has non-canonical ZIP platform/version metadata: {name}")
    if info.compress_type != zipfile.ZIP_DEFLATED or info.flag_bits != 0:
        errors.append(f"Wheel member has non-canonical ZIP compression flags: {name}")
    if info.date_time != WHEEL_DATE_TIME:
        errors.append(f"Wheel member has non-canonical timestamp: {name}")
    if info.extra or info.comment or info.reserved != 0 or info.volume != 0 or info.internal_attr != 0:
        errors.append(f"Wheel member has unexpected ZIP metadata: {name}")
    return errors


def verify_record(archive: zipfile.ZipFile, record_name: str, names: set[str], errors: list[str]) -> None:
    """Require RECORD to close over and authenticate every wheel member."""
    try:
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"), newline="")))
    except (KeyError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"Wheel RECORD cannot be read: {exc}")
        return

    record_paths: list[str] = []
    for row in rows:
        if len(row) != 3:
            errors.append(f"Wheel RECORD contains a malformed row: {row!r}")
            continue
        member_name, encoded_hash, encoded_size = row
        record_paths.append(member_name)
        if member_name == record_name:
            if encoded_hash or encoded_size:
                errors.append("Wheel RECORD self-entry must have empty hash and size")
            continue
        if member_name not in names:
            continue
        payload = archive.read(member_name)
        expected_hash = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode("ascii")
        if encoded_hash != f"sha256={expected_hash}":
            errors.append(f"Wheel RECORD hash does not match member: {member_name}")
        if encoded_size != str(len(payload)):
            errors.append(f"Wheel RECORD size does not match member: {member_name}")

    if len(record_paths) != len(set(record_paths)):
        errors.append("Wheel RECORD contains duplicate member rows")
    missing = names - set(record_paths)
    unexpected = set(record_paths) - names
    errors.extend(f"Wheel RECORD is missing member: {name}" for name in sorted(missing))
    errors.extend(f"Wheel RECORD references absent member: {name}" for name in sorted(unexpected))


def verify_manifest_references(names: set[str], manifest: dict[str, Any], errors: list[str]) -> None:
    """Verify Vite manifest references point to packaged files."""
    main_entry = manifest.get("src/main.ts")
    if not isinstance(main_entry, dict):
        errors.append("Admin static manifest missing src/main.ts entry")
        return

    for _key, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        file_name = entry.get("file")
        if (
            isinstance(file_name, str)
            and f"{ADMIN_STATIC_PREFIX}{file_name}" not in names
        ):
            errors.append(f"Admin manifest file reference is missing: {file_name}")
        for css_file in entry.get("css", []) or []:
            if f"{ADMIN_STATIC_PREFIX}{css_file}" not in names:
                errors.append(f"Admin manifest CSS reference is missing: {css_file}")
        for asset_file in entry.get("assets", []) or []:
            if f"{ADMIN_STATIC_PREFIX}{asset_file}" not in names:
                errors.append(f"Admin manifest asset reference is missing: {asset_file}")
        for dynamic_key in entry.get("dynamicImports", []) or []:
            if dynamic_key not in manifest:
                errors.append(f"Admin manifest dynamic import key is missing: {dynamic_key}")

    dynamic_entry_names = {
        str(entry.get("name"))
        for entry in manifest.values()
        if isinstance(entry, dict) and entry.get("isDynamicEntry") is True
    }
    for required_name in REQUIRED_ADMIN_DYNAMIC_ENTRIES:
        if required_name not in dynamic_entry_names:
            errors.append(f"Admin manifest missing required dynamic entry: {required_name}")


def verify_wheel(
    path: Path,
    *,
    expected_inventory: dict[str, str] | None = None,
    expected_source_files: Mapping[str, bytes] | None = None,
) -> list[str]:
    """Verify a single wheel."""
    errors: list[str] = []
    if not path.exists():
        return [f"Wheel does not exist: {path}"]
    if expected_source_files is None:
        expected_source_files = release_source_files(ROOT)

    if expected_inventory is not None:
        try:
            artifact_inventory = wheel_oldman_inventory(path)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            errors.append(f"Cannot read wheel oldman package inventory: {exc}")
        else:
            errors.extend(
                compare_package_inventories(
                    expected_inventory,
                    artifact_inventory,
                    expected_label="committed source",
                    actual_label="wheel",
                )
            )

    with zipfile.ZipFile(path) as archive:
        if archive.comment:
            errors.append("Wheel archive has an unexpected ZIP comment")
        infos = archive.infolist()
        raw_names = [info.filename for info in infos]
        names = set(raw_names)
        if len(raw_names) != len(names):
            errors.append("Wheel contains duplicate archive members")
        for info in infos:
            errors.extend(safe_wheel_member_errors(info))

        dist_info_roots = {
            name.split("/", 1)[0]
            for name in names
            if "/" in name and name.split("/", 1)[0].endswith(".dist-info")
        }
        if len(dist_info_roots) != 1:
            errors.append(f"Wheel must contain exactly one .dist-info directory, found {len(dist_info_roots)}")
            dist_info_root = None
        else:
            dist_info_root = next(iter(dist_info_roots))

        package_names = set(expected_inventory) if expected_inventory is not None else {
            name for name in names if name.startswith("oldman/")
        }
        metadata_names = {
            f"{dist_info_root}/{suffix}" for suffix in DIST_INFO_FILES
        } if dist_info_root is not None else set()
        allowed_names = package_names | metadata_names
        errors.extend(f"Wheel contains unexpected member: {name}" for name in sorted(names - allowed_names))
        errors.extend(f"Wheel is missing expected member: {name}" for name in sorted(allowed_names - names))

        if dist_info_root is not None:
            errors.extend(wheel_metadata_errors(archive, dist_info_root, expected_source_files))
            record_name = f"{dist_info_root}/RECORD"
            if record_name in names and len(raw_names) == len(names):
                verify_record(archive, record_name, names, errors)

        for prefix in REQUIRED_DIR_PREFIXES:
            if not any(name.startswith(prefix) for name in names):
                errors.append(f"Wheel missing required package data: {prefix}")

        for name in REQUIRED_FILES:
            if name not in names:
                errors.append(f"Wheel missing required package file: {name}")

        for name in names:
            if name.startswith(NOTIFICATION_LOCALE_PREFIX) and name.endswith(
                (".po", ".pot")
            ):
                errors.append(
                    f"Wheel must not contain notification translation source: {name}"
                )

        for prefix in REQUIRED_SCAFFOLD_PREFIXES:
            if not any(name.startswith(prefix) and not name.endswith("/") for name in names):
                errors.append(f"Wheel missing scaffold files: {prefix}")

        if any(name.startswith("oldman/dashboard/") for name in names):
            errors.append("Wheel must not contain oldman/dashboard Python package")
        if any(name.startswith("frontend/scaffolds/") for name in names):
            errors.append("Wheel must not contain frontend/scaffolds as scaffold source")
        if any(name.startswith("oldman/web/static/assets/") or name.startswith("oldman/web/static/.vite/") for name in names):
            errors.append("Admin static assets must not be packaged under oldman/web/static")

        manifest_name = f"{ADMIN_STATIC_PREFIX}.vite/manifest.json"
        if manifest_name not in names:
            errors.append(
                "Wheel missing collected-source Admin Vite manifest"
            )
        else:
            verify_manifest_references(names, load_json(archive, manifest_name), errors)

        for name in names:
            if not name.startswith(ADMIN_STATIC_PREFIX):
                continue
            lower = name.lower()
            for token in FORBIDDEN_ADMIN_ASSET_TOKENS:
                if token in lower:
                    errors.append(f"Admin static asset contains forbidden business/demo token: {name}")

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--source-revision", default="HEAD", help=argparse.SUPPRESS)
    parser.add_argument("wheels", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run wheel verification."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source_root = args.source_root.expanduser().resolve()
    try:
        require_clean_oldman_tree(source_root)
        source_inventory = committed_oldman_inventory(source_root, args.source_revision)
        expected_source_files = committed_release_source_files(source_root, source_inventory.revision)
        wheels = resolve_wheel_args(args.wheels)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors: list[str] = []
    for wheel in wheels:
        errors.extend(
            verify_wheel(
                wheel,
                expected_source_files=expected_source_files,
            )
        )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Oldman wheel contents are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
