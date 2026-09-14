"""Admin model identity coercion helpers."""

from __future__ import annotations

import uuid as uuid_pkg
from decimal import Decimal
from typing import Any

from sqlalchemy import Integer
from sqlalchemy.sql.schema import Column


def coerce_value(column: Column[Any], value: Any) -> Any:
    """Coerce a form or identity value through one mapped column's Python type."""
    value = first_value(value)
    if value is None:
        return None
    if value == "" and column.nullable:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if isinstance(value, python_type):
        return value
    if python_type is bool:
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value!r}")
    try:
        if python_type is Decimal:
            return Decimal(str(value))
        if python_type is uuid_pkg.UUID:
            return uuid_pkg.UUID(str(value))
        return python_type(value)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {python_type.__name__} value: {value!r}") from exc


def first_value(value: Any) -> Any:
    """Return a scalar value from Sanic form mappings."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def explicit_primary_key_column(mapper: Any, *, dialect: Any = None) -> Any | None:
    """Return a key that the active SQLAlchemy dialect cannot generate."""
    primary_key = list(mapper.primary_key)
    if len(primary_key) != 1:
        raise ValueError("Admin models require exactly one primary key column")
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
