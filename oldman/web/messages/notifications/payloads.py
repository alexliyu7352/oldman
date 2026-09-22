"""Strong binary payloads shared by notification storage and browser events."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from oldman.i18n import LazyTranslation, TranslatableMsgspecModel
from oldman.serializers import MsgspecModel
from oldman.web.messages.flash import MessageFormat, MessageLevel

MAX_NOTIFICATION_PAYLOAD_SIZE = 32 * 1024


class NotificationPresentation(StrEnum):
    """How an arriving notification may interrupt an online user."""

    NONE = "none"
    TOAST = "toast"
    MODAL = "modal"


class NotificationState(StrEnum):
    """Read-state filter accepted by notification queries."""

    ALL = "all"
    UNREAD = "unread"
    READ = "read"


class NotificationPayload(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports frozen specialized Struct subclasses
):
    """Versioned untranslated content stored in the database and sent to SSE."""

    version: int = 1
    title: LazyTranslation
    body: LazyTranslation | None = None
    level: MessageLevel = MessageLevel.INFO
    format: MessageFormat = MessageFormat.TEXT
    presentation: NotificationPresentation = NotificationPresentation.NONE
    href: str | None = None
    icon: str | None = None

    def __post_init__(self) -> None:
        """Reject loose direct construction that violates the wire schema."""
        if type(self.version) is not int or self.version != 1:
            raise TypeError("version must be the integer 1")
        if not isinstance(self.level, MessageLevel):
            raise TypeError("level must be a MessageLevel")
        if not isinstance(self.format, MessageFormat):
            raise TypeError("format must be a MessageFormat")
        if not isinstance(self.presentation, NotificationPresentation):
            raise TypeError("presentation must be a NotificationPresentation")


class NotificationCreatedPayload(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports frozen specialized Struct subclasses
):
    """Notify an online browser that one persistent notification was created."""

    notification_id: int
    notification: NotificationPayload
    created_at: datetime

    def __post_init__(self) -> None:
        """Keep identifiers, nested content and timestamps unambiguous."""
        if type(self.notification_id) is not int or self.notification_id <= 0:
            raise TypeError("notification_id must be a positive integer")
        if not isinstance(self.notification, NotificationPayload):
            raise TypeError("notification must be a NotificationPayload")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise TypeError("created_at must be a UTC-aware datetime")


class NotificationPushPayload(
    TranslatableMsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports frozen specialized Struct subclasses
):
    """Carry one non-persistent notification to an online browser."""

    notification: NotificationPayload

    def __post_init__(self) -> None:
        """Require the same strong content model used by persistent events."""
        if not isinstance(self.notification, NotificationPayload):
            raise TypeError("notification must be a NotificationPayload")


class NotificationSyncPayload(
    MsgspecModel,
    kw_only=True,
    frozen=True,  # pyright: ignore[reportGeneralTypeIssues] -- msgspec supports frozen Struct subclasses
):
    """Tell browsers how many notification rows changed state."""

    changed_count: int

    def __post_init__(self) -> None:
        """Reject booleans and negative state-change counts."""
        if type(self.changed_count) is not int or self.changed_count < 0:
            raise TypeError("changed_count must be a non-negative integer")


__all__ = [
    "MAX_NOTIFICATION_PAYLOAD_SIZE",
    "NotificationCreatedPayload",
    "NotificationPayload",
    "NotificationPresentation",
    "NotificationPushPayload",
    "NotificationState",
    "NotificationSyncPayload",
]
