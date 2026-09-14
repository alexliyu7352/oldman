"""Fixed internal tables for migration ownership and table management state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql.sqltypes import String as StringType

from oldman.db.migrations.metadata import INTERNAL_TABLE_NAMES
from oldman.db.migrations.project import MigrationProject

INTERNAL_METADATA = MetaData()
MIGRATION_OWNER_TABLE = Table(
    "oldman_migration_owner",
    INTERNAL_METADATA,
    Column("singleton_id", SmallInteger, primary_key=True, nullable=False),
    Column("project_id", String(36), nullable=False),
    Column("project_name", String(255), nullable=False),
    UniqueConstraint("project_id", name="uq_oldman_migration_owner_project_id"),
)
ALEMBIC_VERSION_TABLE = Table(
    "oldman_alembic_version",
    INTERNAL_METADATA,
    Column("version_num", String(32), primary_key=True, nullable=False),
)
SCHEMA_REGISTRY_TABLE = Table(
    "oldman_schema_registry",
    INTERNAL_METADATA,
    Column("table_name", String(255), primary_key=True, nullable=False),
    Column("app_label", String(255), nullable=False),
    Column("managed", Boolean, nullable=False),
    Column("ownership_revision", String(255), nullable=False),
)
INTERNAL_TABLES = (
    MIGRATION_OWNER_TABLE.name,
    ALEMBIC_VERSION_TABLE.name,
    SCHEMA_REGISTRY_TABLE.name,
)


class ReservedMigrationTableError(RuntimeError):
    """Raised when a reserved table exists with a non-framework signature."""


class MigrationStateRecoveryRequired(RuntimeError):
    """Raised when only part of Oldman's internal migration state remains."""


class MigrationOwnershipError(RuntimeError):
    """Raised when another project owns the current database migration state."""


class SchemaOwnershipError(RuntimeError):
    """Raised when code attempts an unsupported table ownership transfer."""


@dataclass(frozen=True, slots=True)
class MigrationOwner:
    """The one project identity stored in oldman_migration_owner."""

    project_id: UUID
    project_name: str


@dataclass(frozen=True, slots=True)
class SchemaOwnership:
    """One table-level ownership row advanced by migration revisions."""

    table_name: str
    app_label: str
    managed: bool
    ownership_revision: str


@dataclass(frozen=True, slots=True)
class MigrationState:
    """Read-only snapshot of all currently present Oldman migration state."""

    present_tables: frozenset[str]
    owner: MigrationOwner | None
    revisions: tuple[str, ...]
    schema_registry: Mapping[str, SchemaOwnership]

    @property
    def missing_tables(self) -> frozenset[str]:
        """Return fixed internal tables absent from the database."""
        return INTERNAL_TABLE_NAMES - self.present_tables

    @property
    def is_complete(self) -> bool:
        """Return whether all three fixed tables exist with valid signatures."""
        return not self.missing_tables

    @property
    def is_partial(self) -> bool:
        """Return whether some, but not all, fixed tables exist."""
        return bool(self.present_tables) and not self.is_complete

    def require_current_owner(self, project: MigrationProject) -> None:
        """Require a complete owner row belonging to the supplied project."""
        if self.owner is None:
            raise MigrationStateRecoveryRequired(
                "Oldman migration owner state is missing; run the controlled migrate recovery flow."
            )
        if self.owner.project_id != project.project_id:
            raise MigrationOwnershipError(
                "Database migrations belong to project "
                f"{self.owner.project_name!r} ({self.owner.project_id}), not "
                f"{project.project_name!r} ({project.project_id})."
            )

    @classmethod
    def inspect(cls, connection: Connection) -> MigrationState:
        """Reflect and validate existing internal tables without creating them."""
        inspector = sqlalchemy_inspect(connection)
        database_tables = set(inspector.get_table_names())
        present = frozenset(database_tables & INTERNAL_TABLE_NAMES)
        for table in (MIGRATION_OWNER_TABLE, ALEMBIC_VERSION_TABLE, SCHEMA_REGISTRY_TABLE):
            if table.name in present:
                _validate_table_signature(inspector, table)

        owner = _read_owner(connection) if MIGRATION_OWNER_TABLE.name in present else None
        revisions = _read_revisions(connection) if ALEMBIC_VERSION_TABLE.name in present else ()
        registry = _read_schema_registry(connection) if SCHEMA_REGISTRY_TABLE.name in present else {}
        return cls(
            present_tables=present,
            owner=owner,
            revisions=revisions,
            schema_registry=MappingProxyType(registry),
        )


