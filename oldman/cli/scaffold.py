"""Project and app scaffold generation."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from uuid import uuid4

from oldman.cli.agent_instructions import agent_instructions
from oldman.conf.constants import _find_project_root
from oldman.version import __VERSION__

FRAMEWORK_VERSION = __VERSION__


class ProjectType(StrEnum):
    """Supported project scaffold types."""

    CLI = "cli"
    SERVICE = "service"
    API = "api"
    WEB = "web"
    DASHBOARD = "dashboard"


class AppType(StrEnum):
    """Supported app scaffold types."""

    SERVICE = "service"
    API = "api"
    WEB = "web"
    DASHBOARD = "dashboard"


class ServiceType(StrEnum):
    """Supported standalone service scaffold types."""

    SIMPLE = "simple"
    WEB = "web"
    TASKIQ_WORKER = "taskiq_worker"
    TASKIQ_SCHEDULER = "taskiq_scheduler"


class DatabaseChoice(StrEnum):
    """Database dependency presets written to generated projects."""

    NONE = "none"
    SQLITE = "sqlite"
    MYSQL = "mysql"
    POSTGRES = "postgres"


@dataclass(frozen=True)
class CreatedApp:
    """Created app metadata."""

    app_slug: str
    project_root: Path


@dataclass(frozen=True)
class CreatedService:
    """Created service metadata."""

    service_name: str
    project_root: Path


PROJECT_TEMPLATE_DIRS = {
    ProjectType.CLI: "cli_app",
    ProjectType.SERVICE: "app_service",
    ProjectType.API: "api_service",
    ProjectType.WEB: "web_service",
    ProjectType.DASHBOARD: "dashboard",
}
# Files every project gets on top of its type's (AGENTS.md, CLAUDE.md).
COMMON_PROJECT_TEMPLATE_DIR = "common"

APP_TEMPLATE_DIRS = {
    AppType.SERVICE: "service_app",
    AppType.API: "api_app",
    AppType.WEB: "web_app",
    AppType.DASHBOARD: "dashboard_app",
}

SERVICE_TEMPLATE_DIRS = {
    ServiceType.SIMPLE: "simple",
    ServiceType.WEB: "web",
    ServiceType.TASKIQ_WORKER: "taskiq_worker",
    ServiceType.TASKIQ_SCHEDULER: "taskiq_scheduler",
}

PROJECT_SERVICE_NAMES = {
    ProjectType.SERVICE: "service",
    ProjectType.API: "api",
    ProjectType.WEB: "web",
    ProjectType.DASHBOARD: "dashboard",
}

PROJECT_SERVICE_CLASSES = {
    ProjectType.SERVICE: "ServiceApplication",
    ProjectType.API: "ApiService",
    ProjectType.WEB: "WebService",
    ProjectType.DASHBOARD: "DashboardService",
}

# The project types that can include the built-in Admin: it has pages and signs users in.
ADMIN_PROJECT_TYPES = frozenset({ProjectType.WEB, ProjectType.DASHBOARD})

# A project with users has the roles beside them (who may do what), whether or not it has the Admin.
USER_APPS = ("oldman.auth", "oldman.apps.roles")
ADMIN_APP = "oldman.apps.admin"
# The dashboard skeleton: notifications, then the project's own accounts (User model, sign-in pages) and home page.
DASHBOARD_APPS = ("oldman.web.messages.notifications",)
DASHBOARD_PROJECT_APPS = ("apps.accounts", "apps.home")
# The web skeleton: the project's welcome page.
WEB_PROJECT_APPS = ("apps.home",)
# The API skeleton: a health check and an endpoint for each way a program signs in.
API_PROJECT_APPS = ("apps.home",)

ADMIN_IMPORT = "from oldman.apps.admin import install_admin\n"

# The last step of the web and dashboard services' init().
ADMIN_INSTALL = """        # The built-in Admin, under app_settings.admin.prefix.
        install_admin(app)
"""

# The web welcome page's link to the Admin, by route name so it follows the prefix setting.
WEB_HOME_ADMIN = """    <p><a href="{{ url_for("oldman_admin_index") }}">{{ _("Sign in to the Admin") }}</a></p>
"""

# The dashboard's menu entry for the Admin, for staff (the Admin's own floor): a whole-page link, by route
# name so it follows the prefix setting.
DASHBOARD_SIDEBAR_ADMIN = """  {% if request.ctx.user.is_staff %}
    {{ sidebar_menu_item(url_for("oldman_admin_index"), _("Admin"), turbo=false) }}
  {% endif %}
"""

SESSION_SETTINGS = """web:
  session:
    enabled: true
