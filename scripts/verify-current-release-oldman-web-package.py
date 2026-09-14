#!/usr/bin/env python3
"""Build exact current artifacts and run the oldman-web package verifier."""

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
VERIFIER = ROOT / "scripts" / "verify-oldman-web-package.py"
DEFAULT_EVIDENCE_ROOT = Path(tempfile.gettempdir()) / "oldman-web-package-evidence"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--use-existing-artifacts", action="store_true")
    parser.add_argument("--expected-wheel-sha256")
    parser.add_argument("--expected-npm-tarball-sha256")
    return parser.parse_args(argv)


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["CI"] = "1"
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
            wheel.unlink(missing_ok=True)
            npm_tarball.unlink(missing_ok=True)
            for command, log_name in (
                (("pnpm", "build:python"), "build-python.log"),
                (("pnpm", "pack:web"), "pack-web.log"),
            ):
                run(command, cwd=root, environment=environment, log_path=evidence_dir / log_name, timeout=1200)
        for artifact, label in ((wheel, "wheel"), (npm_tarball, "npm tarball")):
            if artifact.is_symlink() or not artifact.is_file():
                raise RuntimeError(f"Current-release {label} was not created at its exact path: {artifact}")
        if args.use_existing_artifacts:
            require_expected_artifact_sha256(wheel, args.expected_wheel_sha256, label="wheel")
            require_expected_artifact_sha256(
                npm_tarball,
                args.expected_npm_tarball_sha256,
                label="npm tarball",
            )
        elif args.expected_wheel_sha256 is not None or args.expected_npm_tarball_sha256 is not None:
            raise RuntimeError("Expected artifact hashes are only valid with --use-existing-artifacts")
        verifier_evidence = evidence_dir / "verifier"
        run(
            (
                sys.executable,
                str(VERIFIER),
                "--wheel",
                str(wheel),
                "--npm-tarball",
                str(npm_tarball),
                "--evidence-dir",
                str(verifier_evidence),
            ),
            cwd=root,
            environment=environment,
            log_path=evidence_dir / "verifier.log",
            timeout=1800,
        )
        result = json.loads((verifier_evidence / "result.json").read_text(encoding="utf-8"))
        if result.get("ok") is not True:
            raise RuntimeError("oldman-web verifier returned without successful evidence")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    write_json(
        evidence_dir / "result.json",
        {
            "errors": errors,
            "finishedAt": datetime.now(UTC).isoformat(),
            "ok": not errors,
            "releaseVersion": version,
            "startedAt": started_at,
            "verifierEvidence": str(evidence_dir / "verifier"),
        },
    )
    if errors:
        print("\n".join((*errors, f"Evidence: {evidence_dir}")), file=sys.stderr)
        return 1
    print(f"Current oldman-web {version} package passed. Evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
