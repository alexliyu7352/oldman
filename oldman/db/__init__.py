"""Public database models and lazy sessions; deployments use migrations."""

from oldman.db.introspection import explicit_primary_key_column, session_dialect
from oldman.db.models import (
    APP_LABEL_INFO_KEY,
    MANAGED_INFO_KEY,
    Base,
    DatabaseModel,
    ModelMetadata,
    assign_model_table_app_labels,
    resolve_model_display_names,
)
from oldman.db.session import (
    DatabaseConfigSource,
    DatabaseManager,
    DatabaseNotConfiguredError,
    db_manager,
)

__all__ = [
    "APP_LABEL_INFO_KEY",
    "Base",
    "DatabaseConfigSource",
    "DatabaseManager",
    "DatabaseModel",
    "DatabaseNotConfiguredError",
    "MANAGED_INFO_KEY",
    "ModelMetadata",
    "assign_model_table_app_labels",
    "resolve_model_display_names",
    "db_manager",
    "explicit_primary_key_column",
    "session_dialect",
]