def ensure_for_first_migrate(
    connection: Connection,
    project: MigrationProject,
) -> MigrationState:
    """Acquire first ownership before Alembic starts any business-table DDL."""
    state = MigrationState.inspect(connection)
    if state.is_partial:
        raise MigrationStateRecoveryRequired(
            "Oldman migration state is only partially present; run the controlled migrate recovery flow."
        )
    if state.is_complete:
        state.require_current_owner(project)
        return state

    MIGRATION_OWNER_TABLE.create(connection)
    SCHEMA_REGISTRY_TABLE.create(connection)
    connection.execute(
        MIGRATION_OWNER_TABLE.insert().values(
            singleton_id=1,
            project_id=str(project.project_id),
            project_name=project.project_name,
        )
    )
    return MigrationState.inspect(connection)


def set_table_ownership(
    connection: Connection,
    *,
    table_name: str,
    app_label: str,
    managed: bool,
    ownership_revision: str,
) -> None:
    """Insert or update ownership without allowing an implicit App transfer."""
    _require_nonempty("table_name", table_name)
    _require_nonempty("app_label", app_label)
    _require_nonempty("ownership_revision", ownership_revision)
    if not isinstance(managed, bool):
        raise TypeError("managed must be a bool")
    if table_name in INTERNAL_TABLE_NAMES:
        raise SchemaOwnershipError(
            f"Internal migration table {table_name!r} cannot enter Schema Registry."
        )
    if table_name == "oldman_user" and app_label != "auth":
        raise SchemaOwnershipError("oldman_user table ownership must remain with Auth.")

    _require_registry_signature(connection)
    existing = connection.execute(
        select(SCHEMA_REGISTRY_TABLE.c.app_label).where(
            SCHEMA_REGISTRY_TABLE.c.table_name == table_name
        )
    ).scalar_one_or_none()
    if existing is not None and existing != app_label:
        raise SchemaOwnershipError(
            f"Table {table_name!r} belongs to App {existing!r}, not {app_label!r}."
        )
    values = {
        "app_label": app_label,
        "managed": managed,
        "ownership_revision": ownership_revision,
    }
    if existing is None:
        connection.execute(
            SCHEMA_REGISTRY_TABLE.insert().values(
                table_name=table_name,
                **values,
            )
        )
    else:
        connection.execute(
            SCHEMA_REGISTRY_TABLE.update()
            .where(SCHEMA_REGISTRY_TABLE.c.table_name == table_name)
            .values(**values)
        )


def delete_table_ownership(connection: Connection, table_name: str) -> None:
    """Remove one ownership row after its revision has removed or retired it."""
    _require_nonempty("table_name", table_name)
    _require_registry_signature(connection)
    connection.execute(
        SCHEMA_REGISTRY_TABLE.delete().where(
            SCHEMA_REGISTRY_TABLE.c.table_name == table_name
        )
    )


def rebuild_internal_state(
    connection: Connection,
    project: MigrationProject,
) -> None:
    """Recreate and clear only fixed migration state after recovery validation."""
    state = MigrationState.inspect(connection)
    if state.owner is not None:
        state.require_current_owner(project)
    INTERNAL_METADATA.create_all(connection)
    connection.execute(SCHEMA_REGISTRY_TABLE.delete())
    connection.execute(ALEMBIC_VERSION_TABLE.delete())
    connection.execute(MIGRATION_OWNER_TABLE.delete())
    connection.execute(
        MIGRATION_OWNER_TABLE.insert().values(
            singleton_id=1,
            project_id=str(project.project_id),
            project_name=project.project_name,
        )
    )


def _read_owner(connection: Connection) -> MigrationOwner | None:
    """Read and validate the singleton owner record."""
    rows = connection.execute(
        select(
            MIGRATION_OWNER_TABLE.c.singleton_id,
            MIGRATION_OWNER_TABLE.c.project_id,
            MIGRATION_OWNER_TABLE.c.project_name,
        )
    ).all()
    if not rows:
        return None
    if len(rows) != 1 or rows[0].singleton_id != 1:
        raise ReservedMigrationTableError(
            "oldman_migration_owner must contain exactly the singleton row with singleton_id=1."
        )
    try:
        project_id = UUID(rows[0].project_id)
    except (TypeError, ValueError):
        raise ReservedMigrationTableError(
            "oldman_migration_owner.project_id must contain a valid UUID string."
        ) from None
    if not isinstance(rows[0].project_name, str) or not rows[0].project_name:
        raise ReservedMigrationTableError(
            "oldman_migration_owner.project_name must contain a non-empty string."
        )
    return MigrationOwner(project_id=project_id, project_name=rows[0].project_name)


