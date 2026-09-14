#!/usr/bin/env python3
"""Verify every public scaffold/database combination from explicit release artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path

from ruamel.yaml import YAML

try:
    from scripts.release_artifacts import python_distribution_version
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_artifacts import python_distribution_version

try:
    from scripts.linux_process_tree import ProcessTreeError, ProcessTreeTracker, tracked_popen
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from linux_process_tree import ProcessTreeError, ProcessTreeTracker, tracked_popen

try:
    from scripts.browser_cdp import BrowserResult, ChromePage, configure_viewport, navigate, save_screenshot
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from browser_cdp import BrowserResult, ChromePage, configure_viewport, navigate, save_screenshot

MATRIX_CASES = (
    ("cli", "none"),
    ("service", "none"),
    ("api", "postgres"),
    ("web", "mysql"),
    ("dashboard", "sqlite"),
)
PROJECT_SERVICE_NAMES = {
    "service": "service",
    "api": "api",
    "web": "web",
    "dashboard": "dashboard",
}
APP_TYPES = {
    "service": "service",
    "api": "api",
    "web": "web",
    "dashboard": "dashboard",
}
DB_URLS = {
    "none": "",
    "sqlite": "sqlite+aiosqlite:///data/app.db",
    "mysql": "mysql+aiomysql://user:password@127.0.0.1:3306/app",
    "postgres": "postgresql+asyncpg://user:password@127.0.0.1:5432/app",
}
DB_DRIVERS = {"none": None, "sqlite": None, "mysql": "aiomysql", "postgres": "asyncpg"}

INSTALLED_IMPORT_PROBE = (
    "import json,pathlib,sys,oldman; from importlib.metadata import version; "
    "print(json.dumps({'module':str(pathlib.Path(oldman.__file__).resolve()),"
    "'prefix':str(pathlib.Path(sys.prefix).resolve()),'version':version('oldman')}))"
)

DATABASE_PROBE = r'''from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

service_name, database, expected_url = sys.argv[1:]
if not service_name:
    url = ""
else:
    from oldman import bootstrap_service

    context = bootstrap_service(service_name)
    configured_url = context.settings.database.url
    url = "" if configured_url is None else str(configured_url)
    if url != expected_url:
        raise RuntimeError(f"database URL mismatch: expected {expected_url!r}, got {url!r}")


async def probe() -> None:
    if database == "none":
        return
    if database == "mysql":
        import aiomysql  # noqa: F401
    elif database == "postgres":
        import asyncpg  # noqa: F401

    engine = create_async_engine(url)
    try:
        if database == "sqlite":
            async with engine.connect() as connection:
                value = await connection.scalar(text("SELECT 1"))
                if value != 1:
                    raise RuntimeError(f"SQLite SELECT returned {value!r}")
    finally:
        await engine.dispose()


asyncio.run(probe())
print(json.dumps({"database": database, "service": service_name, "url": url}, sort_keys=True))
'''

DASHBOARD_COMPONENT_FIXTURE = '''{% extends "base.html" %}

{% block content %}
  <header id="page-topbar" class="om-card mb-4 flex items-center justify-between p-3">
    <strong>Matrix Topbar</strong>
    <button type="button" class="om-button om-button-light light-dark-mode">Toggle theme</button>
  </header>
  <main class="om-page-section">
    <div class="om-page-header"><h1 class="om-page-title">MatrixProbe</h1></div>

    <section id="matrix-table" class="mt-4" data-om-component="table" data-om-table-page-size="1">
      <div class="om-table-shell">
        <div class="om-table-scroll">
          <table class="om-table min-w-full">
            <thead><tr><th data-om-column="name" data-om-column-searchable="true">Name</th></tr></thead>
            <tbody data-om-table-body>
              <tr data-om-table-row><td data-om-column="name">Alpha row</td></tr>
              <tr data-om-table-row><td data-om-column="name">Beta row</td></tr>
            </tbody>
          </table>
        </div>
        <div class="mt-3 flex items-center gap-3">
          <select data-om-table-page-size-control aria-label="Rows per page"><option value="1">1</option></select>
          <span data-om-table-summary></span>
          <nav data-om-table-pagination aria-label="Table pagination"></nav>
        </div>
      </div>
      <p data-om-table-empty hidden></p>
      <p data-om-table-loading hidden></p>
      <p data-om-table-error hidden></p>
    </section>

    <div id="matrix-select" class="mt-4" data-om-component="select" data-om-select-options='[{"label":"Alpha","value":"alpha"},{"label":"Beta","value":"beta"}]'>
      <label for="matrix-select-control">Matrix Select</label>
      <select id="matrix-select-control" data-om-select-control data-choices data-choices-search-false></select>
    </div>

    <button id="matrix-modal-open" type="button" class="om-button om-button-primary mt-4" data-om-modal-target="#matrix-modal">Open modal</button>
    <section id="matrix-modal" class="om-modal" data-om-component="modal" hidden aria-hidden="true">
      <div class="om-modal-dialog"><div class="om-modal-surface">
        <div class="om-modal-header"><h2 class="om-modal-title" data-om-modal-title>Matrix Modal</h2></div>
        <div class="om-modal-body" data-om-modal-content>Exact tarball modal fixture.</div>
        <div class="om-modal-footer"><button id="matrix-modal-close" type="button" class="om-button om-button-light" data-om-modal-close>Close</button></div>
      </div></div>
    </section>
  </main>
{% endblock %}
'''

DASHBOARD_BROWSER_CONTRACT = r'''(async () => {
  const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const deadline = Date.now() + 15000;
  while (document.documentElement.dataset.omReady !== "true" && Date.now() < deadline) {
    await sleep(50);
  }
  if (document.fonts?.ready) await document.fonts.ready;
  const loaded300 = await document.fonts.load('300 16px "DM Sans"');
  const loaded700 = await document.fonts.load('700 16px "DM Sans"');

  const topbar = document.querySelector("#page-topbar");
  const themeToggle = topbar?.querySelector(".light-dark-mode");
  const themeBefore = document.documentElement.dataset.theme;
  if (themeToggle) themeToggle.click();
  await sleep(50);
  const themeAfter = document.documentElement.dataset.theme;
  if (themeToggle) themeToggle.click();

  const table = document.querySelector("#matrix-table");
  const tableRows = Array.from(table?.querySelectorAll("[data-om-table-row]") ?? []);
  const tablePages = Array.from(table?.querySelectorAll("[data-om-table-page]") ?? []);
  const tableFirstPage = tableRows.length === 2 && !tableRows[0].hidden && tableRows[1].hidden;
  if (tablePages[1]) tablePages[1].click();
  await sleep(50);
  const tableSecondPage = tableRows.length === 2 && tableRows[0].hidden && !tableRows[1].hidden;

  const modal = document.querySelector("#matrix-modal");
  document.querySelector("#matrix-modal-open")?.click();
  await sleep(100);
  const modalOpened = Boolean(
    modal
    && modal.dataset.omState === "open"
    && modal.getAttribute("aria-hidden") === "false"
    && document.querySelector(".om-modal-backdrop")
  );
  document.querySelector("#matrix-modal-close")?.click();
  const modalDeadline = Date.now() + 2000;
  while (modal?.dataset.omState !== "closed" && Date.now() < modalDeadline) await sleep(25);
  const modalClosed = Boolean(
    modal
    && modal.dataset.omState === "closed"
    && modal.getAttribute("aria-hidden") === "true"
    && !document.querySelector(".om-modal-backdrop")
  );

  const selectRoot = document.querySelector("#matrix-select");
  const selectControl = selectRoot?.querySelector("select");
  let selectEventValues = [];
  let nativeSelectChangeCount = 0;
  let oldmanSelectChangeCount = 0;
  selectControl?.addEventListener("change", () => {
    nativeSelectChangeCount += 1;
  });
  selectRoot?.addEventListener("om:select:change", (event) => {
    oldmanSelectChangeCount += 1;
    selectEventValues = Array.from(event.detail?.values ?? []);
  }, { once: true });
  const choicesInner = selectRoot?.querySelector(".choices__inner");
  choicesInner?.click();
  await sleep(50);
  const betaChoice = selectRoot?.querySelector('.choices__item--choice[data-value="beta"]');
  betaChoice?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
  betaChoice?.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, button: 0 }));
  betaChoice?.click();
  await sleep(100);
  const selectChanged = (
    selectControl?.value === "beta"
    && nativeSelectChangeCount === 1
    && oldmanSelectChangeCount === 1
    && selectEventValues.includes("beta")
  );

  const sidebar = document.querySelector(".oldman-sidebar");
  const sidebarLink = sidebar?.querySelector('#navbar-nav a[href="/matrix_probe"]');

  const button = document.querySelector("#back-to-top");
  const spacer = document.createElement("div");
  spacer.dataset.matrixBrowserSpacer = "true";
  spacer.style.height = "3000px";
  document.body.append(spacer);
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
  await sleep(250);
  const scrollBeforeClick = window.scrollY;
  const topbarShadowed = Boolean(topbar?.classList.contains("topbar-shadow"));
  const buttonVisible = Boolean(
    button
    && !button.hidden
    && getComputedStyle(button).display !== "none"
    && button.getBoundingClientRect().width > 0
  );
  if (button) button.click();
  const scrollDeadline = Date.now() + 3000;
  while (window.scrollY > 1 && Date.now() < scrollDeadline) {
    await sleep(25);
  }
  const scrollAfterClick = window.scrollY;
  spacer.remove();
  return {
    backToTop: {
      clickedToTop: scrollBeforeClick > 100 && scrollAfterClick <= 1,
      exists: Boolean(button),
      scrollAfterClick,
      scrollBeforeClick,
      visible: buttonVisible
    },
    bodyFontFamily: getComputedStyle(document.body).fontFamily,
    components: {
      modal: { closed: modalClosed, mounted: modal?.dataset.omComponentState === "mounted", opened: modalOpened },
      select: {
        changed: selectChanged,
        choiceExists: Boolean(betaChoice),
        choicesMounted: Boolean(selectRoot?.querySelector(".choices")),
        eventValues: selectEventValues,
        mounted: selectRoot?.dataset.omComponentState === "mounted",
        nativeChangeCount: nativeSelectChangeCount,
        oldmanChangeCount: oldmanSelectChangeCount,
        value: selectControl?.value ?? ""
      },
      sidebar: {
        active: Boolean(sidebarLink?.classList.contains("active")),
        exists: Boolean(sidebar),
        mounted: sidebar?.dataset.omComponentState === "mounted"
      },
      table: {
        firstPage: tableFirstPage,
        mounted: table?.dataset.omComponentState === "mounted",
        pageCount: tablePages.length,
        paginationShell: Boolean(table?.querySelector("[data-om-table-pagination]")),
        secondPage: tableSecondPage,
        summary: table?.querySelector("[data-om-table-summary]")?.textContent?.trim() ?? ""
      },
      topbar: {
        exists: Boolean(topbar),
        shadowed: topbarShadowed,
        themeToggled: Boolean(themeBefore && themeAfter && themeBefore !== themeAfter)
      }
    },
    dmSansLoaded: document.fonts.check('16px "DM Sans"'),
    dmSansWeightsLoaded: { "300": loaded300.length > 0, "700": loaded700.length > 0 },
    heading: document.querySelector("h1")?.textContent?.trim() ?? "",
    location: window.location.href,
    ready: document.documentElement.dataset.omReady ?? "",
    resourceUrls: performance.getEntriesByType("resource").map((entry) => entry.name),
    scriptUrls: Array.from(document.querySelectorAll("script[src]"), (node) => node.src),
    styleUrls: Array.from(document.querySelectorAll('link[rel="stylesheet"][href]'), (node) => node.href)
  };
})()'''


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, help="Exact Oldman wheel path")
    parser.add_argument("--npm-tarball", required=True, help="Exact oldman-web npm tarball path")
    parser.add_argument("--evidence-dir", required=True, type=Path, help="Persistent, initially empty evidence directory")
    return parser.parse_args(argv)


def matrix_cases() -> tuple[tuple[str, str], ...]:
    """Return the representative installed-consumer scenarios in execution order."""
    return MATRIX_CASES


def resolve_artifact(value: str, *, label: str, suffix: str) -> Path:
    """Resolve one explicit artifact path without latest-file or glob fallback."""
    if any(character in value for character in "*?[]"):
        raise RuntimeError(f"{label} must be an explicit path, not a glob: {value!r}")
    candidate = Path(value).expanduser()
    if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(suffix):
        raise RuntimeError(f"{label} is not a readable regular {suffix} file: {candidate}")
    return candidate.resolve()


def prepare_evidence_directory(requested: Path) -> Path:
    evidence_dir = requested.expanduser().resolve()
    if evidence_dir.exists() and not evidence_dir.is_dir():
        raise RuntimeError(f"Evidence path is not a directory: {evidence_dir}")
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise RuntimeError(f"Evidence directory is not empty: {evidence_dir}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove inherited Python and uv paths that could expose repository source."""
    environment = dict(os.environ if source is None else source)
    for name in ("PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["CI"] = "1"
    return environment


def environment_executable(environment_root: Path, name: str) -> Path:
    return environment_root / ("Scripts" if os.name == "nt" else "bin") / name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_npm_tree_evidence(package_root: Path, npm_tarball: Path) -> dict[str, object]:
    """Bind every installed oldman-web file to the exact selected tarball payload."""
    with tarfile.open(npm_tarball, "r:gz") as archive:
        members = archive.getmembers()
        if len({member.name for member in members}) != len(members) or any(
            member.type != tarfile.REGTYPE or not member.name.startswith("package/") for member in members
        ):
            raise RuntimeError("selected oldman-web tarball has duplicate, unsafe, or non-package members")
        expected = {
            member.name.removeprefix("package/"): {
                "mode": member.mode,
                "sha256": hashlib.sha256(extracted.read()).hexdigest(),
            }
            for member in members
            if (extracted := archive.extractfile(member)) is not None
        }
    invalid_archive_modes = sorted(
        name for name, record in expected.items() if record["mode"] not in {0o644, 0o755}
    )
    if invalid_archive_modes:
        raise RuntimeError(f"selected oldman-web tarball contains unsafe modes: {invalid_archive_modes}")
    package_manager_root = package_root / "node_modules"
    if package_manager_root.exists() and (package_manager_root.is_symlink() or not package_manager_root.is_dir()):
        raise RuntimeError("installed oldman-web package-manager node_modules is not a regular directory")
    actual: dict[str, dict[str, object]] = {}
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        if relative.parts and relative.parts[0] == "node_modules":
            continue
        if path.is_symlink():
            raise RuntimeError(f"installed oldman-web contains an unexpected symlink: {path}")
        if not path.is_file():
            continue
        actual[relative.as_posix()] = {
            "mode": stat.S_IMODE(path.stat().st_mode),
            "sha256": sha256_file(path),
        }
    mode_errors = sorted(
        name
        for name in set(actual) & set(expected)
        if actual[name]["mode"] not in ({0o644, 0o664} if expected[name]["mode"] == 0o644 else {0o755})
    )
    content_errors = sorted(
        name
        for name in set(actual) & set(expected)
        if actual[name]["sha256"] != expected[name]["sha256"]
    )
    if set(actual) != set(expected) or mode_errors or content_errors:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise RuntimeError(
            "installed oldman-web tree differs from selected tarball "
            f"(missing={missing}, unexpected={unexpected}, content={content_errors}, mode={mode_errors})"
        )
    canonical = json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
    return {
        "excludedPackageManagerRoots": ["node_modules"],
        "fileCount": len(actual),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def pnpm_tarball_lock_evidence(lock_path: Path, npm_tarball: Path) -> dict[str, str]:
    """Bind one importer, package resolution, and snapshot to the same npm tarball."""
    try:
        lock = YAML(typ="safe").load(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot parse generated pnpm lockfile: {exc}") from exc
    if not isinstance(lock, dict) or str(lock.get("lockfileVersion")) != "9.0":
        raise RuntimeError("generated pnpm lockfile must use the reviewed version 9.0 schema")

    relative_tarball = Path(os.path.relpath(npm_tarball, lock_path.parent)).as_posix()
    locked_tarball = f"file:{relative_tarball}"
    declared_tarball = f"file:{npm_tarball}"
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(npm_tarball.read_bytes()).digest()).decode("ascii")

    importers = lock.get("importers")
    importer = importers.get(".") if isinstance(importers, dict) else None
    dependencies = importer.get("dependencies") if isinstance(importer, dict) else None
    dependency = dependencies.get("oldman-web") if isinstance(dependencies, dict) else None
    version = dependency.get("version") if isinstance(dependency, dict) else None
    if (
        not isinstance(dependency, dict)
        or dependency.get("specifier") != declared_tarball
        or not isinstance(version, str)
        or not (version == locked_tarball or version.startswith(f"{locked_tarball}("))
    ):
        raise RuntimeError("pnpm importer does not bind oldman-web to the exact selected tarball")

    packages = lock.get("packages")
    package_matches = {
        key: value
        for key, value in packages.items()
        if isinstance(packages, dict) and isinstance(key, str) and key.startswith("oldman-web@")
    } if isinstance(packages, dict) else {}
    package_key = f"oldman-web@{locked_tarball}"
    if set(package_matches) != {package_key}:
        raise RuntimeError(f"pnpm lockfile has an ambiguous oldman-web package resolution: {sorted(package_matches)}")
    package_record = package_matches[package_key]
    if not isinstance(package_record, dict) or package_record.get("resolution") != {
        "integrity": integrity,
        "tarball": locked_tarball,
    }:
        raise RuntimeError("pnpm oldman-web resolution does not bind tarball and integrity together")

    snapshots = lock.get("snapshots")
    snapshot_matches = [
        key
        for key in snapshots
        if isinstance(snapshots, dict) and isinstance(key, str) and key.startswith("oldman-web@")
    ] if isinstance(snapshots, dict) else []
    snapshot_key = f"oldman-web@{version}"
    if snapshot_matches != [snapshot_key]:
        raise RuntimeError(f"pnpm lockfile has an ambiguous oldman-web snapshot: {snapshot_matches}")
    return {
        "integrity": integrity,
        "packageKey": package_key,
        "snapshotKey": snapshot_key,
        "specifier": declared_tarball,
        "tarball": locked_tarball,
    }


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_service_settings(
    config_file: Path,
    *,
    install_app: str | None = None,
    listen_port: int | None = None,
) -> None:
    """Apply gate-only App or listener values to one generated YAML file."""
    yaml = YAML()
    data = yaml.load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Generated settings are not a YAML mapping: {config_file}")
    if install_app is not None:
        apps = data.setdefault("apps", [])
        if not isinstance(apps, list):
            raise RuntimeError(f"Generated settings.apps is not a list: {config_file}")
        if install_app not in apps:
            apps.append(install_app)
    if listen_port is not None:
        web = data.setdefault("web", {})
        if not isinstance(web, dict):
            raise RuntimeError(f"Generated settings.web is not a mapping: {config_file}")
        web.update(
            {
                "access_log": False,
                "auto_reload": False,
                "debug": False,
                "listen_host": "127.0.0.1",
                "listen_port": listen_port,
                "workers": 1,
            }
        )
    with config_file.open("w", encoding="utf-8") as stream:
        yaml.dump(data, stream)


def preserve_evidence_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Cannot preserve missing evidence file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def prepare_wheel_index(root: Path, wheel: Path) -> Path:
    """Expose only the selected Oldman wheel through a highest-priority local index."""
    index_root = root / "wheel-index"
    package_root = index_root / "oldman"
    package_root.mkdir(parents=True)
    indexed_wheel = package_root / wheel.name
    try:
        os.link(wheel, indexed_wheel)
    except OSError:
        shutil.copy2(wheel, indexed_wheel)
    digest = sha256_file(indexed_wheel)
    package_root.joinpath("index.html").write_text(
        f'<a href="{urllib.parse.quote(indexed_wheel.name)}#sha256={digest}">{indexed_wheel.name}</a>\n',
        encoding="utf-8",
    )
    return index_root.resolve()


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
    timeout: int = 300,
    input_text: str | None = None,
) -> str:
    """Run one probe command and persist its exact cwd, return code and output."""
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            input=input_text,
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
    return completed.stdout


def run_tty(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
    input_text: str,
    timeout: int = 300,
) -> str:
    """Run one intentionally interactive migration command in a real POSIX TTY."""
    master, slave = pty.openpty()
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        os.write(master, input_text.encode())
        while process.poll() is None or select.select((master,), (), (), 0)[0]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(command)}")
            readable, _, _ = select.select((master,), (), (), min(0.1, remaining))
            if not readable:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
    finally:
        os.close(master)
    returncode = process.wait()
    rendered_output = output.decode(errors="replace")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"cwd={cwd.resolve()}\ncommand={' '.join(command)}\nreturncode={returncode}\n{rendered_output}\n",
        encoding="utf-8",
    )
    if returncode:
        raise RuntimeError(f"Command failed ({returncode}): {' '.join(command)}\n{rendered_output[-6000:]}")
    return rendered_output


