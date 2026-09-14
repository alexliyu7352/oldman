"""Project-level database migration APIs."""

from oldman.db.migrations.alembic import (
    AppMigrationLocation,
    AppRevisionBranch,
    MigrationGraph,
    MigrationGraphError,
    build_alembic_config,
    collect_migration_locations,
    load_migration_graph,
)
from oldman.db.migrations.metadata import (
    INTERNAL_TABLE_NAMES,
    MigrationMetadata,
    TableMigrationMetadata,
    UserCoreStructure,
    UserMigrationMetadata,
    load_migration_metadata,
)
from oldman.db.migrations.project import (
    MigrationProject,
    ServiceMigrationConfig,
    load_migration_project,
)
from oldman.db.migrations.state import (
    MigrationOwner,
    MigrationOwnershipError,
    MigrationState,
    MigrationStateRecoveryRequired,
    ReservedMigrationTableError,
    SchemaOwnership,
    SchemaOwnershipError,
    delete_table_ownership,
    ensure_for_first_migrate,
    set_table_ownership,
)

__all__ = [
    "AppMigrationLocation",
    "AppRevisionBranch",
    "INTERNAL_TABLE_NAMES",
    "MigrationGraph",
    "MigrationGraphError",
    "MigrationMetadata",
    "MigrationProject",
    "MigrationOwner",
    "MigrationOwnershipError",
    "MigrationState",
    "MigrationStateRecoveryRequired",
    "ReservedMigrationTableError",
    "ServiceMigrationConfig",
    "SchemaOwnership",
    "SchemaOwnershipError",
    "TableMigrationMetadata",
    "UserCoreStructure",
    "UserMigrationMetadata",
    "build_alembic_config",
    "collect_migration_locations",
    "delete_table_ownership",
    "ensure_for_first_migrate",
    "load_migration_graph",
    "load_migration_metadata",
    "load_migration_project",
    "set_table_ownership",
]
