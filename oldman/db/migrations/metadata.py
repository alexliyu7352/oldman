"""In-memory schema ownership used by Oldman's Alembic wrapper."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from sqlalchemy import MetaData, Table

from oldman.auth.base import (
    USER_APP_LABEL_INFO_KEY,
    USER_TABLE_OWNER_LABEL,
    AbstractUser,
)
from oldman.auth.contracts import (
    USER_CORE_CHECK_CONSTRAINTS,
    USER_CORE_FIELD_NAMES,
    USER_CORE_INDEXES,
    USER_CORE_UNIQUE_COLUMN_SETS,
    USER_PRIMARY_KEY_NAME,
)
from oldman.db.migrations.project import MigrationProject
from oldman.db.models import (
    APP_LABEL_INFO_KEY,
    MANAGED_INFO_KEY,
    Base,
    ModelMetadata,
)

INTERNAL_TABLE_NAMES = frozenset(
    {
        "oldman_migration_owner",
        "oldman_alembic_version",
        "oldman_schema_registry",
    }
)


@dataclass(frozen=True, slots=True)
class TableMigrationMetadata:
    """Current code ownership for one SQLAlchemy Table."""

    table: Table
    app_label: str
    managed: bool
    models: tuple[type[Any], ...]


@dataclass(frozen=True, slots=True)
class UserCoreStructure:
    """Stable Auth-owned structure used to classify oldman_user changes."""

    column_names: frozenset[str]
    primary_key_column_names: tuple[str, ...]
    index_names: frozenset[str]
    check_constraint_names: frozenset[str]
    unique_column_sets: frozenset[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class UserMigrationMetadata:
    """Separate the Auth table owner from the selected User extension App."""

    model: type[AbstractUser]
    table: Table
    app_label: str
    core: UserCoreStructure


@dataclass(frozen=True, slots=True)
class MigrationMetadata:
    """Complete current schema and immutable owner lookups for one project."""

    metadata: MetaData
    models: Mapping[type[Any], ModelMetadata]
    tables: Mapping[Table, TableMigrationMetadata]
    managed_tables: tuple[Table, ...]
    user: UserMigrationMetadata | None


def load_migration_metadata(project: MigrationProject) -> MigrationMetadata:
    """Load all project models and freeze their current migration ownership."""
    project.apps.load_models(user_model_path=project.user_model_path)
    model_items = project.apps.models
    models = {item.model: item for item in model_items}
    models_by_table: dict[Table, list[type[Any]]] = {}
    for item in model_items:
        models_by_table.setdefault(item.table, []).append(item.model)

    table_items: dict[Table, TableMigrationMetadata] = {}
    for table in Base.metadata.tables.values():
        if table.name in INTERNAL_TABLE_NAMES:
            raise ValueError(
                f"Table name {table.name!r} is reserved for Oldman migration state."
            )
        app_label = table.info.get(APP_LABEL_INFO_KEY)
        if not isinstance(app_label, str) or not app_label:
            raise RuntimeError(
                f"Table {table.fullname!r} has no registered App owner."
            )
        managed = table.info.get(MANAGED_INFO_KEY)
        if not isinstance(managed, bool):
            raise RuntimeError(
                f"Table {table.fullname!r} has no valid managed state."
            )
        if managed and table.schema is not None:
            raise ValueError(
                f"Managed table {table.fullname!r} cannot declare an explicit schema."
            )
        table_items[table] = TableMigrationMetadata(
            table=table,
            app_label=app_label,
            managed=managed,
            models=tuple(models_by_table.get(table, ())),
        )

    user = _resolve_user_metadata(project, model_items, table_items)
    managed_tables = tuple(
        table
        for table in Base.metadata.sorted_tables
        if table_items[table].managed
    )
    return MigrationMetadata(
        metadata=Base.metadata,
        models=MappingProxyType(models),
        tables=MappingProxyType(table_items),
        managed_tables=managed_tables,
        user=user,
    )


def _resolve_user_metadata(
    project: MigrationProject,
    model_items: tuple[ModelMetadata, ...],
    table_items: Mapping[Table, TableMigrationMetadata],
) -> UserMigrationMetadata | None:
    """Resolve the one configured User and its split structure ownership."""
    user_models = [
        item.model
        for item in model_items
        if issubclass(item.model, AbstractUser)
    ]
    if project.user_model_path is None:
        if user_models:
            names = ", ".join(
                f"{model.__module__}.{model.__qualname__}"
                for model in user_models
            )
            raise RuntimeError(
                f"Concrete User model(s) loaded without project Auth selection: {names}."
            )
        return None
    if len(user_models) != 1:
        raise RuntimeError(
            "Migration metadata must contain exactly one configured User model."
        )

    model = user_models[0]
    qualified_name = f"{model.__module__}.{model.__qualname__}"
    if qualified_name != project.user_model_path:
        raise RuntimeError(
            f"Loaded User {qualified_name!r} does not match project selection "
            f"{project.user_model_path!r}."
        )
    table = cast(Table, model.__table__)
    table_metadata = table_items[table]
    if table_metadata.app_label != USER_TABLE_OWNER_LABEL:
        raise RuntimeError("oldman_user table ownership must remain with Auth.")
    user_app_label = table.info.get(USER_APP_LABEL_INFO_KEY)
    if not isinstance(user_app_label, str) or not user_app_label:
        raise RuntimeError("oldman_user has no selected User App owner.")

    return UserMigrationMetadata(
        model=model,
        table=table,
        app_label=user_app_label,
        core=UserCoreStructure(
            column_names=frozenset(USER_CORE_FIELD_NAMES),
            primary_key_column_names=(USER_PRIMARY_KEY_NAME,),
            index_names=frozenset(USER_CORE_INDEXES),
            check_constraint_names=frozenset(USER_CORE_CHECK_CONSTRAINTS),
            unique_column_sets=frozenset(USER_CORE_UNIQUE_COLUMN_SETS),
        ),
    )


__all__ = [
    "INTERNAL_TABLE_NAMES",
    "MigrationMetadata",
    "TableMigrationMetadata",
    "UserCoreStructure",
    "UserMigrationMetadata",
    "load_migration_metadata",
]
