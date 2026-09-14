"""Programmatic Alembic environment and App revision graph."""

from __future__ import annotations

import importlib
import importlib.util
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util.exc import CommandError

from oldman.db.migrations.metadata import load_migration_metadata
from oldman.db.migrations.project import MigrationProject

VERSION_TABLE_NAME = "oldman_alembic_version"
TEMPLATE_DIRECTORY = Path(__file__).with_name("templates")


class MigrationGraphError(ValueError):
    """Raised when installed App revisions do not form valid independent branches."""


@dataclass(frozen=True, slots=True)
class AppMigrationLocation:
    """One registered App's conventional Alembic version location."""

    package: str
    label: str
    module_name: str
    path: Path
    exists: bool


@dataclass(frozen=True, slots=True)
class AppRevisionBranch:
    """Validated revisions and current heads belonging to one App label."""

    location: AppMigrationLocation
    revisions: tuple[Script, ...]
    heads: tuple[Script, ...]


@dataclass(frozen=True, slots=True)
class MigrationGraph:
    """Alembic's native ScriptDirectory plus App-scoped read-only views."""

    script_directory: ScriptDirectory
    branches: Mapping[str, AppRevisionBranch]

    @property
    def heads(self) -> tuple[Script, ...]:
        """Return Alembic's effective project heads after dependency resolution."""
        branch_heads = tuple(script for branch in self.branches.values() for script in branch.heads)
        return tuple(
            script
            for script in branch_heads
            if not any(script.revision in self.revision_closure((other.revision,)) for other in branch_heads if other is not script)
        )

    def revision_closure(self, revisions: tuple[str, ...]) -> frozenset[str]:
        """Expand version rows through standard down_revision and depends_on edges."""
        seen: set[str] = set()
        pending = list(revisions)
        while pending:
            revision = pending.pop()
            if revision in seen:
                continue
            script = self.script_directory.get_revision(revision)
            if script is None:
                continue
            seen.add(revision)
            pending.extend(_revision_ids(script.down_revision))
            pending.extend(_revision_ids(script.dependencies))
        return frozenset(seen)


def collect_migration_locations(project: MigrationProject) -> tuple[AppMigrationLocation, ...]:
    """Resolve only registered App migration modules without scanning directories."""
    locations: list[AppMigrationLocation] = []
    for package, app in zip(project.apps.packages, project.apps.configs, strict=True):
        module_name = f"{package}.{app.migrations_module}"
        path = _module_directory(package, app.migrations_module)
        locations.append(
            AppMigrationLocation(
                package=package,
                label=app.label,
                module_name=module_name,
                path=path,
                exists=path.is_dir(),
            )
        )
    return tuple(locations)


def build_alembic_config(project: MigrationProject) -> Config:
    """Build Alembic Config entirely in memory for the complete project schema."""
    migration_metadata = load_migration_metadata(project)
    locations = collect_migration_locations(project)
    config = Config()
    config.set_main_option("script_location", _config_value(TEMPLATE_DIRECTORY))
    config.set_main_option("path_separator", "os")
    config.set_main_option(
        "version_locations",
        _config_value(os.pathsep.join(str(location.path) for location in locations if location.exists)),
    )
    config.set_main_option("sqlalchemy.url", _config_value(project.database_url))
    config.set_main_option("version_table", VERSION_TABLE_NAME)
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
    config.set_main_option("output_encoding", "utf-8")
    config.set_main_option("revision_environment", "true")
    config.attributes["oldman_project"] = project
    config.attributes["oldman_metadata"] = migration_metadata
    config.attributes["oldman_locations"] = locations
    return config