"""

DB_DEPENDENCIES = {
    DatabaseChoice.NONE: "",
    DatabaseChoice.SQLITE: "",
    DatabaseChoice.MYSQL: '    "aiomysql>=0.3",',
    DatabaseChoice.POSTGRES: '    "asyncpg>=0.29",',
}

DB_URLS = {
    DatabaseChoice.NONE: "",
    DatabaseChoice.SQLITE: "sqlite+aiosqlite:///data/app.db",
    DatabaseChoice.MYSQL: "mysql+aiomysql://user:password@127.0.0.1:3306/app",
    DatabaseChoice.POSTGRES: "postgresql+asyncpg://user:password@127.0.0.1:5432/app",
}


def start_project(
    name: str,
    *,
    project_type: ProjectType,
    db: DatabaseChoice = DatabaseChoice.NONE,
    admin: bool = False,
) -> Path:
    """Create one project after all template choices have been collected.

    `admin` adds the built-in Admin (web and dashboard projects, which need a database for it).
    """
    project_name = name.strip()
    if not project_name:
        raise ValueError("Project name cannot be empty")
    target = Path(project_name).resolve()
    context = project_context(target.name, project_type=project_type, db=db, admin=admin)
    ensure_writable_directory(target)
    copy_template_tree(
        (scaffold_root("project", PROJECT_TEMPLATE_DIRS[project_type]), scaffold_root("project", COMMON_PROJECT_TEMPLATE_DIR)),
        target,
        context=context,
    )
    service_name = PROJECT_SERVICE_NAMES.get(project_type)
    if service_name is not None:
        settings_path = target / "data" / f"{service_name}_settings.yaml"
        settings_path.chmod(0o600)
        (target / "run.sh").chmod(0o755)
    return target


def start_app(
    name: str,
    *,
    app_type: AppType,
    display_name: str,
) -> CreatedApp:
    """Create one App package in the discovered Oldman project."""
    app_slug = slugify_name(name)
    normalized_display_name = display_name.strip()
    if not normalized_display_name:
        raise ValueError("App display name cannot be empty")
    target_root = _find_project_root()
    app_root = target_root / "apps" / app_slug
    if app_root.exists():
        raise FileExistsError(f"Target app already exists: {app_root}")
    context = {
        "app_slug": app_slug,
        "app_class": pascal_case(app_slug),
        "app_type": app_type.value,
        "display_name_literal": repr(normalized_display_name),
    }
    copy_template_tree(
        (scaffold_root("app", APP_TEMPLATE_DIRS[app_type]),),
        target_root,
        context=context,
    )
    return CreatedApp(app_slug=app_slug, project_root=target_root)


def start_service(name: str, *, service_type: ServiceType) -> CreatedService:
    """Create one standalone service module in the discovered project."""
    service_name = validate_service_name(name)
    target_root = _find_project_root()
    target = target_root / "services" / f"{service_name}.py"
    if target.exists():
        raise FileExistsError(f"Target service already exists: {target}")
    context = {
        "service_name": service_name,
        "service_class": f"{pascal_case(service_name)}Service",
    }
    copy_template_tree(
        (scaffold_root("service", SERVICE_TEMPLATE_DIRS[service_type]),),
        target_root,
        context=context,
    )
    return CreatedService(service_name=service_name, project_root=target_root)


def ensure_writable_directory(path: Path) -> None:
    """Ensure a scaffold target can be written."""
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Target directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def scaffold_root(scope: str, name: str):
    """Return a package resource directory."""
    return files("oldman.scaffolds").joinpath(scope, name)


def copy_template_tree(
    template_roots: Sequence[Traversable],
    target_root: Path,
    *,
    context: dict[str, str],
) -> None:
    """Copy one or more template trees into one target, after checking every destination before writing any."""
    resources = [
        (resource, target_root / render_path(relative, context))
        for template_root in template_roots
        for resource, relative in iter_template_resources(template_root)
        if resource.name != ".gitkeep"
    ]
    files_by_destination: dict[Path, Traversable] = {}
    for resource, destination in resources:
        if resource.is_dir():
            continue
        if destination in files_by_destination:
            # Two trees writing one file is a scaffold bug; one of them would silently win.
            raise FileExistsError(f"Two template trees both write {destination}")
        files_by_destination[destination] = resource
    for resource, destination in resources:
        if resource.is_dir():
            if destination.exists() and not destination.is_dir():
                raise FileExistsError(f"Target path is not a directory: {destination}")
            continue
        if destination.exists():
            raise FileExistsError(f"Target file already exists: {destination}")

    for resource, destination in resources:
        if resource.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if resource.name.endswith(".tpl"):
            destination.write_text(render_text(resource.read_text(encoding="utf-8"), context), encoding="utf-8")
        else:
            with resource.open("rb") as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def iter_template_resources(root: Traversable, relative: Path = Path()):
    """Yield template resources with a filesystem-like relative path."""
    for child in root.iterdir():
        child_relative = relative / child.name
        yield child, child_relative
        if child.is_dir():
            yield from iter_template_resources(child, child_relative)


def project_apps(project_type: ProjectType, *, admin: bool) -> tuple[str, ...]:
    """The App packages a new project's service installs: the framework's first, the project's own last."""
    admin_apps = (ADMIN_APP,) if admin else ()
    if project_type == ProjectType.DASHBOARD:
        return (*USER_APPS, *DASHBOARD_APPS, *admin_apps, *DASHBOARD_PROJECT_APPS)
    if project_type == ProjectType.WEB:
        user_apps = (*USER_APPS, *admin_apps) if admin else ()
        return (*user_apps, *WEB_PROJECT_APPS)
    if project_type == ProjectType.API:
        return API_PROJECT_APPS
    return ()


