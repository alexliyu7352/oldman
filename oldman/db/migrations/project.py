"""Collect the project-wide App and database view used by migration commands."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from ruamel.yaml import YAML

from oldman.apps import AppRegistry
from oldman.auth.settings import AuthSettings
from oldman.conf.constants import _find_project_root
from oldman.runtime.discovery import discover_service_definitions


@dataclass(frozen=True, slots=True)
class ServiceMigrationConfig:
    """Schema-relevant fields read from one real service configuration."""

    module_name: str
    config_file: Path
    app_packages: tuple[str, ...]
    database_url: str | None
    user_model_path: str | None


@dataclass(frozen=True, slots=True)
class MigrationProject:
    """One complete migration owner view assembled without service bootstrap."""

    project_root: Path
    project_id: UUID
    project_name: str
    database_url: str
    service_configs: tuple[ServiceMigrationConfig, ...]
    apps: AppRegistry
    user_model_path: str | None


@dataclass(frozen=True, slots=True)
class _ProjectMetadata:
    """Validated migration metadata stored in the project's pyproject.toml."""

    project_id: UUID
    project_name: str
    migration_apps: tuple[str, ...]


def load_migration_project(project_root: Path | None = None) -> MigrationProject:
    """Load the sole project migration context without importing service modules."""
    root = (project_root if project_root is not None else _find_project_root()).expanduser().resolve()
    metadata = _read_project_metadata(root / "pyproject.toml")
    definitions = discover_service_definitions(root)
    if not definitions:
        raise ValueError("Oldman database commands require at least one real service in services/.")

    config_paths = {
        module_name: root / "data" / f"{module_name}_settings.yaml"
        for module_name in definitions
    }
    missing = [path for path in config_paths.values() if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path.relative_to(root)) for path in missing)
        raise ValueError(f"Service settings files are missing: {rendered}")

    service_configs = tuple(
        _read_service_config(module_name, config_paths[module_name])
        for module_name in definitions
    )
    database_url = _resolve_database_url(service_configs)
    user_model_path = _resolve_user_model(service_configs, metadata.migration_apps)

    app_packages = _ordered_union(
        package
        for config in service_configs
        for package in config.app_packages
    )
    app_packages = _ordered_union((*app_packages, *metadata.migration_apps))
    registry = AppRegistry()
    registry.register_packages(app_packages)

    return MigrationProject(
        project_root=root,
        project_id=metadata.project_id,
        project_name=metadata.project_name,
        database_url=database_url,
        service_configs=service_configs,
        apps=registry,
        user_model_path=user_model_path,
    )


