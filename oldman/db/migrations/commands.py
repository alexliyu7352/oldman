"""Execute reviewed project migration plans through Alembic's command API."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.migration import MigrationContext
from alembic.script import Script
from sqlalchemy import (
    CheckConstraint,
    Connection,
    PrimaryKeyConstraint,
    UniqueConstraint,
    delete,
)
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from oldman.auth.base import USER_TABLE_OWNER_LABEL
from oldman.db.migrations.alembic import (
    MigrationGraph,
    build_alembic_config,
    load_migration_graph,
)
from oldman.db.migrations.autogenerate import table_structure_errors
from oldman.db.migrations.interaction import (
    ExactMigrationInteraction,
    MigrationInteraction,
    MigrationInteractionRequired,
)
from oldman.db.migrations.metadata import (
    INTERNAL_TABLE_NAMES,
    MigrationMetadata,
    load_migration_metadata,
)
from oldman.db.migrations.project import MigrationProject
from oldman.db.migrations.revisions import (
    GeneratedMigration,
    make_migration,
    plan_adoption_execution,
)
from oldman.db.migrations.state import (
    SCHEMA_REGISTRY_TABLE,
    MigrationOwner,
    MigrationState,
    ensure_for_first_migrate,
    rebuild_internal_state,
    set_table_ownership,
)

RECOVERY_CONFIRMATION = "recover migration state"


class MigrationCommandError(RuntimeError):
    """Base error for a migration command plan that cannot safely execute."""


class MissingInitialMigrationError(MigrationCommandError):
    """Raised when a managed App has no migration branch."""


class MigrationMultipleHeadsError(MigrationCommandError):
    """Raised when execution sees source heads that must first be merged."""


class MigrationAppliedStateError(MigrationCommandError):
    """Raised when database revisions do not belong to the current source graph."""


class MigrationDependencyBlockedError(MigrationCommandError):
    """Raised when another applied App prevents downgrade or retirement."""


class MigrationRecoverySchemaError(MigrationCommandError):
    """Raised when current managed models do not match recovery-time schema."""


class RetireNotAllowedError(MigrationCommandError):
    """Raised when no selected App can safely leave migration management."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Outcome of one migrate invocation."""

    target_app: str | None
    applied_revisions: tuple[str, ...]
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class DowngradeResult:
    """Outcome of one explicit branch downgrade."""

    app_label: str
    target_revision: str
    removed_revisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetireResult:
    """State removed for one App while its physical tables remain."""

    app_label: str
    package: str
    retained_tables: tuple[str, ...]
    service_config_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class AppMigrationStatus:
    """Database and source revisions for one registered App."""

    app_label: str
    current_revisions: tuple[str, ...]
    source_heads: tuple[str, ...]
    pending_revisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    """Read-only project migration state."""

    owner: MigrationOwner | None
    present_tables: tuple[str, ...]
    missing_tables: tuple[str, ...]
    apps: tuple[AppMigrationStatus, ...]


@dataclass(frozen=True, slots=True)
class RevisionHistory:
    """One source revision shown without connecting to the database."""

    revision: str
    down_revisions: tuple[str, ...]
    dependencies: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class AppMigrationHistory:
    """Ordered source revisions for one registered App."""

    app_label: str
    revisions: tuple[RevisionHistory, ...]


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    """Validated source metadata shared by mutating commands."""

    graph: MigrationGraph
    metadata: MigrationMetadata


@dataclass(frozen=True, slots=True)
class _UpgradePlan:
    """Alembic target and ordered revisions selected for one migrate."""

    target: str
    target_app: str | None
    scripts: tuple[Script, ...]


@dataclass(frozen=True, slots=True)
class _RecoveryPlan:
    """Exact Registry rows and external tables shown before state recovery."""

    rows: tuple[tuple[str, str, bool], ...]
    external_tables: tuple[str, ...]