def installed_import_provenance(
    python: Path,
    environment_root: Path,
    *,
    expected_version: str,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
) -> dict[str, str]:
    """Prove a project-cwd import still resolves to the exact installed wheel environment."""
    imported = run(
        (str(python), "-c", INSTALLED_IMPORT_PROBE),
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    ).strip()
    return validate_import_provenance(imported, environment_root, expected_version=expected_version)


def validate_import_provenance(imported: str, environment_root: Path, *, expected_version: str) -> dict[str, str]:
    try:
        raw = json.loads(imported)
        provenance = {name: raw[name] for name in ("module", "prefix", "version")}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Installed Oldman import evidence is malformed: {exc}") from exc
    if not all(isinstance(value, str) for value in provenance.values()):
        raise RuntimeError(f"Installed Oldman import evidence has non-string fields: {provenance}")
    prefix = Path(provenance["prefix"]).resolve()
    module = Path(provenance["module"]).resolve()
    if prefix != environment_root.resolve() or not module.is_relative_to(prefix):
        raise RuntimeError(f"Installed Oldman import escaped the isolated environment: {provenance}")
    if provenance["version"] != expected_version:
        raise RuntimeError(f"Installed Oldman version changed inside the scaffold environment: {provenance}")
    return provenance


def uv_run_import_provenance(
    project: Path,
    environment_root: Path,
    *,
    wheel_index: Path,
    expected_version: str,
    environment: Mapping[str, str],
    log_path: Path,
) -> dict[str, str]:
    """Exercise plain ``uv run`` against the generated project's local environment."""
    run_environment = dict(environment)
    run_environment.pop("VIRTUAL_ENV", None)
    run_environment.pop("UV_PROJECT_ENVIRONMENT", None)
    inherited_indexes = run_environment.get("UV_INDEX", "").strip()
    run_environment["UV_INDEX"] = " ".join(filter(None, (str(wheel_index.resolve()), inherited_indexes)))
    imported = run(
        ("uv", "run", "python", "-c", INSTALLED_IMPORT_PROBE),
        cwd=project,
        environment=run_environment,
        log_path=log_path,
    ).strip()
    return validate_import_provenance(imported, environment_root, expected_version=expected_version)


