"""Database engine and async session lifecycle management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import AsyncAdaptedQueuePool, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import NoSuchModuleError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import Pool
from sqlmodel.ext.asyncio.session import AsyncSession

from oldman.conf.schemas import DatabaseConfig
from oldman.db.models import MANAGED_INFO_KEY, Base
from oldman.logging import logger
from oldman.storage.lifecycle import OldmanWriteSession, finalize_model_files, take_file_cleanup_records

DatabaseConfigSource = DatabaseConfig | Callable[[], DatabaseConfig]
DebugSource = bool | Callable[[], bool]


class DatabaseNotConfiguredError(RuntimeError):
    """Report database use before a valid database URL is available."""


SERVER_POOL_DEFAULTS: dict[str, Any] = {
    "pool_size": 100,
    "poolclass": AsyncAdaptedQueuePool,
    "max_overflow": 10,
    "pool_timeout": 30,
    "pool_recycle": 1800,
}

DATABASE_DRIVER_PACKAGES = {
    "aiosqlite": "aiosqlite",
    "aiomysql": "aiomysql",
    "asyncpg": "asyncpg",
    "psycopg": "psycopg",
}


def _enable_sqlite_foreign_keys(
    engine: AsyncEngine,
    database_url: URL | str,
) -> None:
    """Enable foreign-key enforcement on every new SQLite connection."""
    if make_url(database_url).get_backend_name() != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(
        dbapi_connection: Any,
        _connection_record: Any,
    ) -> None:
        """Apply SQLite's connection-local foreign-key setting once."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