def _read_project_metadata(path: Path) -> _ProjectMetadata:
    """Read committed project identity and migration-only App packages."""
    if not path.is_file():
        raise ValueError(f"Project metadata file is missing: {path}")
    source = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        if source.count("project_id") > 1:
            raise ValueError("pyproject.toml defines project_id more than once.") from None
        raise ValueError(f"pyproject.toml is invalid: {exc}") from None

    project = data.get("project")
    if not isinstance(project, Mapping):
        raise ValueError("pyproject.toml must define [project].")
    project_name = project.get("name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("pyproject.toml [project].name must be a non-empty string.")

    tool = data.get("tool", {})
    oldman = tool.get("oldman", {}) if isinstance(tool, Mapping) else {}
    if not isinstance(oldman, Mapping):
        raise ValueError("pyproject.toml [tool.oldman] must be a table.")

    raw_project_id = oldman.get("project_id")
    if raw_project_id is None:
        generated = uuid4()
        raise ValueError(
            "Oldman database commands require a committed project UUID. Add:\n\n"
            "[tool.oldman]\n"
            f'project_id = "{generated}"'
        )
    if not isinstance(raw_project_id, str):
        raise ValueError("pyproject.toml [tool.oldman].project_id must be a UUID string.")
    try:
        project_id = UUID(raw_project_id)
    except ValueError:
        raise ValueError("pyproject.toml [tool.oldman].project_id must be a valid UUID.") from None

    raw_migration_apps = oldman.get("migration_apps", [])
    if not isinstance(raw_migration_apps, list):
        raise ValueError("pyproject.toml [tool.oldman].migration_apps must be a list of package paths.")
    migration_apps = _validate_app_packages(raw_migration_apps, "[tool.oldman].migration_apps")
    return _ProjectMetadata(
        project_id=project_id,
        project_name=project_name.strip(),
        migration_apps=migration_apps,
    )


def _read_service_config(module_name: str, path: Path) -> ServiceMigrationConfig:
    """Read only App, database URL and Auth User selection from one YAML file."""
    yaml = YAML(typ="safe", pure=True)
    try:
        data = yaml.load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot read service settings {path}: {exc}") from None
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Service settings must be a mapping: {path}")

    raw_apps = data.get("apps", [])
    if not isinstance(raw_apps, list):
        raise ValueError(f"settings.apps must be a YAML list in {path}")
    app_packages = _validate_app_packages(raw_apps, f"settings.apps in {path}")
    database_url = _read_database_url(data, path)
    user_model_path = _read_user_model(module_name, data, app_packages, path)
    return ServiceMigrationConfig(
        module_name=module_name,
        config_file=path.resolve(),
        app_packages=app_packages,
        database_url=database_url,
        user_model_path=user_model_path,
    )


def _read_database_url(data: Mapping[str, Any], path: Path) -> str | None:
    """Return an unchanged non-empty database URL without resolving credentials."""
    database = data.get("database")
    if database is None:
        return None
    if not isinstance(database, Mapping):
        raise ValueError(f"settings.database must be a mapping in {path}")
    raw_url = database.get("url")
    if raw_url is None or raw_url == "":
        return None
    if not isinstance(raw_url, str):
        raise ValueError(f"settings.database.url must be a string in {path}")
    if not raw_url.strip():
        return None
    return raw_url


def _read_user_model(
    module_name: str,
    data: Mapping[str, Any],
    app_packages: tuple[str, ...],
    path: Path,
) -> str | None:
    """Validate only Auth's schema-changing App setting for one service."""
    app_settings = data.get("app_settings", {})
    has_auth = "oldman.auth" in app_packages
    if isinstance(app_settings, Mapping):
        raw_auth = app_settings.get("auth")
    elif has_auth:
        raise ValueError(f"settings.app_settings must be a mapping in {path}")
    else:
        raw_auth = None

    if not has_auth:
        if raw_auth is not None:
            raise ValueError(f"Service {module_name!r} configures app_settings.auth without installing oldman.auth.")
        return None

    if raw_auth is None:
        raw_auth = {}
    if not isinstance(raw_auth, Mapping):
        raise ValueError(f"app_settings.auth must be a mapping in {path}")
    try:
        user_model_path = AuthSettings.model_validate(raw_auth).user_model
    except ValidationError as exc:
        raise ValueError(f"Invalid app_settings.auth in {path}: {exc}") from None

    owner_package = _model_package(user_model_path, app_packages)
    if owner_package is None:
        raise ValueError(
            f"Service {module_name!r} selects User model {user_model_path!r}, "
            "but its owning App is not listed in that service's settings.apps."
        )
    return user_model_path


def _resolve_database_url(service_configs: tuple[ServiceMigrationConfig, ...]) -> str:
    """Require one exact database URL across every database-backed service."""
    configured = [config for config in service_configs if config.database_url is not None]
    if not configured:
        raise ValueError("Oldman database commands require a non-empty database.url in at least one real service.")
    urls = {config.database_url for config in configured}
    if len(urls) != 1:
        services = ", ".join(f"{config.module_name} ({config.config_file.name})" for config in configured)
        raise ValueError(f"database.url conflicts across service settings: {services}. Values are hidden because they may contain credentials.")
    database_url = configured[0].database_url
    assert database_url is not None
    return database_url


def _resolve_user_model(
    service_configs: tuple[ServiceMigrationConfig, ...],
    migration_apps: tuple[str, ...],
) -> str | None:
    """Require one normalized concrete User across all Auth-enabled services."""
    configured = [config for config in service_configs if config.user_model_path is not None]
    if not configured:
        if "oldman.auth" in migration_apps:
            raise ValueError("oldman.auth appears only in migration_apps; at least one real service must install and configure Auth.")
        return None
    paths = {config.user_model_path for config in configured}
    if len(paths) != 1:
        services = ", ".join(config.module_name for config in configured)
        raise ValueError(f"auth.user_model conflicts across services: {services}.")
    user_model_path = configured[0].user_model_path
    assert user_model_path is not None
    return user_model_path


def _model_package(model_path: str, packages: tuple[str, ...]) -> str | None:
    """Match a model path to the longest explicitly installed package boundary."""
    module_name, separator, _ = model_path.rpartition(".")
    if not separator:
        return None
    matches = [
        package
        for package in packages
        if module_name == package or module_name.startswith(f"{package}.")
    ]
    return max(matches, key=len) if matches else None


def _validate_app_packages(values: list[Any], source: str) -> tuple[str, ...]:
    """Validate raw package strings while leaving App identity to AppRegistry."""
    packages: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{source}[{index}] must be a non-empty package path.")
        packages.append(value)
    return tuple(packages)


def _ordered_union(values: Any) -> tuple[str, ...]:
    """Deduplicate App membership without assigning order dependency semantics."""
    return tuple(dict.fromkeys(values))


__all__ = [
    "MigrationProject",
    "ServiceMigrationConfig",
    "load_migration_project",
]
