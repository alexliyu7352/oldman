"""Write one reviewed App revision from grouped Alembic operations."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from alembic import op
from alembic.autogenerate import render, render_python_code
from alembic.migration import MigrationContext
from alembic.operations import ops
from alembic.script import Script
from alembic.util import rev_id
from sqlalchemy import Connection
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.ext.asyncio import create_async_engine

from oldman.db.migrations.alembic import (
    AppMigrationLocation,
    build_alembic_config,
    collect_migration_locations,
    load_migration_graph,
)
from oldman.db.migrations.autogenerate import (
    AppSchemaChanges,
    MigrationAdoptionConflict,
    MigrationModelChangeRequired,
    OwnershipChange,
    attach_cross_app_dependencies,
    collect_schema_changes,
    resolve_schema_intent,
    table_structure_errors,
)
from oldman.db.migrations.interaction import MigrationInteraction
from oldman.db.migrations.metadata import load_migration_metadata
from oldman.db.migrations.project import MigrationProject


@render.renderers.dispatch_for(ops.RenameTableOp, replace=True)
def _render_rename_table(
    autogen_context: object,
    operation: ops.RenameTableOp,
) -> str:
    """Render Alembic's built-in rename operation, which has no autogen renderer."""
    del autogen_context
    arguments = f"{operation.table_name!r}, {operation.new_table_name!r}"
    if operation.schema is not None:
        arguments += f", schema={operation.schema!r}"
    return f"op.rename_table({arguments})"


class MigrationRevisionWriteError(RuntimeError):
    """Raised when a revision cannot safely be written to App source."""


class AdoptionRevisionError(RuntimeError):
    """Raised when a guarded adoption revision is missing or was edited."""


@dataclass(frozen=True, slots=True)
class AdoptionExecutionPlan:
    """Tell migrate whether a guarded adoption can run normally or skip CREATE."""

    adoption_tables: tuple[str, ...]
    skip_schema: bool


@dataclass(frozen=True, slots=True)
class GeneratedMigration:
    """The one candidate revision written by a makemigrations invocation."""

    app_label: str
    message: str
    revision: str
    path: Path
    adoption_tables: tuple[str, ...] = ()


