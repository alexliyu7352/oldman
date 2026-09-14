#!/usr/bin/env python3
"""Install Oldman artifacts in clean environments and exercise public workflows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from packaging.utils import canonicalize_version
from packaging.version import InvalidVersion, Version
from ruamel.yaml import YAML

try:
    from scripts.python_release_inventory import (
        compare_package_inventories,
        inventory_digest,
        wheel_oldman_inventory,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from python_release_inventory import compare_package_inventories, inventory_digest, wheel_oldman_inventory


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, help="Exact wheel path")
    parser.add_argument("--sdist", required=True, help="Exact source distribution path")
    parser.add_argument("--python", dest="pythons", action="append", help="Exact interpreter for an install smoke")
    return parser.parse_args(argv)


def resolve_single_artifact(value: str, label: str, suffix: str) -> Path:
    """Resolve one explicit artifact path without glob or latest-file fallback."""
    if any(character in value for character in "*?[]"):
        raise RuntimeError(f"{label} must be an explicit path, not a glob: {value!r}")
    candidate = Path(value).expanduser()
    if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(suffix):
        raise RuntimeError(f"{label} is not a readable regular {suffix} file: {candidate}")
    return candidate.resolve()


def sdist_distribution_version(sdist: Path) -> str:
    """Read and validate the normalized Oldman version encoded in an sdist name."""
    prefix = "oldman-"
    suffix = ".tar.gz"
    if not sdist.name.startswith(prefix) or not sdist.name.endswith(suffix):
        raise RuntimeError(f"Source distribution has an unexpected release name: {sdist.name}")
    raw_version = sdist.name[len(prefix) : -len(suffix)]
    try:
        return canonicalize_version(Version(raw_version), strip_trailing_zero=False)
    except InvalidVersion as exc:
        raise RuntimeError(f"Source distribution has an invalid release version: {sdist.name}") from exc


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove Python path mechanisms that could leak repository source into probes."""
    environment = dict(os.environ if source is None else source)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        input=input_text,
        text=True,
    )
    if completed.returncode:
        rendered = " ".join(command)
        raise RuntimeError(f"Command failed ({completed.returncode}): {rendered}\n{completed.stdout}\n{completed.stderr}")
    return completed.stdout


def environment_executable(environment_root: Path, name: str) -> Path:
    return environment_root / ("Scripts" if os.name == "nt" else "bin") / name


