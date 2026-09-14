#!/usr/bin/env python3
"""Build and verify the exact wheel and sdist for the current release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

try:
    from scripts.python_release_inventory import (
        committed_oldman_inventory,
        inventory_json,
        require_clean_oldman_tree,
    )
    from scripts.release_artifacts import (
        authoritative_version,
        python_release_artifact_paths,
        require_expected_artifact_sha256,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from python_release_inventory import committed_oldman_inventory, inventory_json, require_clean_oldman_tree
    from release_artifacts import authoritative_version, python_release_artifact_paths, require_expected_artifact_sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = Path(tempfile.gettempdir()) / "oldman-python-package-evidence"
WHEEL_CONTENTS_VERIFIER = ROOT / "scripts" / "verify-wheel-contents.py"
SDIST_CONTENTS_VERIFIER = ROOT / "scripts" / "verify-sdist-contents.py"
INSTALL_VERIFIER = ROOT / "scripts" / "verify-python-package-install.py"
ADMIN_BROWSER_VERIFIER = ROOT / "scripts" / "verify-installed-wheel-admin-browser.py"
SUPPORTED_PYTHON_MINORS = ("3.12", "3.13", "3.14")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--use-existing-artifacts", action="store_true")
    parser.add_argument("--expected-wheel-sha256")
    parser.add_argument("--expected-sdist-sha256")
    return parser.parse_args(argv)


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["CI"] = "1"
    environment["SOURCE_DATE_EPOCH"] = "1580601600"
    return environment


def create_evidence_directory(parent: Path, version: str) -> Path:
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"oldman-{version}-", dir=parent)).resolve()


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
    timeout: int,
) -> None:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part.decode(errors="replace") if isinstance(part, bytes) else part or ""
            for part in (exc.stdout, exc.stderr)
        ).strip()
        returncode = -1
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"cwd={cwd.resolve()}\ncommand={' '.join(command)}\nreturncode={returncode}\n{output}\n",
        encoding="utf-8",
    )
    if returncode:
        if returncode == -1:
            raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(command)}\n{output[-6000:]}")
        raise RuntimeError(f"Command failed ({returncode}): {' '.join(command)}\n{output[-6000:]}")


def require_built_artifact(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Current-release {label} was not created at its exact path: {path}")


def declared_supported_python_minors(root: Path) -> tuple[str, ...]:
    """Keep the runtime install matrix equal to the public ``requires-python`` range."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project")
        requires_python = project.get("requires-python") if isinstance(project, dict) else None
        if not isinstance(requires_python, str):
            raise RuntimeError("Root pyproject.toml project.requires-python must be a string")
        specifier = SpecifierSet(requires_python)
    except (OSError, tomllib.TOMLDecodeError, InvalidSpecifier) as exc:
        raise RuntimeError(f"Cannot read supported Python range: {exc}") from exc
    declared = tuple(
        f"3.{minor}"
        for minor in range(8, 21)
        if specifier.contains(Version(f"3.{minor}.0"), prereleases=True)
    )
    if declared != SUPPORTED_PYTHON_MINORS:
        raise RuntimeError(
            "Python release gate matrix must be updated with project.requires-python; "
            f"declared={declared}, gate={SUPPORTED_PYTHON_MINORS}"
        )
    return declared