def environment_package_state(
    python: Path,
    *,
    database: str,
    expected_version: str,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
) -> dict[str, str | None]:
    """Require one case-local environment to contain only its declared runtime packages."""
    output = run(
        (
            str(python),
            "-c",
            "import json; from importlib.metadata import PackageNotFoundError,version; "
            "names=('oldman','aiosqlite','aiomysql','asyncpg','pyright'); values={}; "
            "exec(\"for name in names:\\n try: values[name]=version(name)\\n except PackageNotFoundError: values[name]=None\"); "
            "print(json.dumps(values,sort_keys=True))",
        ),
        cwd=cwd,
        environment=environment,
        log_path=log_path,
    ).strip()
    try:
        packages = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Database environment package evidence is malformed: {exc}") from exc
    if packages.get("oldman") != expected_version:
        raise RuntimeError(f"database={database} environment does not contain the exact Oldman wheel: {packages}")
    if not packages.get("aiosqlite"):
        raise RuntimeError(f"database={database} environment is missing the default SQLite driver: {packages}")
    if packages.get("pyright") is not None:
        raise RuntimeError(f"database={database} plain uv sync retained an undeclared Pyright package: {packages}")
    expected_driver = DB_DRIVERS[database]
    for driver in ("aiomysql", "asyncpg"):
        expected = driver == expected_driver
        if bool(packages.get(driver)) is not expected:
            raise RuntimeError(f"database={database} optional driver isolation failed: {packages}")
    return {
        "aiomysql": packages.get("aiomysql"),
        "aiosqlite": packages.get("aiosqlite"),
        "asyncpg": packages.get("asyncpg"),
        "oldman": packages.get("oldman"),
        "pyright": packages.get("pyright"),
    }