def package_module_names(files: Mapping[str, str]) -> tuple[str, ...]:
    """Return every importable module represented by the wheel package inventory."""
    modules: set[str] = set()
    names = set(files)
    for value in files:
        path = PurePosixPath(value)
        if path.suffix != ".py":
            continue
        if any(
            PurePosixPath(*path.parts[:depth], "__init__.py").as_posix()
            not in names
            for depth in range(1, len(path.parts))
        ):
            continue
        parts = list(path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            modules.add(".".join(parts))
    return tuple(sorted(modules))


def python_minor(python: Path, *, environment: Mapping[str, str]) -> str:
    """Read the interpreter's actual major/minor instead of trusting its filename."""
    return run(
        (str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"),
        cwd=python.parent,
        environment=environment,
    ).strip()


def configure_probe_settings(config_file: Path, package: str) -> None:
    """Register the generated App and enable Taskiq for the post-bootstrap import probe."""
    yaml = YAML()
    data = yaml.load(config_file.read_text(encoding="utf-8"))
    apps = data.setdefault("apps", [])
    if package not in apps:
        apps.append(package)
    # Importing distributed task declarations requires configured process objects,
    # but does not connect to NATS/Redis until their explicit startup lifecycle.
    data.setdefault("taskiq", {}).update(enabled=True, namespace="installed_probe")
    with config_file.open("w", encoding="utf-8") as stream:
        yaml.dump(data, stream)


def install_and_probe(wheel: Path, *, python_executable: Path, label: str, modules: Sequence[str]) -> str:
    """Install one wheel and exercise CLI, imports, settings and scaffolding."""
    with tempfile.TemporaryDirectory(prefix=f"oldman-{label}-install-") as temporary_directory:
        root = Path(temporary_directory)
        environment_root = root / ".venv"
        environment = clean_environment()
        run(("uv", "venv", str(environment_root), "--python", str(python_executable)), cwd=root, environment=environment)
        python = environment_executable(environment_root, "python")
        oldman = environment_executable(environment_root, "oldman")
        installed_minor = python_minor(python, environment=environment)
        run(
            ("uv", "pip", "install", "--python", str(python), "--strict", str(wheel)),
            cwd=root,
            environment=environment,
        )
        imported_from = run(
            (
                str(python),
                "-c",
                "import pathlib,oldman; "
                "print(pathlib.Path(oldman.__file__).resolve())",
            ),
            cwd=root,
            environment=environment,
        ).strip()
        if not imported_from.startswith(str(environment_root.resolve())):
            raise RuntimeError(f"Installed import escaped the clean environment: {imported_from}")

        project_root = run(
            (
                str(python),
                "-c",
                "from oldman.conf.constants import PROJECT_ROOT; print(PROJECT_ROOT)",
            ),
            cwd=root,
            environment=environment,
        ).strip()
        if Path(project_root).resolve() != root.resolve():
            raise RuntimeError(f"Installed markerless project root escaped the working directory: {project_root}")

        run((str(oldman), "--help"), cwd=root, environment=environment)
        run(
            (str(oldman), "startproject", "installed_probe"),
            cwd=root,
            environment=environment,
            input_text="web\nsqlite\n",
        )
        project = root / "installed_probe"
        run(
            (str(oldman), "startapp", "installed_probe_app"),
            cwd=project,
            environment=environment,
            input_text="web\n\n",
        )
        run(
            (str(oldman), "startservice", "installed_probe_worker"),
            cwd=project,
            environment=environment,
            input_text="simple\n",
        )
        run(
            (str(oldman), "installed_probe_worker", "settings", "init"),
            cwd=project,
            environment=environment,
        )
        configure_probe_settings(project / "data" / "web_settings.yaml", "apps.installed_probe_app")
        run((str(oldman), "web", "settings", "sync"), cwd=project, environment=environment)
        run((str(oldman), "web", "settings", "check"), cwd=project, environment=environment)
        run((str(oldman), "db", "history"), cwd=project, environment=environment)
        encoded_modules = json.dumps(list(modules), separators=(",", ":"))
        run(
            (
                str(python),
                "-c",
                "import importlib,json; "
                "from oldman import bootstrap_service; "
                "from config.schemas import Settings; "
                "context=bootstrap_service('web'); "
                f"modules=json.loads({encoded_modules!r}); "
                "[importlib.import_module(module) for module in modules]; "
                "assert isinstance(context.settings, Settings); print(Settings.__name__)",
            ),
            cwd=project,
            environment=environment,
        )
        return installed_minor


def rebuild_sdist(sdist: Path, output: Path) -> Path:
    """Build a wheel from the published source distribution in isolation."""
    version = sdist_distribution_version(sdist)
    expected_wheel = (output / f"oldman-{version}-py3-none-any.whl").resolve()
    expected_wheel.unlink(missing_ok=True)
    run(
        ("uv", "build", str(sdist), "--wheel", "--out-dir", str(output), "--no-sources"),
        cwd=output,
        environment=clean_environment(),
    )
    if not expected_wheel.is_file():
        raise RuntimeError(f"Source distribution did not rebuild the exact expected wheel: {expected_wheel}")
    return expected_wheel


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    wheel = resolve_single_artifact(args.wheel, "Wheel", ".whl")
    sdist = resolve_single_artifact(args.sdist, "Source distribution", ".tar.gz")
    direct_inventory = wheel_oldman_inventory(wheel)
    modules = package_module_names(direct_inventory)
    if not modules:
        raise RuntimeError("Direct wheel contains no importable oldman modules")
    requested_pythons = args.pythons or [sys.executable]
    interpreters = tuple(dict.fromkeys(Path(value).expanduser().resolve() for value in requested_pythons))
    if not interpreters or any(not path.is_file() for path in interpreters):
        raise RuntimeError("Every --python value must resolve to an existing interpreter")

    installed_versions: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="oldman-sdist-wheel-") as temporary_directory:
        rebuilt_wheel = rebuild_sdist(sdist, Path(temporary_directory))
        rebuilt_inventory = wheel_oldman_inventory(rebuilt_wheel)
        inventory_errors = compare_package_inventories(
            direct_inventory,
            rebuilt_inventory,
            expected_label="direct wheel",
            actual_label="sdist-rebuilt wheel",
        )
        if inventory_errors:
            raise RuntimeError("\n".join(inventory_errors))
        for interpreter in interpreters:
            expected_minor = python_minor(interpreter, environment=clean_environment())
            direct_minor = install_and_probe(
                wheel,
                python_executable=interpreter,
                label=f"wheel-py{expected_minor.replace('.', '')}",
                modules=modules,
            )
            rebuilt_minor = install_and_probe(
                rebuilt_wheel,
                python_executable=interpreter,
                label=f"sdist-py{expected_minor.replace('.', '')}",
                modules=modules,
            )
            if direct_minor != expected_minor or rebuilt_minor != expected_minor:
                raise RuntimeError(
                    f"Install interpreter drifted: requested {expected_minor}, direct={direct_minor}, rebuilt={rebuilt_minor}"
                )
            installed_versions.add(expected_minor)
    versions = ", ".join(sorted(installed_versions))
    print(
        "Oldman direct wheel and sdist-rebuilt wheel have identical package contents "
        f"({len(direct_inventory)} files, sha256={inventory_digest(direct_inventory)}) and passed Python {versions} install probes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
