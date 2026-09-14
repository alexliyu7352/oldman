#!/usr/bin/env python3
"""Verify the oldman-web package boundary and packed artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.oldman_tailwind_inventory import css_class_selector, framework_tailwind_utilities, inventory_block, inventory_utilities
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from oldman_tailwind_inventory import css_class_selector, framework_tailwind_utilities, inventory_block, inventory_utilities

try:
    from scripts.release_artifacts import python_distribution_version
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_artifacts import python_distribution_version

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "frontend" / "packages" / "oldman-web"
PACKAGE_JSON = PACKAGE_ROOT / "package.json"

REQUIRED_COMPONENTS = (
    "apex-chart",
    "autocomplete",
    "date-time-picker",
    "dropdown",
    "form-mask",
    "form",
    "form-validator",
    "list",
    "modal",
    "preloader",
    "scroll-area",
    "select",
    "sidebar-menu",
    "slider",
    "table",
    "table-filter-form",
    "upload",
    "feedback",
    "back-to-top",
    "history-back",
)

REQUIRED_EXPORTS = (
    ".",
    "./core",
    "./app",
    "./components",
    "./dashboard",
    "./dashboard/feedback",
    "./dashboard/modal",
    "./styles/tailwind.css",
    "./styles/icons.css",
    "./package.json",
)

FORBIDDEN_SOURCE_TOKENS = (
    "@app/",
    "DashboardOverview",
    "NotificationsCenter",
    "programme-trend-chart",
    "feed-status-chart",
    "logo-quality-chart",
    "channels-epg",
    "match-decisions",
    "logo-assets",
    "component-coverage",
)

HEAVY_DEPENDENCIES = ("apexcharts", "choices.js", "flatpickr")
UNTYPED_DECLARATION_IMPORTS = ("cleave.js", "wnumb", "@hotwired/turbo")
LIGHT_ENTRY_GLOBS = (
    "src/index.ts",
    "src/core/**/*.ts",
    "src/app/**/*.ts",
    "src/dashboard/**/*.ts",
)
REQUIRED_DM_SANS_IMPORTS = tuple(f'@import "@fontsource/dm-sans/latin-{weight}.css";' for weight in (300, 400, 500, 600, 700))
PACK_FILE_ENTRIES = ("bin", "dist", "LICENSE", "README.md", "package.json")
PACK_EXECUTABLE_MEMBERS = frozenset(
    {
        "package/bin/oldman-web-i18n.mjs",
        "package/bin/oldman-web-icons.mjs",
    }
)
NPM_PACK_MTIME = 499_162_500

CLEAN_CONSUMER_COMMANDS = (
    ("pnpm", "install", "--prefer-offline", "--ignore-scripts"),
    ("pnpm", "exec", "tsc", "--noEmit", "--project", "tsconfig.json"),
    ("pnpm", "exec", "vite", "build"),
)

CLEAN_CONSUMER_SOURCE = '''import "./app.css";
import { createDashboardCrudComponentLoaders, DashboardPage, DashboardTopbar } from "oldman-web/dashboard";
import { DashboardFeedback } from "oldman-web/dashboard/feedback";
import { DashboardModal } from "oldman-web/dashboard/modal";
import { Form } from "oldman-web/components/form";
import { Select } from "oldman-web/components/select";
import { Table } from "oldman-web/components/table";

const crudLoaders = createDashboardCrudComponentLoaders({
  feedback: async () => DashboardFeedback,
  form: async () => Form
});
const dashboard = new DashboardPage({
  backToTopOptions: {
    buttonSelector: "[data-consumer-back-to-top]"
  },
  sidebarOptions: {
    defaultSidebarSize: "sm-hover",
    menuPanelSelector: "[data-consumer-menu-panel]"
  }
});

console.info(
  dashboard,
  DashboardTopbar,
  DashboardFeedback,
  DashboardModal,
  Form,
  crudLoaders,
  Table,
  Select
);
'''

CLEAN_CONSUMER_TSCONFIG: dict[str, object] = {
    "compilerOptions": {
        "target": "ES2022",
        "lib": ["ES2022", "DOM", "DOM.Iterable"],
        "module": "ESNext",
        "moduleResolution": "Bundler",
        "strict": True,
        "noEmit": True,
        "noUncheckedIndexedAccess": True,
        "exactOptionalPropertyTypes": True,
        "verbatimModuleSyntax": True,
    },
    "include": ["src/**/*.ts"],
}


def clean_consumer_package(artifact: Path) -> dict[str, object]:
    """Return the manifest for the consumer that can only install the selected tarball."""
    return {
        "name": "oldman-web-consumer-gate",
        "private": True,
        "type": "module",
        "dependencies": {
            "@fontsource/dm-sans": "5.2.7",
            "oldman-web": f"file:{artifact.resolve()}",
        },
        "devDependencies": {
            "@tailwindcss/vite": "4.3.0",
            "tailwindcss": "4.3.0",
            "typescript": "5.7.2",
            "vite": "5.4.21",
        },
    }


def clean_consumer_contract_errors(
    artifact: Path,
    package: Mapping[str, object],
    tsconfig: Mapping[str, object],
    source: str,
    commands: Sequence[Sequence[str]],
) -> list[str]:
    """Reject a consumer fixture that could bypass the packed declaration boundary."""
    errors: list[str] = []
    dependencies = package.get("dependencies")
    selected_dependency = dependencies.get("oldman-web") if isinstance(dependencies, Mapping) else None
    if selected_dependency != f"file:{artifact.resolve()}":
        errors.append("Clean consumer must install oldman-web from the exact selected npm tarball")

    compiler_options = tsconfig.get("compilerOptions")
    if not isinstance(compiler_options, Mapping):
        errors.append("Clean consumer tsconfig must define compilerOptions")
    else:
        for fallback in ("baseUrl", "paths", "rootDirs", "typeRoots"):
            if fallback in compiler_options:
                errors.append(f"Clean consumer tsconfig must not define source fallback {fallback}")
        if compiler_options.get("moduleResolution") != "Bundler" or compiler_options.get("strict") is not True:
            errors.append("Clean consumer tsc gate must use strict Bundler resolution")
    if "extends" in tsconfig:
        errors.append("Clean consumer tsconfig must not extend a workspace configuration")

    required_source_fragments = (
        'new DashboardPage({',
        "backToTopOptions: {",
        'buttonSelector: "[data-consumer-back-to-top]"',
        "sidebarOptions: {",
        'defaultSidebarSize: "sm-hover"',
        'menuPanelSelector: "[data-consumer-menu-panel]"',
    )
    for fragment in required_source_fragments:
        if fragment not in source:
            errors.append(f"Clean consumer declaration probe is missing: {fragment}")
    for fallback in ("frontend/packages/oldman-web", "workspace:", "link:", "oldman-web/src/"):
        if fallback in source:
            errors.append(f"Clean consumer source contains package-source fallback: {fallback}")

    normalized_commands = tuple(tuple(command) for command in commands)
    if normalized_commands != CLEAN_CONSUMER_COMMANDS:
        errors.append("Clean consumer commands must install, run explicit tsc --noEmit, then build with Vite")
    return errors

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, help="Exact Oldman wheel used to verify the shared release version")
    parser.add_argument("--npm-tarball", required=True, help="Exact oldman-web npm tarball")
    parser.add_argument("--evidence-dir", type=Path, help="Persistent, initially empty evidence directory")
    return parser.parse_args(argv)


def resolve_artifact(value: str, *, label: str, suffix: str) -> Path:
    """Resolve one explicit artifact and reject all discovery syntax."""
    if any(character in value for character in "*?[]"):
        raise RuntimeError(f"{label} must be an explicit path, not a glob: {value!r}")
    candidate = Path(value).expanduser()
    if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(suffix):
        raise RuntimeError(f"{label} is not a readable regular {suffix} file: {candidate}")
    return candidate.resolve()


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove every inherited mechanism that can expose repository Python source."""
    environment = dict(os.environ if source is None else source)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["CI"] = "1"
    return environment