def interpreter_minor(path: Path, *, environment: Mapping[str, str]) -> str:
    completed = subprocess.run(
        (str(path), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"),
        check=False,
        capture_output=True,
        text=True,
        env=dict(environment),
        timeout=30,
    )
    if completed.returncode:
        raise RuntimeError(f"Cannot execute Python interpreter {path}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def resolve_python_interpreters(
    minors: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> dict[str, Path]:
    """Resolve and verify every declared interpreter through uv's managed inventory."""
    interpreters: dict[str, Path] = {}
    for minor in minors:
        configured = environment.get(f"OLDMAN_RELEASE_PYTHON_{minor.replace('.', '_')}")
        if configured:
            candidate = Path(configured).expanduser()
            if candidate.is_symlink() or not candidate.is_file():
                raise RuntimeError(f"Configured Python {minor} interpreter is not a regular file: {candidate}")
            path = candidate.resolve()
        else:
            completed = subprocess.run(
                ("uv", "python", "find", minor),
                cwd=cwd,
                env=dict(environment),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode:
                raise RuntimeError(f"Required Python {minor} interpreter is unavailable: {completed.stderr.strip()}")
            path = Path(completed.stdout.strip()).expanduser().resolve()
            if not path.is_file():
                raise RuntimeError(f"uv returned a missing Python {minor} interpreter: {path}")
        actual_minor = interpreter_minor(path, environment=environment)
        if actual_minor != minor:
            raise RuntimeError(f"uv Python {minor} resolved to Python {actual_minor}: {path}")
        interpreters[minor] = path
    return interpreters


def verification_commands(
    wheel: Path,
    sdist: Path,
    *,
    source_root: Path,
    source_revision: str,
    interpreters: Mapping[str, Path],
) -> tuple[tuple[tuple[str, ...], str, int], ...]:
    """Use only explicit current-release artifact paths in every verifier."""
    source_args = ("--source-root", str(source_root), "--source-revision", source_revision)
    python_args = tuple(value for path in interpreters.values() for value in ("--python", str(path)))
    return (
        ((sys.executable, str(WHEEL_CONTENTS_VERIFIER), *source_args, str(wheel)), "wheel-contents.log", 300),
        ((sys.executable, str(SDIST_CONTENTS_VERIFIER), *source_args, str(sdist)), "sdist-contents.log", 300),
        (
            (
                sys.executable,
                str(INSTALL_VERIFIER),
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                *python_args,
            ),
            "install.log",
            3600,
        ),
        (
            (sys.executable, str(ADMIN_BROWSER_VERIFIER), "--wheel", str(wheel)),
            "admin-browser.log",
            1800,
        ),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        version = authoritative_version(root)
        wheel, sdist = python_release_artifact_paths(root, version)
        require_clean_oldman_tree(root)
        source_inventory = committed_oldman_inventory(root)
        supported_minors = declared_supported_python_minors(root)
        environment = clean_environment()
        interpreters = resolve_python_interpreters(supported_minors, cwd=root, environment=environment)
        evidence_dir = create_evidence_directory(args.evidence_root, version)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    started_at = datetime.now(UTC).isoformat()
    errors: list[str] = []
    write_json(evidence_dir / "source-inventory.json", inventory_json(source_inventory))
    write_json(
        evidence_dir / "inputs.json",
        {
            "oldmanSdist": str(sdist),
            "oldmanSdistExpectedSha256": args.expected_sdist_sha256,
            "oldmanWheel": str(wheel),
            "oldmanWheelExpectedSha256": args.expected_wheel_sha256,
            "pythonInterpreters": {minor: str(path) for minor, path in interpreters.items()},
            "releaseVersion": version,
            "root": str(root),
            "sourceInventory": str(evidence_dir / "source-inventory.json"),
            "sourceInventoryFileCount": len(source_inventory.files),
            "sourceInventorySha256": source_inventory.digest,
            "sourceRevision": source_inventory.revision,
            "startedAt": started_at,
            "useExistingArtifacts": args.use_existing_artifacts,
        },
    )
    artifacts: dict[str, object] = {}
    try:
        if not args.use_existing_artifacts:
            for artifact in (wheel, sdist):
                artifact.unlink(missing_ok=True)
            run(
                ("pnpm", "build:python"),
                cwd=root,
                environment=environment,
                log_path=evidence_dir / "build-python.log",
                timeout=1200,
            )
        require_built_artifact(wheel, label="wheel")
        require_built_artifact(sdist, label="source distribution")
        if args.use_existing_artifacts:
            require_expected_artifact_sha256(wheel, args.expected_wheel_sha256, label="wheel")
            require_expected_artifact_sha256(
                sdist,
                args.expected_sdist_sha256,
                label="source distribution",
            )
        elif args.expected_wheel_sha256 is not None or args.expected_sdist_sha256 is not None:
            raise RuntimeError("Expected artifact hashes are only valid with --use-existing-artifacts")
        artifacts = {
            "sdist": {"path": str(sdist), "sha256": sha256(sdist)},
            "wheel": {"path": str(wheel), "sha256": sha256(wheel)},
        }
        for command, log_name, timeout in verification_commands(
            wheel,
            sdist,
            source_root=root,
            source_revision=source_inventory.revision,
            interpreters=interpreters,
        ):
            run(
                command,
                cwd=root,
                environment=environment,
                log_path=evidence_dir / log_name,
                timeout=timeout,
            )
    except (OSError, RuntimeError) as exc:
        errors.append(str(exc))

    write_json(
        evidence_dir / "result.json",
        {
            "artifacts": artifacts,
            "errors": errors,
            "finishedAt": datetime.now(UTC).isoformat(),
            "ok": not errors,
            "pythonVersions": list(interpreters),
            "releaseVersion": version,
            "sourceInventoryFileCount": len(source_inventory.files),
            "sourceInventorySha256": source_inventory.digest,
            "sourceRevision": source_inventory.revision,
            "startedAt": started_at,
        },
    )
    if errors:
        print("\n".join((*errors, f"Evidence: {evidence_dir}")), file=sys.stderr)
        return 1
    print(f"Current Oldman {version} Python package passed. Evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
