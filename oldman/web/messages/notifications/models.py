"""Persistent per-user notification model."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, text
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import DatabaseModel
from oldman.i18n import gettext_lazy as _
from oldman.web.messages.notifications.payloads import (
    MAX_NOTIFICATION_PAYLOAD_SIZE,
)


def _utc_now_naive() -> datetime:
    """Return the UTC wall-clock form stored by the framework's database models."""
    return datetime.now(UTC).replace(tzinfo=None)


class Notification(DatabaseModel):
    """Store one unread or read notification owned by a concrete User row."""

    __tablename__ = "oldman_notification"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override
    __table_args__ = (
        Index(
            "ix_oldman_notification_recipient_created",
            "recipient_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_oldman_notification_recipient_read_created",
            "recipient_id",
            "read_at",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    recipient_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("oldman_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload: Mapped[bytes] = mapped_column(
        LargeBinary(MAX_NOTIFICATION_PAYLOAD_SIZE),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=_utc_now_naive,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )

    class Meta:
        """Provide Admin-facing names without changing database identity."""

        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")


__all__ = ["Notification"]