def prepare_evidence_directory(requested: Path | None) -> Path:
    if requested is None:
        return Path(tempfile.mkdtemp(prefix="oldman-web-package-evidence-")).resolve()
    evidence_dir = requested.expanduser().resolve()
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise RuntimeError(f"Evidence directory is not empty: {evidence_dir}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(*arguments: str, text: bool = True) -> str | bytes:
    """Run one read-only Git query against the release source root."""
    completed = subprocess.run(
        ("git", "-C", str(ROOT), *arguments),
        check=False,
        capture_output=True,
        text=text,
    )
    if completed.returncode:
        stderr = completed.stderr if text else completed.stderr.decode(errors="replace")
        raise RuntimeError(f"Git source query failed ({' '.join(arguments)}): {stderr.strip()}")
    return completed.stdout


def committed_source_inventory() -> dict[str, object]:
    """Identify the complete committed tree used for the isolated rebuild."""
    revision = git_output("rev-parse", "--verify", "HEAD")
    tree_id = git_output("rev-parse", "--verify", "HEAD^{tree}")
    tree = git_output("ls-tree", "-r", "-z", "--full-tree", "HEAD", text=False)
    if not isinstance(revision, str) or not isinstance(tree, bytes):
        raise RuntimeError("Git source inventory returned an unexpected result type")
    entries = [entry for entry in tree.split(b"\0") if entry]
    if not entries:
        raise RuntimeError("Committed release source inventory is empty")
    if not isinstance(tree_id, str):
        raise RuntimeError("Git tree query returned an unexpected result type")
    return {
        "fileCount": len(entries),
        "revision": revision.strip(),
        "sha256": hashlib.sha256(tree).hexdigest(),
        "tree": tree_id.strip(),
    }


def committed_tree_entries(revision: str) -> dict[str, tuple[str, str]]:
    """Return regular-file mode/object identities for the complete committed tree."""
    tree = git_output("ls-tree", "-r", "-z", "--full-tree", revision, text=False)
    if not isinstance(tree, bytes):
        raise RuntimeError("Git tree query returned an unexpected result type")
    entries: dict[str, tuple[str, str]] = {}
    for entry in (value for value in tree.split(b"\0") if value):
        try:
            header, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(f"Malformed committed tree entry: {entry!r}") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise RuntimeError(f"Unsupported committed build input: {mode} {object_type} {path}")
        entries[path] = (mode, object_id)
    return entries


def verify_checkout_matches_revision(checkout: Path, revision: str) -> None:
    """Reject build-time edits or injected source outside ignored install/build outputs."""
    expected = committed_tree_entries(revision)
    actual: set[str] = set()
    package_dist = Path("frontend/packages/oldman-web/dist")
    package_root = package_dist.parent
    for current_root, directory_names, file_names in os.walk(checkout, followlinks=False):
        current = Path(current_root)
        relative_root = current.relative_to(checkout)
        kept_directories: list[str] = []
        for name in directory_names:
            path = current / name
            relative = relative_root / name
            if name in {".git", "node_modules"} or relative == package_dist:
                continue
            if path.is_symlink():
                actual.add(relative.as_posix())
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in file_names:
            relative = relative_root / name
            if relative.parent == package_root and name.endswith(".tgz"):
                continue
            actual.add(relative.as_posix())
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unexpected = sorted(actual - set(expected))
        raise RuntimeError(f"Frozen rebuild checkout differs from committed tree (missing={missing}, unexpected={unexpected})")

    object_format = git_output("rev-parse", "--show-object-format")
    if not isinstance(object_format, str) or object_format.strip() not in hashlib.algorithms_available:
        raise RuntimeError(f"Unsupported Git object format: {object_format!r}")
    for relative, (mode, object_id) in expected.items():
        path = checkout / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Frozen rebuild input is not a regular file: {relative}")
        payload = path.read_bytes()
        digest = hashlib.new(object_format.strip())
        digest.update(f"blob {len(payload)}\0".encode("ascii"))
        digest.update(payload)
        actual_mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        if digest.hexdigest() != object_id or actual_mode != mode:
            raise RuntimeError(f"Frozen rebuild input bytes or mode differ from committed tree: {relative}")


def isolated_node_environment(root: Path) -> dict[str, str]:
    """Remove inherited Node/package-manager injection and configuration channels."""
    environment = clean_environment()
    for name in tuple(environment):
        lowered = name.lower()
        if lowered.startswith(("npm_config_", "pnpm_", "corepack_", "git_")) or name in {
            "NODE_OPTIONS",
            "NODE_PATH",
        }:
            environment.pop(name, None)
    home = root / "home"
    home.mkdir(exist_ok=True)
    environment.update(
        {
            "COREPACK_HOME": str(home / ".corepack"),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(home),
            "npm_config_userconfig": "/dev/null",
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
        }
    )
    return environment


def frozen_node_toolchain(environment: Mapping[str, str], root_package: Mapping[str, object]) -> dict[str, str]:
    """Validate the external Node/pnpm tools against committed release declarations."""
    package_manager = root_package.get("packageManager")
    if not isinstance(package_manager, str) or not package_manager.startswith("pnpm@"):
        raise RuntimeError("Committed root package.json must pin pnpm with packageManager")
    expected_pnpm = package_manager.removeprefix("pnpm@")
    evidence: dict[str, str] = {}
    for name, command in (("node", ("node", "--version")), ("pnpm", ("pnpm", "--version"))):
        executable = shutil.which(command[0], path=environment.get("PATH"))
        if executable is None:
            raise RuntimeError(f"Frozen rebuild tool is unavailable: {name}")
        completed = subprocess.run(command, env=dict(environment), check=False, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(f"Cannot identify frozen rebuild {name} tool")
        version = completed.stdout.strip()
        evidence[f"{name}Path"] = str(Path(executable).resolve())
        evidence[f"{name}Sha256"] = sha256_file(Path(executable).resolve())
        evidence[f"{name}Version"] = version
    if evidence["pnpmVersion"] != expected_pnpm:
        raise RuntimeError(f"pnpm version does not match committed packageManager: {evidence['pnpmVersion']}")
    node_version = evidence["nodeVersion"].removeprefix("v")
    try:
        node_major = int(node_version.split(".", 1)[0])
    except ValueError as exc:
        raise RuntimeError(f"Cannot parse Node version: {evidence['nodeVersion']}") from exc
    if node_major < 20:
        raise RuntimeError(f"Node version is outside the committed >=20 boundary: {evidence['nodeVersion']}")
    return evidence


def wheel_identity(path: Path) -> dict[str, str]:
    """Require the explicitly selected artifact itself to be the Oldman distribution."""
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise RuntimeError(f"Expected one wheel METADATA file in {path}, found {len(metadata_names)}")
            metadata_text = archive.read(metadata_names[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Cannot read Oldman wheel metadata from {path}: {exc}") from exc
    metadata = Parser().parsestr(metadata_text)
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or name.lower().replace("_", "-") != "oldman":
        raise RuntimeError(f"Selected wheel is not the Oldman distribution: {name!r}")
    if not isinstance(version, str) or not version:
        raise RuntimeError("Selected Oldman wheel has no distribution version")
    return {"name": name, "version": version}


def npm_tarball_identity(path: Path) -> dict[str, str]:
    """Require the explicitly selected tarball itself to be oldman-web."""
    try:
        with tarfile.open(path, "r:gz") as archive:
            member = archive.extractfile("package/package.json")
            if member is None:
                raise RuntimeError(f"npm tarball has no package/package.json: {path}")
            metadata = json.loads(member.read().decode("utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, tarfile.TarError) as exc:
        raise RuntimeError(f"Cannot read oldman-web metadata from {path}: {exc}") from exc
    name = metadata.get("name")
    version = metadata.get("version")
    if name != "oldman-web":
        raise RuntimeError(f"Selected npm tarball is not oldman-web: {name!r}")
    if not isinstance(version, str) or not version:
        raise RuntimeError("Selected oldman-web tarball has no version")
    return {"name": name, "version": version}


def require_matching_artifact_versions(wheel_version: str, npm_version: str) -> None:
    """Require one shared release despite Python's normalized version spelling."""
    try:
        expected_wheel_version = python_distribution_version(npm_version)
    except RuntimeError as exc:
        raise RuntimeError(f"oldman-web artifact has no Python/npm-compatible release version: {npm_version}") from exc
    if wheel_version != expected_wheel_version:
        raise RuntimeError(f"Artifact version mismatch: Oldman {wheel_version} != oldman-web {npm_version}")


def load_package_json() -> dict[str, Any]:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))


def iter_workspace_package_jsons(root: Path = ROOT) -> list[Path]:
    """Return frontend workspace package manifests."""
    return sorted(
        path
        for path in (root / "frontend").rglob("package.json")
        if "node_modules" not in path.parts and "dist" not in path.parts
    )


def export_targets(export_value: Any) -> list[str]:
    if isinstance(export_value, str):
        return [export_value]
    if isinstance(export_value, dict):
        return [value for value in export_value.values() if isinstance(value, str)]
    return []


def iter_export_targets(package_json: Mapping[str, object]) -> list[str]:
    exports = package_json.get("exports", {})
    if not isinstance(exports, dict):
        return []
    targets: list[str] = []
    for value in exports.values():
        targets.extend(export_targets(value))
    return targets


def tailwind_inventory_errors(
    css: str,
    *,
    label: str,
    expected: Sequence[str] | None = None,
) -> list[str]:
    """Require the packed CSS to include every framework Python/Jinja utility."""
    expected = tuple(framework_tailwind_utilities(ROOT) if expected is None else expected)
    if inventory_block(css) is None:
        return [f"{label} has no generated framework Tailwind utility inventory"]
    actual = inventory_utilities(css)
    expected_set = set(expected)
    actual_set = set(actual)
    return [
        f"{label} is missing framework Tailwind utility: {utility}"
        for utility in sorted(expected_set - actual_set)
    ]


def verify_static_package(
    *,
    root: Path = ROOT,
    package_root: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    package_root = root / "frontend" / "packages" / "oldman-web" if package_root is None else package_root
    package_json = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    exports = package_json.get("exports", {})

    if package_json.get("name") != "oldman-web":
        errors.append("frontend/packages/oldman-web/package.json name must be oldman-web")
    if package_json.get("private") is True:
        errors.append("oldman-web must be publishable; private must not be true")
    if package_json.get("engines", {}).get("node") != ">=20":
        errors.append("oldman-web must declare the Node >=20 runtime boundary")
    if package_json.get("peerDependencies", {}).get("tailwindcss") != ">=4.0.0 <5":
        errors.append("oldman-web must declare its Tailwind CSS 4 consumer contract")
    runtime_dependencies = package_json.get("dependencies", {})
    if not isinstance(runtime_dependencies, dict) or "sass" not in runtime_dependencies:
        errors.append("oldman-web must install a Sass implementation for published component SCSS imports")
    if not isinstance(runtime_dependencies, dict) or "typescript" not in runtime_dependencies:
        errors.append("oldman-web i18n extractor is missing its TypeScript runtime dependency")

    side_effects = package_json.get("sideEffects", [])
    if not isinstance(side_effects, list) or not {"./dist/**/*.scss", "./src/**/*.scss"} <= set(side_effects):
        errors.append("oldman-web sideEffects must retain published and workspace component SCSS")

    publishable_package_names: list[str] = []
    for manifest_path in iter_workspace_package_jsons(root):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = manifest.get("name")
        if isinstance(name, str) and manifest.get("private") is not True:
            publishable_package_names.append(name)
    if publishable_package_names != ["oldman-web"]:
        errors.append(f"Frontend workspace must publish exactly oldman-web: {publishable_package_names}")

    for field_name in ("dependencies", "peerDependencies", "devDependencies"):
        dependencies = package_json.get(field_name, {})
        if isinstance(dependencies, dict):
            for name in dependencies:
                if name.startswith("@oldman/") or name.startswith("oldman-"):
                    errors.append(f"oldman-web must not depend on another Oldman frontend package: {name}")

    if not isinstance(exports, dict):
        return errors + ["oldman-web exports must be an object"]

    for export_name in REQUIRED_EXPORTS:
        if export_name not in exports:
            errors.append(f"Missing required export: {export_name}")
    for component in REQUIRED_COMPONENTS:
        export_name = f"./components/{component}"
        if export_name not in exports:
            errors.append(f"Missing component export: {export_name}")

    package_source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (package_root / "src").rglob("*.ts")
    )
    for token in FORBIDDEN_SOURCE_TOKENS:
        if token in package_source:
            errors.append(f"oldman-web source contains forbidden business token: {token}")

    for pattern in LIGHT_ENTRY_GLOBS:
        for path in package_root.glob(pattern):
            source = path.read_text(encoding="utf-8", errors="ignore")
            for token in HEAVY_DEPENDENCIES:
                if token in source:
                    errors.append(f"Light entry {path.relative_to(package_root)} statically references {token}")

    root_source = (package_root / "src" / "index.ts").read_text(encoding="utf-8")
    for forbidden_component in ("./components/apex-chart", "./components/date-time-picker", "./components/select"):
        if forbidden_component in root_source:
            errors.append(f"Root entry must not statically export heavy component: {forbidden_component}")

    shared_css = (package_root / "src" / "styles" / "tailwind.css").read_text(encoding="utf-8")
    for token in ("@theme", ".oldman-sidebar", ".oldman-topbar", ".om-button-primary", ".om-field", ".om-table"):
        if token not in shared_css:
            errors.append(f"Shared Tailwind layer is missing framework style: {token}")
    if '@source "../";' not in shared_css:
        errors.append("Shared Tailwind layer must scan compiled oldman-web runtime JavaScript")
    if "[hidden] {\n    display: none !important;" not in shared_css:
        errors.append("Shared Tailwind layer is missing the source global hidden contract")
    errors.extend(
        tailwind_inventory_errors(
            shared_css,
            label="Shared Tailwind layer",
            expected=framework_tailwind_utilities(root),
        )
    )

    package_bin = package_json.get("bin", {})
    if not isinstance(package_bin, dict) or package_bin.get("oldman-web-icons") != "./bin/oldman-web-icons.mjs":
        errors.append("oldman-web must publish the oldman-web-icons executable")
    if not isinstance(package_bin, dict) or package_bin.get("oldman-web-i18n") != "./bin/oldman-web-i18n.mjs":
        errors.append("oldman-web must publish the oldman-web-i18n executable")
    for dependency in ("@iconify-json/bx", "@iconify-json/mdi", "@iconify-json/ri"):
        if not isinstance(runtime_dependencies, dict) or dependency not in runtime_dependencies:
            errors.append(f"oldman-web icon generator is missing runtime dependency: {dependency}")

    return errors


def expected_pack_files(
    package_json: Mapping[str, object],
    *,
    package_root: Path = PACKAGE_ROOT,
) -> dict[str, Path]:
    """Expand the package allowlist into exact packed member/source pairs."""
    declared = package_json.get("files")
    if not isinstance(declared, list) or not all(isinstance(value, str) for value in declared):
        raise RuntimeError("oldman-web package.json files must be an explicit string list")
    if tuple(declared) != PACK_FILE_ENTRIES:
        raise RuntimeError(
            "oldman-web package.json files must equal the verifier-owned publish roots: "
            f"{list(PACK_FILE_ENTRIES)!r}"
        )

    expected: dict[str, Path] = {}
    for value in PACK_FILE_ENTRIES:
        if any(token in value for token in ("*", "?", "[", "]")):
            raise RuntimeError(f"oldman-web package files entry must not use a glob: {value!r}")
        relative = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != value
        ):
            raise RuntimeError(f"oldman-web package files entry is unsafe: {value!r}")
        source = package_root.joinpath(*relative.parts)
        if source.is_symlink():
            raise RuntimeError(f"oldman-web package allowlist entry is a symlink: {value}")
        if source.is_file():
            expected[f"package/{relative.as_posix()}"] = source
            continue
        if not source.is_dir():
            raise RuntimeError(f"oldman-web package allowlist entry does not exist: {value}")
        for child in sorted(source.rglob("*")):
            if child.is_symlink():
                raise RuntimeError(f"oldman-web package tree contains a symlink: {child.relative_to(package_root)}")
            if child.is_file():
                child_relative = child.relative_to(package_root).as_posix()
                expected[f"package/{child_relative}"] = child
    return expected


def snapshot_expected_pack_files(
    package_json: Mapping[str, object],
    *,
    package_root: Path = PACKAGE_ROOT,
) -> dict[str, bytes]:
    """Freeze the independently rebuilt publish tree before reading the selected tarball."""
    return {
        name: source.read_bytes()
        for name, source in expected_pack_files(package_json, package_root=package_root).items()
    }


def expected_pnpm_packed_package_json(package_json: Mapping[str, object]) -> bytes:
    """Derive the exact package manifest emitted by the frozen pnpm pack command."""
    packed = dict(package_json)
    scripts = packed.pop("scripts", None)
    if scripts is not None:
        if not isinstance(scripts, dict) or not all(
            isinstance(name, str) and isinstance(command, str) for name, command in scripts.items()
        ):
            raise RuntimeError("oldman-web package scripts must be a string mapping")
        packed["scripts"] = {name: command for name, command in scripts.items() if name != "prepack"}
    return json.dumps(packed, ensure_ascii=False, indent=2).encode("utf-8")


def safe_pack_member_errors(member: tarfile.TarInfo) -> list[str]:
    """Reject paths and tar member types outside the npm release-file model."""
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
        or parts[0] != "package"
        or len(parts) < 2
    ):
        errors.append(f"Packed artifact contains unsafe member path: {name!r}")
    if member.type != tarfile.REGTYPE:
        errors.append(f"Packed artifact contains unsafe member type: {name}")
    expected_mode = expected_pack_mode(name)
    if member.mode != expected_mode:
        errors.append(f"Packed artifact member mode differs from the verifier-owned rule: {name}")
    if member.uid != 0 or member.gid != 0 or member.uname != "" or member.gname != "":
        errors.append(f"Packed artifact member has non-canonical ownership metadata: {name}")
    if member.mtime != NPM_PACK_MTIME:
        errors.append(f"Packed artifact member has non-canonical mtime: {name}")
    if member.pax_headers:
        errors.append(f"Packed artifact member has unexpected PAX metadata: {name}")
    if member.linkname or member.devmajor != 0 or member.devminor != 0 or member.sparse is not None:
        errors.append(f"Packed artifact member has unexpected link/device metadata: {name}")
    return errors


def expected_pack_mode(name: str) -> int:
    """Return the verifier-owned npm executable/non-executable mode."""
    return 0o755 if name in PACK_EXECUTABLE_MEMBERS else 0o644


def canonical_npm_gzip_header_errors(path: Path) -> list[str]:
    """Require pnpm/npm's deterministic gzip wrapper metadata."""
    expected = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"
    return [] if path.read_bytes()[:10] == expected else ["Packed artifact has non-canonical gzip header metadata"]


def verify_pack_artifact(
    artifact: Path,
    *,
    expected_payloads: Mapping[str, bytes],
    package_json: Mapping[str, object] | None = None,
    expected_tailwind_utilities: Sequence[str] | None = None,
) -> list[str]:
    errors: list[str] = canonical_npm_gzip_header_errors(artifact)
    package_json = load_package_json() if package_json is None else package_json
    targets = iter_export_targets(package_json)
    declared = package_json.get("files")
    if not isinstance(declared, list) or tuple(declared) != PACK_FILE_ENTRIES:
        return ["Frozen oldman-web package.json files do not match the verifier-owned publish roots"]
    allowed_exact = {"package/LICENSE", "package/README.md", "package/package.json"}
    unexpected_snapshot = [
        name
        for name in expected_payloads
        if name not in allowed_exact and not name.startswith(("package/bin/", "package/dist/"))
    ]
    if unexpected_snapshot:
        return [f"Frozen oldman-web publish snapshot escaped the verifier-owned roots: {unexpected_snapshot}"]

    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        raw_names = [member.name for member in members]
        names = set(raw_names)
        if len(raw_names) != len(names):
            errors.append("Packed artifact contains duplicate archive members")
        for member in members:
            errors.extend(safe_pack_member_errors(member))
        expected_names = set(expected_payloads)
        errors.extend(f"Packed artifact contains unexpected member: {name}" for name in sorted(names - expected_names))
        errors.extend(f"Packed artifact is missing expected member: {name}" for name in sorted(expected_names - names))

        declarations: dict[str, str] = {}
        packed_text: dict[str, str] = {}
        source_maps: dict[str, dict[str, Any]] = {}
        modes = {member.name: member.mode for member in members}
        member_payloads: dict[str, bytes] = {}
        for archive_member in members:
            if not archive_member.isfile():
                continue
            extracted = archive.extractfile(archive_member)
            if extracted is None:
                errors.append(f"Packed artifact member cannot be read: {archive_member.name}")
                continue
            name = archive_member.name
            payload = extracted.read()
            member_payloads[name] = payload
            if name.endswith(".d.ts"):
                declarations[name] = payload.decode("utf-8")
            elif name.endswith((".d.ts.map", ".js.map")):
                source_maps[name] = json.loads(payload.decode("utf-8"))
            elif name.endswith((".css", ".mjs")):
                packed_text[name] = payload.decode("utf-8")

        packed_manifest_payload = member_payloads.get("package/package.json")
        if packed_manifest_payload is not None:
            try:
                expected_manifest_payload = expected_pnpm_packed_package_json(package_json)
            except RuntimeError as exc:
                errors.append(str(exc))
            else:
                if packed_manifest_payload != expected_manifest_payload:
                    errors.append("Packed package.json differs from the frozen pnpm manifest transformation")

        for name in sorted(names & set(expected_payloads)):
            payload = member_payloads.get(name)
            if payload is None:
                continue
            source_payload = expected_payloads[name]
            if payload != source_payload:
                errors.append(f"Packed artifact content differs from package source: {name}")

    required_paths = {
        "package/LICENSE",
        "package/dist/index.js",
        "package/dist/index.d.ts",
        "package/dist/styles/icons.css",
        "package/dist/styles/tailwind.css",
        "package/bin/oldman-web-i18n.mjs",
        "package/bin/oldman-web-icons.mjs",
    }
    for path in required_paths:
        if path not in names:
            errors.append(f"Packed artifact missing required file: {path}")

    if modes.get("package/bin/oldman-web-icons.mjs", 0) & 0o111 == 0:
        errors.append("Packed oldman-web-icons executable is not marked executable")
    if modes.get("package/bin/oldman-web-i18n.mjs", 0) & 0o111 == 0:
        errors.append("Packed oldman-web-i18n executable is not marked executable")
    packed_tailwind = packed_text.get("package/dist/styles/tailwind.css", "")
    if '@source "../";' not in packed_tailwind:
        errors.append("Packed Tailwind CSS does not scan compiled runtime JavaScript")
    if "[hidden] {\n    display: none !important;" not in packed_tailwind:
        errors.append("Packed Tailwind CSS is missing the source global hidden contract")
    errors.extend(
        tailwind_inventory_errors(
            packed_tailwind,
            label="Packed Tailwind CSS",
            expected=expected_tailwind_utilities,
        )
    )
    packed_icons = packed_text.get("package/dist/styles/icons.css", "")
    for framework_icon in (".ri-arrow-up-down-line::before", ".ri-moon-line::before", ".ri-user-settings-line::before"):
        if framework_icon not in packed_icons:
            errors.append(f"Packed framework icon CSS is missing shared icon: {framework_icon}")
    for consumer_icon in (".ri-database-2-line::before",):
        if consumer_icon in packed_icons:
            errors.append(f"Packed framework icon CSS contains consumer-owned icon: {consumer_icon}")

    for target in targets:
        if not target.startswith("./"):
            continue
        packed_path = "package/" + target[2:]
        if packed_path not in names:
            errors.append(f"Export target missing from packed artifact: {target}")

    for name, source in declarations.items():
        for dependency in UNTYPED_DECLARATION_IMPORTS:
            if f'from "{dependency}"' in source or f"from '{dependency}'" in source:
                errors.append(f"Packed declaration leaks untyped dependency {dependency}: {name}")

    if not source_maps:
        errors.append("Packed artifact has no JavaScript or declaration source maps")
    for name, source_map in source_maps.items():
        sources = source_map.get("sources")
        sources_content = source_map.get("sourcesContent")
        if not isinstance(sources, list) or not isinstance(sources_content, list) or len(sources_content) != len(sources):
            errors.append(f"Packed source map does not embed its referenced sources: {name}")
            continue
        if any(not isinstance(content, str) or not content for content in sources_content):
            errors.append(f"Packed source map contains an empty embedded source: {name}")

    forbidden_path_parts = (
        "src/pages/",
        "src/components/dashboard-overview",
        "src/components/notifications-center",
        "apps/admin",
        "apps/epg",
        "templates/pages/",
    )
    for name in names:
        for part in forbidden_path_parts:
            if part in name:
                errors.append(f"Packed artifact contains forbidden app source: {name}")

    return errors


def verify_clean_consumer_build(
    artifact: Path,
    evidence_dir: Path | None = None,
    *,
    expected_tailwind_utilities: Sequence[str] | None = None,
) -> list[str]:
    """Typecheck and build Dashboard APIs solely from the selected tarball."""
    with tempfile.TemporaryDirectory(prefix="oldman-web-consumer-") as temp_dir:
        root = Path(temp_dir)
        environment = isolated_node_environment(root)
        package = clean_consumer_package(artifact)
        errors = clean_consumer_contract_errors(
            artifact,
            package,
            CLEAN_CONSUMER_TSCONFIG,
            CLEAN_CONSUMER_SOURCE,
            CLEAN_CONSUMER_COMMANDS,
        )
        if errors:
            return errors
        (root / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        (root / "tsconfig.json").write_text(
            json.dumps(CLEAN_CONSUMER_TSCONFIG, indent=2) + "\n",
            encoding="utf-8",
        )
        (root / "index.html").write_text('<script type="module" src="/src/main.ts"></script>\n', encoding="utf-8")
        source_dir = root / "src"
        source_dir.mkdir()
        (root / "vite.config.ts").write_text(
            'import tailwindcss from "@tailwindcss/vite";\n'
            'import { defineConfig } from "vite";\n\n'
            "export default defineConfig({ plugins: [tailwindcss()] });\n",
            encoding="utf-8",
        )
        (source_dir / "app.css").write_text(
            '@import "@fontsource/dm-sans/latin-300.css";\n'
            '@import "@fontsource/dm-sans/latin-400.css";\n'
            '@import "@fontsource/dm-sans/latin-500.css";\n'
            '@import "@fontsource/dm-sans/latin-600.css";\n'
            '@import "@fontsource/dm-sans/latin-700.css";\n'
            '@import "tailwindcss";\n'
            '@import "oldman-web/styles/tailwind.css";\n'
            '@import "oldman-web/styles/icons.css";\n'
            '@source "./**/*.ts";\n',
            encoding="utf-8",
        )
        (source_dir / "main.ts").write_text(CLEAN_CONSUMER_SOURCE, encoding="utf-8")

        log_names = (
            "npm-consumer-install.log",
            "npm-consumer-typecheck.log",
            "npm-consumer-build.log",
        )
        for command, log_name in zip(CLEAN_CONSUMER_COMMANDS, log_names, strict=True):
            errors = run_consumer_command(
                root,
                *command,
                environment=environment,
                log_path=evidence_dir / log_name if evidence_dir is not None else None,
            )
            if errors:
                return errors

        built_css = "\n".join(path.read_text(encoding="utf-8") for path in (root / "dist" / "assets").glob("*.css"))
        built_font_names = {path.name for path in (root / "dist" / "assets").glob("*.woff2")}
        required_selectors = (
            ".oldman-sidebar{",
            ".om-modal{",
            ".om-table{",
            ".choices{",
            ".bg-red-600{",
            ".border-red-300{",
            ".line-clamp-2{",
            ".min-h-9{",
            ".min-w-5{",
            ".rounded-lg{",
            ".text-end{",
            "[hidden]{display:none!important}",
        )
        errors = [
            f"Clean Dashboard consumer CSS is missing published runtime selector: {selector}"
            for selector in required_selectors
            if selector not in built_css
        ]
        errors.extend(
            f"Clean Dashboard consumer CSS is missing framework-emitted utility selector: {utility}"
            for utility in (
                framework_tailwind_utilities(ROOT)
                if expected_tailwind_utilities is None
                else expected_tailwind_utilities
            )
            if css_class_selector(utility) not in built_css
        )
        errors.extend(
            f"Clean Dashboard consumer build is missing DM Sans latin {weight} font asset"
            for weight in (300, 400, 500, 600, 700)
            if not any(name.startswith(f"dm-sans-latin-{weight}-normal-") for name in built_font_names)
        )
        return errors


def run_consumer_command(
    cwd: Path,
    *command: str,
    environment: Mapping[str, str] | None = None,
    input_text: str | None = None,
    log_path: Path | None = None,
) -> list[str]:
    """Run an isolated consumer command and return a concise failure."""
    isolated_environment = clean_environment(environment)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=isolated_environment,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"cwd={cwd.resolve()}\ncommand={' '.join(command)}\nreturncode={completed.returncode}\n{output}\n",
            encoding="utf-8",
        )
    if completed.returncode == 0:
        return []
    return [f"Consumer command failed ({' '.join(command)}):\n{output[-6000:]}"]


def rebuild_pack_snapshot(
    evidence_dir: Path,
) -> tuple[dict[str, bytes], dict[str, object], dict[str, object], list[str], tuple[str, ...]]:
    """Rebuild from a fresh clone of the complete committed tree and freeze exact output."""
    source_inventory = committed_source_inventory()
    revision = str(source_inventory["revision"])
    with tempfile.TemporaryDirectory(prefix="oldman-web-frozen-build-", dir=ROOT.parent) as temp_dir:
        temporary = Path(temp_dir)
        clone = temporary / "source"
        environment = isolated_node_environment(temporary)

        def run_frozen_command(command: Sequence[str], cwd: Path, log_name: str, timeout: int) -> None:
            try:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Frozen oldman-web rebuild timed out: {' '.join(command)}") from exc
            output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
            (evidence_dir / log_name).write_text(
                f"cwd={cwd.resolve()}\ncommand={' '.join(command)}\nreturncode={completed.returncode}\n{output}\n",
                encoding="utf-8",
            )
            if completed.returncode:
                raise RuntimeError(f"Frozen oldman-web rebuild failed ({' '.join(command)}):\n{output[-6000:]}")

        run_frozen_command(
            ("git", "clone", "--no-local", "--no-checkout", "--quiet", str(ROOT), str(clone)),
            ROOT,
            "rebuild-clone.log",
            300,
        )
        run_frozen_command(
            ("git", "checkout", "--detach", "--quiet", revision),
            clone,
            "rebuild-checkout.log",
            120,
        )
        verify_checkout_matches_revision(clone, revision)
        root_package = json.loads((clone / "package.json").read_text(encoding="utf-8"))
        if not isinstance(root_package, dict):
            raise RuntimeError("Frozen root package.json is not an object")
        source_inventory["toolchain"] = frozen_node_toolchain(environment, root_package)
        frozen_package_root = clone / "frontend" / "packages" / "oldman-web"
        for command, log_name, timeout in (
            (("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--prefer-offline"), "rebuild-install.log", 1200),
            (("pnpm", "generate:icons"), "rebuild-generate-icons.log", 300),
            (("pnpm", "exec", "tsc", "-p", "tsconfig.build.json"), "rebuild-typescript.log", 600),
            (("node", "scripts/copy-css.mjs"), "rebuild-copy-css.log", 300),
        ):
            cwd = clone if command[1] == "install" else frozen_package_root
            run_frozen_command(command, cwd, log_name, timeout)
        verify_checkout_matches_revision(clone, revision)
        frozen_package_root = clone / "frontend" / "packages" / "oldman-web"
        package_json = json.loads((frozen_package_root / "package.json").read_text(encoding="utf-8"))
        if not isinstance(package_json, dict):
            raise RuntimeError("Frozen oldman-web package.json is not an object")
        source_payloads = snapshot_expected_pack_files(package_json, package_root=frozen_package_root)
        expected_tailwind = framework_tailwind_utilities(clone)
        static_errors = verify_static_package(root=clone, package_root=frozen_package_root)
        pack_destination = temporary / "pack"
        pack_destination.mkdir()
        run_frozen_command(
            ("pnpm", "--config.ignore-scripts=true", "pack", "--pack-destination", str(pack_destination), "--silent"),
            frozen_package_root,
            "rebuild-pack.log",
            300,
        )
        verify_checkout_matches_revision(clone, revision)
        version = package_json.get("version")
        if not isinstance(version, str) or not version:
            raise RuntimeError("Frozen oldman-web package version is missing")
        independent_pack = pack_destination / f"oldman-web-{version}.tgz"
        if independent_pack.is_symlink() or not independent_pack.is_file():
            raise RuntimeError(f"Frozen npm pack did not create its exact artifact: {independent_pack}")
        with tarfile.open(independent_pack, "r:gz") as archive:
            members = archive.getmembers()
            if len({member.name for member in members}) != len(members) or any(
                member.type != tarfile.REGTYPE for member in members
            ):
                raise RuntimeError("Frozen npm pack contains duplicate or non-regular members")
            payloads = {
                member.name: extracted.read()
                for member in members
                if (extracted := archive.extractfile(member)) is not None
            }
        if set(payloads) != set(source_payloads):
            raise RuntimeError("Frozen npm pack member set differs from its rebuilt publish source tree")
        for name, payload in source_payloads.items():
            if name != "package/package.json" and payloads[name] != payload:
                raise RuntimeError(f"Frozen npm pack rewrote an unexpected publish member: {name}")
        packed_package_payload = payloads["package/package.json"]
        packed_package_json = json.loads(packed_package_payload)
        if not isinstance(packed_package_json, dict):
            raise RuntimeError("Frozen packed package.json is not an object")
        if packed_package_payload != expected_pnpm_packed_package_json(package_json):
            raise RuntimeError("Frozen pnpm pack rewrote package.json outside the exact permitted transformation")
        return payloads, source_inventory, package_json, static_errors, expected_tailwind


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence_dir = prepare_evidence_directory(args.evidence_dir)
    started_at = datetime.now(UTC).isoformat()
    try:
        wheel = resolve_artifact(args.wheel, label="Oldman wheel", suffix=".whl")
        npm_tarball = resolve_artifact(args.npm_tarball, label="oldman-web npm tarball", suffix=".tgz")
        distribution = wheel_identity(wheel)
        npm_distribution = npm_tarball_identity(npm_tarball)
        require_matching_artifact_versions(distribution["version"], npm_distribution["version"])
        write_json(
            evidence_dir / "inputs.json",
            {
                "npmTarball": str(npm_tarball),
                "npmTarballDistribution": npm_distribution,
                "npmTarballSha256": sha256_file(npm_tarball),
                "oldmanWheel": str(wheel),
                "oldmanWheelDistribution": distribution,
                "oldmanWheelSha256": sha256_file(wheel),
                "startedAt": started_at,
            },
        )
        expected_payloads, source_inventory, frozen_package_json, static_errors, expected_tailwind = (
            rebuild_pack_snapshot(evidence_dir)
        )
        write_json(evidence_dir / "source-inventory.json", source_inventory)
        errors = static_errors + verify_pack_artifact(
            npm_tarball,
            expected_payloads=expected_payloads,
            package_json=frozen_package_json,
            expected_tailwind_utilities=expected_tailwind,
        )
        if not errors:
            errors.extend(
                verify_clean_consumer_build(
                    npm_tarball,
                    evidence_dir,
                    expected_tailwind_utilities=expected_tailwind,
                )
            )
    except (OSError, RuntimeError) as exc:
        errors = [str(exc)]
    write_json(
        evidence_dir / "result.json",
        {
            "errors": errors,
            "finishedAt": datetime.now(UTC).isoformat(),
            "ok": not errors,
            "startedAt": started_at,
        },
    )
    if errors:
        print("\n".join((*errors, f"Evidence: {evidence_dir}")), file=sys.stderr)
        return 1
    print(f"oldman-web package artifact is valid. Evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
