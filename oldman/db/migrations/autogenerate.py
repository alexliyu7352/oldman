"""Alembic schema comparison and App ownership grouping."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, cast

from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext
from alembic.operations import ops
from sqlalchemy import (
    CheckConstraint,
    Column,
    Constraint,
    ForeignKeyConstraint,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.engine import Connection

from oldman.auth.base import USER_TABLE_OWNER_LABEL
from oldman.db.migrations.alembic import build_alembic_config, load_migration_graph
from oldman.db.migrations.interaction import (
    ExactMigrationInteraction,
    MigrationInteraction,
    MigrationInteractionRequired,
)
from oldman.db.migrations.metadata import INTERNAL_TABLE_NAMES, MigrationMetadata, load_migration_metadata
from oldman.db.migrations.project import MigrationProject
from oldman.db.migrations.state import (
    MigrationState,
    MigrationStateRecoveryRequired,
    SchemaOwnership,
)


class MigrationSchemaDriftError(RuntimeError):
    """Raised when physical schema state contradicts persisted ownership."""


class MigrationRevisionStateError(RuntimeError):
    """Raised when the database is not at the registered source heads."""


class MigrationAdoptionConflict(RuntimeError):
    """Raised when an existing table does not exactly match its managed model."""


class MigrationModelChangeRequired(RuntimeError):
    """Raised when the selected ownership intent requires changing Model.Meta."""


class MigrationDeletionCancelled(RuntimeError):
    """Raised when exact destructive confirmation was not supplied."""


class MigrationRenameConflict(RuntimeError):
    """Raised when a possible rename cannot be represented safely."""


class MigrationDependencyError(RuntimeError):
    """Raised when a real cross-App foreign key has no safe revision target."""


OwnershipChangeKind = Literal[
    "create",
    "adopt",
    "release",
    "reacquire",
    "drop",
    "rename",
]


@dataclass(frozen=True, slots=True)
class OwnershipChange:
    """One revision-time Schema Registry transition."""

    table_name: str
    app_label: str
    kind: OwnershipChangeKind
    before: SchemaOwnership | None
    after_managed: bool | None
    previous_table_name: str | None = None


@dataclass(frozen=True, slots=True)
class OperationSummary:
    """One standard Alembic operation with a compact user-facing description."""

    operation: ops.MigrateOperation | None
    kind: str
    table_names: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class AppSchemaChanges:
    """Standard upgrade operations assigned to one App revision branch."""

    app_label: str
    upgrade_ops: ops.UpgradeOps
    summaries: tuple[OperationSummary, ...]
    ownership_changes: tuple[OwnershipChange, ...] = ()
    adoption_tables: tuple[str, ...] = ()
    downgrade_ops: ops.DowngradeOps | None = None
    depends_on: tuple[str, ...] = ()

    @property
    def table_names(self) -> tuple[str, ...]:
        """Return touched tables once, preserving global Alembic order."""
        return _ordered_unique(table_name for summary in self.summaries for table_name in summary.table_names)


@dataclass(frozen=True, slots=True)
class SchemaChanges:
    """Full-database comparison with App-scoped revision candidates."""

    by_app: Mapping[str, AppSchemaChanges]
    summaries: tuple[OperationSummary, ...]

    @property
    def table_names(self) -> tuple[str, ...]:
        """Return every touched table once in full comparison order."""
        return _ordered_unique(table_name for summary in self.summaries for table_name in summary.table_names)


def collect_schema_changes(
    project: MigrationProject,
    connection: Connection,
) -> SchemaChanges:
    """Compare the complete managed metadata, then group standard ops by owner."""
    metadata = load_migration_metadata(project)
    state = MigrationState.inspect(connection)
    _validate_state(project, state)
    physical_tables = frozenset(sqlalchemy_inspect(connection).get_table_names())
    missing_managed = sorted(
        table_name for table_name, ownership in state.schema_registry.items() if ownership.managed and table_name not in physical_tables
    )
    if missing_managed:
        raise MigrationSchemaDriftError(
            f"Schema Registry marks table(s) as managed, but they are missing from the database: {', '.join(missing_managed)}."
        )

    current_by_name = {item.table.name: item for item in metadata.tables.values()}

    def include_name(
        name: str | None,
        type_: str,
        parent_names: Mapping[str, str | None],
    ) -> bool:
        del parent_names
        if type_ != "table" or name is None:
            return True
        return _include_table(name, current_by_name, state)

    def include_object(
        object_: Any,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: Any,
    ) -> bool:
        del object_, reflected, compare_to
        if type_ != "table" or name is None:
            return True
        return _include_table(name, current_by_name, state)

    context = MigrationContext.configure(
        connection,
        opts={
            "target_metadata": metadata.metadata,
            "compare_type": True,
            "compare_server_default": True,
            "render_as_batch": connection.dialect.name == "sqlite",
            "include_name": include_name,
            "include_object": include_object,
        },
    )
    script = produce_migrations(context, metadata.metadata)
    upgrade_ops = script.upgrade_ops
    if upgrade_ops is None:
        raise RuntimeError("Alembic did not produce an upgrade operation tree.")
    ordered_operations = _order_table_operations(
        connection,
        metadata,
        state,
        upgrade_ops.ops,
    )
    grouped = _group_operations(project, metadata, state, ordered_operations)
    return _add_ownership_changes(
        connection,
        metadata,
        state,
        physical_tables,
        grouped,
    )


def _add_ownership_changes(
    connection: Connection,
    metadata: MigrationMetadata,
    state: MigrationState,
    physical_tables: frozenset[str],
    changes: SchemaChanges,
) -> SchemaChanges:
    """Add table ownership transitions that Alembic schema diff cannot express."""
    by_app = dict(changes.by_app)
    all_summaries = list(changes.summaries)
    current_by_name = {item.table.name: item for item in metadata.tables.values()}
    operation_tables = {table_name for app_changes in by_app.values() for table_name in app_changes.table_names}
    managed_order = [table.name for table in metadata.managed_tables]
    current_order = [
        *managed_order,
        *sorted(set(current_by_name) - set(managed_order)),
    ]

    for table_name in current_order:
        current = current_by_name[table_name]
        ownership = state.schema_registry.get(table_name)
        exists = table_name in physical_tables
        if current.managed:
            if ownership is None and not exists:
                _append_ownership_change(
                    by_app,
                    current.app_label,
                    OwnershipChange(
                        table_name=table_name,
                        app_label=current.app_label,
                        kind="create",
                        before=None,
                        after_managed=True,
                    ),
                )
            elif ownership is None:
                _require_exact_existing_table(
                    connection_errors=_ownership_structure_errors(
                        connection,
                        current.table,
                        table_name in operation_tables,
                    ),
                    table_name=table_name,
                )
                _append_adoption(by_app, current, table_name, all_summaries)
            elif ownership.managed:
                if ownership.app_label != current.app_label:
                    raise MigrationAdoptionConflict(
                        f"Managed table {table_name!r} belongs to App {ownership.app_label!r}, not {current.app_label!r}."
                    )
            else:
                if not exists:
                    raise MigrationSchemaDriftError(
                        f"Released table {table_name!r} is missing; restore and align it before restoring Oldman management."
                    )
                _require_exact_existing_table(
                    connection_errors=_ownership_structure_errors(
                        connection,
                        current.table,
                        table_name in operation_tables,
                    ),
                    table_name=table_name,
                )
                _append_ownership_change(
                    by_app,
                    ownership.app_label,
                    OwnershipChange(
                        table_name=table_name,
                        app_label=ownership.app_label,
                        kind="reacquire",
                        before=ownership,
                        after_managed=True,
                    ),
                    summary=OperationSummary(
                        operation=None,
                        kind="reacquire_ownership",
                        table_names=(table_name,),
                        description=f"restore {table_name} ownership",
                    ),
                    all_summaries=all_summaries,
                )
        elif ownership is not None and ownership.managed:
            if ownership.app_label != current.app_label:
                raise MigrationAdoptionConflict(
                    f"Table {table_name!r} must be released from App {ownership.app_label!r} before moving its model to {current.app_label!r}."
                )
            _append_ownership_change(
                by_app,
                ownership.app_label,
                OwnershipChange(
                    table_name=table_name,
                    app_label=ownership.app_label,
                    kind="release",
                    before=ownership,
                    after_managed=False,
                ),
                summary=OperationSummary(
                    operation=None,
                    kind="release_ownership",
                    table_names=(table_name,),
                    description=f"release {table_name} ownership",
                ),
                all_summaries=all_summaries,
            )

    for table_name, ownership in state.schema_registry.items():
        if table_name in current_by_name or not ownership.managed:
            continue
        _append_ownership_change(
            by_app,
            ownership.app_label,
            OwnershipChange(
                table_name=table_name,
                app_label=ownership.app_label,
                kind="drop",
                before=ownership,
                after_managed=None,
            ),
        )

    return SchemaChanges(
        by_app=MappingProxyType(dict(sorted(by_app.items()))),
        summaries=tuple(all_summaries),
    )


def _ownership_structure_errors(
    connection: Connection,
    table: Any,
    alembic_has_differences: bool,
) -> tuple[str, ...]:
    """Add PK/check comparisons that Alembic autogenerate does not promise."""
    errors: list[str] = []
    if alembic_has_differences:
        errors.append("Alembic detected column, index, constraint, default or foreign-key differences")
    inspector = sqlalchemy_inspect(connection)
    actual_primary_key = tuple(
        inspector.get_pk_constraint(table.name, schema=table.schema).get(
            "constrained_columns",
            (),
        )
        or ()
    )
    expected_primary_key = tuple(column.name for column in table.primary_key.columns)
    if actual_primary_key != expected_primary_key:
        errors.append(f"primary key is {actual_primary_key!r}, expected {expected_primary_key!r}")

    actual_checks = {_normalized_sql(check.get("sqltext", "")) for check in inspector.get_check_constraints(table.name, schema=table.schema)}
    expected_checks = {_normalized_sql(constraint.sqltext) for constraint in table.constraints if isinstance(constraint, CheckConstraint)}
    if actual_checks != expected_checks:
        errors.append("check constraints differ")
    return tuple(errors)


def _require_exact_existing_table(
    *,
    connection_errors: tuple[str, ...],
    table_name: str,
) -> None:
    """Reject ownership changes when ordinary comparison found any structural drift."""
    if connection_errors:
        raise MigrationAdoptionConflict(f"Existing table {table_name!r} does not exactly match its managed model: {'; '.join(connection_errors)}.")


def table_structure_errors(
    project: MigrationProject,
    connection: Connection,
    table_names: Sequence[str],
) -> Mapping[str, tuple[str, ...]]:
    """Compare selected current models for guarded adoption execution."""
    metadata = load_migration_metadata(project)
    names = frozenset(table_names)
    current_by_name = {item.table.name: item for item in metadata.tables.values()}
    unknown = sorted(names - current_by_name.keys())
    if unknown:
        raise MigrationAdoptionConflict(f"Adoption revision refers to table(s) absent from current models: {', '.join(unknown)}.")

    def include_name(
        name: str | None,
        type_: str,
        parent_names: Mapping[str, str | None],
    ) -> bool:
        del parent_names
        return type_ != "table" or name in names

    def include_object(
        object_: Any,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: Any,
    ) -> bool:
        del object_, reflected, compare_to
        return type_ != "table" or name in names

    context = MigrationContext.configure(
        connection,
        opts={
            "target_metadata": metadata.metadata,
            "compare_type": True,
            "compare_server_default": True,
            "render_as_batch": connection.dialect.name == "sqlite",
            "include_name": include_name,
            "include_object": include_object,
        },
    )
    script = produce_migrations(context, metadata.metadata)
    upgrade_ops = script.upgrade_ops
    if upgrade_ops is None:
        raise RuntimeError("Alembic did not produce an upgrade operation tree.")
    changed_names = {table_name for operation in upgrade_ops.ops if (table_name := _operation_table_name(operation)) is not None}
    return MappingProxyType(
        {
            name: _ownership_structure_errors(
                connection,
                current_by_name[name].table,
                name in changed_names,
            )
            for name in table_names
        }
    )


def _normalized_sql(value: object) -> str:
    """Normalize harmless formatting in reflected check expressions."""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _append_adoption(
    by_app: dict[str, AppSchemaChanges],
    current: Any,
    table_name: str,
    all_summaries: list[OperationSummary],
) -> None:
    """Synthesize the standard CREATE path needed when replaying on an empty DB."""
    create = ops.CreateTableOp.from_table(current.table)
    operations: list[ops.MigrateOperation] = [create]
    if current.table.indexes:
        operations.append(
            ops.ModifyTableOps(
                table_name,
                [
                    ops.CreateIndexOp.from_index(index)
                    for index in sorted(
                        current.table.indexes,
                        key=lambda item: str(item.name),
                    )
                ],
                schema=current.table.schema,
            )
        )
    summaries = tuple(_summarize(operation) for operation in operations)
    existing = by_app.get(current.app_label)
    existing_operations = list(existing.upgrade_ops.ops) if existing is not None else []
    existing_summaries = list(existing.summaries) if existing is not None else []
    existing_changes = list(existing.ownership_changes) if existing is not None else []
    existing_adoptions = list(existing.adoption_tables) if existing is not None else []
    existing_operations.extend(operations)
    existing_summaries.extend(summaries)
    existing_changes.append(
        OwnershipChange(
            table_name=table_name,
            app_label=current.app_label,
            kind="adopt",
            before=None,
            after_managed=True,
        )
    )
    existing_adoptions.append(table_name)
    by_app[current.app_label] = AppSchemaChanges(
        app_label=current.app_label,
        upgrade_ops=ops.UpgradeOps(ops=existing_operations),
        summaries=tuple(existing_summaries),
        ownership_changes=tuple(existing_changes),
        adoption_tables=tuple(existing_adoptions),
        downgrade_ops=existing.downgrade_ops if existing is not None else None,
        depends_on=existing.depends_on if existing is not None else (),
    )
    all_summaries.extend(summaries)


def _append_ownership_change(
    by_app: dict[str, AppSchemaChanges],
    app_label: str,
    ownership_change: OwnershipChange,
    *,
    summary: OperationSummary | None = None,
    all_summaries: list[OperationSummary] | None = None,
) -> None:
    """Append one Registry transition without mutating an existing frozen view."""
    existing = by_app.get(app_label)
    summaries = list(existing.summaries) if existing is not None else []
    if summary is not None:
        summaries.append(summary)
        if all_summaries is not None:
            all_summaries.append(summary)
    by_app[app_label] = AppSchemaChanges(
        app_label=app_label,
        upgrade_ops=existing.upgrade_ops if existing is not None else ops.UpgradeOps(ops=[]),
        summaries=tuple(summaries),
        ownership_changes=(
            *(existing.ownership_changes if existing is not None else ()),
            ownership_change,
        ),
        adoption_tables=existing.adoption_tables if existing is not None else (),
        downgrade_ops=existing.downgrade_ops if existing is not None else None,
        depends_on=existing.depends_on if existing is not None else (),
    )


def resolve_schema_intent(
    project: MigrationProject,
    connection: Connection,
    changes: AppSchemaChanges,
    interaction: MigrationInteraction,
) -> AppSchemaChanges:
    """Resolve rename candidates and require exact confirmation for real deletion."""
    metadata = load_migration_metadata(project)
    operations, ownership_changes, summaries = _resolve_table_intent(
        connection,
        metadata,
        list(changes.upgrade_ops.ops),
        list(changes.ownership_changes),
        list(changes.summaries),
        interaction,
    )
    operations = _resolve_column_intent(
        connection,
        operations,
        interaction,
    )
    upgrade_ops = ops.UpgradeOps(ops=operations)
    return AppSchemaChanges(
        app_label=changes.app_label,
        upgrade_ops=upgrade_ops,
        downgrade_ops=_reverse_upgrade_ops(upgrade_ops),
        summaries=tuple(summaries),
        ownership_changes=tuple(ownership_changes),
        adoption_tables=changes.adoption_tables,
        depends_on=changes.depends_on,
    )


def attach_cross_app_dependencies(
    project: MigrationProject,
    connection: Connection,
    changes: AppSchemaChanges,
) -> AppSchemaChanges:
    """Bind newly introduced foreign keys to the referenced App's applied head."""
    metadata = load_migration_metadata(project)
    tables_by_name = {item.table.name: item for item in metadata.tables.values()}
    referenced_apps: set[str] = set()
    for operation in changes.upgrade_ops.ops:
        for table_name in _introduced_foreign_key_tables(operation):
            referenced = tables_by_name.get(table_name)
            if referenced is not None and referenced.managed and referenced.app_label != changes.app_label:
                referenced_apps.add(referenced.app_label)

    if not referenced_apps:
        return changes

    graph = load_migration_graph(
        project,
        config=build_alembic_config(project),
    )
    state = MigrationState.inspect(connection)
    applied_revisions = graph.revision_closure(state.revisions)
    dependencies: list[str] = []
    for app_label in sorted(referenced_apps):
        branch = graph.branches[app_label]
        if len(branch.heads) != 1:
            raise MigrationDependencyError(
                f"Cross-App foreign key references App {app_label!r}, which must have "
                "exactly one migration head before this migration can be generated."
            )
        revision = branch.heads[0].revision
        if revision not in applied_revisions:
            raise MigrationDependencyError(f"Cross-App foreign key references unapplied App {app_label!r} head {revision!r}; run migrate first.")
        dependencies.append(revision)

    return AppSchemaChanges(
        app_label=changes.app_label,
        upgrade_ops=changes.upgrade_ops,
        summaries=changes.summaries,
        ownership_changes=changes.ownership_changes,
        adoption_tables=changes.adoption_tables,
        downgrade_ops=changes.downgrade_ops,
        depends_on=tuple(dependencies),
    )


