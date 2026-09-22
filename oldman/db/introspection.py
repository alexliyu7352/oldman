"""SQLAlchemy introspection helpers shared by forms and admin tooling."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer


def explicit_primary_key_column(mapper: Any, *, dialect: Any = None) -> Any | None:
    """Return the single primary key column when the active dialect cannot generate it, else None."""
    primary_key = list(mapper.primary_key)
    if len(primary_key) != 1:
        raise ValueError("Models managed through forms require exactly one primary key column")
    column = primary_key[0]
    if column.default is not None or column.server_default is not None or column.identity is not None:
        return None
    if not isinstance(column.type, Integer) or column.autoincrement not in {True, "auto", "ignore_fk"}:
        return column
    if getattr(column.table, "_autoincrement_column", None) is not column:
        return column

    if dialect is None:
        # With no bound session, keep the framework's portable Integer default
        # while requiring dialect-sensitive subclasses such as BigInteger.
        return None if type(column.type) is Integer else column

    dialect_name = str(getattr(dialect, "name", "")).lower()
    if dialect_name == "sqlite":
        # SQLite generates rowids only when the dialect renders the declared
        # type as the exact token INTEGER (including Integer with_variant()).
        rendered_type = str(column.type.compile(dialect=dialect)).strip().upper()
        if rendered_type == "INTEGER":
            return None
        return column
    if dialect_name in {"cockroachdb", "mariadb", "mssql", "mysql", "postgresql"}:
        return None
    return column


def session_dialect(session: Any) -> Any | None:
    """Return the SQLAlchemy dialect bound to a sync or async session."""
    if session is None:
        return None
    bind = None
    get_bind = getattr(session, "get_bind", None)
    if callable(get_bind):
        try:
            bind = get_bind()
        except (AttributeError, NotImplementedError):
            bind = None
    if bind is None:
        bind = getattr(session, "bind", None)
    return getattr(bind, "dialect", None)


__all__ = ["explicit_primary_key_column", "session_dialect"]
