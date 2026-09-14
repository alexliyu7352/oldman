#!/usr/bin/env python3
"""Build current release artifacts and run the installed scaffold matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.release_artifacts import authoritative_version, release_artifact_paths, require_expected_artifact_sha256
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_artifacts import authoritative_version, release_artifact_paths, require_expected_artifact_sha256

ROOT = Path(__file__).resolve().parents[1]
MATRIX_SCRIPT = ROOT / "scripts" / "verify-installed-scaffold-matrix.py"
DEFAULT_EVIDENCE_ROOT = Path(tempfile.gettempdir()) / "oldman-scaffold-matrix-evidence"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT, help="Parent for persistent evidence runs")
    parser.add_argument("--use-existing-artifacts", action="store_true")
    parser.add_argument("--expected-wheel-sha256")
    parser.add_argument("--expected-npm-tarball-sha256")
    return parser.parse_args(argv)


def create_evidence_directory(parent: Path, version: str) -> Path:
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"oldman-{version}-", dir=parent)).resolve()


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["CI"] = "1"
    return environment


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command: Sequence[str], *, cwd: Path, environment: Mapping[str, str], log_path: Path, timeout: int) -> None:
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


def build_commands() -> tuple[tuple[str, ...], ...]:
    """Use existing package gates' build entrypoints without artifact name guessing."""
    return (("pnpm", "build:python"), ("pnpm", "pack:web"))


def require_built_artifact(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Current-release {label} was not created at its exact path: {path}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        version = authoritative_version(root)
        wheel, npm_tarball = release_artifact_paths(root, version)
        evidence_dir = create_evidence_directory(args.evidence_root, version)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    environment = clean_environment()
    started_at = datetime.now(UTC).isoformat()
    errors: list[str] = []
    write_json(
        evidence_dir / "inputs.json",
        {
            "evidenceDirectory": str(evidence_dir),
            "npmTarball": str(npm_tarball),
            "npmTarballExpectedSha256": args.expected_npm_tarball_sha256,
            "oldmanWheel": str(wheel),
            "oldmanWheelExpectedSha256": args.expected_wheel_sha256,
            "releaseVersion": version,
            "useExistingArtifacts": args.use_existing_artifacts,
            "root": str(root),
            "startedAt": started_at,
        },
    )
    try:
        if not args.use_existing_artifacts:
            for artifact in (wheel, npm_tarball):
                artifact.unlink(missing_ok=True)
            for index, command in enumerate(build_commands(), start=1):
                run(
                    command,
                    cwd=root,
                    environment=environment,
                    log_path=evidence_dir / "build" / f"{index}-{'-'.join(command[1:])}.log",
                    timeout=1200,
                )
        require_built_artifact(wheel, label="wheel")
        require_built_artifact(npm_tarball, label="npm tarball")
        if args.use_existing_artifacts:
            require_expected_artifact_sha256(wheel, args.expected_wheel_sha256, label="wheel")
            require_expected_artifact_sha256(
                npm_tarball,
                args.expected_npm_tarball_sha256,
                label="npm tarball",
            )
        elif args.expected_wheel_sha256 is not None or args.expected_npm_tarball_sha256 is not None:
            raise RuntimeError("Expected artifact hashes are only valid with --use-existing-artifacts")
        matrix_evidence = evidence_dir / "matrix"
        run(
            (
                sys.executable,
                str(MATRIX_SCRIPT),
                "--wheel",
                str(wheel),
                "--npm-tarball",
                str(npm_tarball),
                "--evidence-dir",
                str(matrix_evidence),
            ),
            cwd=root,
            environment=environment,
            log_path=evidence_dir / "matrix.log",
            timeout=3600,
        )
        matrix_result = json.loads((matrix_evidence / "result.json").read_text(encoding="utf-8"))
        if matrix_result.get("ok") is not True:
            raise RuntimeError("Installed scaffold matrix returned without successful evidence")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    write_json(
        evidence_dir / "result.json",
        {
            "errors": errors,
            "finishedAt": datetime.now(UTC).isoformat(),
            "matrixEvidence": str(evidence_dir / "matrix"),
            "ok": not errors,
            "releaseVersion": version,
            "startedAt": started_at,
        },
    )
    if errors:
        print("\n".join((*errors, f"Evidence: {evidence_dir}")), file=sys.stderr)
        return 1
    print(f"Current Oldman {version} scaffold matrix passed. Evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
