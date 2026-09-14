"""Unmapped base model for project-defined User models."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Table, event, func
from sqlalchemy.orm import Mapped, Session, declared_attr, mapped_column

from oldman.auth.contracts import (
    USER_CORE_FIELD_NAMES,
    USER_TABLE_NAME,
    UserModelContractError,
    validate_user_table_contract,
)
from oldman.auth.security import check_password, make_password
from oldman.db.models import APP_LABEL_INFO_KEY, DatabaseModel

USER_TABLE_OWNER_LABEL = "auth"
USER_APP_LABEL_INFO_KEY = "oldman_user_app_label"
USER_CORE_FIELDS_INFO_KEY = "oldman_user_core_fields"


class AbstractUser(DatabaseModel):
    """Provide the standard User schema without registering a concrete table."""

    __abstract__ = True

    @declared_attr.directive
    @classmethod
    def __tablename__(cls) -> str:
        """Fix every concrete User to the framework-owned table."""
        return USER_TABLE_NAME

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the stable table once SQLAlchemy maps a concrete subclass."""
        explicit_table_name = cls.__dict__.get("__tablename__")
        if (
            explicit_table_name is not None
            and explicit_table_name != USER_TABLE_NAME
        ):
            raise UserModelContractError(
                f"User model {cls.__module__}.{cls.__qualname__} must map "
                f"the unqualified table {USER_TABLE_NAME!r}."
            )
        explicit_table = cls.__dict__.get("__table__")
        if explicit_table is not None and (
            getattr(explicit_table, "name", None) != USER_TABLE_NAME
            or getattr(explicit_table, "schema", None) is not None
        ):
            raise UserModelContractError(
                f"User model {cls.__module__}.{cls.__qualname__} must map "
                f"the unqualified table {USER_TABLE_NAME!r}."
            )

        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("__abstract__", False):
            validate_user_table_contract(cls)

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def set_password(self, raw_password: str) -> None:
        """Hash and store a raw password."""
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Return whether a raw password matches this User."""
        return check_password(raw_password, self.password_hash)

    @property
    def label(self) -> str:
        """Return the preferred human-readable identity label."""
        return self.display_name or self.username


def normalize_user_staff_flags(user: AbstractUser) -> None:
    """Keep the invariant that every superuser is also a staff user."""
    if user.is_superuser:
        user.is_staff = True


def assign_user_model_ownership(
    model: type[AbstractUser],
    user_app_label: str,
) -> None:
    """Record Auth's table ownership and the selected extension App once."""
    validate_user_table_contract(model)
    table = model.__table__
    if not isinstance(table, Table):
        raise UserModelContractError("configured User must expose one mapped Table")

    existing_user_app = table.info.get(USER_APP_LABEL_INFO_KEY)
    if existing_user_app is not None and existing_user_app != user_app_label:
        raise UserModelContractError(
            f"oldman_user is already assigned to User App {existing_user_app!r}, "
            f"not {user_app_label!r}."
        )
    table.info[APP_LABEL_INFO_KEY] = USER_TABLE_OWNER_LABEL
    table.info[USER_APP_LABEL_INFO_KEY] = user_app_label
    table.info[USER_CORE_FIELDS_INFO_KEY] = USER_CORE_FIELD_NAMES


@event.listens_for(Session, "before_flush")
def normalize_user_staff_flags_before_flush(
    session: Session,
    flush_context: Any,
    instances: Any,
) -> None:
    """Normalize inherited User permission fields immediately before persistence."""
    del flush_context, instances
    for obj in session.new.union(session.dirty):
        if isinstance(obj, AbstractUser):
            normalize_user_staff_flags(obj)


__all__ = [
    "AbstractUser",
    "USER_APP_LABEL_INFO_KEY",
    "USER_CORE_FIELDS_INFO_KEY",
    "USER_TABLE_OWNER_LABEL",
    "assign_user_model_ownership",
    "normalize_user_staff_flags",
]
