#!/usr/bin/env python3
"""Run the Admin application from an installed wheel and verify it with Chrome."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

try:
    from scripts.linux_process_tree import ProcessTreeError, ProcessTreeTracker, tracked_popen
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from linux_process_tree import ProcessTreeError, ProcessTreeTracker, tracked_popen

ADMIN_USERNAME = "installed_wheel_admin"
ADMIN_PASSWORD = "InstalledWheelAdmin123"
ADMIN_STATIC_URL = "/static/oldman/admin"
REQUIRED_DYNAMIC_ENTRIES = ("date-time-picker", "dropdown", "modal", "table-filter-form")

COLLECT_SOURCE = r'''"""Collect installed framework assets before the server starts."""

from __future__ import annotations

import os
from pathlib import Path

from oldman.web.staticfiles import collect_project_static

collect_project_static(
    project_directory=Path(os.environ["OLDMAN_INSTALLED_ADMIN_STATIC_SOURCE"]),
    destination=Path(os.environ["OLDMAN_INSTALLED_ADMIN_STATIC_ROOT"]),
    clear=True,
)
'''

MIGRATE_SOURCE = r'''from pathlib import Path

from oldman.db.migrations.commands import migrate
from oldman.db.migrations.project import load_migration_project


class FirstUseInteraction:
    """Confirm only the empty database created by this browser gate."""

    is_interactive = False

    def choose(self, prompt, choices):
        if "internal migration state" in prompt and "first use" in choices:
            return "first use"
        raise RuntimeError(f"Unexpected migration choice: {prompt}")

    def confirm(self, prompt, *, default=False):
        del default
        raise RuntimeError(f"Unexpected migration confirmation: {prompt}")

    def text(self, prompt, *, default):
        del default
        raise RuntimeError(f"Unexpected migration text request: {prompt}")


project = load_migration_project(Path.cwd())
migrate(project, FirstUseInteraction())
'''

SERVER_SOURCE = r'''"""Ephemeral Admin server used by the installed-wheel browser gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import oldman
from sanic import Sanic
from sanic.response import json as json_response
from sanic_ext import Config, Extend

from oldman.apps.admin import install_admin
from oldman.apps.admin.apps import app as admin_app
from oldman.apps.admin.template import admin_template_dir
from oldman.auth import ensure_superuser
from oldman.auth.apps import app as auth_app
from oldman.db import db_manager
from oldman.providers.redis import redis_client
from oldman.runtime import bootstrap_service
from oldman.web.session import Session

HOST = os.environ["OLDMAN_INSTALLED_ADMIN_HOST"]
PORT = int(os.environ["OLDMAN_INSTALLED_ADMIN_PORT"])
USERNAME = os.environ["OLDMAN_INSTALLED_ADMIN_USERNAME"]
PASSWORD = os.environ["OLDMAN_INSTALLED_ADMIN_PASSWORD"]
STATIC_ROOT = Path(os.environ["OLDMAN_INSTALLED_ADMIN_STATIC_ROOT"]).resolve()
STATIC_URL = "/static"
ADMIN_STATIC_PATH = Path("oldman/admin")
bootstrap_context = bootstrap_service("web")
app = Sanic("oldman_installed_wheel_admin", strict_slashes=True)
Extend(
    app,
    config=Config(
        oas=False,
        oas_autodoc=False,
        templating_enable_async=True,
        logging=False,
    ),
)
app.ctx.oldman_app_registry = bootstrap_context.apps
Session(app)
app.static(STATIC_URL, str(STATIC_ROOT), name="static")
install_admin(
    app,
    auth_settings=auth_app.settings,
    admin_settings=admin_app.settings,
)


@app.listener("before_server_start")
async def initialize_admin_user(_app: Sanic, _loop) -> None:
    await ensure_superuser(USERNAME, PASSWORD, auth_settings=auth_app.settings, db_manager=db_manager)