def _introduced_foreign_key_tables(
    operation: ops.MigrateOperation,
) -> tuple[str, ...]:
    """Return referenced tables only for foreign keys created by this operation."""
    if isinstance(operation, ops.ModifyTableOps):
        return _ordered_unique(table_name for child in operation.ops for table_name in _introduced_foreign_key_tables(child))
    if isinstance(operation, ops.CreateForeignKeyOp):
        return (operation.referent_table,)
    if isinstance(operation, ops.AddColumnOp):
        return _ordered_unique(foreign_key.column.table.name for foreign_key in operation.column.foreign_keys)
    if isinstance(operation, ops.CreateTableOp):
        return _ordered_unique(
            foreign_key.column.table.name for item in operation.columns if isinstance(item, Column) for foreign_key in item.foreign_keys
        )
    return ()


def _resolve_table_intent(
    connection: Connection,
    metadata: MigrationMetadata,
    operations: list[ops.MigrateOperation],
    ownership_changes: list[OwnershipChange],
    summaries: list[OperationSummary],
    interaction: MigrationInteraction,
) -> tuple[
    list[ops.MigrateOperation],
    list[OwnershipChange],
    list[OperationSummary],
]:
    """Replace confirmed create/drop pairs with standard table rename operations."""
    creates = {operation.table_name: operation for operation in operations if isinstance(operation, ops.CreateTableOp)}
    drops = {operation.table_name: operation for operation in operations if isinstance(operation, ops.DropTableOp)}
    if not drops:
        return operations, ownership_changes, summaries

    current_tables = {item.table.name: item.table for item in metadata.tables.values()}
    reflected = MetaData()
    reflected.reflect(connection, only=tuple(drops))
    candidates = {
        old_name: tuple(
            new_name
            for new_name in creates
            if new_name in current_tables
            and _table_shapes_match(
                reflected.tables[old_name],
                current_tables[new_name],
                connection,
            )
        )
        for old_name in drops
    }
    reverse_candidates: dict[str, list[str]] = {}
    for old_name, new_names in candidates.items():
        for new_name in new_names:
            reverse_candidates.setdefault(new_name, []).append(old_name)

    rename_pairs: dict[str, str] = {}
    used_new_names: set[str] = set()
    for old_name in drops:
        available = tuple(new_name for new_name in candidates[old_name] if new_name not in used_new_names)
        new_name: str | None = None
        if len(available) == 1 and len(reverse_candidates.get(available[0], ())) == 1:
            candidate = available[0]
            if interaction.confirm(
                f"Treat managed table {old_name!r} as renamed to {candidate!r}?",
                default=False,
            ):
                new_name = candidate
        elif available:
            choice = interaction.choose(
                f"Choose the new model table for managed table {old_name!r}.",
                (*available, "not a rename"),
            )
            if choice != "not a rename":
                if choice not in available:
                    raise ValueError(f"Unknown table rename selection: {choice!r}.")
                new_name = choice
        if new_name is not None:
            rename_pairs[old_name] = new_name
            used_new_names.add(new_name)

    for old_name in drops:
        if old_name in rename_pairs:
            continue
        answer = _enter_exact(
            interaction,
            f"Deleting managed table {old_name!r} removes its data. Enter {old_name} to confirm",
        )
        if answer != old_name:
            raise MigrationDeletionCancelled(f"Deletion of managed table {old_name!r} was not confirmed.")

    if not rename_pairs:
        return operations, ownership_changes, summaries

    renamed_new_names = frozenset(rename_pairs.values())
    object_operations = {
        old_name: _table_object_reconciliation(
            reflected.tables[old_name],
            current_tables[new_name],
        )
        for old_name, new_name in rename_pairs.items()
    }
    rewritten: list[ops.MigrateOperation] = []
    inserted_renames: set[str] = set()
    for operation in operations:
        if isinstance(operation, ops.DropTableOp) and operation.table_name in rename_pairs:
            new_name = rename_pairs[operation.table_name]
            rewritten.append(
                ops.RenameTableOp(
                    operation.table_name,
                    new_name,
                    schema=operation.schema,
                )
            )
            if object_operations[operation.table_name]:
                rewritten.append(
                    ops.ModifyTableOps(
                        new_name,
                        object_operations[operation.table_name],
                        schema=operation.schema,
                    )
                )
            inserted_renames.add(operation.table_name)
            continue
        if isinstance(operation, ops.CreateTableOp) and operation.table_name in renamed_new_names:
            continue
        if isinstance(operation, ops.ModifyTableOps) and operation.table_name in renamed_new_names:
            if not all(isinstance(child, ops.CreateIndexOp) for child in operation.ops):
                raise MigrationRenameConflict(
                    f"Table {operation.table_name!r} changes structure while being renamed; split rename and structure changes into separate migrations."
                )
            continue
        rewritten.append(operation)
    if set(rename_pairs) != inserted_renames:
        raise RuntimeError("Every confirmed table rename must replace one DROP TABLE operation.")

    change_by_table_kind = {(change.table_name, change.kind): change for change in ownership_changes}
    new_ownership: list[OwnershipChange] = []
    consumed: set[tuple[str, str]] = set()
    for old_name, new_name in rename_pairs.items():
        old_change = change_by_table_kind.get((old_name, "drop"))
        new_change = change_by_table_kind.get((new_name, "create"))
        if old_change is None or old_change.before is None or new_change is None:
            raise RuntimeError(f"Table rename {old_name!r} -> {new_name!r} has incomplete ownership state.")
        new_ownership.append(
            OwnershipChange(
                table_name=new_name,
                previous_table_name=old_name,
                app_label=old_change.app_label,
                kind="rename",
                before=old_change.before,
                after_managed=True,
            )
        )
        consumed.update({(old_name, "drop"), (new_name, "create")})
    new_ownership.extend(change for change in ownership_changes if (change.table_name, change.kind) not in consumed)

    renamed_tables = frozenset((*rename_pairs, *rename_pairs.values()))
    new_summaries = [summary for summary in summaries if not set(summary.table_names) & renamed_tables]
    new_summaries.extend(
        OperationSummary(
            operation=next(operation for operation in rewritten if isinstance(operation, ops.RenameTableOp) and operation.table_name == old_name),
            kind="rename_table",
            table_names=(old_name, new_name),
            description=f"rename {old_name} to {new_name}",
        )
        for old_name, new_name in rename_pairs.items()
    )
    return rewritten, new_ownership, new_summaries