def _read_revisions(connection: Connection) -> tuple[str, ...]:
    """Return stable current Alembic heads from the standard version table."""
    return tuple(
        connection.execute(
            select(ALEMBIC_VERSION_TABLE.c.version_num).order_by(
                ALEMBIC_VERSION_TABLE.c.version_num
            )
        ).scalars()
    )


def _read_schema_registry(connection: Connection) -> dict[str, SchemaOwnership]:
    """Return table ownership keyed by the Registry primary key."""
    rows = connection.execute(
        select(SCHEMA_REGISTRY_TABLE).order_by(SCHEMA_REGISTRY_TABLE.c.table_name)
    ).mappings()
    return {
        row["table_name"]: SchemaOwnership(
            table_name=row["table_name"],
            app_label=row["app_label"],
            managed=bool(row["managed"]),
            ownership_revision=row["ownership_revision"],
        )
        for row in rows
    }


def _validate_table_signature(inspector: Inspector, expected: Table) -> None:
    """Compare reflected columns, semantic types, nullability, keys and uniqueness."""
    actual_columns = {
        column["name"]: column for column in inspector.get_columns(expected.name)
    }
    expected_columns = {column.name: column for column in expected.columns}
    errors: list[str] = []
    if set(actual_columns) != set(expected_columns):
        errors.append(
            f"columns expected={sorted(expected_columns)!r} actual={sorted(actual_columns)!r}"
        )
    for name in sorted(set(actual_columns) & set(expected_columns)):
        actual = actual_columns[name]
        column = expected_columns[name]
        if not _types_equivalent(actual["type"], column.type):
            errors.append(
                f"column {name!r} type expected={column.type!r} actual={actual['type']!r}"
            )
        if bool(actual["nullable"]) is not column.nullable:
            errors.append(
                f"column {name!r} nullable expected={column.nullable!r} actual={actual['nullable']!r}"
            )

    actual_primary_key = tuple(
        inspector.get_pk_constraint(expected.name).get("constrained_columns") or ()
    )
    expected_primary_key = tuple(column.name for column in expected.primary_key.columns)
    if actual_primary_key != expected_primary_key:
        errors.append(
            f"primary key expected={expected_primary_key!r} actual={actual_primary_key!r}"
        )

    expected_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in expected.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    actual_unique = {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints(expected.name)
    }
    if actual_unique != expected_unique:
        errors.append(
            f"unique constraints expected={sorted(expected_unique)!r} actual={sorted(actual_unique)!r}"
        )
    if errors:
        raise ReservedMigrationTableError(
            f"Reserved table {expected.name!r} has a conflicting signature: "
            + "; ".join(errors)
        )


def _types_equivalent(actual: object, expected: object) -> bool:
    """Compare SQLAlchemy type affinity and meaningful String length."""
    actual_affinity = getattr(actual, "_type_affinity", None)
    expected_affinity = getattr(expected, "_type_affinity", None)
    if actual_affinity is not expected_affinity:
        return False
    if isinstance(expected, StringType):
        return getattr(actual, "length", None) == expected.length
    return True


def _require_registry_signature(connection: Connection) -> None:
    """Require the Registry table to exist with the exact fixed signature."""
    inspector = sqlalchemy_inspect(connection)
    if not inspector.has_table(SCHEMA_REGISTRY_TABLE.name):
        raise MigrationStateRecoveryRequired(
            "oldman_schema_registry is missing; run the controlled migrate recovery flow."
        )
    _validate_table_signature(inspector, SCHEMA_REGISTRY_TABLE)


def _require_nonempty(name: str, value: str) -> None:
    """Validate one persisted identifier without silently normalizing it."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


__all__ = [
    "ALEMBIC_VERSION_TABLE",
    "INTERNAL_METADATA",
    "INTERNAL_TABLE_NAMES",
    "INTERNAL_TABLES",
    "MIGRATION_OWNER_TABLE",
    "SCHEMA_REGISTRY_TABLE",
    "MigrationOwner",
    "MigrationOwnershipError",
    "MigrationState",
    "MigrationStateRecoveryRequired",
    "ReservedMigrationTableError",
    "SchemaOwnership",
    "SchemaOwnershipError",
    "delete_table_ownership",
    "ensure_for_first_migrate",
    "rebuild_internal_state",
    "set_table_ownership",
]