def load_migration_graph(
    project: MigrationProject,
    *,
    config: Config | None = None,
) -> MigrationGraph:
    """Parse Alembic revisions and validate each App's independent branch contract."""
    resolved_config = config if config is not None else build_alembic_config(project)
    locations = _config_locations(resolved_config)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            script_directory = ScriptDirectory.from_config(resolved_config)
            revisions_descending = tuple(
                script_directory.walk_revisions(base="base", head="heads")
            )
    except (CommandError, RevisionError, UserWarning) as exc:
        raise MigrationGraphError(f"Invalid Alembic revision graph: {exc}") from None

    location_by_path = {
        location.path.resolve(): location
        for location in locations
        if location.exists
    }
    revision_locations: dict[str, AppMigrationLocation] = {}
    revisions_by_label: dict[str, list[Script]] = {
        location.label: [] for location in locations
    }
    for revision in revisions_descending:
        parent = Path(revision.path).resolve().parent
        location = location_by_path.get(parent)
        if location is None:
            raise MigrationGraphError(
                f"Revision {revision.revision!r} is outside every registered App migration location."
            )
        revision_locations[revision.revision] = location
        revisions_by_label[location.label].append(revision)

    branches: dict[str, AppRevisionBranch] = {}
    for location in locations:
        revisions = tuple(reversed(revisions_by_label[location.label]))
        _validate_app_branch(location, revisions, revision_locations)
        heads = tuple(
            sorted(
                (revision for revision in revisions if revision.is_head),
                key=lambda revision: revision.revision,
            )
        )
        branches[location.label] = AppRevisionBranch(
            location=location,
            revisions=revisions,
            heads=heads,
        )
    return MigrationGraph(
        script_directory=script_directory,
        branches=MappingProxyType(branches),
    )


def _validate_app_branch(
    location: AppMigrationLocation,
    revisions: tuple[Script, ...],
    revision_locations: Mapping[str, AppMigrationLocation],
) -> None:
    """Require one labeled base and App-local down_revision edges."""
    if not revisions:
        return
    bases = [revision for revision in revisions if revision.down_revision is None]
    if len(bases) != 1:
        raise MigrationGraphError(
            f"App {location.label!r} must contain exactly one base revision; found {len(bases)}."
        )
    base = bases[0]
    if _declared_branch_labels(base) != (location.label,):
        raise MigrationGraphError(
            f"App {location.label!r} base revision {base.revision!r} must declare "
            f"branch_labels=({location.label!r},)."
        )

    for revision in revisions:
        if revision is not base and _declared_branch_labels(revision):
            raise MigrationGraphError(
                f"App {location.label!r} revision {revision.revision!r} repeats branch_labels; "
                "only the base revision may declare it."
            )
        for down_revision in _revision_ids(revision.down_revision):
            down_location = revision_locations.get(down_revision)
            if down_location is None:
                raise MigrationGraphError(
                    f"Revision {revision.revision!r} refers to unknown down_revision {down_revision!r}."
                )
            if down_location.label != location.label:
                raise MigrationGraphError(
                    f"Revision {revision.revision!r} in App {location.label!r} uses "
                    f"down_revision from App {down_location.label!r}; cross-App edges must use depends_on."
                )


def _config_locations(config: Config) -> tuple[AppMigrationLocation, ...]:
    """Read locations attached by build_alembic_config without reconstructing them."""
    value = config.attributes.get("oldman_locations")
    if not isinstance(value, tuple) or not all(
        isinstance(item, AppMigrationLocation) for item in value
    ):
        raise TypeError("Alembic Config does not contain Oldman App migration locations.")
    return value


def _module_directory(package: str, relative_module: str) -> Path:
    """Resolve one conventional package-relative module directory, existing or not."""
    package_module = importlib.import_module(package)
    package_paths = tuple(Path(path).resolve() for path in getattr(package_module, "__path__", ()))
    if len(package_paths) != 1:
        raise MigrationGraphError(
            f"App package {package!r} must resolve to exactly one filesystem directory."
        )
    path = package_paths[0].joinpath(*relative_module.split("."))
    if path.exists() and not path.is_dir():
        raise MigrationGraphError(
            f"App migration module {package}.{relative_module} must be a package directory."
        )
    if path.is_dir():
        spec = importlib.util.find_spec(f"{package}.{relative_module}")
        if spec is None or spec.submodule_search_locations is None:
            raise MigrationGraphError(
                f"App migration module {package}.{relative_module} is not an importable package."
            )
    return path.resolve()


def _declared_branch_labels(revision: Script) -> tuple[str, ...]:
    """Read labels declared in this file rather than inherited graph labels."""
    value = getattr(revision.module, "branch_labels", None)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _revision_ids(value: Any) -> tuple[str, ...]:
    """Normalize Alembic's scalar-or-tuple revision reference."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _config_value(value: str | Path) -> str:
    """Escape ConfigParser interpolation while preserving the logical value."""
    return str(value).replace("%", "%%")


__all__ = [
    "AppMigrationLocation",
    "AppRevisionBranch",
    "MigrationGraph",
    "MigrationGraphError",
    "VERSION_TABLE_NAME",
    "build_alembic_config",
    "collect_migration_locations",
    "load_migration_graph",
]