def make_migration(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> GeneratedMigration | None:
    """Compare the project database and write at most one selected App revision."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("make_migration() must be called from a synchronous CLI context.")
    merge_handled, merge_revision = _merge_multiple_heads(project, interaction)
    if merge_handled:
        return merge_revision
    return asyncio.run(_make_migration(project, interaction))


def _merge_multiple_heads(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> tuple[bool, GeneratedMigration | None]:
    """Offer one standard merge revision before opening the database."""
    graph = load_migration_graph(project)
    candidates = tuple(sorted(label for label, branch in graph.branches.items() if len(branch.heads) > 1))
    if not candidates:
        return False, None
    app_label = candidates[0] if len(candidates) == 1 else interaction.choose("Multiple Apps have divergent migration heads.", candidates)
    if app_label not in candidates:
        raise ValueError(f"Unknown App merge selection: {app_label!r}.")
    try:
        location = _writable_location(project, app_label)
    except MigrationRevisionWriteError as exc:
        raise MigrationRevisionWriteError(f"{exc} Upgrade the third-party App to a release with one migration head.") from None
    heads = tuple(revision.revision for revision in graph.branches[app_label].heads)
    rendered_heads = ", ".join(heads)
    if not interaction.confirm(
        f"App {app_label!r} has migration heads {rendered_heads}. Create a merge revision?",
        default=False,
    ):
        return True, None
    suggested_message = f"merge {app_label} heads"
    message = interaction.text(
        "Migration description",
        default=suggested_message,
    ).strip()
    if not message:
        raise ValueError("Migration description cannot be empty.")
    _ensure_migration_package(location)
    generated = graph.script_directory.generate_revision(
        rev_id(),
        message,
        head=heads,
        version_path=str(location.path),
        upgrades="",
        downgrades="",
        imports="",
    )
    if not isinstance(generated, Script):
        raise RuntimeError("Alembic did not write exactly one merge revision file.")
    return True, GeneratedMigration(
        app_label=app_label,
        message=message,
        revision=generated.revision,
        path=Path(generated.path).resolve(),
    )


async def _make_migration(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> GeneratedMigration | None:
    """Use the configured async driver without exposing a second database URL."""
    engine = create_async_engine(project.database_url)
    try:
        async with engine.connect() as async_connection:
            return await async_connection.run_sync(
                _make_migration_with_connection,
                project,
                interaction,
            )
    finally:
        await engine.dispose()


def _make_migration_with_connection(
    connection: Connection,
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> GeneratedMigration | None:
    """Keep comparison and revision rendering on one connection snapshot."""
    changes = collect_schema_changes(project, connection)
    if changes.by_app:
        candidates = tuple(changes.by_app)
        app_label = candidates[0] if len(candidates) == 1 else interaction.choose("Multiple Apps have schema changes.", candidates)
        if app_label not in changes.by_app:
            raise ValueError(f"Unknown changed App selection: {app_label!r}.")
        selected = changes.by_app[app_label]
    else:
        candidates = tuple(sorted(project.apps.labels))
        if not candidates:
            raise MigrationRevisionWriteError("The project has no registered App that can own a migration.")
        app_label = candidates[0] if len(candidates) == 1 else interaction.choose("Choose the App for the blank revision.", candidates)
        if app_label not in candidates:
            raise ValueError(f"Unknown App selection: {app_label!r}.")
        if not interaction.confirm(
            f"No schema changes were detected for {app_label}. Create a blank revision?",
            default=False,
        ):
            return None
        selected = AppSchemaChanges(
            app_label=app_label,
            upgrade_ops=ops.UpgradeOps(ops=[]),
            summaries=(),
        )

    for table_name in selected.adoption_tables:
        choice = interaction.choose(
            f"Managed model table {table_name!r} already exists without Oldman ownership.",
            ("keep external", "adopt", "cancel"),
        )
        if choice == "keep external":
            raise MigrationModelChangeRequired(
                f"Table {table_name!r} remains externally managed; set its model Meta.managed=False and run makemigrations again."
            )
        if choice == "cancel":
            return None
        if choice != "adopt":
            raise ValueError(f"Unknown adoption choice: {choice!r}.")
    if selected.adoption_tables:
        selected = _adoption_only_changes(selected)
    selected = resolve_schema_intent(
        project,
        connection,
        selected,
        interaction,
    )
    selected = attach_cross_app_dependencies(project, connection, selected)

    location = _writable_location(project, app_label)
    suggested_message = _suggest_message(selected)
    message = interaction.text(
        "Migration description",
        default=suggested_message,
    ).strip()
    if not message:
        raise ValueError("Migration description cannot be empty.")
    _ensure_migration_package(location)
    return _write_revision(
        project,
        connection,
        location,
        selected,
        message,
    )


def _adoption_only_changes(changes: AppSchemaChanges) -> AppSchemaChanges:
    """Keep a guarded adoption revision free from unrelated schema work."""
    table_names = frozenset(changes.adoption_tables)
    operations = [operation for operation in changes.upgrade_ops.ops if getattr(operation, "table_name", None) in table_names]
    summaries = tuple(summary for summary in changes.summaries if summary.table_names and set(summary.table_names).issubset(table_names))
    ownership_changes = tuple(change for change in changes.ownership_changes if change.kind == "adopt" and change.table_name in table_names)
    if len(ownership_changes) != len(table_names):
        raise RuntimeError("Every guarded adoption table must have one ownership transition.")
    return AppSchemaChanges(
        app_label=changes.app_label,
        upgrade_ops=ops.UpgradeOps(ops=operations),
        summaries=summaries,
        ownership_changes=ownership_changes,
        adoption_tables=changes.adoption_tables,
        downgrade_ops=changes.downgrade_ops,
        depends_on=changes.depends_on,
    )


def _write_revision(
    project: MigrationProject,
    connection: Connection,
    location: AppMigrationLocation,
    changes: AppSchemaChanges,
    message: str,
) -> GeneratedMigration:
    """Let Alembic render selected standard operations into one App branch."""
    config = build_alembic_config(project)
    graph = load_migration_graph(project, config=config)
    branch = graph.branches[location.label]
    if len(branch.heads) > 1:
        rendered = ", ".join(revision.revision for revision in branch.heads)
        raise MigrationRevisionWriteError(
            f"App {location.label!r} has multiple migration heads ({rendered}); merge them before writing a schema revision."
        )
    if branch.heads:
        head = branch.heads[0].revision
        branch_label = None
    else:
        head = "base"
        branch_label = location.label

    revision_id = rev_id()
    selected_upgrade, selected_downgrade = _materialize_revision_operations(
        changes,
        revision_id,
    )
    migration_context = MigrationContext.configure(
        connection,
        opts={
            "target_metadata": config.attributes["oldman_metadata"].metadata,
            "compare_type": True,
            "compare_server_default": True,
            "render_as_batch": connection.dialect.name == "sqlite",
        },
    )
    upgrades = (
        render_python_code(
            selected_upgrade,
            render_as_batch=connection.dialect.name == "sqlite",
            migration_context=migration_context,
        )
        if selected_upgrade.ops
        else ""
    )
    downgrades = (
        render_python_code(
            selected_downgrade,
            render_as_batch=connection.dialect.name == "sqlite",
            migration_context=migration_context,
        )
        if selected_downgrade.ops
        else ""
    )
    generated = graph.script_directory.generate_revision(
        revision_id,
        message,
        head=head,
        branch_labels=branch_label,
        depends_on=changes.depends_on or None,
        version_path=str(location.path),
        upgrades=upgrades,
        downgrades=downgrades,
        imports="",
    )
    if not isinstance(generated, Script):
        raise RuntimeError("Alembic did not write exactly one revision file.")
    generated_path = Path(generated.path).resolve()
    if changes.adoption_tables:
        _append_adoption_guard(
            generated_path,
            changes.app_label,
            changes.adoption_tables,
        )
    return GeneratedMigration(
        app_label=location.label,
        message=message,
        revision=generated.revision,
        path=generated_path,
        adoption_tables=changes.adoption_tables,
    )


def _materialize_revision_operations(
    changes: AppSchemaChanges,
    revision_id: str,
) -> tuple[ops.UpgradeOps, ops.DowngradeOps]:
    """Add portable Registry SQL around Alembic's ordinary schema operations."""
    schema_upgrade = changes.upgrade_ops
    schema_downgrade = changes.downgrade_ops if changes.downgrade_ops is not None else schema_upgrade.reverse()
    registry_upgrade = [ops.ExecuteSQLOp(_ownership_upgrade_sql(change, revision_id)) for change in changes.ownership_changes]
    registry_downgrade_before = [
        ops.ExecuteSQLOp(_ownership_downgrade_sql(change)) for change in reversed(changes.ownership_changes) if change.kind not in {"drop", "rename"}
    ]
    registry_downgrade_after = [
        ops.ExecuteSQLOp(_ownership_downgrade_sql(change)) for change in reversed(changes.ownership_changes) if change.kind in {"drop", "rename"}
    ]
    return (
        ops.UpgradeOps(ops=[*schema_upgrade.ops, *registry_upgrade]),
        ops.DowngradeOps(
            ops=[
                *registry_downgrade_before,
                *schema_downgrade.ops,
                *registry_downgrade_after,
            ]
        ),
    )


def _ownership_upgrade_sql(change: OwnershipChange, revision_id: str) -> str:
    """Render one fixed-table DML statement without dialect-specific parameters."""
    table_name = _sql_literal(change.table_name)
    app_label = _sql_literal(change.app_label)
    ownership_revision = _sql_literal(revision_id)
    if change.kind in {"create", "adopt"}:
        return (
            "INSERT INTO oldman_schema_registry "
            "(table_name, app_label, managed, ownership_revision) VALUES "
            f"({table_name}, {app_label}, TRUE, {ownership_revision})"
        )
    if change.kind in {"release", "reacquire"}:
        managed = "TRUE" if change.after_managed else "FALSE"
        return (
            "UPDATE oldman_schema_registry SET "
            f"managed = {managed}, ownership_revision = {ownership_revision} "
            f"WHERE table_name = {table_name} AND app_label = {app_label}"
        )
    if change.kind == "rename":
        if change.previous_table_name is None:
            raise RuntimeError("Table rename ownership change has no previous name.")
        previous_name = _sql_literal(change.previous_table_name)
        return (
            "UPDATE oldman_schema_registry SET "
            f"table_name = {table_name}, ownership_revision = {ownership_revision} "
            f"WHERE table_name = {previous_name} AND app_label = {app_label}"
        )
    return f"DELETE FROM oldman_schema_registry WHERE table_name = {table_name} AND app_label = {app_label}"


def _ownership_downgrade_sql(change: OwnershipChange) -> str:
    """Restore the exact Registry state that preceded the generated revision."""
    table_name = _sql_literal(change.table_name)
    app_label = _sql_literal(change.app_label)
    if change.before is None:
        return f"DELETE FROM oldman_schema_registry WHERE table_name = {table_name} AND app_label = {app_label}"
    previous_revision = _sql_literal(change.before.ownership_revision)
    if change.kind == "rename":
        if change.previous_table_name is None:
            raise RuntimeError("Table rename ownership change has no previous name.")
        previous_name = _sql_literal(change.previous_table_name)
        return (
            "UPDATE oldman_schema_registry SET "
            f"table_name = {previous_name}, ownership_revision = {previous_revision} "
            f"WHERE table_name = {table_name} AND app_label = {app_label}"
        )
    if change.kind == "drop":
        managed = "TRUE" if change.before.managed else "FALSE"
        return (
            "INSERT INTO oldman_schema_registry "
            "(table_name, app_label, managed, ownership_revision) VALUES "
            f"({table_name}, {app_label}, {managed}, {previous_revision})"
        )
    managed = "TRUE" if change.before.managed else "FALSE"
    return (
        "UPDATE oldman_schema_registry SET "
        f"managed = {managed}, ownership_revision = {previous_revision} "
        f"WHERE table_name = {table_name} AND app_label = {app_label}"
    )


def _sql_literal(value: str) -> str:
    """Quote a validated metadata value as a portable SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _append_adoption_guard(
    path: Path,
    app_label: str,
    table_names: tuple[str, ...],
) -> None:
    """Bind the specialized marker to the exact generated upgrade/downgrade AST."""
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "import sqlalchemy as sa\n",
        "import sqlalchemy as sa\nfrom oldman.db.migrations.revisions import run_adoption_upgrade\n",
        1,
    )
    source = source.replace(
        "def upgrade() -> None:\n",
        f"def upgrade() -> None:\n    if run_adoption_upgrade(revision, {app_label!r}, {table_names!r}):\n        return\n",
        1,
    )
    path.write_text(source, encoding="utf-8")
    upgrade_digest, downgrade_digest = _revision_function_digests(path)
    marker = (
        "\n\n# Oldman validates these guards before skipping CREATE for an existing table.\n"
        f"oldman_adoption_tables: tuple[str, ...] = {table_names!r}\n"
        f"oldman_adoption_upgrade_sha256: str = {upgrade_digest!r}\n"
        f"oldman_adoption_downgrade_sha256: str = {downgrade_digest!r}\n"
    )
    with path.open("a", encoding="utf-8") as file:
        file.write(marker)


def run_adoption_upgrade(
    revision: str,
    app_label: str,
    table_names: tuple[str, ...],
) -> bool:
    """Replace CREATE with Registry writes only for a validated migrate adoption path."""
    context = op.get_context()
    config = context.config
    if config is None:
        raise RuntimeError("Adoption execution requires an Alembic Config.")
    revisions = config.attributes.get(
        "oldman_skip_adoption_revisions",
        frozenset(),
    )
    if revision not in revisions:
        return False
    connection = op.get_bind()
    from oldman.db.migrations.state import set_table_ownership

    for table_name in table_names:
        set_table_ownership(
            connection,
            table_name=table_name,
            app_label=app_label,
            managed=True,
            ownership_revision=revision,
        )
    return True


def _revision_function_digests(path: Path) -> tuple[str, str]:
    """Hash semantic function ASTs so harmless surrounding comments do not matter."""
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path))
    functions = {node.name: node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    try:
        upgrade = functions["upgrade"]
        downgrade = functions["downgrade"]
    except KeyError as exc:
        raise AdoptionRevisionError(f"Adoption revision {path} must define upgrade() and downgrade().") from exc
    return (_ast_digest(upgrade), _ast_digest(downgrade))


def _ast_digest(node: ast.AST) -> str:
    """Return a stable digest of one generated function body."""
    value = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan_adoption_execution(
    project: MigrationProject,
    script: Script,
    connection: Connection,
    interaction: MigrationInteraction,
) -> AdoptionExecutionPlan:
    """Validate a generated adoption revision before migrate chooses its path."""
    module = script.module
    raw_tables = getattr(module, "oldman_adoption_tables", None)
    expected_upgrade = getattr(module, "oldman_adoption_upgrade_sha256", None)
    expected_downgrade = getattr(module, "oldman_adoption_downgrade_sha256", None)
    if (
        not isinstance(raw_tables, tuple)
        or not raw_tables
        or not all(isinstance(table_name, str) and table_name for table_name in raw_tables)
        or len(set(raw_tables)) != len(raw_tables)
        or not isinstance(expected_upgrade, str)
        or not isinstance(expected_downgrade, str)
    ):
        raise AdoptionRevisionError(f"Revision {script.revision!r} is not a complete Oldman adoption revision.")
    table_names = tuple(raw_tables)
    actual_upgrade, actual_downgrade = _revision_function_digests(Path(script.path))
    if actual_upgrade != expected_upgrade or actual_downgrade != expected_downgrade:
        raise AdoptionRevisionError(
            f"Adoption revision {script.revision!r} was edited after generation; split custom operations into a normal revision."
        )

    migration_metadata = load_migration_metadata(project)
    metadata_by_name = {item.table.name: item for item in migration_metadata.tables.values()}
    branch_labels = frozenset(script.branch_labels)
    for table_name in table_names:
        table_metadata = metadata_by_name.get(table_name)
        if table_metadata is None or not table_metadata.managed:
            raise AdoptionRevisionError(f"Adoption table {table_name!r} is not a current managed model.")
        if table_metadata.app_label not in branch_labels:
            raise AdoptionRevisionError(
                f"Adoption table {table_name!r} belongs to App {table_metadata.app_label!r}, not revision {script.revision!r}."
            )

    inspector = sqlalchemy_inspect(connection)
    physical_tables = frozenset(inspector.get_table_names())
    present = tuple(table_name for table_name in table_names if table_name in physical_tables)
    if not present:
        return AdoptionExecutionPlan(
            adoption_tables=table_names,
            skip_schema=False,
        )
    if len(present) != len(table_names):
        raise AdoptionRevisionError(f"Adoption revision {script.revision!r} has a mixed physical state; present: {', '.join(present)}.")

    errors = table_structure_errors(project, connection, table_names)
    mismatches = {table_name: table_errors for table_name, table_errors in errors.items() if table_errors}
    if mismatches:
        rendered = "; ".join(f"{table_name}: {', '.join(table_errors)}" for table_name, table_errors in mismatches.items())
        raise MigrationAdoptionConflict(f"Existing adoption table structure changed: {rendered}.")
    if not interaction.confirm(
        "The adoption table already exists and matches the model. Skip CREATE and record ownership?",
        default=False,
    ):
        raise AdoptionRevisionError("Existing-table adoption was cancelled.")
    return AdoptionExecutionPlan(
        adoption_tables=table_names,
        skip_schema=True,
    )


def _writable_location(
    project: MigrationProject,
    app_label: str,
) -> AppMigrationLocation:
    """Resolve one App and reject installed dependency source before prompting text."""
    location = next(
        (candidate for candidate in collect_migration_locations(project) if candidate.label == app_label),
        None,
    )
    if location is None:
        raise MigrationRevisionWriteError(f"App {app_label!r} has no migration location.")
    project_root = project.project_root.resolve()
    try:
        location.path.resolve().relative_to(project_root)
    except ValueError:
        raise MigrationRevisionWriteError(
            f"App {app_label!r} is outside the current project. Third-party Apps must ship their own revisions; this project may only execute them."
        ) from None

    writable_parent = location.path if location.path.exists() else _nearest_existing_parent(location.path)
    if not _is_writable_directory(writable_parent):
        raise MigrationRevisionWriteError(f"App {app_label!r} migration directory is not writable: {location.path}.")
    return location


def _nearest_existing_parent(path: Path) -> Path:
    """Find the directory whose permissions control creation of a missing location."""
    candidate = path
    while not candidate.exists():
        candidate = candidate.parent
    if not candidate.is_dir():
        raise MigrationRevisionWriteError(f"Migration path parent is not a directory: {candidate}.")
    return candidate


def _is_writable_directory(path: Path) -> bool:
    """Check effective access and explicit mode bits, including privileged test runs."""
    return path.is_dir() and bool(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)) and os.access(path, os.W_OK)


def _ensure_migration_package(location: AppMigrationLocation) -> None:
    """Create only the selected local App's conventional import package."""
    if location.path.exists():
        return
    missing: list[Path] = []
    candidate = location.path
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    for directory in reversed(missing):
        directory.mkdir()
        directory.joinpath("__init__.py").write_text("", encoding="utf-8")
    importlib.invalidate_caches()


def _suggest_message(changes: AppSchemaChanges) -> str:
    """Offer a mechanical description that remains explicitly editable."""
    if not changes.summaries:
        return f"empty {changes.app_label} migration"
    if len(changes.summaries) == 1:
        return changes.summaries[0].description
    return f"update {changes.app_label} schema"


__all__ = [
    "AdoptionExecutionPlan",
    "AdoptionRevisionError",
    "GeneratedMigration",
    "MigrationRevisionWriteError",
    "make_migration",
    "plan_adoption_execution",
    "run_adoption_upgrade",
]
