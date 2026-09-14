"""Verify Oldman startproject/startapp scaffold resources."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oldman.cli.scaffold import (  # noqa: E402
    AppType,
    DatabaseChoice,
    ProjectType,
    ServiceType,
    start_app,
    start_project,
    start_service,
)

SCAFFOLD_ROOT = ROOT / "oldman" / "scaffolds"


@contextlib.contextmanager
def working_directory(path: Path):
    """Temporarily switch the current working directory."""
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def assert_true(condition: bool, message: str) -> None:
    """Raise a deterministic assertion error."""
    if not condition:
        raise AssertionError(message)


def verify_template_resources() -> None:
    """Check scaffold templates live under oldman/scaffolds and avoid legacy names."""
    required_dirs = [
        SCAFFOLD_ROOT / "project" / "cli_app",
        SCAFFOLD_ROOT / "project" / "app_service",
        SCAFFOLD_ROOT / "project" / "api_service",
        SCAFFOLD_ROOT / "project" / "web_service",
        SCAFFOLD_ROOT / "project" / "dashboard",
        SCAFFOLD_ROOT / "app" / "service_app",
        SCAFFOLD_ROOT / "app" / "api_app",
        SCAFFOLD_ROOT / "app" / "web_app",
        SCAFFOLD_ROOT / "app" / "dashboard_app",
        SCAFFOLD_ROOT / "service" / "simple",
        SCAFFOLD_ROOT / "service" / "web",
    ]
    for directory in required_dirs:
        assert_true(directory.is_dir(), f"missing scaffold dir: {directory}")
        assert_true(any(path.name != ".gitkeep" for path in directory.rglob("*") if path.is_file()), f"empty scaffold dir: {directory}")

    assert_true(not (ROOT / "frontend" / "scaffolds").exists(), "scaffold resources must not live under frontend/")


def verify_generation() -> None:
    """Generate each scaffold type and verify key boundaries."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with working_directory(tmp_path):
            cli_project = start_project("CLI Tool", project_type=ProjectType.CLI)
            service_project = start_project("Worker Service", project_type=ProjectType.SERVICE)
            api_project = start_project("API Service", project_type=ProjectType.API, db=DatabaseChoice.POSTGRES)
            web_project = start_project("Web Site", project_type=ProjectType.WEB, db=DatabaseChoice.SQLITE)
            dashboard_project = start_project(
                "Ops Dashboard",
                project_type=ProjectType.DASHBOARD,
                db=DatabaseChoice.SQLITE,
            )

        assert_true(not (cli_project / "services").exists(), "cli project must not create services/")
        assert_true((service_project / "services" / "__init__.py").exists(), "service project must create services package")
        assert_true(not (api_project / "templates").exists(), "api project must not create templates/")
        assert_true((web_project / "templates" / "base.html").exists(), "web project must create templates")
        assert_true((dashboard_project / "frontend" / "package.json").exists(), "dashboard project must create frontend package")
        for project in (cli_project, service_project, api_project, web_project, dashboard_project):
            metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
            readme = (project / "README.md").read_text(encoding="utf-8")
            assert_true(metadata.get("tool", {}).get("uv", {}).get("package") is False, f"{project.name} must be a flat uv application")
            assert_true("uv sync" in readme, f"{project.name} must document dependency installation")
            if project == cli_project:
                assert_true("uv run python main.py" in readme, "CLI projects must document their Python entry point")
                continue
            launcher = project / "run.sh"
            assert_true("./run.sh" in readme, f"{project.name} must document its launcher")
            assert_true(launcher.is_file(), f"{project.name} must generate run.sh")
            assert_true(launcher.stat().st_mode & 0o111 != 0, f"{project.name} run.sh must be executable")
        dashboard_main = (dashboard_project / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        dashboard_css = (dashboard_project / "frontend" / "src" / "app.css").read_text(encoding="utf-8")
        assert_true('"./app.css"' in dashboard_main, "dashboard frontend must load its Tailwind entry")
        assert_true('from "oldman-web/core"' in dashboard_main, "dashboard frontend must start the public Oldman runtime")
        assert_true("import.meta.glob" in dashboard_main, "dashboard frontend must load generated page entries")
        assert_true("oldman-web/styles/tailwind.css" in dashboard_css, "dashboard Tailwind entry must consume the public oldman-web style export")
        assert_true("oldman-web/styles/icons.css" in dashboard_css, "dashboard entry must consume the shared oldman-web icon export")
        assert_true("./generated/icons.css" in dashboard_css, "dashboard entry must consume its generated business icons")
        assert_true('../../apps/**/*.py' in dashboard_css, "dashboard Tailwind entry must scan business Python emitters")
        dashboard_package = json.loads((dashboard_project / "frontend" / "package.json").read_text(encoding="utf-8"))
        assert_true("oldman-web-icons" in dashboard_package["scripts"]["generate:icons"], "dashboard must generate consumer icons")
        assert_true((dashboard_project / "frontend" / "src" / "generated" / "icons.css").exists(), "dashboard must include initial generated icons")

        with working_directory(api_project):
            start_app(
                "Report API",
                app_type=AppType.API,
                display_name="Report API",
            )
            start_service("report_api", service_type=ServiceType.WEB)
        with working_directory(dashboard_project):
            start_app(
                "Admin Area",
                app_type=AppType.DASHBOARD,
                display_name="Admin Area",
            )

        assert_true((api_project / "apps" / "report_api" / "apps.py").exists(), "api startapp must create App metadata")
        assert_true((api_project / "services" / "report_api.py").exists(), "startservice must create a service entry")
        assert_true((dashboard_project / "frontend" / "src" / "pages" / "admin_area.ts").exists(), "dashboard startapp must create frontend page stub")
        assert_true(not (dashboard_project / "services" / "admin_area.py").exists(), "dashboard startapp must not create a service entry")
        dashboard_page = (dashboard_project / "frontend" / "src" / "pages" / "admin_area.ts").read_text(encoding="utf-8")
        assert_true("DashboardPage" in dashboard_page, "dashboard page must use the shared DashboardPage")
        assert_true("createDashboardComponentLoaders" in dashboard_page, "dashboard page must use shared component loaders")


def main() -> int:
    """Run scaffold verification."""
    verify_template_resources()
    verify_generation()
    print("Oldman scaffold verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