def sync_generated_project(
    project: Path,
    *,
    wheel_index: Path,
    expected_version: str,
    environment: Mapping[str, str],
    log_path: Path,
) -> dict[str, object]:
    """Run plain project-local ``uv sync`` and validate the IDE-standard ``.venv``."""
    sync_environment = dict(environment)
    sync_environment.pop("VIRTUAL_ENV", None)
    sync_environment.pop("UV_PROJECT_ENVIRONMENT", None)
    sync_environment["UV_PYTHON"] = sys.executable
    inherited_indexes = sync_environment.get("UV_INDEX", "").strip()
    sync_environment["UV_INDEX"] = " ".join(filter(None, (str(wheel_index.resolve()), inherited_indexes)))
    run(
        ("uv", "sync"),
        cwd=project,
        environment=sync_environment,
        log_path=log_path,
        timeout=600,
    )
    environment_root = project / ".venv"
    python = environment_executable(environment_root, "python")
    if environment_root.is_symlink() or not environment_root.is_dir():
        raise RuntimeError(f"uv sync did not create a project-local .venv for {project.name}")
    if not (environment_root / "pyvenv.cfg").is_file() or not python.is_file():
        raise RuntimeError(f"uv sync created an incomplete IDE environment for {project.name}: {environment_root}")
    lock_path = project / "uv.lock"
    if not lock_path.is_file():
        raise RuntimeError(f"uv sync did not create a lockfile for {project.name}")
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    locked_oldman = [package for package in lock.get("package", []) if package.get("name") == "oldman"]
    if len(locked_oldman) != 1 or locked_oldman[0].get("version") != expected_version:
        raise RuntimeError(f"uv sync did not resolve the selected Oldman release for {project.name}: {locked_oldman}")
    indexed_wheels = sorted((wheel_index / "oldman").glob("*.whl"))
    if len(indexed_wheels) != 1:
        raise RuntimeError(f"local Oldman wheel index is not closed: {indexed_wheels}")
    indexed_wheel = indexed_wheels[0]
    expected_registry = Path(os.path.relpath(wheel_index, project)).as_posix()
    expected_wheels = [
        {
            "path": f"oldman/{indexed_wheel.name}",
            "hash": f"sha256:{sha256_file(indexed_wheel)}",
        }
    ]
    if locked_oldman[0].get("source") != {"registry": expected_registry}:
        raise RuntimeError(f"uv.lock Oldman source is not the explicit local wheel index: {locked_oldman[0].get('source')}")
    if locked_oldman[0].get("wheels") != expected_wheels or "sdist" in locked_oldman[0]:
        raise RuntimeError(f"uv.lock Oldman artifact is not the exact selected wheel: {locked_oldman[0].get('wheels')}")
    evidence_lock = log_path.parent / "uv.lock"
    evidence_lock.parent.mkdir(parents=True, exist_ok=True)
    evidence_lock.write_bytes(lock_path.read_bytes())
    ide_python = environment_executable(environment_root.resolve(), "python")
    return {
        "environment": str(environment_root.resolve()),
        "interpreter": str(ide_python),
        "path": str(evidence_lock.resolve()),
        "projectLocal": True,
        "registry": expected_registry,
        "sha256": sha256_file(lock_path),
        "version": expected_version,
        "wheel": expected_wheels[0],
    }


def install_dashboard_component_fixture(project: Path) -> Path:
    """Turn the generated app page into an exact-tarball browser component fixture."""
    template = project / "templates" / "matrix_probe" / "index.html"
    if not template.is_file():
        raise RuntimeError(f"Generated Dashboard app template is missing: {template}")
    template.write_text(DASHBOARD_COMPONENT_FIXTURE, encoding="utf-8")
    return template


def reserve_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def tcp_port_is_open(host: str, port: int) -> bool:
    """Return whether a TCP listener currently owns the selected address."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex((host, port)) == 0


def process_group_exists(process_group: int) -> bool:
    """Return whether any process remains in an owned POSIX process group."""
    if os.name != "posix":  # pragma: no cover - current release scope is Linux
        return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def http_response_contract_errors(
    project_type: str,
    *,
    status: int,
    body: bytes,
    content_type: str,
) -> list[str]:
    """Validate the generated route's status, media type, and semantic payload."""
    errors: list[str] = []
    normalized_content_type = content_type.partition(";")[0].strip().lower()
    if status != 200:
        errors.append(f"server returned HTTP {status}")
    if not body:
        errors.append("server returned an empty response body")
        return errors
    if project_type == "api":
        if normalized_content_type != "application/json":
            errors.append(f"API response has unexpected Content-Type {content_type!r}")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"API response is not valid JSON: {exc}")
        else:
            if payload != {"name": "matrix_probe", "status": "ok"}:
                errors.append(f"API response payload does not match the generated route: {payload!r}")
        return errors
    if normalized_content_type != "text/html":
        errors.append(f"{project_type} response has unexpected Content-Type {content_type!r}")
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{project_type} response is not UTF-8 HTML: {exc}")
        return errors
    expected_tokens = {
        "web": ("<h1>MatrixProbe</h1>",),
        "dashboard": (
            "MatrixProbe",
            'data-om-component="sidebar-menu"',
            'data-om-component="table"',
            'data-om-component="modal"',
            'data-om-component="select"',
        ),
    }.get(project_type)
    if expected_tokens is None:
        errors.append(f"HTTP response contract is undefined for project type {project_type!r}")
    else:
        missing = [token for token in expected_tokens if token not in html]
        if missing:
            errors.append(f"{project_type} response is missing generated-route markers: {missing}")
    return errors


def read_http_probe_response(
    opener: urllib.request.OpenerDirector,
    url: str,
    project_type: str,
) -> tuple[int, bytes, str, list[str]]:
    """Read a complete response before publishing its HTTP status as readiness."""
    with opener.open(url, timeout=1) as response:
        body = response.read()
        status = int(response.status)
        content_type = str(response.headers.get("Content-Type", ""))
    errors = http_response_contract_errors(
        project_type,
        status=status,
        body=body,
        content_type=content_type,
    )
    return status, body, content_type, errors


def settle_http_probe_process(
    process: subprocess.Popen[str],
    *,
    timeout: float = 0.25,
) -> str:
    """Wait through Sanic's post-readiness worker-ACK window without hiding an early exit."""
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    return f"server exited during the post-readiness settle window with code {returncode}"