@app.listener("after_server_stop")
async def close_database(_app: Sanic, _loop) -> None:
    try:
        await db_manager.close()
    finally:
        await redis_client.close()


@app.get("/__oldman_probe__/runtime")
async def runtime_probe(_request):
    manifest_path = STATIC_ROOT / ADMIN_STATIC_PATH / ".vite" / "manifest.json"
    return json_response(
        {
            "oldman_file": str(Path(oldman.__file__).resolve()),
            "python_executable": str(Path(sys.executable).absolute()),
            "python_prefix": str(Path(sys.prefix).resolve()),
            "template_dir": str(admin_template_dir().resolve()),
            "static_dir": str(STATIC_ROOT),
            "manifest_path": str(manifest_path.resolve()),
        }
    )


@app.get("/__oldman_probe__/manifest")
async def manifest_probe(_request):
    manifest_path = STATIC_ROOT / ADMIN_STATIC_PATH / ".vite" / "manifest.json"
    return json_response(json.loads(manifest_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, single_process=True, access_log=False, motd=False)
'''


@dataclass(frozen=True)
class ManifestContract:
    """Asset paths that the installed Admin page must expose."""

    main_script: str
    main_styles: tuple[str, ...]
    dynamic_files: dict[str, str]
    font_files: tuple[str, ...]
    all_files: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, help="Exact wheel path")
    return parser.parse_args()


def resolve_single_wheel(value: str) -> Path:
    """Resolve one explicit wheel path without artifact discovery."""
    if any(character in value for character in "*?[]"):
        raise RuntimeError(f"Wheel must be an explicit path, not a glob: {value!r}")
    candidate = Path(value).expanduser()
    if candidate.is_symlink() or not candidate.is_file() or not candidate.name.endswith(".whl"):
        raise RuntimeError(f"Wheel is not a readable regular .whl file: {candidate}")
    return candidate.resolve()


def clean_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove path mechanisms that could import Oldman from the repository."""
    environment = dict(os.environ if source is None else source)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("UV_PROJECT_ENVIRONMENT", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def environment_executable(environment_root: Path, name: str) -> Path:
    return environment_root / ("Scripts" if os.name == "nt" else "bin") / name


def run(command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        rendered = " ".join(command)
        raise RuntimeError(f"Command failed ({completed.returncode}): {rendered}\n{completed.stdout}\n{completed.stderr}")
    return completed.stdout


def write_probe_server(project_root: Path) -> Path:
    """Write the isolated server without copying any repository package source."""
    server_path = project_root / "installed_admin_server.py"
    server_path.write_text(SERVER_SOURCE, encoding="utf-8")
    return server_path


def prepare_migration_project(project_root: Path, database_path: Path) -> None:
    """Write the minimum real project metadata consumed by ``oldman db migrate``."""
    config = project_root / "config"
    services = project_root / "services"
    data = project_root / "data"
    config.mkdir()
    services.mkdir()
    data.mkdir()
    (config / "__init__.py").write_text("", encoding="utf-8")
    (config / "schemas.py").write_text(
        "from oldman.conf import DefaultSettings\n\n"
        "class Settings(DefaultSettings):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "web.py").write_text(
        "from oldman.runtime import WebApplication\n\n"
        "class WebService(WebApplication):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (project_root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "oldman-installed-admin-browser"\n'
        'version = "0.0.0"\n\n'
        "[tool.oldman]\n"
        'project_id = "2eb38615-9831-4a68-88be-552b69e16bc8"\n',
        encoding="utf-8",
    )
    (data / "web_settings.yaml").write_text(
        json.dumps(
            {
                "apps": ["oldman.auth", "oldman.apps.admin"],
                "app_settings": {
                    "auth": {"user_model": "oldman.auth.models.User"},
                    "admin": {"require_superuser": True},
                },
                "database": {
                    "url": f"sqlite+aiosqlite:///{database_path.as_posix()}",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def prepare_runtime_settings(
    project_root: Path,
    database_path: Path,
    static_source: Path,
    static_root: Path,
    *,
    host: str,
    port: int,
    redis_url: str,
) -> None:
    """Replace the migration-only seed with the complete isolated Web config."""
    payload = {
        "apps": ["oldman.auth", "oldman.apps.admin"],
        "app_settings": {
            "auth": {"user_model": "oldman.auth.models.User"},
            "admin": {"require_superuser": True},
        },
        "database": {
            "url": f"sqlite+aiosqlite:///{database_path.as_posix()}",
        },
        "process": {"pid_dir": str(project_root / "pids")},
        "redis": {"SESSION": {"redis_url": redis_url}},
        "web": {
            "listen_host": host,
            "listen_port": port,
            "access_log": False,
            "security": {
                "secret_key": secrets.token_urlsafe(48),
                "fingerprint": {
                    "aes_secret_key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
                },
            },
            "session": {
                "enabled": True,
                "redis_alias": "SESSION",
                "expiry": 86400,
                "prefix": "installed_wheel_admin_session:",
                "user_prefix": "installed_wheel_admin_user:",
                "cookie_name": "installed_wheel_admin_session_id",
                "cookie_secure": False,
            },
            "messages": {"enabled": True},
            "static": {
                "dir": str(static_source),
                "root": str(static_root),
                "url": "/static",
            },
        },
    }
    (project_root / "data" / "web_settings.yaml").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def manifest_contract(manifest: Mapping[str, Any]) -> ManifestContract:
    """Resolve the production entry, dynamic chunks and fonts from a Vite manifest."""
    main_entry = manifest.get("src/main.ts")
    if not isinstance(main_entry, Mapping) or not isinstance(main_entry.get("file"), str):
        raise RuntimeError("Installed Admin manifest is missing src/main.ts")

    dynamic_files: dict[str, str] = {}
    for entry in manifest.values():
        if not isinstance(entry, Mapping) or entry.get("isDynamicEntry") is not True:
            continue
        name = entry.get("name")
        file_name = entry.get("file")
        if isinstance(name, str) and isinstance(file_name, str) and name in REQUIRED_DYNAMIC_ENTRIES:
            dynamic_files[name] = file_name
    missing_dynamic = sorted(set(REQUIRED_DYNAMIC_ENTRIES) - set(dynamic_files))
    if missing_dynamic:
        raise RuntimeError(f"Installed Admin manifest is missing dynamic entries: {', '.join(missing_dynamic)}")

    files: set[str] = set()
    for entry in manifest.values():
        if not isinstance(entry, Mapping):
            continue
        file_name = entry.get("file")
        if isinstance(file_name, str):
            files.add(file_name)
        for field_name in ("assets", "css"):
            values = entry.get(field_name, ())
            if isinstance(values, list):
                files.update(value for value in values if isinstance(value, str))

    font_files = tuple(sorted(file_name for file_name in files if "dm-sans" in file_name and file_name.endswith((".woff", ".woff2"))))
    if not font_files:
        raise RuntimeError("Installed Admin manifest contains no DM Sans webfonts")

    styles = main_entry.get("css", ())
    main_styles = tuple(value for value in styles if isinstance(value, str)) if isinstance(styles, list) else ()
    if not main_styles:
        raise RuntimeError("Installed Admin manifest src/main.ts contains no stylesheet")
    return ManifestContract(
        main_script=str(main_entry["file"]),
        main_styles=main_styles,
        dynamic_files=dynamic_files,
        font_files=font_files,
        all_files=tuple(sorted(files)),
    )


def read_json(url: str, *, timeout: float = 2.0) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local ephemeral server only
        return json.loads(response.read().decode("utf-8"))


def wait_for_runtime(base_url: str, process: subprocess.Popen[str], *, timeout: float = 30.0) -> dict[str, Any]:
    """Wait for the temporary installed-wheel server to expose its runtime proof."""
    deadline = time.monotonic() + timeout
    probe_url = f"{base_url}/__oldman_probe__/runtime"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"Installed-wheel Admin server exited early ({process.returncode})\n{stdout}\n{stderr}")
        try:
            return read_json(probe_url)
        except (OSError, URLError, ValueError):
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for installed-wheel Admin server: {probe_url}")


def assert_installed_runtime(
    runtime: Mapping[str, Any],
    environment_root: Path,
    static_root: Path,
) -> None:
    """Require package paths in the venv and public assets in the collected root."""
    resolved_environment = environment_root.resolve()
    expected_python = environment_executable(environment_root, "python")
    for field_name in ("oldman_file", "python_executable", "python_prefix", "template_dir"):
        raw_path = runtime.get(field_name)
        if not isinstance(raw_path, str):
            raise RuntimeError(f"Installed runtime probe omitted {field_name}")
        if field_name == "python_executable":
            candidate = Path(raw_path).absolute()
            if candidate.name != expected_python.name or candidate.parent.resolve() != expected_python.parent.resolve():
                raise RuntimeError(f"Installed runtime {field_name} escaped the clean environment: {raw_path}")
            continue
        try:
            Path(raw_path).resolve().relative_to(resolved_environment)
        except ValueError as exc:
            raise RuntimeError(f"Installed runtime {field_name} escaped the clean environment: {raw_path}") from exc

    expected_paths = {
        "static_dir": static_root.resolve(),
        "manifest_path": (
            static_root / "oldman" / "admin" / ".vite" / "manifest.json"
        ).resolve(),
    }
    for field_name, expected_path in expected_paths.items():
        raw_path = runtime.get(field_name)
        if not isinstance(raw_path, str) or Path(raw_path).resolve() != expected_path:
            raise RuntimeError(
                f"Installed runtime {field_name} did not use the explicit "
                f"collection output: {raw_path}"
            )


def login_page_script(contract: ManifestContract) -> str:
    config = json.dumps(
        {
            "mainScript": contract.main_script,
            "mainStyles": list(contract.main_styles),
            "staticUrl": ADMIN_STATIC_URL,
        }
    )
    return f"""
    (() => {{
      const config = {config};
      const failures = [];
      if (document.body.dataset.omPage !== "admin") failures.push("login template did not declare the Admin page");
      if (!document.body.classList.contains("oldman-auth-page")) failures.push("login template is missing its auth layout");
      if (!document.querySelector('form input[name="csrfmiddlewaretoken"]')) failures.push("login template is missing CSRF");
      if (!document.querySelector('input[name="username"]')) failures.push("login template is missing username");
      if (!document.querySelector('input[name="password"]')) failures.push("login template is missing password");
      const scripts = Array.from(document.querySelectorAll('script[type="module"][src]')).map((item) => new URL(item.src).pathname);
      if (!scripts.includes(`${{config.staticUrl}}/${{config.mainScript}}`)) failures.push("login template did not render the manifest script");
      const styles = Array.from(document.querySelectorAll('link[rel="stylesheet"][href]')).map((item) => new URL(item.href).pathname);
      for (const file of config.mainStyles) {{
        if (!styles.includes(`${{config.staticUrl}}/${{file}}`)) failures.push(`login template did not render stylesheet ${{file}}`);
      }}
      return {{ failures, scripts, styles }};
    }})()
    """


def login_submit_script(username: str, password: str) -> str:
    credentials = json.dumps({"username": username, "password": password})
    return f"""
    (() => {{
      const credentials = {credentials};
      const form = document.querySelector("form");
      const username = form?.querySelector('[name="username"]');
      const password = form?.querySelector('[name="password"]');
      const csrf = form?.querySelector('input[name="csrfmiddlewaretoken"]');
      if (!form || !username || !password || !csrf?.value) return {{ submitted: false }};
      username.value = credentials.username;
      password.value = credentials.password;
      form.submit();
      return {{ submitted: true }};
    }})()
    """


def admin_contract_script(
    contract: ManifestContract,
    environment_root: Path,
    static_root: Path,
) -> str:
    """Return the in-browser contract for installed templates and manifest assets."""
    environment_roots = sorted({str(environment_root.absolute()), str(environment_root.resolve())})
    config = json.dumps(
        {
            "allFiles": list(contract.all_files),
            "dynamicFiles": contract.dynamic_files,
            "environmentRoots": environment_roots,
            "fontFiles": list(contract.font_files),
            "mainScript": contract.main_script,
            "mainStyles": list(contract.main_styles),
            "requiredDynamicEntries": list(REQUIRED_DYNAMIC_ENTRIES),
            "staticRoot": str(static_root.resolve()),
            "staticUrl": ADMIN_STATIC_URL,
        }
    )
    return f"""
    (async () => {{
      const config = {config};
      const failures = [];
      const waitUntil = async (predicate, label) => {{
        for (let attempt = 0; attempt < 240; attempt += 1) {{
          if (predicate()) return;
          await new Promise((resolve) => setTimeout(resolve, 50));
        }}
        failures.push(`timed out waiting for ${{label}}`);
      }};
      await waitUntil(() => document.documentElement.dataset.omReady === "true", "Admin startup");
      await waitUntil(
        () => document.querySelector('[data-om-table-partial]:not([data-om-initial-table-partial])'),
        "the async user table",
      );

      const runtimeResponse = await fetch("/__oldman_probe__/runtime");
      if (!runtimeResponse.ok) failures.push(`runtime probe returned ${{runtimeResponse.status}}`);
      const runtime = runtimeResponse.ok ? await runtimeResponse.json() : {{}};
      for (const field of ["oldman_file", "python_executable", "python_prefix", "template_dir"]) {{
        const value = String(runtime[field] || "");
        if (!config.environmentRoots.some((root) => value === root || value.startsWith(`${{root}}/`))) failures.push(`runtime ${{field}} escaped installed environment`);
      }}
      if (String(runtime.static_dir || "") !== config.staticRoot) failures.push("runtime static_dir did not use the explicit collection output");
      if (String(runtime.manifest_path || "") !== `${{config.staticRoot}}/oldman/admin/.vite/manifest.json`) failures.push("runtime manifest_path did not use the collected Admin manifest");

      const manifestResponse = await fetch("/__oldman_probe__/manifest");
      if (!manifestResponse.ok) failures.push(`manifest probe returned ${{manifestResponse.status}}`);
      const manifest = manifestResponse.ok ? await manifestResponse.json() : {{}};
      if (manifest["src/main.ts"]?.file !== config.mainScript) failures.push("served manifest main entry differs from installed contract");
      for (const [name, file] of Object.entries(config.dynamicFiles)) {{
        const entry = Object.values(manifest).find((candidate) => candidate?.name === name && candidate?.isDynamicEntry === true);
        if (entry?.file !== file) failures.push(`served manifest dynamic entry differs for ${{name}}`);
      }}

      const responses = await Promise.all(
        config.allFiles.map(async (file) => {{
          const response = await fetch(`${{config.staticUrl}}/${{file}}`);
          return {{ file, status: response.status }};
        }}),
      );
      for (const response of responses) {{
        if (response.status < 200 || response.status >= 300) failures.push(`manifest asset ${{response.file}} returned ${{response.status}}`);
      }}

      await Promise.all([document.fonts.load('400 16px "DM Sans"'), document.fonts.load('700 16px "DM Sans"')]);
      await document.fonts.ready;
      if (!document.fonts.check('400 16px "DM Sans"')) failures.push("DM Sans 400 did not activate");
      if (!document.fonts.check('700 16px "DM Sans"')) failures.push("DM Sans 700 did not activate");
      if (!getComputedStyle(document.body).fontFamily.includes("DM Sans")) failures.push("Admin body does not use DM Sans");

      if (location.pathname !== "/admin/oldman_user") failures.push(`unexpected Admin list URL ${{location.pathname}}`);
      if (document.body.dataset.omPage !== "admin") failures.push("model-list template did not declare the Admin page");
      if (!document.querySelector(".oldman-sidebar")) failures.push("model-list template is missing the shared dashboard sidebar");
      if (!document.querySelector('[data-om-component="table-filter-form"]')) failures.push("model-list template is missing the filter form");
      if (!document.querySelector('[data-om-component="table"]')) failures.push("model-list template is missing the table shell");
      if (!document.querySelector('#removeNotificationModal[data-om-component="modal"]')) failures.push("Admin shell is missing the shared notification modal");
      if (!document.querySelector('[data-om-table-row]')) failures.push("installed SQLite table returned no Admin user row");
      if (!document.querySelector('[data-om-dropdown-toggle]')) failures.push("installed Admin row is missing its dropdown action");
      for (const name of ["last_login_from", "last_login_to"]) {{
        if (!document.querySelector(`[data-om-component="table-filter-form"] [name="${{name}}"]`)) failures.push(`missing date-time filter ${{name}}`);
      }}

      const scripts = Array.from(document.querySelectorAll('script[type="module"][src]')).map((item) => new URL(item.src).pathname);
      if (!scripts.includes(`${{config.staticUrl}}/${{config.mainScript}}`)) failures.push("model-list template did not render the manifest script");
      const styles = Array.from(document.querySelectorAll('link[rel="stylesheet"][href]')).map((item) => new URL(item.href).pathname);
      for (const file of config.mainStyles) {{
        if (!styles.includes(`${{config.staticUrl}}/${{file}}`)) failures.push(`model-list template did not render stylesheet ${{file}}`);
      }}

      const resources = performance.getEntriesByType("resource").map((entry) => new URL(entry.name).pathname);
      for (const name of config.requiredDynamicEntries) {{
        const path = `${{config.staticUrl}}/${{config.dynamicFiles[name]}}`;
        if (!resources.includes(path)) failures.push(`dynamic chunk ${{name}} was not loaded by the real page`);
      }}
      if (!config.fontFiles.some((file) => resources.includes(`${{config.staticUrl}}/${{file}}`))) failures.push("no installed DM Sans font was fetched");
      const foreignResources = resources.filter((path) => path.startsWith("/static/") && !path.startsWith(`${{config.staticUrl}}/`));
      if (foreignResources.length) failures.push(`Admin loaded assets outside its package boundary: ${{foreignResources.join(", ")}}`);

      return {{ failures, resources, runtime }};
    }})()
    """


def require_browser_assertion(label: str, state: object) -> None:
    result = state if isinstance(state, dict) else {"failures": ["browser assertion returned no result"]}
    failures = [str(item) for item in result.get("failures", [])]
    if failures:
        raise RuntimeError(f"{label} failed:\n- " + "\n- ".join(failures))


def verify_with_chrome(
    base_url: str,
    contract: ManifestContract,
    environment_root: Path,
    static_root: Path,
) -> None:
    """Exercise login and the async model list in a real isolated Chrome profile."""
    from browser_cdp import BrowserResult, ChromePage, configure_viewport, navigate

    browser_result = BrowserResult()
    with ChromePage(browser_result) as client:
        configure_viewport(client, 1440, 1000, mobile=False)
        navigate(client, f"{base_url}/admin/login")
        require_browser_assertion("installed Admin login template", client.evaluate(login_page_script(contract)))

        client.load_seen = False
        submission = client.evaluate(login_submit_script(ADMIN_USERNAME, ADMIN_PASSWORD))
        if not isinstance(submission, dict) or not submission.get("submitted"):
            raise RuntimeError("Installed Admin login form could not be submitted")
        client.wait_for_load()
        client.pump(0.25)
        if str(client.evaluate("location.pathname")) == "/admin/login":
            raise RuntimeError("Installed Admin login did not authenticate the wheel-created SQLite user")

        navigate(client, f"{base_url}/admin/oldman_user")
        require_browser_assertion(
            "installed Admin runtime contract",
            client.evaluate(
                admin_contract_script(contract, environment_root, static_root),
                timeout=40.0,
            ),
        )
        client.pump(0.5)

    if not browser_result.ok:
        raise RuntimeError(
            "Installed Admin emitted browser errors:\n"
            + json.dumps(
                {
                    "console_errors": browser_result.console_errors,
                    "page_errors": browser_result.page_errors,
                    "bad_responses": browser_result.bad_responses,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def find_loopback_port() -> int:
    """Reserve one currently free loopback port for a gate-owned process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def owned_redis_server(
    state_root: Path,
    *,
    environment: Mapping[str, str],
) -> Iterator[str]:
    """Run one non-persistent Redis and prove its process group and port are removed."""
    executable = shutil.which("redis-server", path=environment.get("PATH"))
    if executable is None:
        raise RuntimeError("Installed-wheel Admin browser gate requires redis-server")

    state_root.mkdir(parents=True, exist_ok=True)
    port = find_loopback_port()
    log_handle = (state_root / "redis.log").open("wb")
    process = subprocess.Popen(
        [
            executable,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--daemonize",
            "no",
            "--dir",
            str(state_root),
            "--pidfile",
            str(state_root / "redis.pid"),
        ],
        cwd=state_root,
        env=dict(environment),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    try:
        while not port_is_open(port) and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not port_is_open(port):
            raise RuntimeError(f"Gate-owned Redis did not start (return code {process.returncode})")
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        cleanup_errors: list[str] = []
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        if process.returncode not in {0, -signal.SIGTERM}:
            cleanup_errors.append(f"Redis returned unexpected code {process.returncode}")
        if process_group_exists(process.pid):
            cleanup_errors.append(f"Redis process group {process.pid} remains after shutdown")
        if not wait_until(lambda: not port_is_open(port)):
            cleanup_errors.append(f"Redis port 127.0.0.1:{port} remains open after shutdown")
        log_handle.close()
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))


def process_group_exists(process_group: int) -> bool:
    """Return whether any process remains in a gate-owned POSIX group."""
    if os.name != "posix":  # pragma: no cover - current release scope is Linux
        return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def port_is_open(port: int) -> bool:
    """Return whether the installed Admin listener still owns its loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex(("127.0.0.1", port)) == 0


def wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> bool:
    """Wait briefly for one shutdown condition."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return bool(predicate())


def stop_server(
    process: subprocess.Popen[str],
    process_tree: ProcessTreeTracker,
    *,
    port: int,
) -> tuple[str, str, list[str]]:
    """Signal the live leader, then prove the complete owned tree and port are gone."""
    errors: list[str] = []
    leader_was_running = process.poll() is None
    if not leader_was_running:
        errors.append(f"installed Admin server exited before gate-initiated shutdown ({process.returncode})")
    try:
        process_tree.terminate(
            process,
            require_live_leader=leader_was_running,
            term_timeout=10,
            kill_timeout=5,
        )
    except ProcessTreeError as exc:
        errors.append(str(exc))
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        errors.append("installed Admin server leader could not be reaped after process-tree cleanup")
        process.kill()
        stdout, stderr = process.communicate(timeout=5)

    acceptable_returncodes = {0, -signal.SIGTERM} if leader_was_running else {0}
    if process.returncode not in acceptable_returncodes:
        errors.append(f"installed Admin server returned {process.returncode}")
    if not wait_until(lambda: not port_is_open(port)):
        errors.append(f"installed Admin port 127.0.0.1:{port} remains open after shutdown")
    return stdout, stderr, errors


def report_server_shutdown(process: subprocess.Popen[str], stdout: str, stderr: str) -> None:
    """Emit server lifecycle evidence so the parent package gate persists it."""
    print(f"Installed-wheel Admin server returncode={process.returncode}", file=sys.stderr)
    if stdout:
        print(stdout, file=sys.stderr)
    if stderr:
        print(stderr, file=sys.stderr)


def install_and_verify(wheel: Path) -> None:
    """Install exactly one wheel, start Admin from it, then run Chrome."""
    from browser_cdp import find_free_port

    with tempfile.TemporaryDirectory(prefix="oldman-installed-admin-browser-") as temporary_directory:
        root = Path(temporary_directory)
        environment_root = root / ".venv"
        project_root = root / "project"
        project_root.mkdir()
        database_path = project_root / "installed_admin.db"
        static_source = project_root / "static-source"
        static_root = project_root / "public-static"
        static_source.mkdir()
        environment = clean_environment()
        run(("uv", "venv", str(environment_root), "--python", sys.executable), cwd=root, environment=environment)
        python = environment_executable(environment_root, "python")
        run(("uv", "pip", "install", "--python", str(python), "--strict", str(wheel)), cwd=root, environment=environment)

        prepare_migration_project(project_root, database_path)
        server_path = write_probe_server(project_root)
        port = find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        server_environment = clean_environment(environment)
        server_environment.update(
            {
                "OLDMAN_INSTALLED_ADMIN_HOST": "127.0.0.1",
                "OLDMAN_INSTALLED_ADMIN_PASSWORD": ADMIN_PASSWORD,
                "OLDMAN_INSTALLED_ADMIN_PORT": str(port),
                "OLDMAN_INSTALLED_ADMIN_STATIC_ROOT": str(static_root),
                "OLDMAN_INSTALLED_ADMIN_STATIC_SOURCE": str(static_source),
                "OLDMAN_INSTALLED_ADMIN_USERNAME": ADMIN_USERNAME,
                "VIRTUAL_ENV": str(environment_root),
            }
        )
        run(
            (str(python), "-I", "-c", MIGRATE_SOURCE),
            cwd=project_root,
            environment=server_environment,
        )
        with owned_redis_server(project_root / "redis", environment=server_environment) as redis_url:
            prepare_runtime_settings(
                project_root,
                database_path,
                static_source,
                static_root,
                host="127.0.0.1",
                port=port,
                redis_url=redis_url,
            )
            run(
                (str(python), "-I", "-c", COLLECT_SOURCE),
                cwd=project_root,
                environment=server_environment,
            )
            with tracked_popen(
                (str(python), str(server_path)),
                cwd=project_root,
                env=server_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            ) as (process, process_tree):
                try:
                    runtime = wait_for_runtime(base_url, process)
                    assert_installed_runtime(runtime, environment_root, static_root)
                    manifest = read_json(f"{base_url}/__oldman_probe__/manifest")
                    contract = manifest_contract(manifest)
                    verify_with_chrome(
                        base_url,
                        contract,
                        environment_root,
                        static_root,
                    )
                except Exception as exc:
                    stdout, stderr, cleanup_errors = stop_server(process, process_tree, port=port)
                    report_server_shutdown(process, stdout, stderr)
                    if cleanup_errors:
                        raise RuntimeError("; ".join(cleanup_errors)) from exc
                    raise
                else:
                    stdout, stderr, cleanup_errors = stop_server(process, process_tree, port=port)
                    report_server_shutdown(process, stdout, stderr)
                    if cleanup_errors:
                        raise RuntimeError("; ".join(cleanup_errors))


def main() -> int:
    args = parse_args()
    install_and_verify(resolve_single_wheel(args.wheel))
    print("Installed-wheel Admin Chrome gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
