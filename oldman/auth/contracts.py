"""Stable database contract shared by every concrete User model."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import ColumnProperty
from sqlalchemy.schema import Table, UniqueConstraint

USER_TABLE_NAME = "oldman_user"
USER_PRIMARY_KEY_NAME = "id"
USER_CORE_FIELD_NAMES = (
    "id",
    "username",
    "email",
    "password_hash",
    "display_name",
    "is_active",
    "is_staff",
    "is_superuser",
    "last_login_at",
    "created_at",
    "updated_at",
)
USER_SUPERUSER_STAFF_CONSTRAINT = "ck_oldman_user_superuser_is_staff"
USER_CORE_CHECK_CONSTRAINTS = {
    USER_SUPERUSER_STAFF_CONSTRAINT: "NOT is_superuser OR is_staff",
}

_STRING_LENGTHS = {
    "username": 150,
    "email": 254,
    "password_hash": 255,
    "display_name": 150,
}
_BOOLEAN_FIELDS = ("is_active", "is_staff", "is_superuser")
_DATETIME_FIELDS = ("last_login_at", "created_at", "updated_at")
_NULLABLE_FIELDS = {"email", "display_name", "last_login_at"}
USER_CORE_INDEXES = {
    "ix_oldman_user_username": (("username",), True),
    "ix_oldman_user_is_active": (("is_active",), False),
    "ix_oldman_user_is_staff": (("is_staff",), False),
    "ix_oldman_user_is_superuser": (("is_superuser",), False),
}
USER_CORE_UNIQUE_COLUMN_SETS = (("email",),)


class UserModelContractError(TypeError):
    """Raised when a concrete User changes the stable database identity."""


def _contract_error(model: type[Any], detail: str) -> UserModelContractError:
    """Build one error that identifies the rejected mapped class."""
    return UserModelContractError(
        f"User model {model.__module__}.{model.__qualname__} {detail}"
    )


def _normalized_sql(expression: object) -> str:
    """Normalize harmless whitespace when comparing the fixed check expression."""
    return re.sub(r"\s+", " ", str(expression).strip()).casefold()


def _validate_core_columns(model: type[Any], table: Table) -> None:
    """Reject missing, remapped or structurally changed Auth-owned columns."""
    mapper = sqlalchemy_inspect(model)
    missing = [name for name in USER_CORE_FIELD_NAMES if name not in table.c]
    if missing:
        raise _contract_error(
            model,
            f"is missing core field(s): {', '.join(missing)}.",
        )

    for name in USER_CORE_FIELD_NAMES:
        property_ = mapper.attrs.get(name)
        if (
            not isinstance(property_, ColumnProperty)
            or len(property_.columns) != 1
            or property_.columns[0] is not table.c[name]
        ):
            raise _contract_error(
                model,
                f"must map core attribute {name!r} to column {name!r}.",
            )

    primary_key = tuple(mapper.primary_key)
    if primary_key != (table.c.id,):
        raise _contract_error(
            model,
            "must expose exactly one primary key column named 'id'.",
        )
    if type(table.c.id.type) is not Integer:
        raise _contract_error(model, "oldman_user.id must use Integer.")
    if table.c.id.autoincrement is not True:
        raise _contract_error(
            model,
            "oldman_user.id must use database autoincrement=True.",
        )

    for name, length in _STRING_LENGTHS.items():
        column = table.c[name]
        if type(column.type) is not String or column.type.length != length:
            raise _contract_error(
                model,
                f"core field {name!r} must use String({length}).",
            )
    for name in _BOOLEAN_FIELDS:
        if type(table.c[name].type) is not Boolean:
            raise _contract_error(
                model,
                f"core field {name!r} must use Boolean.",
            )
    for name in _DATETIME_FIELDS:
        if type(table.c[name].type) is not DateTime:
            raise _contract_error(
                model,
                f"core field {name!r} must use DateTime.",
            )

    for name in USER_CORE_FIELD_NAMES:
        expected_nullable = name in _NULLABLE_FIELDS
        if table.c[name].nullable is not expected_nullable:
            raise _contract_error(
                model,
                f"core field {name!r} must set nullable={expected_nullable}.",
            )

    expected_defaults = {
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
    }
    for name, expected in expected_defaults.items():
        default = table.c[name].default
        if (
            default is None
            or not default.is_scalar
            or getattr(default, "arg", None) is not expected
        ):
            raise _contract_error(
                model,
                f"core field {name!r} must retain its {expected!r} default.",
            )

    if table.c.created_at.server_default is None:
        raise _contract_error(
            model,
            "core field 'created_at' must retain its server default.",
        )
    if table.c.updated_at.server_default is None or table.c.updated_at.onupdate is None:
        raise _contract_error(
            model,
            "core field 'updated_at' must retain its server default and on-update value.",
        )


def _validate_core_indexes(model: type[Any], table: Table) -> None:
    """Require the fixed lookup and uniqueness indexes without banning extras."""
    for name, (columns, unique) in USER_CORE_INDEXES.items():
        matches = [
            index
            for index in table.indexes
            if index.name is not None and str(index.name) == name
        ]
        if (
            len(matches) != 1
            or tuple(column.name for column in matches[0].columns) != columns
            or matches[0].unique is not unique
        ):
            raise _contract_error(
                model,
                f"must retain core index {name!r} on {', '.join(columns)}.",
            )

    email_unique = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        in USER_CORE_UNIQUE_COLUMN_SETS
    ]
    if len(email_unique) != 1:
        raise _contract_error(
            model,
            "must retain the unique constraint on core field 'email'.",
        )


def _install_core_constraints(model: type[Any], table: Table) -> None:
    """Append missing named checks while rejecting a conflicting declaration."""
    for name, expression in USER_CORE_CHECK_CONSTRAINTS.items():
        matches = [
            constraint
            for constraint in table.constraints
            if constraint.name == name
        ]
        if not matches:
            table.append_constraint(CheckConstraint(expression, name=name))
            continue
        if (
            len(matches) != 1
            or not isinstance(matches[0], CheckConstraint)
            or _normalized_sql(matches[0].sqltext) != _normalized_sql(expression)
        ):
            raise _contract_error(
                model,
                f"declares a conflicting core constraint {name!r}.",
            )


def validate_user_table_contract(model: type[Any]) -> Table:
    """Validate and complete one concrete User table during model mapping."""
    mapper = sqlalchemy_inspect(model, raiseerr=False)
    if mapper is None or not hasattr(mapper, "local_table"):
        raise _contract_error(model, "must be a mapped class.")
    table = mapper.local_table
    if not isinstance(table, Table):
        raise _contract_error(model, "must map a concrete Table.")
    if table.name != USER_TABLE_NAME or table.schema is not None:
        raise _contract_error(
            model,
            f"must map the unqualified table {USER_TABLE_NAME!r}.",
        )

    _validate_core_columns(model, table)
    _validate_core_indexes(model, table)
    _install_core_constraints(model, table)
    return table


__all__ = [
    "USER_CORE_CHECK_CONSTRAINTS",
    "USER_CORE_FIELD_NAMES",
    "USER_CORE_INDEXES",
    "USER_CORE_UNIQUE_COLUMN_SETS",
    "USER_PRIMARY_KEY_NAME",
    "USER_SUPERUSER_STAFF_CONSTRAINT",
    "USER_TABLE_NAME",
    "UserModelContractError",
    "validate_user_table_contract",
]
