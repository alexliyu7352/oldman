"""Admin model identity coercion helpers."""

from __future__ import annotations

import uuid as uuid_pkg
from decimal import Decimal
from typing import Any

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


