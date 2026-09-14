"""SQLAlchemy-facing exports for the canonical database manager."""

from sqlalchemy import AsyncAdaptedQueuePool

from oldman.db.session import (
    DatabaseConfigSource,
    DatabaseManager,
    DatabaseNotConfiguredError,
    db_manager,
)

connect_args = {"check_same_thread": False}
POOL_CLASS = AsyncAdaptedQueuePool

__all__ = [
    "POOL_CLASS",
    "DatabaseConfigSource",
    "DatabaseManager",
    "DatabaseNotConfiguredError",
    "connect_args",
    "db_manager",
]