class DatabaseManager:
    """Own one lazily initialized async engine and its session factories."""

    def __init__(
        self,
        config: DatabaseConfigSource,
        *,
        debug: DebugSource = False,
        pool_size: int | None = None,
        pool_class: type[Pool] | None = None,
        max_overflow: int | None = None,
        pool_timeout: float | None = None,
        pool_recycle: int | None = None,
        enable_sql_logging: bool | None = None,
    ) -> None:
        if not isinstance(config, DatabaseConfig) and not callable(config):
            raise TypeError("DatabaseManager requires DatabaseConfig or a DatabaseConfig factory")
        if not isinstance(debug, bool) and not callable(debug):
            raise TypeError("debug must be a bool or a bool factory")

        self._config_source = config
        self._resolved_config = config if isinstance(config, DatabaseConfig) else None
        self._debug_source = debug
        self._pool_size = pool_size
        self._pool_class = pool_class
        self._max_overflow = max_overflow
        self._pool_timeout = pool_timeout
        self._pool_recycle = pool_recycle
        self._enable_sql_logging = enable_sql_logging

        self._engine: AsyncEngine | None = None
        self.async_session: async_sessionmaker[AsyncSession] | None = None
        self.async_scoped_session: async_scoped_session[AsyncSession] | None = None
        self.read_session_maker: async_sessionmaker[AsyncSession] | None = None
        self._tracker: Any | None = None
        self._initialize_lock = asyncio.Lock()

    @property
    def is_initialized(self) -> bool:
        """Return whether this process has published an engine."""
        return self._engine is not None

    @property
    def engine(self) -> AsyncEngine:
        """Return the initialized engine without performing hidden sync setup."""
        if self._engine is None:
            raise DatabaseNotConfiguredError("DatabaseManager is not initialized; await initialize() or use a session context")
        return self._engine

    def _config(self) -> DatabaseConfig:
        """Resolve and retain this manager's fixed database configuration."""
        if self._resolved_config is not None:
            return self._resolved_config

        source = self._config_source
        if not callable(source):
            raise TypeError("DatabaseManager requires DatabaseConfig or a DatabaseConfig factory")
        resolved = source()
        if not isinstance(resolved, DatabaseConfig):
            raise TypeError("Database configuration factory must return DatabaseConfig")
        self._resolved_config = resolved
        return resolved

    def _debug(self) -> bool:
        """Resolve the engine echo fallback without importing project settings."""
        source = self._debug_source
        resolved = source() if callable(source) else source
        if not isinstance(resolved, bool):
            raise TypeError("Database debug factory must return bool")
        return resolved

    def _engine_options(
        self,
        config: DatabaseConfig,
        database_url: URL,
    ) -> dict[str, Any]:
        """Build SQLAlchemy options while preserving server pool defaults."""
        resolved_echo = config.echo if config.echo is not None else self._debug()
        options: dict[str, Any] = {"echo": resolved_echo}
        if database_url.get_backend_name() != "sqlite":
            options.update(SERVER_POOL_DEFAULTS)

        # Explicit constructor values override server defaults and remain available
        # for advanced SQLite pool choices.
        overrides = {
            "pool_size": self._pool_size,
            "poolclass": self._pool_class,
            "max_overflow": self._max_overflow,
            "pool_timeout": self._pool_timeout,
            "pool_recycle": self._pool_recycle,
        }
        options.update({name: value for name, value in overrides.items() if value is not None})
        return options

    async def initialize(self) -> None:
        """Create and atomically publish this manager's engine on first use."""
        if self._engine is not None:
            return

        async with self._initialize_lock:
            if self._engine is not None:
                return

            config = self._config()
            if not config.url:
                raise DatabaseNotConfiguredError("settings.database.url is required before opening database sessions")

            database_url = make_url(config.url)
            _, separator, driver_name = database_url.drivername.partition("+")
            engine_options = self._engine_options(config, database_url)
            try:
                candidate_engine = create_async_engine(
                    config.url,
                    **engine_options,
                )
            except (ModuleNotFoundError, NoSuchModuleError) as exc:
                resolved_driver = driver_name if separator else getattr(exc, "name", None) or database_url.drivername
                package = DATABASE_DRIVER_PACKAGES.get(
                    resolved_driver,
                    resolved_driver,
                )
                raise RuntimeError(
                    f"Database driver {resolved_driver!r} is not installed; add the {package!r} package to the project dependencies"
                ) from exc

            try:
                _enable_sqlite_foreign_keys(candidate_engine, database_url)
                candidate_session = async_sessionmaker(
                    candidate_engine,
                    class_=AsyncSession,
                    sync_session_class=OldmanWriteSession,
                    expire_on_commit=False,
                )
                candidate_scoped_session = async_scoped_session(
                    candidate_session,
                    scopefunc=asyncio.current_task,
                )
                candidate_read_session = async_sessionmaker(
                    candidate_engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                )
                tracking_enabled = config.enable_sql_logging if self._enable_sql_logging is None else self._enable_sql_logging
                candidate_tracker = None
                if tracking_enabled:
                    from oldman.db.sqlalchemy.log import SQLQueryTracker

                    candidate_tracker = SQLQueryTracker()
                    candidate_tracker.setup_logging(candidate_engine.sync_engine)
            except BaseException as exc:
                try:
                    await candidate_engine.dispose()
                except BaseException as cleanup_error:
                    exc.add_note(f"Database candidate engine cleanup also failed: {cleanup_error}")
                raise

            # Publish only after every object has been created successfully.
            self._engine = candidate_engine
            self.async_session = candidate_session
            self.async_scoped_session = candidate_scoped_session
            self.read_session_maker = candidate_read_session
            self._tracker = candidate_tracker
            logger.info(
                "Configured database engine: %s",
                database_url.render_as_string(hide_password=True),
            )

    async def close(self) -> None:
        """Dispose this manager's engine and allow later lazy reinitialization."""
        async with self._initialize_lock:
            if self._engine is not None:
                await self._engine.dispose()
            self._engine = None
            self.async_session = None
            self.async_scoped_session = None
            self.read_session_maker = None
            self._tracker = None

    def _get_async_session(self, scoped: bool = False) -> AsyncSession:
        """Create a regular or current-task-scoped SQLModel session."""
        if scoped:
            if self.async_scoped_session is None:
                raise DatabaseNotConfiguredError("DatabaseManager is not initialized")
            return self.async_scoped_session()
        if self.async_session is None:
            raise DatabaseNotConfiguredError("DatabaseManager is not initialized")
        return self.async_session()

    @asynccontextmanager
    async def transaction(
        self,
        nested: bool = False,
    ) -> AsyncIterator[AsyncSession]:
        """Yield an automatically finalized transaction or nested savepoint."""
        await self.initialize()
        session = self._get_async_session()
        try:
            if nested:
                async with session.begin_nested():
                    yield session
            else:
                async with session.begin():
                    yield session
        finally:
            await self._finish_write_session(session)

    @asynccontextmanager
    async def get_session(
        self,
        request_info: str = "",
    ) -> AsyncIterator[AsyncSession]:
        """Yield a write session and optionally summarize its tracked queries."""
        await self.initialize()
        session = self._get_async_session()
        if self._tracker is None:
            try:
                async with session.begin():
                    yield session
            finally:
                await self._finish_write_session(session)
            return

        async with self._tracker.track() as tracker_data:
            try:
                async with session.begin():
                    yield session
            finally:
                await self._finish_write_session(session)
                queries = tracker_data["queries"]
                if queries:
                    self._tracker.check_performance(queries, request_info)
                    self._tracker.log_summary(queries, request_info)

    async def _finish_write_session(self, session: AsyncSession) -> None:
        """关闭写 Session，并在确有文件候选时执行最终状态核对。"""
        await session.close()
        records = take_file_cleanup_records(session)
        if records:
            await finalize_model_files(self, records)

    @asynccontextmanager
    async def get_read_session(self) -> AsyncIterator[AsyncSession]:
        """Yield an autoflush-disabled session without an explicit transaction."""
        await self.initialize()
        if self.read_session_maker is None:
            raise DatabaseNotConfiguredError("DatabaseManager is not initialized")
        session = self.read_session_maker()
        try:
            yield session
        finally:
            await session.close()

    async def create_db_and_tables(self) -> None:
        """Create managed metadata for low-level tests, never for deployment."""
        await self.initialize()
        managed_tables = [
            table
            for table in Base.metadata.sorted_tables
            if table.info.get(MANAGED_INFO_KEY, True)
        ]
        async with self.engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    sync_connection,
                    tables=managed_tables,
                )
            )


def _configured_database() -> DatabaseConfig:
    """Resolve the concrete project database only when the default manager is used."""
    from oldman.conf import settings

    return settings.database


def _configured_debug() -> bool:
    """Resolve the project debug flag for default engine echo behavior."""
    from oldman.conf import settings

    return settings.web.debug


db_manager = DatabaseManager(_configured_database, debug=_configured_debug)

__all__ = [
    "DATABASE_DRIVER_PACKAGES",
    "SERVER_POOL_DEFAULTS",
    "DatabaseConfigSource",
    "DatabaseManager",
    "DatabaseNotConfiguredError",
    "db_manager",
]