def stop_http_probe_process(
    process: subprocess.Popen[str],
    *,
    host: str,
    port: int,
    process_tree: ProcessTreeTracker | None = None,
) -> tuple[str, str, list[str], bool]:
    """Stop the server through its leader, then prove its group and port are gone."""
    cleanup_errors: list[str] = []
    process_group = process.pid
    shutdown_initiated = False
    leader_running = process.poll() is None
    if process_tree is not None:
        if not leader_running:
            cleanup_errors.append(
                f"server leader exited before gate-initiated shutdown with code {process.returncode}"
            )
        try:
            process_tree.terminate(
                process,
                require_live_leader=leader_running,
                term_timeout=15,
                kill_timeout=5,
            )
        except ProcessTreeError as exc:
            cleanup_errors.append(str(exc))
        else:
            shutdown_initiated = leader_running
    elif leader_running:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        else:
            shutdown_initiated = True
    try:
        stdout, stderr = process.communicate(timeout=1 if process_tree is not None else 15)
    except subprocess.TimeoutExpired:
        cleanup_errors.append("server leader did not stop gracefully after SIGTERM")
        if os.name == "posix":
            try:
                os.killpg(process_group, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:  # pragma: no cover - current release scope is Linux
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            cleanup_errors.append("server process group required SIGKILL")
            if os.name == "posix":
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:  # pragma: no cover - current release scope is Linux
                process.kill()
            stdout, stderr = process.communicate(timeout=5)

    group_deadline = time.monotonic() + 2
    while process_group_exists(process_group) and time.monotonic() < group_deadline:
        time.sleep(0.05)
    if process_group_exists(process_group):
        cleanup_errors.append(f"owned server process group {process_group} remains after shutdown")
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        kill_deadline = time.monotonic() + 2
        while process_group_exists(process_group) and time.monotonic() < kill_deadline:
            time.sleep(0.05)
        if process_group_exists(process_group):
            cleanup_errors.append(f"owned server process group {process_group} survived SIGKILL")
    deadline = time.monotonic() + 2
    while tcp_port_is_open(host, port) and time.monotonic() < deadline:
        time.sleep(0.05)
    if tcp_port_is_open(host, port):
        cleanup_errors.append(f"owned server port {host}:{port} remains open after shutdown")
    return stdout, stderr, cleanup_errors, shutdown_initiated


def http_probe_outcome_errors(
    *,
    status: int | None,
    returncode: int | None,
    stdout: str,
    stderr: str,
    response_errors: Sequence[str],
    shutdown_initiated: bool,
    cleanup_errors: Sequence[str],
) -> list[str]:
    """Turn readiness, lifecycle, and output evidence into fail-closed errors."""
    errors = list(cleanup_errors)
    if status != 200:
        errors.append(f"server never returned HTTP 200 (status={status!r})")
    errors.extend(response_errors)
    if status == 200 and not shutdown_initiated:
        errors.append("server exited after HTTP 200 before the gate initiated shutdown")
    if returncode != 0:
        errors.append(f"server exited with non-zero return code {returncode!r}")
    combined = f"{stdout}\n{stderr}"
    error_pattern = re.compile(r"(?im)(?:\[ERROR\]|\bERROR\b|Traceback \(most recent call last\)|Unhandled exception)")
    if error_pattern.search(combined):
        errors.append("server output contains an ERROR, traceback, or unhandled exception")
    return errors


def browser_asset_evidence(project: Path, base_url: str, urls: object, *, label: str) -> list[dict[str, str]]:
    """Map every browser-observed bundle URL back to a generated static/dist file."""
    if not isinstance(urls, list) or not urls or any(not isinstance(url, str) for url in urls):
        raise RuntimeError(f"Dashboard browser did not expose any valid {label} URLs: {urls!r}")
    expected_origin = urllib.parse.urlsplit(base_url)
    static_root = (project / "static" / "dist").resolve()
    evidence: list[dict[str, str]] = []
    for url in urls:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme, parsed.netloc) != (expected_origin.scheme, expected_origin.netloc):
            raise RuntimeError(f"Dashboard {label} escaped the generated server origin: {url}")
        prefix = "/static/dist/"
        if not parsed.path.startswith(prefix):
            raise RuntimeError(f"Dashboard {label} did not come from generated static/dist: {url}")
        relative = Path(urllib.parse.unquote(parsed.path.removeprefix(prefix)))
        artifact = (static_root / relative).resolve()
        if not artifact.is_relative_to(static_root) or not artifact.is_file():
            raise RuntimeError(f"Dashboard {label} URL has no generated build artifact: {url} -> {artifact}")
        evidence.append({"path": str(artifact), "sha256": sha256_file(artifact), "url": url})
    return evidence


