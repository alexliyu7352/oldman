"""A role is a named set of permissions; users hold roles."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import DatabaseModel
from oldman.i18n import gettext_lazy as _


class Role(DatabaseModel):
    """A named set of permission names."""

    __tablename__ = "oldman_role"
    # Sessions and tokens carry role ids, and deleting a role does not end them: an id handed
    # out again would give those sessions the new role. SQLite reuses the highest id unless told not to.
    # Not fixed (G2-9): MySQL 5.7 and earlier keep the counter in memory and restart it from the highest
    # id after a server restart; the permissions docs say so.
    __table_args__ = (
        UniqueConstraint("name", name="uq_oldman_role_name"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    class Meta:
        """Provide Admin-facing names without changing database identity."""

        verbose_name = _("Role")
        verbose_name_plural = _("Roles")


class UserRole(DatabaseModel):
    """One user holding one role."""

    __tablename__ = "oldman_user_role"
    __table_args__ = (Index("ix_oldman_user_role_role_id", "role_id"),)

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("oldman_user.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("oldman_role.id", ondelete="CASCADE"), primary_key=True)

    class Meta:
        """Provide Admin-facing names without changing database identity."""

        verbose_name = _("User role")
        verbose_name_plural = _("User roles")


__all__ = ["Role", "UserRole"]