def _table_shapes_match(
    old_table: Table,
    new_table: Table,
    connection: Connection,
) -> bool:
    """Compare logical table structure while ignoring the table identity itself."""
    dialect = connection.dialect

    def column_shape(column: Column[Any]) -> tuple[Any, ...]:
        server_default = column.server_default
        default_value = _normalized_sql(getattr(server_default, "arg", server_default)) if server_default is not None else None
        return (
            column.name,
            str(column.type.compile(dialect=dialect)).casefold(),
            column.nullable,
            default_value,
        )

    if tuple(column_shape(column) for column in old_table.columns) != tuple(column_shape(column) for column in new_table.columns):
        return False
    if tuple(column.name for column in old_table.primary_key.columns) != tuple(column.name for column in new_table.primary_key.columns):
        return False

    def index_shapes(table: Table) -> set[tuple[Any, ...]]:
        return {
            (
                tuple(column.name for column in index.columns),
                bool(index.unique),
            )
            for index in table.indexes
        }

    if index_shapes(old_table) != index_shapes(new_table):
        return False

    def unique_shapes(table: Table) -> set[tuple[str, ...]]:
        return {tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}

    if unique_shapes(old_table) != unique_shapes(new_table):
        return False

    def foreign_key_shapes(table: Table) -> set[tuple[Any, ...]]:
        result = set()
        for constraint in table.foreign_key_constraints:
            remote = tuple(
                (
                    element.target_fullname.rsplit(".", 1)[0],
                    element.target_fullname.rsplit(".", 1)[1],
                )
                for element in constraint.elements
            )
            result.add(
                (
                    tuple(column.name for column in constraint.columns),
                    remote,
                    constraint.ondelete,
                    constraint.onupdate,
                )
            )
        return result

    old_foreign_keys = foreign_key_shapes(old_table)
    new_foreign_keys = foreign_key_shapes(new_table)
    old_foreign_keys = {
        (
            local,
            tuple((new_table.name if table_name == old_table.name else table_name, column_name) for table_name, column_name in remote),
            ondelete,
            onupdate,
        )
        for local, remote, ondelete, onupdate in old_foreign_keys
    }
    if old_foreign_keys != new_foreign_keys:
        return False

    old_checks = {
        _normalized_sql(constraint.sqltext).replace(old_table.name.casefold(), new_table.name.casefold())
        for constraint in old_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    new_checks = {_normalized_sql(constraint.sqltext) for constraint in new_table.constraints if isinstance(constraint, CheckConstraint)}
    return old_checks == new_checks


def _table_object_reconciliation(
    old_table: Table,
    new_table: Table,
) -> list[ops.MigrateOperation]:
    """Recreate named indexes/constraints whose name followed the old table."""
    operations: list[ops.MigrateOperation] = []
    old_indexes = {(tuple(column.name for column in index.columns), bool(index.unique)): index for index in old_table.indexes}
    new_indexes = {(tuple(column.name for column in index.columns), bool(index.unique)): index for index in new_table.indexes}
    for key, old_index in old_indexes.items():
        new_index = new_indexes[key]
        if old_index.name == new_index.name:
            continue
        if old_index.name is None or new_index.name is None:
            raise MigrationRenameConflict(f"Cannot safely reconcile an unnamed index while renaming {old_table.name!r}.")
        operations.extend(
            (
                ops.DropIndexOp(
                    str(old_index.name),
                    table_name=new_table.name,
                    schema=new_table.schema,
                ),
                ops.CreateIndexOp.from_index(new_index),
            )
        )

    old_constraints = {
        _constraint_shape(constraint, old_table, new_table.name): constraint
        for constraint in old_table.constraints
        if not isinstance(constraint, PrimaryKeyConstraint)
    }
    new_constraints = {
        _constraint_shape(constraint, new_table, new_table.name): constraint
        for constraint in new_table.constraints
        if not isinstance(constraint, PrimaryKeyConstraint)
    }
    for key, old_constraint in old_constraints.items():
        new_constraint = new_constraints[key]
        if old_constraint.name == new_constraint.name:
            continue
        if old_constraint.name is None or new_constraint.name is None:
            continue
        operations.extend(
            (
                ops.DropConstraintOp(
                    str(old_constraint.name),
                    new_table.name,
                    type_=_constraint_type(old_constraint),
                    schema=new_table.schema,
                ),
                ops.AddConstraintOp.from_constraint(new_constraint),
            )
        )

    if old_table.primary_key.name != new_table.primary_key.name and all(
        name is not None for name in (old_table.primary_key.name, new_table.primary_key.name)
    ):
        raise MigrationRenameConflict(f"Named primary key changes while renaming {old_table.name!r}; split the operations manually.")
    return operations


def _constraint_shape(
    constraint: Constraint,
    table: Table,
    normalized_table_name: str,
) -> tuple[Any, ...]:
    """Describe a non-PK constraint without its generated name."""
    columns = tuple(column.name for column in getattr(constraint, "columns", ()))
    if isinstance(constraint, UniqueConstraint):
        return ("unique", columns)
    if isinstance(constraint, CheckConstraint):
        expression = _normalized_sql(constraint.sqltext).replace(
            table.name.casefold(),
            normalized_table_name.casefold(),
        )
        return ("check", expression)
    if isinstance(constraint, ForeignKeyConstraint):
        remote = tuple(
            (
                normalized_table_name if element.target_fullname.rsplit(".", 1)[0] == table.name else element.target_fullname.rsplit(".", 1)[0],
                element.target_fullname.rsplit(".", 1)[1],
            )
            for element in constraint.elements
        )
        return (
            "foreignkey",
            columns,
            remote,
            constraint.ondelete,
            constraint.onupdate,
        )
    return (type(constraint).__name__, columns)


def _constraint_type(constraint: Constraint) -> str:
    """Return Alembic's standard DROP CONSTRAINT type name."""
    if isinstance(constraint, UniqueConstraint):
        return "unique"
    if isinstance(constraint, CheckConstraint):
        return "check"
    if isinstance(constraint, ForeignKeyConstraint):
        return "foreignkey"
    raise MigrationRenameConflict(f"Unsupported named constraint type during table rename: {type(constraint).__name__}.")


def _resolve_column_intent(
    connection: Connection,
    operations: list[ops.MigrateOperation],
    interaction: MigrationInteraction,
) -> list[ops.MigrateOperation]:
    """Replace confirmed add/drop column pairs and confirm unmatched deletion."""
    operations = _merge_modify_table_operations(operations)
    resolved: list[ops.MigrateOperation] = []
    for operation in operations:
        if not isinstance(operation, ops.ModifyTableOps):
            resolved.append(operation)
            continue
        adds = [child for child in operation.ops if isinstance(child, ops.AddColumnOp)]
        drops = [child for child in operation.ops if isinstance(child, ops.DropColumnOp)]
        if not drops:
            resolved.append(operation)
            continue

        mappings: dict[str, ops.AddColumnOp] = {}
        available_adds = list(adds)
        for drop in drops:
            selected: ops.AddColumnOp | None = None
            if len(drops) == 1 and len(available_adds) == 1:
                candidate = available_adds[0]
                if interaction.confirm(
                    f"Treat column {operation.table_name}.{drop.column_name} as renamed to {candidate.column.name}?",
                    default=False,
                ):
                    selected = candidate
            elif available_adds:
                choices = (
                    *(str(candidate.column.name) for candidate in available_adds),
                    "not a rename",
                )
                choice = interaction.choose(
                    f"Choose the new column for {operation.table_name}.{drop.column_name}.",
                    choices,
                )
                if choice != "not a rename":
                    selected = next(
                        (candidate for candidate in available_adds if candidate.column.name == choice),
                        None,
                    )
                    if selected is None:
                        raise ValueError(f"Unknown column rename selection: {choice!r}.")
            if selected is not None:
                mappings[drop.column_name] = selected
                available_adds.remove(selected)

        for drop in drops:
            if drop.column_name in mappings:
                continue
            full_name = f"{operation.table_name}.{drop.column_name}"
            answer = _enter_exact(
                interaction,
                f"Deleting column {full_name!r} removes its data. Enter {full_name} to confirm",
            )
            if answer != full_name:
                raise MigrationDeletionCancelled(f"Deletion of column {full_name!r} was not confirmed.")

        if not mappings:
            resolved.append(operation)
            continue
        rewritten_children: list[ops.MigrateOperation] = []
        inserted: set[str] = set()
        mapped_add_ids = {id(add) for add in mappings.values()}
        old_name_by_add_id = {id(add): old_name for old_name, add in mappings.items()}
        for child in operation.ops:
            if isinstance(child, ops.DropColumnOp) and child.column_name in mappings:
                if child.column_name not in inserted:
                    rewritten_children.append(
                        _rename_column_operation(
                            connection,
                            operation.table_name,
                            operation.schema,
                            child,
                            mappings[child.column_name],
                        )
                    )
                    inserted.add(child.column_name)
                continue
            if isinstance(child, ops.AddColumnOp) and id(child) in mapped_add_ids:
                old_name = old_name_by_add_id[id(child)]
                if old_name not in inserted:
                    dropped = next(item for item in drops if item.column_name == old_name)
                    rewritten_children.append(
                        _rename_column_operation(
                            connection,
                            operation.table_name,
                            operation.schema,
                            dropped,
                            child,
                        )
                    )
                    inserted.add(old_name)
                continue
            rewritten_children.append(child)
        dependency_drops = [child for child in rewritten_children if isinstance(child, (ops.DropIndexOp, ops.DropConstraintOp))]
        column_renames = [child for child in rewritten_children if isinstance(child, ops.AlterColumnOp) and child.modify_name is not None]
        remaining_children = [child for child in rewritten_children if child not in dependency_drops and child not in column_renames]
        _append_modify_segments(
            resolved,
            operation.table_name,
            operation.schema,
            [*dependency_drops, *column_renames, *remaining_children],
        )
    return resolved


def _enter_exact(
    interaction: MigrationInteraction,
    prompt: str,
) -> str:
    """Require exact-entry support only when a destructive path is selected."""
    if not isinstance(interaction, ExactMigrationInteraction):
        raise MigrationInteractionRequired("This deletion requires an interactive terminal with exact text confirmation.")
    return interaction.enter(prompt)


def _merge_modify_table_operations(
    operations: list[ops.MigrateOperation],
) -> list[ops.MigrateOperation]:
    """Join Alembic's separate column/index containers before rename ordering."""
    children_by_table: dict[
        tuple[str | None, str],
        list[ops.MigrateOperation],
    ] = {}
    for operation in operations:
        if isinstance(operation, ops.ModifyTableOps):
            children_by_table.setdefault(
                (operation.schema, operation.table_name),
                [],
            ).extend(operation.ops)

    merged: list[ops.MigrateOperation] = []
    emitted: set[tuple[str | None, str]] = set()
    for operation in operations:
        if not isinstance(operation, ops.ModifyTableOps):
            merged.append(operation)
            continue
        key = (operation.schema, operation.table_name)
        if key in emitted:
            continue
        merged.append(
            ops.ModifyTableOps(
                operation.table_name,
                children_by_table[key],
                schema=operation.schema,
            )
        )
        emitted.add(key)
    return merged


def _append_modify_segments(
    operations: list[ops.MigrateOperation],
    table_name: str,
    schema: str | None,
    children: list[ops.MigrateOperation],
) -> None:
    """Keep index/constraint work outside the batch that renames a column."""
    buffered: list[ops.MigrateOperation] = []

    def flush() -> None:
        if not buffered:
            return
        operations.append(
            ops.ModifyTableOps(
                table_name,
                tuple(buffered),
                schema=schema,
            )
        )
        buffered.clear()

    for child in children:
        if isinstance(child, ops.AlterColumnOp) and child.modify_name is not None:
            flush()
            operations.append(
                ops.ModifyTableOps(
                    table_name,
                    (child,),
                    schema=schema,
                )
            )
        else:
            buffered.append(child)
    flush()


def _rename_column_operation(
    connection: Connection,
    table_name: str,
    schema: str | None,
    dropped: ops.DropColumnOp,
    added: ops.AddColumnOp,
) -> ops.AlterColumnOp:
    """Build one standard ALTER COLUMN using reflected old and current new values."""
    old_column = dropped.to_column()
    new_column = added.column
    dialect = connection.dialect
    old_type = str(old_column.type.compile(dialect=dialect)).casefold()
    new_type = str(new_column.type.compile(dialect=dialect)).casefold()
    old_default = old_column.server_default
    new_default = new_column.server_default
    return ops.AlterColumnOp(
        table_name,
        dropped.column_name,
        schema=schema,
        existing_type=old_column.type,
        existing_nullable=old_column.nullable,
        existing_server_default=old_default,
        existing_comment=old_column.comment,
        modify_name=str(new_column.name),
        modify_type=new_column.type if old_type != new_type else None,
        modify_nullable=(new_column.nullable if old_column.nullable != new_column.nullable else None),
        modify_server_default=(
            new_default
            if _normalized_sql(getattr(old_default, "arg", old_default)) != _normalized_sql(getattr(new_default, "arg", new_default))
            else False
        ),
        modify_comment=(new_column.comment if old_column.comment != new_column.comment else False),
    )


def _reverse_upgrade_ops(upgrade_ops: ops.UpgradeOps) -> ops.DowngradeOps:
    """Build explicit reverse operations, including Alembic's non-reversible rename."""
    return ops.DowngradeOps(ops=[_reverse_operation(operation) for operation in reversed(upgrade_ops.ops)])


def _reverse_operation(operation: ops.MigrateOperation) -> ops.MigrateOperation:
    """Reverse standard operations while preserving table and column names."""
    if isinstance(operation, ops.RenameTableOp):
        return ops.RenameTableOp(
            operation.new_table_name,
            operation.table_name,
            schema=operation.schema,
        )
    if isinstance(operation, ops.ModifyTableOps):
        return ops.ModifyTableOps(
            operation.table_name,
            [_reverse_operation(child) for child in reversed(operation.ops)],
            schema=operation.schema,
        )
    if isinstance(operation, ops.AlterColumnOp) and operation.modify_name is not None:
        return _reverse_column_rename(operation)
    return operation.reverse()


def _reverse_column_rename(operation: ops.AlterColumnOp) -> ops.AlterColumnOp:
    """Reverse Alembic's column rename while restoring every prior attribute."""
    new_name = operation.modify_name
    if new_name is None:
        raise RuntimeError("Column rename reverse requires the modified name.")
    return ops.AlterColumnOp(
        operation.table_name,
        new_name,
        schema=operation.schema,
        existing_type=operation.modify_type or operation.existing_type,
        existing_nullable=(operation.modify_nullable if operation.modify_nullable is not None else operation.existing_nullable),
        existing_server_default=cast(
            Any,
            operation.modify_server_default if operation.modify_server_default is not False else operation.existing_server_default,
        ),
        existing_comment=cast(
            str | None,
            operation.modify_comment if operation.modify_comment is not False else operation.existing_comment,
        ),
        modify_name=operation.column_name,
        modify_type=(operation.existing_type if operation.modify_type is not None else None),
        modify_nullable=(operation.existing_nullable if operation.modify_nullable is not None else None),
        modify_server_default=(operation.existing_server_default if operation.modify_server_default is not False else False),
        modify_comment=(operation.existing_comment if operation.modify_comment is not False else False),
    )


def _order_table_operations(
    connection: Connection,
    metadata: MigrationMetadata,
    state: MigrationState,
    operations: Sequence[ops.MigrateOperation],
) -> tuple[ops.MigrateOperation, ...]:
    """Stabilize Alembic's set-based create/drop output with real FK order."""
    create_order = {table.name: index for index, table in enumerate(metadata.managed_tables)}
    create_operations = sorted(
        (operation for operation in operations if isinstance(operation, ops.CreateTableOp)),
        key=lambda operation: create_order[operation.table_name],
    )

    reflected = MetaData()
    reflected.reflect(
        connection,
        only=[table_name for table_name, ownership in state.schema_registry.items() if ownership.managed],
    )
    drop_order = {table.name: index for index, table in enumerate(reversed(reflected.sorted_tables))}
    drop_operations = sorted(
        (operation for operation in operations if isinstance(operation, ops.DropTableOp)),
        key=lambda operation: drop_order[operation.table_name],
    )
    create_iterator = iter(create_operations)
    drop_iterator = iter(drop_operations)
    return tuple(
        next(create_iterator)
        if isinstance(operation, ops.CreateTableOp)
        else next(drop_iterator)
        if isinstance(operation, ops.DropTableOp)
        else operation
        for operation in operations
    )


def _validate_state(project: MigrationProject, state: MigrationState) -> None:
    """Require a coherent owner and source revision before autogenerate."""
    if state.is_partial:
        raise MigrationStateRecoveryRequired("Oldman migration state is only partially present; run the controlled migrate recovery flow.")

    graph = load_migration_graph(project, config=build_alembic_config(project))
    source_heads = frozenset(revision.revision for revision in graph.heads)
    if state.is_complete:
        state.require_current_owner(project)
        if frozenset(state.revisions) != source_heads:
            raise MigrationRevisionStateError("The database is not at the current project migration heads; run oldman db migrate first.")
    elif source_heads:
        raise MigrationRevisionStateError("The database has no Oldman migration state but the project has revisions; run oldman db migrate first.")


def _include_table(
    table_name: str,
    current_by_name: Mapping[str, Any],
    state: MigrationState,
) -> bool:
    """Include current managed models and formerly managed Registry tables only."""
    if table_name in INTERNAL_TABLE_NAMES:
        return False
    current = current_by_name.get(table_name)
    if current is not None:
        return bool(current.managed)
    ownership = state.schema_registry.get(table_name)
    return ownership is not None and ownership.managed


def _group_operations(
    project: MigrationProject,
    metadata: MigrationMetadata,
    state: MigrationState,
    operations: Sequence[ops.MigrateOperation],
) -> SchemaChanges:
    """Assign full-tree operations without changing their dependency order."""
    known_labels = frozenset(project.apps.labels)
    grouped: dict[str, list[ops.MigrateOperation]] = {}
    summaries: list[OperationSummary] = []
    for operation in operations:
        for app_label, owned_operation in _owned_operations(operation, metadata, state):
            if app_label not in known_labels:
                raise RuntimeError(f"Schema operation belongs to unregistered App {app_label!r}.")
            grouped.setdefault(app_label, []).append(owned_operation)
            summaries.append(_summarize(owned_operation))

    by_app: dict[str, AppSchemaChanges] = {}
    for app_label in sorted(grouped):
        app_operations = grouped[app_label]
        app_summaries = tuple(summary for summary in summaries if summary.operation in app_operations)
        by_app[app_label] = AppSchemaChanges(
            app_label=app_label,
            upgrade_ops=ops.UpgradeOps(ops=app_operations),
            summaries=app_summaries,
        )
    return SchemaChanges(
        by_app=MappingProxyType(by_app),
        summaries=tuple(summaries),
    )


def _owned_operations(
    operation: ops.MigrateOperation,
    metadata: MigrationMetadata,
    state: MigrationState,
) -> tuple[tuple[str, ops.MigrateOperation], ...]:
    """Split the one shared User table where needed; assign ordinary tables directly."""
    table_name = _operation_table_name(operation)
    if table_name is None:
        raise RuntimeError(f"Cannot determine an App owner for Alembic operation {type(operation).__name__}.")
    if metadata.user is not None and table_name == metadata.user.table.name:
        return _owned_user_operations(operation, metadata)

    current = next(
        (item for item in metadata.tables.values() if item.table.name == table_name),
        None,
    )
    if current is not None:
        return ((current.app_label, operation),)
    ownership = state.schema_registry.get(table_name)
    if ownership is not None and ownership.managed:
        return ((ownership.app_label, operation),)
    raise RuntimeError(f"Table {table_name!r} has no managed App owner.")


def _owned_user_operations(
    operation: ops.MigrateOperation,
    metadata: MigrationMetadata,
) -> tuple[tuple[str, ops.MigrateOperation], ...]:
    """Keep Auth core structure separate from the configured User App extension."""
    user = metadata.user
    if user is None:
        raise RuntimeError("User migration metadata is unavailable.")
    if isinstance(operation, ops.CreateTableOp):
        core_items: list[Any] = []
        extension_operations: list[ops.MigrateOperation] = []
        for item in operation.columns:
            if isinstance(item, Column):
                if item.name in user.core.column_names:
                    core_items.append(item)
                else:
                    extension_operations.append(ops.AddColumnOp(operation.table_name, item, schema=operation.schema))
            elif isinstance(item, Constraint):
                if _is_user_core_constraint(item, user.core):
                    core_items.append(item)
                elif not isinstance(item, PrimaryKeyConstraint):
                    extension_operations.append(ops.AddConstraintOp.from_constraint(item))

        core_create = copy.copy(operation)
        core_create.columns = core_items
        result: list[tuple[str, ops.MigrateOperation]] = [(USER_TABLE_OWNER_LABEL, core_create)]
        if extension_operations:
            result.append(
                (
                    user.app_label,
                    ops.ModifyTableOps(
                        operation.table_name,
                        extension_operations,
                        schema=operation.schema,
                    ),
                )
            )
        return tuple(result)

    if isinstance(operation, ops.ModifyTableOps):
        by_owner: dict[str, list[ops.MigrateOperation]] = {}
        for child in operation.ops:
            owner = _user_child_owner(child, metadata)
            by_owner.setdefault(owner, []).append(child)
        return tuple(
            (
                owner,
                ops.ModifyTableOps(
                    operation.table_name,
                    children,
                    schema=operation.schema,
                ),
            )
            for owner, children in by_owner.items()
        )

    return ((USER_TABLE_OWNER_LABEL, operation),)


def _user_child_owner(
    operation: ops.MigrateOperation,
    metadata: MigrationMetadata,
) -> str:
    """Classify a change inside oldman_user by the frozen core contract."""
    user = metadata.user
    if user is None:
        raise RuntimeError("User migration metadata is unavailable.")
    column_name = getattr(operation, "column_name", None)
    if isinstance(operation, ops.AddColumnOp):
        column_name = operation.column.name
    if isinstance(column_name, str):
        return USER_TABLE_OWNER_LABEL if column_name in user.core.column_names else user.app_label

    index_name = getattr(operation, "index_name", None)
    if index_name is not None:
        return USER_TABLE_OWNER_LABEL if str(index_name) in user.core.index_names else user.app_label

    constraint_name = getattr(operation, "constraint_name", None)
    if constraint_name is not None and str(constraint_name) in user.core.check_constraint_names:
        return USER_TABLE_OWNER_LABEL
    reverse = getattr(operation, "_reverse", None)
    columns = tuple(getattr(operation, "columns", ()) or getattr(reverse, "columns", ()))
    normalized_columns = tuple(column if isinstance(column, str) else getattr(column, "name", None) for column in columns)
    if normalized_columns in user.core.unique_column_sets:
        return USER_TABLE_OWNER_LABEL
    return user.app_label


def _is_user_core_constraint(constraint: Constraint, core: Any) -> bool:
    """Recognize only constraints fixed by the Auth table contract."""
    if isinstance(constraint, PrimaryKeyConstraint):
        return tuple(column.name for column in constraint.columns) == core.primary_key_column_names
    if isinstance(constraint, CheckConstraint):
        return constraint.name in core.check_constraint_names
    if isinstance(constraint, UniqueConstraint):
        return tuple(column.name for column in constraint.columns) in core.unique_column_sets
    return False


def _operation_table_name(operation: ops.MigrateOperation) -> str | None:
    """Read the source table carried by standard schema operations."""
    table_name = getattr(operation, "table_name", None)
    if isinstance(table_name, str):
        return table_name
    source_table = getattr(operation, "source_table", None)
    return source_table if isinstance(source_table, str) else None


def _summarize(operation: ops.MigrateOperation) -> OperationSummary:
    """Convert one top-level operation to concise, stable text."""
    table_name = _operation_table_name(operation)
    table_names = (table_name,) if table_name is not None else ()
    if isinstance(operation, ops.CreateTableOp):
        kind = "create_table"
        description = f"create {table_name}"
    elif isinstance(operation, ops.DropTableOp):
        kind = "drop_table"
        description = f"drop {table_name}"
    elif isinstance(operation, ops.ModifyTableOps):
        kind = "alter_table"
        description = f"alter {table_name}"
    else:
        kind = type(operation).__name__
        description = f"update {table_name or 'schema'}"
    return OperationSummary(
        operation=operation,
        kind=kind,
        table_names=table_names,
        description=description,
    )


def _ordered_unique(values: Any) -> tuple[str, ...]:
    """Return unique strings without replacing meaningful operation order."""
    return tuple(dict.fromkeys(values))


__all__ = [
    "AppSchemaChanges",
    "MigrationAdoptionConflict",
    "MigrationDeletionCancelled",
    "MigrationModelChangeRequired",
    "MigrationRenameConflict",
    "MigrationRevisionStateError",
    "MigrationSchemaDriftError",
    "OperationSummary",
    "OwnershipChange",
    "SchemaChanges",
    "collect_schema_changes",
    "resolve_schema_intent",
    "table_structure_errors",
]