def run_dashboard_browser_probe(
    project: Path,
    url: str,
    *,
    evidence_dir: Path,
    package_provenance: Mapping[str, object],
) -> dict[str, object]:
    """Require the exact-tarball Dashboard to initialize in a real Chrome page."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / "matrix-probe.png"
    browser_result = BrowserResult()
    dom_state: dict[str, object] = {}
    browser_failure = ""
    try:
        with ChromePage(browser_result) as client:
            configure_viewport(client, 1440, 1000, mobile=False)
            navigate(client, url)
            evaluated = client.evaluate(DASHBOARD_BROWSER_CONTRACT, timeout=25.0)
            if not isinstance(evaluated, dict):
                raise RuntimeError(f"Dashboard browser contract returned malformed state: {evaluated!r}")
            dom_state = dict(evaluated)
            client.pump(0.5)
            save_screenshot(client, str(screenshot), capture_beyond_viewport=False)
    except (OSError, RuntimeError) as exc:
        browser_failure = str(exc)

    contract_failures: list[str] = []
    fonts: list[dict[str, str]] = []
    resources: list[dict[str, str]] = []
    scripts: list[dict[str, str]] = []
    styles: list[dict[str, str]] = []
    if dom_state:
        if dom_state.get("ready") != "true":
            contract_failures.append("html[data-om-ready=true] was not reached")
        if dom_state.get("heading") != "MatrixProbe":
            contract_failures.append(f"expected MatrixProbe heading, found {dom_state.get('heading')!r}")
        back_to_top = dom_state.get("backToTop")
        if not isinstance(back_to_top, dict) or not all(
            back_to_top.get(field) is True for field in ("exists", "visible", "clickedToTop")
        ):
            contract_failures.append(f"shared #back-to-top visibility/click contract failed: {back_to_top!r}")
        if dom_state.get("dmSansLoaded") is not True or "DM Sans" not in str(dom_state.get("bodyFontFamily", "")):
            contract_failures.append(
                f"DM Sans did not load as the Dashboard body font: "
                f"loaded={dom_state.get('dmSansLoaded')!r}, family={dom_state.get('bodyFontFamily')!r}"
            )
        weights = dom_state.get("dmSansWeightsLoaded")
        if not isinstance(weights, dict) or weights.get("300") is not True or weights.get("700") is not True:
            contract_failures.append(f"DM Sans 300/700 document.fonts.load contract failed: {weights!r}")
        components = dom_state.get("components")
        expected_component_state = {
            "modal": ("mounted", "opened", "closed"),
            "select": ("mounted", "choicesMounted", "changed"),
            "sidebar": ("exists", "mounted", "active"),
            "table": ("mounted", "paginationShell", "firstPage", "secondPage"),
            "topbar": ("exists", "themeToggled", "shadowed"),
        }
        if not isinstance(components, dict):
            contract_failures.append(f"Dashboard browser component state is missing: {components!r}")
        else:
            for component_name, fields in expected_component_state.items():
                state = components.get(component_name)
                if not isinstance(state, dict) or any(state.get(field) is not True for field in fields):
                    contract_failures.append(f"Dashboard {component_name} interaction contract failed: {state!r}")
            table_state = components.get("table")
            if not isinstance(table_state, dict) or table_state.get("pageCount") != 2 or not table_state.get("summary"):
                contract_failures.append(f"Dashboard Table pagination DOM contract failed: {table_state!r}")
        try:
            scripts = browser_asset_evidence(project, url, dom_state.get("scriptUrls"), label="JavaScript")
            styles = browser_asset_evidence(project, url, dom_state.get("styleUrls"), label="CSS")
            resources = browser_asset_evidence(project, url, dom_state.get("resourceUrls"), label="resource")
            fonts = [item for item in resources if "dm-sans-latin-" in Path(item["path"]).name]
            for weight in (300, 700):
                if not any(Path(item["path"]).name.startswith(f"dm-sans-latin-{weight}-normal-") for item in fonts):
                    contract_failures.append(f"Dashboard did not fetch its DM Sans latin {weight} font resource")
        except RuntimeError as exc:
            contract_failures.append(str(exc))
    payload: dict[str, object] = {
        "browserFailure": browser_failure,
        "consoleErrors": browser_result.console_errors,
        "contractFailures": contract_failures,
        "dom": dom_state,
        "fonts": fonts,
        "javascript": scripts,
        "npmPackage": dict(package_provenance),
        "pageErrors": browser_result.page_errors,
        "resourceErrors": browser_result.bad_responses,
        "resources": resources,
        "screenshot": str(screenshot) if screenshot.is_file() else None,
        "screenshotSha256": sha256_file(screenshot) if screenshot.is_file() else None,
        "stylesheets": styles,
        "url": url,
    }
    write_json(evidence_dir / "result.json", payload)
    if browser_failure or contract_failures or not browser_result.ok:
        raise RuntimeError("Generated Dashboard failed its real-Chrome contract:\n" + json.dumps(payload, indent=2))
    return payload


def run_http_probe(
    project: Path,
    *,
    project_type: str,
    service_name: str,
    launcher: Path,
    environment: Mapping[str, str],
    log_path: Path,
    browser_evidence_dir: Path | None = None,
    browser_package_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Start the generated Web service on a dynamic port and require a real HTTP 200 response."""
    port = reserve_tcp_port()
    url = f"http://127.0.0.1:{port}/matrix_probe"
    update_service_settings(
        project / "data" / f"{service_name}_settings.yaml",
        listen_port=port,
    )
    command = (str(launcher), service_name, "start")
    status: int | None = None
    body = b""
    content_type = ""
    error = ""
    response_errors: list[str] = []
    browser: dict[str, object] | None = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 30
    with tracked_popen(
        command,
        cwd=project,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as (process, process_tree):
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    error = f"server exited before readiness with code {process.returncode}"
                    break
                try:
                    candidate_status, candidate_body, candidate_content_type, candidate_errors = read_http_probe_response(
                        opener,
                        url,
                        project_type,
                    )
                    status = candidate_status
                    body = candidate_body
                    content_type = candidate_content_type
                    response_errors = candidate_errors
                    if not response_errors:
                        error = ""
                        break
                    error = "; ".join(response_errors)
                except (OSError, http.client.HTTPException, urllib.error.URLError) as exc:
                    status = None
                    body = b""
                    content_type = ""
                    error = str(exc)
                    response_errors = [f"HTTP response read failed: {type(exc).__name__}: {exc}"]
                time.sleep(0.1)
            response_ready = status == 200 and not response_errors
            if response_ready:
                settle_error = settle_http_probe_process(process, timeout=1.0)
                if settle_error:
                    error = settle_error
                    response_errors.append(settle_error)
                    response_ready = False
            if response_ready:
                try:
                    stable_status, _stable_body, stable_content_type, stable_errors = read_http_probe_response(
                        opener,
                        url,
                        project_type,
                    )
                except (OSError, http.client.HTTPException, urllib.error.URLError) as exc:
                    stable_errors = [f"stable HTTP response read failed: {type(exc).__name__}: {exc}"]
                else:
                    if (stable_status, stable_content_type) != (status, content_type):
                        stable_errors.append("stable HTTP status or content type differs from the readiness response")
                if stable_errors:
                    response_errors.extend(stable_errors)
                    error = "; ".join(stable_errors)
                    response_ready = False
            if response_ready and project_type == "dashboard":
                if browser_evidence_dir is None or browser_package_provenance is None:
                    raise RuntimeError("Dashboard HTTP probe requires explicit browser and npm-package evidence")
                browser = run_dashboard_browser_probe(
                    project,
                    url,
                    evidence_dir=browser_evidence_dir,
                    package_provenance=browser_package_provenance,
                )
        finally:
            stdout, stderr, cleanup_errors, shutdown_initiated = stop_http_probe_process(
                process,
                host="127.0.0.1",
                port=port,
                process_tree=process_tree,
            )
    outcome_errors = http_probe_outcome_errors(
        status=status,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        response_errors=response_errors,
        shutdown_initiated=shutdown_initiated,
        cleanup_errors=cleanup_errors,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"cwd={project.resolve()}\ncommand={' '.join(command)}\nurl={url}\nstatus={status}\n"
        f"contentType={content_type}\nbodySha256={hashlib.sha256(body).hexdigest() if body else ''}\n"
        f"returncode={process.returncode}\nerror={error}\nshutdownInitiated={shutdown_initiated}\n"
        f"responseErrors={json.dumps(response_errors)}\n"
        f"cleanupErrors={json.dumps(cleanup_errors)}\n{stdout}\n{stderr}\n",
        encoding="utf-8",
    )
    if outcome_errors:
        raise RuntimeError(
            f"{project_type} generated service failed its HTTP/process lifecycle gate at {url}: "
            f"{'; '.join(outcome_errors)}\n{stderr[-4000:]}"
        )
    result: dict[str, object] = {
        "bodySha256": hashlib.sha256(body).hexdigest(),
        "contentType": content_type,
        "port": port,
        "status": status,
        "url": url,
    }
    if browser is not None:
        result["browser"] = browser
    return result


def wheel_identity(path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise RuntimeError(f"Expected one wheel METADATA file in {path}, found {len(metadata_names)}")
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Cannot read Oldman wheel metadata from {path}: {exc}") from exc
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or name.lower().replace("_", "-") != "oldman":
        raise RuntimeError(f"Selected wheel is not the Oldman distribution: {name!r}")
    if not isinstance(version, str) or not version:
        raise RuntimeError("Selected Oldman wheel has no distribution version")
    return {"name": name, "version": version}


def npm_tarball_identity(path: Path) -> dict[str, str]:
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
    """Match npm's source SemVer to the normalized Python distribution version."""
    try:
        expected_wheel_version = python_distribution_version(npm_version)
    except RuntimeError as exc:
        raise RuntimeError(f"oldman-web artifact has no Python/npm-compatible release version: {npm_version}") from exc
    if wheel_version != expected_wheel_version:
        raise RuntimeError(f"Artifact version mismatch: Oldman {wheel_version} != oldman-web {npm_version}")


def validate_generated_project(project: Path, project_type: str, database: str, *, framework_version: str) -> dict[str, object]:
    """Validate generated metadata and database configuration without importing repository code."""
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    if not isinstance(dependencies, list) or f"oldman>={framework_version}" not in dependencies:
        raise RuntimeError(f"{project.name} does not depend on the installed Oldman release")
    if pyproject.get("tool", {}).get("uv", {}).get("package") is not False:
        raise RuntimeError(f"{project.name} must declare [tool.uv] package = false")

    driver = DB_DRIVERS[database]
    dependency_names = {item.split(">=", 1)[0] for item in dependencies if isinstance(item, str)}
    if driver is not None and driver not in dependency_names:
        raise RuntimeError(f"{project.name} is missing the {driver} dependency for database={database}")
    for unrelated_driver in {"aiomysql", "asyncpg"} - ({driver} if driver is not None else set()):
        if unrelated_driver in dependency_names:
            raise RuntimeError(f"{project.name} unexpectedly depends on {unrelated_driver} for database={database}")

    readme = (project / "README.md").read_text(encoding="utf-8")
    documented_commands = (
        ("uv sync", "uv run")
        if project_type == "cli"
        else ("uv sync", "./run.sh")
    )
    for command in documented_commands:
        if command not in readme:
            raise RuntimeError(f"{project.name} README does not document {command!r}")

    schema_path = project / "config" / "schemas.py"
    if project_type == "cli":
        if schema_path.exists():
            raise RuntimeError(f"{project.name} CLI unexpectedly contains framework settings")
        service_name = ""
    else:
        run_script = project / "run.sh"
        if not run_script.is_file() or run_script.is_symlink():
            raise RuntimeError(f"{project.name} is missing its run.sh launcher")
        if not run_script.stat().st_mode & stat.S_IXUSR:
            raise RuntimeError(f"{project.name} run.sh is not executable")
        if (project / "main.py").exists():
            raise RuntimeError(f"{project.name} still contains the obsolete main.py launcher")
        if not schema_path.is_file():
            raise RuntimeError(f"{project.name} is missing config/schemas.py")
        schema = schema_path.read_text(encoding="utf-8")
        if "class Settings(DefaultSettings):" not in schema:
            raise RuntimeError(f"{project.name} does not define the single project Settings type")
        if DB_URLS[database] and DB_URLS[database] in schema:
            raise RuntimeError(f"{project.name} embeds a service database value in config/schemas.py")

        service_name = PROJECT_SERVICE_NAMES[project_type]
        config_file = project / "data" / f"{service_name}_settings.yaml"
        yaml = YAML(typ="safe", pure=True)
        settings_data = yaml.load(config_file.read_text(encoding="utf-8"))
        if not isinstance(settings_data, Mapping):
            raise RuntimeError(f"{project.name} generated invalid service settings")
        apps = settings_data.get("apps")
        expected_apps = ["oldman.auth", "oldman.apps.admin"] if project_type == "dashboard" else []
        if apps != expected_apps:
            raise RuntimeError(f"{project.name} generated unexpected settings.apps: {apps!r}")
        database_config = settings_data.get("database")
        if not isinstance(database_config, Mapping) or database_config.get("url") != (DB_URLS[database] or None):
            raise RuntimeError(f"{project.name} generated an unexpected database.url")
    return {
        "database": database,
        "dependencies": dependencies,
        "project": project.name,
        "projectType": project_type,
        "serviceName": service_name,
        "uvPackage": False,
    }


def install_gate_tool_environment(
    root: Path,
    wheel: Path,
    *,
    wheel_version: str,
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> tuple[Path, Path]:
    """Install the generator and Pyright once; case runtimes remain project-local."""
    environment_root = root / ".gate-tools"
    environment_evidence = evidence_dir / "tool-environment"
    run(
        ("uv", "venv", str(environment_root), "--python", sys.executable),
        cwd=root,
        environment=environment,
        log_path=environment_evidence / "venv.log",
    )
    python = environment_executable(environment_root, "python")
    oldman = environment_executable(environment_root, "oldman")
    pyright = environment_executable(environment_root, "pyright")
    run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--strict",
            str(wheel),
            "pyright[nodejs]>=1.1",
        ),
        cwd=root,
        environment=environment,
        log_path=environment_evidence / "install.log",
        timeout=600,
    )
    provenance = installed_import_provenance(
        python,
        environment_root,
        expected_version=wheel_version,
        cwd=root,
        environment=environment,
        log_path=environment_evidence / "import.log",
    )
    pyright_version = run(
        (str(pyright), "--version"),
        cwd=root,
        environment=environment,
        log_path=environment_evidence / "pyright-version.log",
    ).strip()
    write_json(
        environment_evidence / "installed.json",
        {
            "environment": str(environment_root.resolve()),
            "pyright": str(pyright.resolve()),
            "pyrightVersion": pyright_version,
            "provenance": provenance,
        },
    )
    return oldman, pyright


def generate_case(
    root: Path,
    *,
    project_type: str,
    database: str,
    generator_oldman: Path,
    pyright: Path,
    wheel_index: Path,
    wheel_version: str,
    npm_tarball: Path,
    npm_version: str,
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> dict[str, object]:
    case_name = f"{project_type}-{database}"
    case_evidence = evidence_dir / "cases" / case_name
    project = root / case_name
    run(
        (str(generator_oldman), "startproject", case_name),
        cwd=root,
        environment=environment,
        log_path=case_evidence / "startproject.log",
        input_text=f"{project_type}\n" + (f"{database}\n" if project_type != "cli" else ""),
    )
    metadata = validate_generated_project(project, project_type, database, framework_version=npm_version)
    preserve_evidence_file(project / "pyproject.toml", case_evidence / "generated" / "pyproject.toml")
    preserve_evidence_file(project / "README.md", case_evidence / "generated" / "README.md")
    if project_type != "cli":
        preserve_evidence_file(project / "run.sh", case_evidence / "generated" / "run.sh")
        preserve_evidence_file(project / "config" / "schemas.py", case_evidence / "generated" / "config-schemas.py")
    uv_lock = sync_generated_project(
        project,
        wheel_index=wheel_index,
        expected_version=wheel_version,
        environment=environment,
        log_path=case_evidence / "uv-sync.log",
    )
    environment_root = project / ".venv"
    python = environment_executable(environment_root, "python")
    oldman = environment_executable(environment_root, "oldman")
    if not oldman.is_file():
        raise RuntimeError(f"plain uv sync did not install the project-local Oldman CLI for {case_name}")
    provenance = installed_import_provenance(
        python,
        environment_root,
        expected_version=wheel_version,
        cwd=project,
        environment=environment,
        log_path=case_evidence / "installed-import.log",
    )
    uv_run_provenance = uv_run_import_provenance(
        project,
        environment_root,
        wheel_index=wheel_index,
        expected_version=wheel_version,
        environment=environment,
        log_path=case_evidence / "uv-run-import.log",
    )
    packages = environment_package_state(
        python,
        database=database,
        expected_version=wheel_version,
        cwd=project,
        environment=environment,
        log_path=case_evidence / "environment-packages.log",
    )
    write_json(case_evidence / "installed-import.json", provenance)
    write_json(case_evidence / "uv-run-import.json", uv_run_provenance)
    write_json(case_evidence / "environment-packages.json", packages)
    metadata["environment"] = str(environment_root.resolve())
    metadata["ide"] = {
        "environment": str(environment_root.resolve()),
        "interpreter": str(environment_executable(environment_root.resolve(), "python")),
        "projectLocal": True,
        "pyright": str(pyright.resolve()),
    }
    metadata["installedOldman"] = provenance
    metadata["uvRunOldman"] = uv_run_provenance
    metadata["packages"] = packages
    metadata["uvLock"] = uv_lock
    browser_package_provenance: dict[str, object] | None = None
    service_name = PROJECT_SERVICE_NAMES.get(project_type, "")

    if project_type != "cli":
        run(
            (str(oldman), "startapp", "matrix_probe"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "startapp.log",
            input_text=f"{APP_TYPES[project_type]}\n\n",
        )
        run(
            (str(oldman), "startservice", "matrix_worker"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "startservice.log",
            input_text="simple\n" if project_type == "service" else "web\n",
        )
        preserve_evidence_file(
            project / "apps" / "matrix_probe" / "apps.py",
            case_evidence / "generated" / "apps-matrix-probe.py",
        )
        preserve_evidence_file(
            project / "services" / "matrix_worker.py",
            case_evidence / "generated" / "services-matrix-worker.py",
        )
        if project_type == "dashboard":
            fixture = install_dashboard_component_fixture(project)
            preserve_evidence_file(fixture, case_evidence / "generated" / "templates-matrix_probe-index.html")
        run(
            (str(oldman), "matrix_worker", "settings", "init"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "matrix-worker-settings-init.log",
        )
        update_service_settings(
            project / "data" / f"{service_name}_settings.yaml",
            install_app="apps.matrix_probe",
        )
        run(
            (str(oldman), service_name, "settings", "sync"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "settings-sync.log",
        )
        run(
            (str(oldman), service_name, "settings", "check"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "settings-check.log",
        )
        run(
            (str(oldman), "matrix_worker", "settings", "check"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "matrix-worker-settings-check.log",
        )
        run(
            (str(project / "run.sh"), "--help"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "service-list.log",
        )
        run(
            (str(project / "run.sh"), service_name, "--help"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "service-help.log",
        )
        if database != "none":
            run(
                (str(oldman), "db", "history"),
                cwd=project,
                environment=environment,
                log_path=case_evidence / "db-history.log",
            )
        if database == "sqlite":
            run_tty(
                (str(oldman), "db", "migrate"),
                cwd=project,
                environment=environment,
                log_path=case_evidence / "db-migrate.log",
                input_text="1\n1\n",
            )
            run(
                (str(oldman), "db", "status"),
                cwd=project,
                environment=environment,
                log_path=case_evidence / "db-status.log",
            )
    else:
        run(
            (str(python), "main.py"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "cli-main.log",
        )

    run(
        (
            str(python),
            "-c",
            DATABASE_PROBE,
            PROJECT_SERVICE_NAMES.get(project_type, ""),
            database,
            DB_URLS[database],
        ),
        cwd=project,
        environment=environment,
        log_path=case_evidence / "database.log",
    )
    run(
        (str(python), "-m", "compileall", "-q", "."),
        cwd=project,
        environment=environment,
        log_path=case_evidence / "compileall.log",
    )
    run(
        (str(pyright), "--pythonpath", str(python), "."),
        cwd=project,
        environment=environment,
        log_path=case_evidence / "pyright.log",
        timeout=600,
    )

    if project_type == "service":
        run(
            (str(project / "run.sh"), service_name, "start"),
            cwd=project,
            environment=environment,
            log_path=case_evidence / "service-start.log",
        )
    elif project_type in {"api", "web", "dashboard"}:
        if project_type == "dashboard":
            frontend = project / "frontend"
            package_path = frontend / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["dependencies"]["oldman-web"] = f"file:{npm_tarball}"
            package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
            preserve_evidence_file(package_path, case_evidence / "generated" / "frontend-package.json")
            for command, log_name, timeout in (
                (("pnpm", "install", "--prefer-offline"), "frontend-install.log", 600),
                (("pnpm", "typecheck"), "frontend-typecheck.log", 600),
                (("pnpm", "build"), "frontend-build.log", 600),
            ):
                run(command, cwd=frontend, environment=environment, log_path=case_evidence / log_name, timeout=timeout)
            preserve_evidence_file(frontend / "pnpm-lock.yaml", case_evidence / "generated" / "pnpm-lock.yaml")
            installed_package_json = frontend / "node_modules" / "oldman-web" / "package.json"
            if not installed_package_json.is_file():
                raise RuntimeError(f"{case_name} did not install oldman-web from the explicit tarball")
            resolved_package_json = installed_package_json.resolve()
            node_modules = (frontend / "node_modules").resolve()
            if not resolved_package_json.is_relative_to(node_modules):
                raise RuntimeError(f"{case_name} oldman-web resolved outside the generated consumer: {resolved_package_json}")
            installed_package = json.loads(installed_package_json.read_text(encoding="utf-8"))
            if installed_package.get("name") != "oldman-web" or installed_package.get("version") != npm_version:
                raise RuntimeError(f"{case_name} installed the wrong oldman-web package: {installed_package}")
            installed_dist_entry = resolved_package_json.parent / "dist" / "index.js"
            if not installed_dist_entry.is_file():
                raise RuntimeError(f"{case_name} installed oldman-web tarball has no built dist/index.js")
            pnpm_lock = frontend / "pnpm-lock.yaml"
            lock_evidence = pnpm_tarball_lock_evidence(pnpm_lock, npm_tarball)
            installed_tree = installed_npm_tree_evidence(resolved_package_json.parent, npm_tarball)
            browser_package_provenance = {
                "dependency": package["dependencies"]["oldman-web"],
                "name": installed_package["name"],
                "npmTarball": str(npm_tarball),
                "npmTarballSha256": sha256_file(npm_tarball),
                "packageJson": str(resolved_package_json),
                "packageEntry": str(installed_dist_entry),
                "installedTree": installed_tree,
                "pnpmLock": lock_evidence,
                "version": installed_package["version"],
            }
            write_json(case_evidence / "frontend-package.json", browser_package_provenance)
            manifest_path = project / "static" / "dist" / ".vite" / "manifest.json"
            if not manifest_path.is_file() or "src/main.ts" not in json.loads(manifest_path.read_text(encoding="utf-8")):
                raise RuntimeError(f"{case_name} Dashboard build did not expose src/main.ts in the Vite manifest")
            preserve_evidence_file(manifest_path, case_evidence / "generated" / "vite-manifest.json")
            metadata["viteManifestSha256"] = sha256_file(manifest_path)
        metadata["http"] = run_http_probe(
            project,
            project_type=project_type,
            service_name=service_name,
            launcher=project / "run.sh",
            environment=environment,
            log_path=case_evidence / "web-http.log",
            browser_evidence_dir=case_evidence / "browser" if project_type == "dashboard" else None,
            browser_package_provenance=browser_package_provenance,
        )

    write_json(case_evidence / "result.json", {**metadata, "ok": True})
    return {**metadata, "ok": True}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = datetime.now(UTC).isoformat()
    try:
        wheel = resolve_artifact(args.wheel, label="Oldman wheel", suffix=".whl")
        npm_tarball = resolve_artifact(args.npm_tarball, label="oldman-web npm tarball", suffix=".tgz")
        evidence_dir = prepare_evidence_directory(args.evidence_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results: list[dict[str, object]] = []
    errors: list[str] = []
    try:
        wheel_metadata = wheel_identity(wheel)
        npm_metadata = npm_tarball_identity(npm_tarball)
        require_matching_artifact_versions(wheel_metadata["version"], npm_metadata["version"])
        write_json(
            evidence_dir / "inputs.json",
            {
                "matrix": [{"database": database, "projectType": project_type} for project_type, database in matrix_cases()],
                "npmTarball": str(npm_tarball),
                "npmTarballMetadata": npm_metadata,
                "npmTarballSha256": sha256_file(npm_tarball),
                "oldmanWheel": str(wheel),
                "oldmanWheelMetadata": wheel_metadata,
                "oldmanWheelSha256": sha256_file(wheel),
                "startedAt": started_at,
            },
        )
        with tempfile.TemporaryDirectory(prefix="oldman-installed-scaffold-matrix-") as temporary_directory:
            root = Path(temporary_directory)
            environment = clean_environment()
            tool_versions = {
                name: run(
                    command,
                    cwd=root,
                    environment=environment,
                    log_path=evidence_dir / "tools" / f"{name}.log",
                ).strip()
                for name, command in (
                    ("node", ("node", "--version")),
                    ("pnpm", ("pnpm", "--version")),
                    ("python", (sys.executable, "--version")),
                    ("uv", ("uv", "--version")),
                )
            }
            write_json(evidence_dir / "tools.json", tool_versions)
            wheel_index = prepare_wheel_index(root, wheel)
            generator_oldman, pyright = install_gate_tool_environment(
                root,
                wheel,
                wheel_version=wheel_metadata["version"],
                evidence_dir=evidence_dir,
                environment=environment,
            )
            matrix_root = root / "matrix"
            matrix_root.mkdir()
            case_environments: set[Path] = set()
            for project_type, database in matrix_cases():
                case_project = matrix_root / f"{project_type}-{database}"
                try:
                    result = generate_case(
                        matrix_root,
                        project_type=project_type,
                        database=database,
                        generator_oldman=generator_oldman,
                        pyright=pyright,
                        wheel_index=wheel_index,
                        wheel_version=wheel_metadata["version"],
                        npm_tarball=npm_tarball,
                        npm_version=npm_metadata["version"],
                        evidence_dir=evidence_dir,
                        environment=environment,
                    )
                    case_environment = Path(str(result["environment"])).resolve()
                    if case_environment in case_environments:
                        raise RuntimeError(f"matrix cases reused a project environment: {case_environment}")
                    case_environments.add(case_environment)
                    results.append(result)
                except (OSError, RuntimeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                    error = f"{project_type}/{database}: {exc}"
                    errors.append(error)
                    write_json(
                        evidence_dir / "cases" / f"{project_type}-{database}" / "result.json",
                        {"database": database, "error": str(exc), "ok": False, "projectType": project_type},
                    )
                finally:
                    if case_project.exists():
                        shutil.rmtree(case_project)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, tarfile.TarError) as exc:
        errors.append(str(exc))

    write_json(
        evidence_dir / "result.json",
        {
            "errors": errors,
            "finishedAt": datetime.now(UTC).isoformat(),
            "ok": not errors and len(results) == len(matrix_cases()),
            "passed": results,
            "startedAt": started_at,
        },
    )
    if errors or len(results) != len(matrix_cases()):
        print("\n".join((*errors, f"Evidence: {evidence_dir}")), file=sys.stderr)
        return 1
    print(f"Installed scaffold matrix passed: {len(results)} combinations. Evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