def project_context(project_name: str, *, project_type: ProjectType, db: DatabaseChoice, admin: bool = False) -> dict[str, str]:
    """Return template context for a generated project."""
    if project_type == ProjectType.CLI and db != DatabaseChoice.NONE:
        raise ValueError("CLI projects do not create a service database configuration")
    if project_type == ProjectType.DASHBOARD and db == DatabaseChoice.NONE:
        raise ValueError("Dashboard projects require SQLite, MySQL, or PostgreSQL")
    if admin and project_type not in ADMIN_PROJECT_TYPES:
        raise ValueError("Only web and dashboard projects can include the built-in Admin")
    if admin and db == DatabaseChoice.NONE:
        raise ValueError("The built-in Admin keeps its users in a database; choose SQLite, MySQL, or PostgreSQL")
    project_slug = slugify_name(project_name)
    service_name = PROJECT_SERVICE_NAMES.get(project_type, "")
    apps = project_apps(project_type, admin=admin)
    settings_apps = "".join(f"\n  - {package}" for package in apps) if apps else " []"
    database_url = DB_URLS[db]
    return {
        **agent_instructions(project_type.value, admin=admin, service_name=service_name),
        "project_name": project_name,
        "project_slug": project_slug,
        "project_type": project_type.value,
        "framework_version": FRAMEWORK_VERSION,
        "project_id": str(uuid4()),
        "service_name": service_name,
        "service_class": PROJECT_SERVICE_CLASSES.get(project_type, ""),
        "settings_apps": settings_apps,
        # Signing in to the Admin needs sessions; the dashboard skeleton turns them on for its own sign-in.
        "settings_session": SESSION_SETTINGS if admin else "",
        "admin_import": ADMIN_IMPORT if admin else "",
        "admin_install": ADMIN_INSTALL if admin else "",
        "web_home_admin": WEB_HOME_ADMIN if admin else "",
        # The API skeleton's caller credentials (web.auth): new for every project, kept only in its settings file.
        "api_example_key": secrets.token_urlsafe(32) if project_type == ProjectType.API else "",
        "api_ops_password": secrets.token_urlsafe(32) if project_type == ProjectType.API else "",
        "dashboard_sidebar_admin": DASHBOARD_SIDEBAR_ADMIN if admin else "",
        "readme_admin_wiring": "、内置 Admin（`app_settings.admin.prefix`，默认 `/admin`，与站点共用登录）" if admin else "",
        # A double-quoted YAML string, whatever the directory is called.
        "project_name_yaml": json.dumps(project_name, ensure_ascii=False),
        "database_url": f'"{database_url}"' if database_url else "null",
        "database_migrate_step": ("./run.sh db migrate\n" if db != DatabaseChoice.NONE else ""),
        "db_dependency_line": DB_DEPENDENCIES[db],
        "frontend_dependency": f'"oldman-web": "^{FRAMEWORK_VERSION}"' if project_type == ProjectType.DASHBOARD else "",
    }


def render_path(path: Path, context: dict[str, str]) -> Path:
    """Render placeholders in a resource path."""
    rendered_parts = [render_text(part, context) for part in path.parts]
    filename = Path(*rendered_parts)
    if filename.suffix == ".tpl":
        filename = filename.with_suffix("")
    return filename


def render_text(text: str, context: dict[str, str]) -> str:
    """Render simple ``{{ name }}`` placeholders."""
    rendered = text
    for key, value in context.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
        rendered = rendered.replace("__" + key + "__", value)
    return rendered


def slugify_name(value: str) -> str:
    """Normalize a user-facing name into a Python package slug."""
    slug = re.sub(r"[^0-9A-Za-z]+", "_", value.strip()).strip("_").lower()
    if not slug:
        raise ValueError("Name cannot be converted to a slug")
    if slug[0].isdigit():
        slug = f"app_{slug}"
    return slug


def humanize_name(value: str) -> str:
    """Return a readable display-name suggestion for one App name."""
    return " ".join(part.capitalize() for part in slugify_name(value).split("_"))


def validate_service_name(value: str) -> str:
    """Validate a service module name against cold discovery's contract."""
    name = value.strip()
    if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
        raise ValueError(f"Service name must match [a-z][a-z0-9_]* (lowercase letters, numbers, and underscores); received {value!r}")
    return name


def pascal_case(value: str) -> str:
    """Return PascalCase for class names."""
    return "".join(part.capitalize() for part in slugify_name(value).split("_"))
