"""How a mapped column's Python value travels through JSON and comes back as the same value.

Shared by the model cache (``oldman.db.sqlalchemy.cache``) and ``DatabaseModel``'s
``model_dump_dict`` / ``model_dump_json`` / ``model_validate_json``, so a row reads back
with the types a database read returns: a date is a ``date`` again, not an ISO string.
"""

__author__ = "alex"

import base64
import enum
import math
import uuid
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    String,
    Time,
    TypeDecorator,
    Uuid,
)

from oldman.db.sqlalchemy.utils import JSONText

#: A column's representation label, and the functions to JSON and back.
ColumnCodec = tuple[str, Callable[[Any], Any], Callable[[Any], Any]]


def _same(value: Any) -> Any:
    return value


def _isoformat(value: date | time) -> str:
    return value.isoformat()


def _interval_encode(value: timedelta) -> list[int]:
    return [value.days, value.seconds, value.microseconds]


def _interval_decode(value: list[int]) -> timedelta:
    return timedelta(days=value[0], seconds=value[1], microseconds=value[2])


def _bytes_encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _float_encode(value: float) -> float | str:
    # JSON has no NaN or infinity - orjson writes them as null - so they travel as their
    # float() spelling. Finite values are encoded as before.
    return value if math.isfinite(value) else str(value)


def _float_decode(value: float | str) -> float:
    return float(value) if isinstance(value, str) else value


def _enum_codec(enum_class: type[enum.Enum]) -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    def encode(value: Any) -> str:
        if isinstance(value, enum_class):
            return value.name
        # SQLAlchemy also takes a member's name for the column, and an uncommitted
        # assignment still holds it as that string.
        if isinstance(value, str) and value in enum_class.__members__:
            return value
        raise ValueError(f"{value!r} is not a member of {enum_class.__name__}")

    return encode, cast(Any, enum_class).__getitem__


def column_codec(column: Column[Any]) -> ColumnCodec:
    """How one column's Python value travels through JSON and comes back as the same value.

    Returns a kind label (it names the representation, so a change of it can be detected)
    and the encode and decode functions; neither is called with None. A type whose Python
    values cannot be told apart from their JSON form - a project's own TypeDecorator, ARRAY -
    is refused with TypeError, since a row that reads back as a different type is wrong data.
    """
    column_type = column.type
    if isinstance(column_type, JSONText | JSON):
        return "json", _same, _same
    if isinstance(column_type, Enum):
        enum_class = column_type.enum_class
        if enum_class is None:
            return "str", _same, _same
        # Members travel by name, which is also what SQLAlchemy's Enum stores by default.
        return (f"enum:{enum_class.__module__}.{enum_class.__qualname__}", *_enum_codec(enum_class))
    if isinstance(column_type, Boolean):
        return "bool", _same, _same
    if isinstance(column_type, Integer):
        return "int", _same, _same
    if isinstance(column_type, String):
        return "str", _same, _same
    if isinstance(column_type, Numeric):
        # Float is a Numeric: with asdecimal=True it returns Decimal values too.
        return ("decimal", str, Decimal) if column_type.asdecimal else ("float", _float_encode, _float_decode)
    if isinstance(column_type, DateTime):
        return "datetime", _isoformat, datetime.fromisoformat
    if isinstance(column_type, Date):
        return "date", _isoformat, date.fromisoformat
    if isinstance(column_type, Time):
        return "time", _isoformat, time.fromisoformat
    if isinstance(column_type, Interval):
        return "interval", _interval_encode, _interval_decode
    if isinstance(column_type, Uuid):
        return ("uuid", str, uuid.UUID) if column_type.as_uuid else ("str", _same, _same)
    if isinstance(column_type, LargeBinary):
        return "bytes", _bytes_encode, base64.b64decode
    if isinstance(column_type, TypeDecorator):
        # Checked last: some built-in types (Interval) are TypeDecorators themselves.
        raise TypeError(f"column {column.name!r} uses {type(column_type).__name__}, a custom type whose JSON round trip cannot be verified")
    raise TypeError(f"column {column.name!r} has type {type(column_type).__name__}, which has no JSON round trip")