def migrate(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> MigrationResult:
    """Apply all pending branches or one interactively selected App and its prerequisites."""
    context = _load_execution_context(project)
    return _run_sync(_migrate(project, context, interaction))


def makemigrations(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> GeneratedMigration | None:
    """Confirm migration-state intent before writing one candidate revision."""
    load_migration_metadata(project)
    graph = load_migration_graph(
        project,
        config=build_alembic_config(project),
    )
    state = _run_sync(_inspect_project_state(project))
    if state.owner is not None:
        state.require_current_owner(project)
    if state.is_partial:
        raise MigrationAppliedStateError(
            "Oldman migration state is incomplete; run migrate and use its recovery flow before generating revisions."
        )
    if state.is_complete:
        state.require_current_owner(project)
        _validate_applied_revisions(graph, state)
    else:
        choice = interaction.choose(
            "The database has no Oldman migration state. Is this first use or was the state lost?",
            ("first use", "state lost", "cancel"),
        )
        if choice == "cancel":
            return None
        if choice == "state lost":
            raise MigrationAppliedStateError(
                "Run migrate and use its controlled recovery flow before generating revisions."
            )
        if choice != "first use":
            raise ValueError(f"Unknown migration-state choice: {choice!r}.")
    return make_migration(project, interaction)


def downgrade(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> DowngradeResult | None:
    """Interactively downgrade one applied App branch to an explicit revision or base."""
    context = _load_execution_context(project)
    return _run_sync(_downgrade(project, context, interaction))


def retire(
    project: MigrationProject,
    interaction: MigrationInteraction,
) -> RetireResult | None:
    """Remove one App's branch and Registry state without changing physical tables."""
    context = _load_execution_context(project)
    return _run_sync(_retire(project, context, interaction))


def status(project: MigrationProject) -> MigrationStatus:
    """Inspect source and database migration state without changing either."""
    load_migration_metadata(project)
    graph = load_migration_graph(
        project,
        config=build_alembic_config(project),
    )
    state = _run_sync(_inspect_project_state(project))
    _validate_applied_revisions(graph, state)
    applied = graph.revision_closure(state.revisions)
    apps = tuple(
        AppMigrationStatus(
            app_label=label,
            current_revisions=_branch_frontier(branch.revisions, applied),
            source_heads=tuple(script.revision for script in branch.heads),
            pending_revisions=tuple(
                script.revision
                for script in branch.revisions
                if script.revision not in applied
            ),
        )
        for label, branch in sorted(graph.branches.items())
    )
    return MigrationStatus(
        owner=state.owner,
        present_tables=tuple(sorted(state.present_tables)),
        missing_tables=tuple(sorted(state.missing_tables)),
        apps=apps,
    )


def history(project: MigrationProject) -> tuple[AppMigrationHistory, ...]:
    """Return registered source migration history without opening the database."""
    load_migration_metadata(project)
    graph = load_migration_graph(
        project,
        config=build_alembic_config(project),
    )
    return tuple(
        AppMigrationHistory(
            app_label=label,
            revisions=tuple(
                RevisionHistory(
                    revision=script.revision,
                    down_revisions=_revision_ids(script.down_revision),
                    dependencies=_revision_ids(script.dependencies),
                    message=(script.doc or "").strip(),
                )
                for script in branch.revisions
            ),
        )
        for label, branch in sorted(graph.branches.items())
    )


def _load_execution_context(project: MigrationProject) -> _ExecutionContext:
    """Reject model and graph errors before opening the configured database."""
    metadata = load_migration_metadata(project)
    graph = load_migration_graph(
        project,
        config=build_alembic_config(project),
    )
    multiple_heads = {label: tuple(script.revision for script in branch.heads) for label, branch in graph.branches.items() if len(branch.heads) > 1}
    if multiple_heads:
        details = "; ".join(f"{label}: {', '.join(heads)}" for label, heads in sorted(multiple_heads.items()))
        raise MigrationMultipleHeadsError(
            f"Migration branches have multiple heads ({details}). Run makemigrations "
            "interactively to create a merge revision; upgrade third-party Apps that ship divergent heads."
        )
    _require_initial_revisions(project, graph, metadata)
    return _ExecutionContext(graph=graph, metadata=metadata)


def _require_initial_revisions(
    project: MigrationProject,
    graph: MigrationGraph,
    metadata: MigrationMetadata,
) -> None:
    """Require branches only for Apps that own real managed structure."""
    required = {item.app_label for item in metadata.tables.values() if item.managed}
    user = metadata.user
    if user is not None and user.app_label != USER_TABLE_OWNER_LABEL and _user_has_extension(metadata):
        required.add(user.app_label)
    missing = tuple(sorted(label for label in required if not graph.branches[label].revisions))
    if not missing:
        return
    package_by_label = dict(zip(project.apps.labels, project.apps.packages, strict=True))
    local = []
    third_party = []
    for label in missing:
        package = package_by_label[label]
        location = graph.branches[label].location
        try:
            location.path.resolve().relative_to(project.project_root.resolve())
        except ValueError:
            third_party.append(f"{label} ({package})")
        else:
            local.append(f"{label} ({package})")
    details = []
    if local:
        details.append("run makemigrations and select: " + ", ".join(local))
    if third_party:
        details.append("install releases that include migrations for: " + ", ".join(third_party))
    raise MissingInitialMigrationError("Managed Apps have no initial migration; " + "; ".join(details) + ".")


def _user_has_extension(metadata: MigrationMetadata) -> bool:
    """Return whether the selected User declares non-core schema structure."""
    user = metadata.user
    if user is None:
        return False
    if {column.name for column in user.table.columns} - set(user.core.column_names):
        return True
    if {str(index.name) for index in user.table.indexes} - set(user.core.index_names):
        return True
    for constraint in user.table.constraints:
        if isinstance(constraint, PrimaryKeyConstraint):
            continue
        if isinstance(constraint, CheckConstraint):
            if constraint.name in user.core.check_constraint_names:
                continue
            return True
        if isinstance(constraint, UniqueConstraint):
            columns = tuple(column.name for column in constraint.columns)
            if columns in user.core.unique_column_sets:
                continue
            return True
        return True
    return False


async def _migrate(
    project: MigrationProject,
    context: _ExecutionContext,
    interaction: MigrationInteraction,
) -> MigrationResult:
    """Inspect state, resolve intent, then execute one Alembic upgrade plan."""
    engine = create_async_engine(project.database_url)
    try:
        state = await _inspect_state(engine)
        if state.owner is not None:
            state.require_current_owner(project)
        if state.is_partial:
            return await _recover(engine, project, context, state, interaction)

        first_use = False
        if not state.present_tables:
            database_table_count = await _database_table_count(engine)
            source_revision_count = sum(len(branch.revisions) for branch in context.graph.branches.values())
            choice = interaction.choose(
                "The database has no Oldman internal migration state. "
                f"It contains {database_table_count} non-internal table(s), while source contains "
                f"{source_revision_count} migration revision(s). Is this first use or was the state lost?",
                ("first use", "state lost", "cancel"),
            )
            if choice == "cancel":
                return MigrationResult(target_app=None, applied_revisions=())
            if choice == "state lost":
                return await _recover(engine, project, context, state, interaction)
            if choice != "first use":
                raise ValueError(f"Unknown migration-state choice: {choice!r}.")
            first_use = True
        else:
            state.require_current_owner(project)
            _validate_applied_revisions(context.graph, state)

        plan = _choose_upgrade_plan(context.graph, state, interaction)
        if plan is None:
            return MigrationResult(target_app=None, applied_revisions=())
        if first_use:
            async with engine.begin() as connection:
                await connection.run_sync(ensure_for_first_migrate, project)

        async with engine.begin() as connection:
            await connection.run_sync(
                _execute_upgrade,
                project,
                plan,
                interaction,
            )
        return MigrationResult(
            target_app=plan.target_app,
            applied_revisions=tuple(script.revision for script in plan.scripts),
        )
    finally:
        await engine.dispose()


def _choose_upgrade_plan(
    graph: MigrationGraph,
    state: MigrationState,
    interaction: MigrationInteraction,
) -> _UpgradePlan | None:
    """Select all pending heads or one App head without inventing dependency edges."""
    applied = _applied_closure(graph, state.revisions)
    pending = tuple(sorted(label for label, branch in graph.branches.items() if branch.heads and branch.heads[0].revision not in applied))
    if not pending:
        return _UpgradePlan(target="heads", target_app=None, scripts=())

    if _is_interactive(interaction):
        pending_plan = "; ".join(f"{label} -> {graph.branches[label].heads[0].revision}" for label in pending)
        choice = interaction.choose(
            f"Pending migration heads: {pending_plan}. Choose the migration scope.",
            ("all", *pending, "cancel"),
        )
        if choice == "cancel":
            return None
        if choice != "all" and choice not in pending:
            raise ValueError(f"Unknown migration target: {choice!r}.")
    else:
        choice = "all"

    if choice == "all":
        targets: str | tuple[str, ...] = "heads"
        target = "heads"
        target_app = None
    else:
        targets = (graph.branches[choice].heads[0].revision,)
        target = f"{choice}@head"
        target_app = choice
    scripts = tuple(script for script in reversed(tuple(graph.script_directory.iterate_revisions(targets, "base"))) if script.revision not in applied)
    return _UpgradePlan(
        target=target,
        target_app=target_app,
        scripts=scripts,
    )


def _execute_upgrade(
    connection: Connection,
    project: MigrationProject,
    plan: _UpgradePlan,
    interaction: MigrationInteraction,
) -> None:
    """Validate guarded adoption paths and delegate revision execution to Alembic."""
    skipped_revisions: set[str] = set()
    for script in plan.scripts:
        if getattr(script.module, "oldman_adoption_tables", None) is None:
            continue
        adoption = plan_adoption_execution(
            project,
            script,
            connection,
            interaction,
        )
        if adoption.skip_schema:
            skipped_revisions.add(script.revision)
    _run_alembic(
        connection,
        project,
        command.upgrade,
        plan.target,
        config_attributes={
            "oldman_skip_adoption_revisions": frozenset(skipped_revisions),
        },
    )


async def _downgrade(
    project: MigrationProject,
    context: _ExecutionContext,
    interaction: MigrationInteraction,
) -> DowngradeResult | None:
    """Build and execute one branch-local downgrade after dependency checks."""
    engine = create_async_engine(project.database_url)
    try:
        state = await _inspect_complete_owned_state(engine, project, context.graph)
        current_by_app = _current_revisions_by_app(context.graph, state.revisions)
        candidates = tuple(sorted(current_by_app))
        if not candidates:
            return None
        app_label = interaction.choose("Choose the applied App to downgrade.", candidates)
        if app_label not in current_by_app:
            raise ValueError(f"Unknown downgrade App: {app_label!r}.")
        current = current_by_app[app_label]
        branch = context.graph.branches[app_label]
        ancestors = tuple(
            script.revision
            for script in branch.revisions
            if script.revision != current and script.revision in _ancestor_ids(context.graph, (current,))
        )
        choices = (*reversed(ancestors), "base")
        target = interaction.choose(
            f"Choose the target revision for App {app_label!r}.",
            choices,
        )
        if target not in choices:
            raise ValueError(f"Unknown downgrade target: {target!r}.")
        removed = _removed_branch_revisions(context.graph, branch.revisions, current, target)
        _require_no_applied_dependents(
            context.graph,
            state.revisions,
            frozenset(removed),
            excluding_app=app_label,
        )
        exact = _exact_interaction(interaction, "Downgrade")
        registry_tables = tuple(sorted(table_name for table_name, ownership in state.schema_registry.items() if ownership.app_label == app_label))
        impact = (
            f"Downgrade will remove revisions {', '.join(removed)} and may alter or "
            f"delete App tables recorded in the Registry: {', '.join(registry_tables) or 'none'}."
        )
        if exact.enter(f"{impact} Type App label {app_label!r} to confirm") != app_label:
            raise MigrationInteractionRequired("Downgrade App confirmation did not match.")
        if exact.enter(f"Type target revision {target!r} to confirm") != target:
            raise MigrationInteractionRequired("Downgrade target confirmation did not match.")
        alembic_target = f"{app_label}@base" if target == "base" else target
        async with engine.begin() as connection:
            await connection.run_sync(
                _run_alembic,
                project,
                command.downgrade,
                alembic_target,
            )
        return DowngradeResult(
            app_label=app_label,
            target_revision=target,
            removed_revisions=removed,
        )
    finally:
        await engine.dispose()


async def _retire(
    project: MigrationProject,
    context: _ExecutionContext,
    interaction: MigrationInteraction,
) -> RetireResult | None:
    """Validate one permanent App exit and clear only its internal state."""
    engine = create_async_engine(project.database_url)
    try:
        state = await _inspect_complete_owned_state(engine, project, context.graph)
        physical_tables = await _database_table_names(engine)
        current_by_app = _current_revisions_by_app(context.graph, state.revisions)
        allowed: dict[str, tuple[str, ...]] = {}
        rejected: dict[str, str] = {}
        for label, current in sorted(current_by_app.items()):
            branch = context.graph.branches[label]
            if not branch.heads or current != branch.heads[0].revision:
                rejected[label] = "database is not at the source head"
                continue
            if _is_user_extension_app(context.metadata, label):
                rejected[label] = "the selected User extension App must be downgraded, not retired"
                continue
            try:
                _require_no_applied_dependents(
                    context.graph,
                    state.revisions,
                    frozenset(script.revision for script in branch.revisions),
                    excluding_app=label,
                )
                retained = _retire_tables(
                    context.metadata,
                    state,
                    physical_tables,
                    label,
                )
            except MigrationCommandError as exc:
                rejected[label] = str(exc)
                continue
            allowed[label] = retained
        if not allowed:
            details = "; ".join(f"{label}: {reason}" for label, reason in rejected.items())
            raise RetireNotAllowedError(f"No App can be retired. {details}")
        app_label = interaction.choose(
            "Choose the App to retire while retaining its physical tables. "
            + ("Rejected Apps: " + "; ".join(f"{label}: {reason}" for label, reason in sorted(rejected.items())) if rejected else ""),
            tuple(sorted(allowed)),
        )
        if app_label not in allowed:
            raise ValueError(f"Unknown retire App: {app_label!r}.")
        exact = _exact_interaction(interaction, "Retire")
        package = dict(zip(project.apps.labels, project.apps.packages, strict=True))[app_label]
        service_files = tuple(config.config_file for config in project.service_configs if package in config.app_packages)
        plan = (
            f"Retire App {app_label!r}: keep tables {', '.join(allowed[app_label]) or 'none'}, "
            f"remove migration head {current_by_app[app_label]!r}, and clear its Registry rows. "
            f"Afterward remove package {package!r} from service files "
            f"{', '.join(str(path) for path in service_files) or 'none'} and from migration_apps if present."
        )
        if exact.enter(f"{plan} Type App label {app_label!r} to retire permanently") != app_label:
            raise MigrationInteractionRequired("Retire App confirmation did not match.")

        remaining_revisions = tuple(revision for label, revision in current_by_app.items() if label != app_label)
        remaining_frontier = _effective_frontier(
            context.graph,
            remaining_revisions,
        )
        async with engine.begin() as connection:
            await connection.run_sync(
                _execute_retire,
                project,
                app_label,
                remaining_frontier,
            )
        return RetireResult(
            app_label=app_label,
            package=package,
            retained_tables=allowed[app_label],
            service_config_files=service_files,
        )
    finally:
        await engine.dispose()


def _execute_retire(
    connection: Connection,
    project: MigrationProject,
    app_label: str,
    remaining_frontier: tuple[str, ...],
) -> None:
    """Use Alembic to rewrite the remaining frontier, then clear App ownership."""
    target: str | tuple[str, ...]
    if not remaining_frontier:
        target = "base"
    elif len(remaining_frontier) == 1:
        target = remaining_frontier[0]
    else:
        target = remaining_frontier
    _run_alembic(
        connection,
        project,
        command.stamp,
        target,
        purge=True,
    )
    connection.execute(delete(SCHEMA_REGISTRY_TABLE).where(SCHEMA_REGISTRY_TABLE.c.app_label == app_label))


async def _recover(
    engine: AsyncEngine,
    project: MigrationProject,
    context: _ExecutionContext,
    state: MigrationState,
    interaction: MigrationInteraction,
) -> MigrationResult:
    """Rebuild only validated internal state and stamp current source heads."""
    if state.owner is not None:
        state.require_current_owner(project)
    async with engine.connect() as async_connection:
        recovery_plan = await async_connection.run_sync(
            _plan_recovery_rows,
            project,
            context.metadata,
            interaction,
        )
    exact = _exact_interaction(interaction, "Migration state recovery")
    heads = tuple(branch.heads[0].revision for branch in context.graph.branches.values() if branch.heads)
    recovery_summary = (
        f"Recovery will stamp source heads {', '.join(heads) or 'none'} and restore Registry rows "
        + ", ".join(f"{table_name}->{app_label} managed={managed}" for table_name, app_label, managed in recovery_plan.rows)
        + ". Tables without current models remain external: "
        + (", ".join(recovery_plan.external_tables) or "none")
        + ". Oldman cannot prove that arbitrary blank revisions or data operations ran; "
        "continuing asserts that the current database already matches the source heads. "
        "Recovery will not run business migration DDL."
    )
    if exact.enter(f"{recovery_summary} Type project name {project.project_name!r} to confirm") != project.project_name:
        raise MigrationInteractionRequired("Recovery project-name confirmation did not match.")
    if exact.enter(f"Type {RECOVERY_CONFIRMATION!r} to rebuild only internal state") != RECOVERY_CONFIRMATION:
        raise MigrationInteractionRequired("Recovery phrase did not match.")
    async with engine.begin() as async_connection:
        await async_connection.run_sync(
            _execute_recovery,
            project,
            recovery_plan.rows,
        )
    return MigrationResult(
        target_app=None,
        applied_revisions=heads,
        recovered=True,
    )


def _plan_recovery_rows(
    connection: Connection,
    project: MigrationProject,
    metadata: MigrationMetadata,
    interaction: MigrationInteraction,
) -> _RecoveryPlan:
    """Prove managed schema equality and collect explicit unmanaged history intent."""
    physical_tables = frozenset(sqlalchemy_inspect(connection).get_table_names())
    managed = tuple(item for item in metadata.tables.values() if item.managed)
    missing = tuple(sorted(item.table.name for item in managed if item.table.name not in physical_tables))
    if missing:
        raise MigrationRecoverySchemaError("Managed model tables are missing from the database: " + ", ".join(missing))
    errors = (
        table_structure_errors(
            project,
            connection,
            tuple(item.table.name for item in managed),
        )
        if managed
        else {}
    )
    mismatches = {table_name: table_errors for table_name, table_errors in errors.items() if table_errors}
    if mismatches:
        details = "; ".join(f"{table_name}: {', '.join(table_errors)}" for table_name, table_errors in mismatches.items())
        raise MigrationRecoverySchemaError("Managed model schema does not match the database: " + details)

    rows = [(item.table.name, item.app_label, True) for item in managed]
    for item in sorted(
        (item for item in metadata.tables.values() if not item.managed),
        key=lambda value: value.table.name,
    ):
        choice = interaction.choose(
            f"Was unmanaged table {item.table.name!r} always external, or was it released by Oldman?",
            ("always external", "released", "cancel"),
        )
        if choice == "cancel":
            raise MigrationInteractionRequired("Migration state recovery was cancelled.")
        if choice == "released":
            rows.append((item.table.name, item.app_label, False))
        elif choice != "always external":
            raise ValueError(f"Unknown unmanaged-table recovery choice: {choice!r}.")
    model_tables = {item.table.name for item in metadata.tables.values()}
    external_tables = tuple(sorted(physical_tables - model_tables - INTERNAL_TABLE_NAMES))
    return _RecoveryPlan(
        rows=tuple(rows),
        external_tables=external_tables,
    )


def _execute_recovery(
    connection: Connection,
    project: MigrationProject,
    rows: tuple[tuple[str, str, bool], ...],
) -> None:
    """Rebuild fixed tables, stamp heads, and restore the confirmed Registry rows."""
    rebuild_internal_state(connection, project)
    _run_alembic(
        connection,
        project,
        command.stamp,
        "heads",
        purge=True,
    )
    for table_name, app_label, managed in rows:
        set_table_ownership(
            connection,
            table_name=table_name,
            app_label=app_label,
            managed=managed,
            ownership_revision="__recovered__",
        )


def _run_alembic(
    connection: Connection,
    project: MigrationProject,
    operation: Any,
    revision: Any,
    config_attributes: dict[str, object] | None = None,
    **kwargs: Any,
) -> None:
    """Inject one transaction and retain original errors with non-transactional help."""
    config = build_alembic_config(project)
    config.attributes["connection"] = connection
    if config_attributes:
        config.attributes.update(config_attributes)
    transactional_ddl = bool(MigrationContext.configure(connection).impl.transactional_ddl)
    try:
        operation(config, revision, **kwargs)
    except Exception as exc:
        if not transactional_ddl:
            exc.add_note(
                "This database does not provide transactional DDL for the whole revision. "
                "The migration may have stopped after partial DDL; inspect the revision and align "
                "the business schema before retrying."
            )
        raise


async def _inspect_state(engine: AsyncEngine) -> MigrationState:
    """Read migration state without changing the database."""
    async with engine.connect() as connection:
        return await connection.run_sync(MigrationState.inspect)


async def _inspect_project_state(project: MigrationProject) -> MigrationState:
    """Open the configured database only for one read-only state snapshot."""
    engine = create_async_engine(project.database_url)
    try:
        return await _inspect_state(engine)
    finally:
        await engine.dispose()


async def _database_table_count(engine: AsyncEngine) -> int:
    """Count only non-internal tables for the first-use versus recovery prompt."""
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: len(set(sqlalchemy_inspect(sync_connection).get_table_names()) - INTERNAL_TABLE_NAMES)
        )


async def _database_table_names(engine: AsyncEngine) -> frozenset[str]:
    """Reflect physical table names for command preconditions without changing state."""
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_connection: frozenset(sqlalchemy_inspect(sync_connection).get_table_names())
        )


async def _inspect_complete_owned_state(
    engine: AsyncEngine,
    project: MigrationProject,
    graph: MigrationGraph,
) -> MigrationState:
    """Require complete, owned, graph-resolvable state for destructive commands."""
    state = await _inspect_state(engine)
    if not state.is_complete:
        raise MigrationAppliedStateError("Oldman migration state is missing or incomplete; run migrate to initialize or recover it.")
    state.require_current_owner(project)
    _validate_applied_revisions(graph, state)
    return state


def _validate_applied_revisions(
    graph: MigrationGraph,
    state: MigrationState,
) -> None:
    """Reject version rows that cannot be resolved by installed migration files."""
    unknown = tuple(revision for revision in state.revisions if graph.script_directory.get_revision(revision) is None)
    if unknown:
        raise MigrationAppliedStateError(
            "Database revision(s) are absent from the installed Apps: "
            + ", ".join(unknown)
            + ". Restore the App version and configuration before migrating, downgrading, or retiring it."
        )


def _applied_closure(
    graph: MigrationGraph,
    revisions: Iterable[str],
) -> frozenset[str]:
    """Expand current version rows through standard down and dependency edges."""
    return _ancestor_ids(graph, tuple(revisions))


def _ancestor_ids(
    graph: MigrationGraph,
    revisions: tuple[str, ...],
) -> frozenset[str]:
    """Traverse public revision references without inferring Python dependencies."""
    return graph.revision_closure(revisions)


def _current_revisions_by_app(
    graph: MigrationGraph,
    revisions: tuple[str, ...],
) -> dict[str, str]:
    """Resolve each App's applied frontier, including dependency-only branches."""
    applied = graph.revision_closure(revisions)
    current: dict[str, str] = {}
    for label, branch in graph.branches.items():
        applied_branch = {script.revision for script in branch.revisions if script.revision in applied}
        if not applied_branch:
            continue
        parents = {
            down_revision
            for script in branch.revisions
            if script.revision in applied_branch
            for down_revision in _revision_ids(script.down_revision)
            if down_revision in applied_branch
        }
        matches = tuple(sorted(applied_branch - parents))
        if len(matches) != 1:
            raise MigrationAppliedStateError(f"Database records multiple current revisions for App {label!r}: {', '.join(matches)}.")
        current[label] = matches[0]
    return current


def _branch_frontier(
    revisions: tuple[Script, ...],
    applied: frozenset[str],
) -> tuple[str, ...]:
    """Return every applied branch revision that has no applied child."""
    applied_branch = {
        script.revision for script in revisions if script.revision in applied
    }
    parents = {
        down_revision
        for script in revisions
        if script.revision in applied_branch
        for down_revision in _revision_ids(script.down_revision)
        if down_revision in applied_branch
    }
    return tuple(sorted(applied_branch - parents))


def _removed_branch_revisions(
    graph: MigrationGraph,
    branch_revisions: tuple[Script, ...],
    current: str,
    target: str,
) -> tuple[str, ...]:
    """List only selected-branch revisions Alembic will remove."""
    target_id = None if target == "base" else target
    branch_ids = {script.revision for script in branch_revisions}
    removed: list[str] = []
    pending = [current]
    while pending:
        revision = pending.pop()
        if revision == target_id or revision in removed:
            continue
        if revision not in branch_ids:
            continue
        removed.append(revision)
        script = graph.script_directory.get_revision(revision)
        if script is not None:
            pending.extend(_revision_ids(script.down_revision))
    return tuple(removed)


def _require_no_applied_dependents(
    graph: MigrationGraph,
    applied_heads: tuple[str, ...],
    removed: frozenset[str],
    *,
    excluding_app: str,
) -> None:
    """Reject removing revisions still required by another applied App."""
    current = _current_revisions_by_app(graph, applied_heads)
    blockers = tuple(sorted(label for label, revision in current.items() if label != excluding_app and _ancestor_ids(graph, (revision,)) & removed))
    if blockers:
        raise MigrationDependencyBlockedError(f"App {excluding_app!r} is still required by applied App(s): {', '.join(blockers)}.")


def _effective_frontier(
    graph: MigrationGraph,
    revisions: tuple[str, ...],
) -> tuple[str, ...]:
    """Remove revisions already represented as ancestors of another current App."""
    return tuple(
        sorted(
            revision for revision in revisions if not any(revision in graph.revision_closure((other,)) for other in revisions if other != revision)
        )
    )


def _retire_tables(
    metadata: MigrationMetadata,
    state: MigrationState,
    physical_tables: frozenset[str],
    app_label: str,
) -> tuple[str, ...]:
    """Require Registry ownership for every current managed table of the App."""
    expected = {item.table.name for item in metadata.tables.values() if item.app_label == app_label and item.managed}
    rows = {table_name: ownership for table_name, ownership in state.schema_registry.items() if ownership.app_label == app_label}
    actual_managed = {table_name for table_name, ownership in rows.items() if ownership.managed}
    missing = expected - physical_tables
    if missing:
        raise RetireNotAllowedError(
            f"Current managed tables are missing from the database: {sorted(missing)}."
        )
    if actual_managed != expected:
        raise RetireNotAllowedError(
            f"Schema Registry does not match current managed tables; expected {sorted(expected)}, found {sorted(actual_managed)}."
        )
    return tuple(sorted(expected | rows.keys()))


def _is_user_extension_app(
    metadata: MigrationMetadata,
    app_label: str,
) -> bool:
    """Keep User extension history on the downgrade-only exit path."""
    user = metadata.user
    return bool(user is not None and user.app_label == app_label and user.app_label != USER_TABLE_OWNER_LABEL and _user_has_extension(metadata))


def _revision_ids(value: Any) -> tuple[str, ...]:
    """Normalize one Alembic scalar-or-sequence revision reference."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _exact_interaction(
    interaction: MigrationInteraction,
    action: str,
) -> ExactMigrationInteraction:
    """Require the terminal capability used for irreversible intent confirmation."""
    if not isinstance(interaction, ExactMigrationInteraction):
        raise MigrationInteractionRequired(f"{action} requires an interactive terminal with exact text confirmation.")
    return interaction


def _is_interactive(interaction: MigrationInteraction) -> bool:
    """Treat custom interaction adapters as interactive unless they say otherwise."""
    value = getattr(interaction, "is_interactive", True)
    return bool(value)


def _run_sync[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run one command coroutine only from the synchronous CLI boundary."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Database migration commands require a synchronous CLI context.")
    return asyncio.run(coroutine)


__all__ = [
    "AppMigrationHistory",
    "AppMigrationStatus",
    "DowngradeResult",
    "MigrationAppliedStateError",
    "MigrationCommandError",
    "MigrationDependencyBlockedError",
    "MigrationMultipleHeadsError",
    "MigrationRecoverySchemaError",
    "MigrationResult",
    "MigrationStatus",
    "MissingInitialMigrationError",
    "RECOVERY_CONFIRMATION",
    "RetireNotAllowedError",
    "RetireResult",
    "RevisionHistory",
    "downgrade",
    "history",
    "makemigrations",
    "migrate",
    "retire",
    "status",
]
