"""Shared Alembic environment loaded from Oldman's installed package."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from oldman.db.migrations.alembic import VERSION_TABLE_NAME
from oldman.db.migrations.metadata import MigrationMetadata

config = context.config
raw_migration_metadata = config.attributes.get("oldman_metadata")
if not isinstance(raw_migration_metadata, MigrationMetadata):
    raise RuntimeError("Oldman migration metadata is missing from Alembic Config.")
migration_metadata: MigrationMetadata = raw_migration_metadata


def configure_context(connection: Connection) -> None:
    """Configure one online migration with Oldman's fixed comparison contract."""
    context.configure(
        connection=connection,
        target_metadata=migration_metadata.metadata,
        version_table=VERSION_TABLE_NAME,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )


def run_with_connection(connection: Connection) -> None:
    """Run migrations on a caller-owned synchronous connection."""
    configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_with_async_engine() -> None:
    """Create the configured async engine only when a command needs a connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(run_with_connection)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Use an injected transaction or Oldman's async database URL."""
    connection = config.attributes.get("connection")
    if connection is not None:
        if not isinstance(connection, Connection):
            raise TypeError("Alembic Config connection must be a synchronous SQLAlchemy Connection.")
        run_with_connection(connection)
        return
    asyncio.run(run_with_async_engine())


if context.is_offline_mode():
    raise RuntimeError("Oldman does not expose offline SQL migrations.")
run_migrations_online()
