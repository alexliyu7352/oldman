"""Database-backed user notifications and best-effort browser delivery."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from markupsafe import escape
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, update
from sqlmodel import select

from oldman.apps.config import _validate_icon_class
from oldman.db import db_manager
from oldman.db.schemas import PageResult
from oldman.i18n import LazyTranslation, gettext_lazy
from oldman.logging import get_logger
from oldman.runtime.bootstrap import (
    ServiceBootstrapContext,
    _get_bootstrap_context,
)
from oldman.utils.date import naive_utcnow
from oldman.web.messages.flash import MessageFormat, MessageLevel
from oldman.web.messages.notifications.payloads import (
    MAX_NOTIFICATION_PAYLOAD_SIZE,
    NotificationCreatedPayload,
    NotificationPayload,
    NotificationPresentation,
    NotificationPushPayload,
    NotificationState,
    NotificationSyncPayload,
)
from oldman.web.messages.paths import is_same_site_path
from oldman.web.sse.publisher import (
    SSEMessageTooLargeError,
    SSEPublisher,
    validate_user_id,
)

if TYPE_CHECKING:
    from oldman.web.messages.notifications.models import Notification

NOTIFICATION_CREATED_EVENT = "oldman.notifications.created"
NOTIFICATION_PUSH_EVENT = "oldman.notifications.push"
NOTIFICATION_SYNC_EVENT = "oldman.notifications.sync"

_NOTIFICATIONS_PACKAGE = "oldman.web.messages.notifications"
_logger = get_logger("default.web.notifications")


def _validate_positive_integer(value: object, *, field_name: str) -> int:
    """Return one positive exact integer without accepting booleans."""
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int")
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def _validate_bounded_integer(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Return one exact integer inside an inclusive public API range."""
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an int")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _normalize_notification_ids(values: Sequence[int]) -> tuple[int, ...]:
    """Validate and deduplicate selected notification IDs in caller order."""
    normalized: dict[int, None] = {}
    for value in values:
        normalized[_validate_positive_integer(value, field_name="notification_id")] = None
    return tuple(normalized)


def _normalize_translation(
    value: str | LazyTranslation,
    *,
    field_name: str,
    require_content: bool,
) -> LazyTranslation:
    """Keep lazy values intact and wrap ordinary source strings exactly once."""
    if isinstance(value, LazyTranslation):
        singular = value.singular
        if not isinstance(singular, str):
            raise TypeError(f"{field_name} source must be a string")
        normalized = value
    elif isinstance(value, str):
        singular = value
        normalized = gettext_lazy(value)
    else:
        raise TypeError(f"{field_name} must be a string or LazyTranslation")
    if require_content and not singular.strip():
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _escape_html_translation(value: LazyTranslation) -> LazyTranslation:
    """Escape string variables while preserving deferred plural selection."""
    variables = {name: str(escape(variable)) if isinstance(variable, str) else variable for name, variable in value.variables.items()}
    return LazyTranslation(
        value.singular,
        value.plural,
        value.n,
        **variables,
    )


def _build_payload(
    *,
    title: str | LazyTranslation,
    body: str | LazyTranslation | None,
    level: MessageLevel,
    format: MessageFormat,
    presentation: NotificationPresentation,
    href: str | None,
    icon: str | None,
    allow_silent: bool,
) -> tuple[NotificationPayload, bytes]:
    """Validate business input once and return its single storage encoding."""
    if not isinstance(level, MessageLevel):
        raise TypeError("level must be a MessageLevel")
    if not isinstance(format, MessageFormat):
        raise TypeError("format must be a MessageFormat")
    if not isinstance(presentation, NotificationPresentation):
        raise TypeError("presentation must be a NotificationPresentation")
    if not allow_silent and presentation is NotificationPresentation.NONE:
        raise ValueError("temporary push presentation must not be none")

    normalized_title = _normalize_translation(
        title,
        field_name="title",
        require_content=True,
    )
    normalized_body = (
        None
        if body is None
        else _normalize_translation(
            body,
            field_name="body",
            require_content=False,
        )
    )
    if format is MessageFormat.HTML and normalized_body is not None:
        normalized_body = _escape_html_translation(normalized_body)

    if href is not None and not is_same_site_path(href):
        raise ValueError("href must be a safe same-site absolute path")
    if icon is not None:
        _validate_icon_class(icon, field_name="icon")

    payload = NotificationPayload(
        title=normalized_title,
        body=normalized_body,
        level=level,
        format=format,
        presentation=presentation,
        href=href,
        icon=icon,
    )
    encoded = payload.to_msgpack()
    if len(encoded) > MAX_NOTIFICATION_PAYLOAD_SIZE:
        raise ValueError(f"notification payload exceeds the {MAX_NOTIFICATION_PAYLOAD_SIZE}-byte limit")
    return payload, encoded


def _as_utc_aware(value: datetime) -> datetime:
    """Attach or normalize UTC before a database timestamp enters an SSE payload."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Notifications:
    """Provide the sole database and realtime notification business API."""

    def __init__(
        self,
        *,
        _publisher_factory: Callable[[], SSEPublisher] = SSEPublisher.from_settings,
    ) -> None:
        """Keep publisher creation injectable without exposing another manager API."""
        self._publisher_factory = _publisher_factory
        self._publisher: SSEPublisher | None = None
        self._publisher_lock = threading.Lock()

    async def create(
        self,
        *,
        user_id: int,
        title: str | LazyTranslation,
        body: str | LazyTranslation | None = None,
        level: MessageLevel = MessageLevel.INFO,
        format: MessageFormat = MessageFormat.TEXT,
        presentation: NotificationPresentation = NotificationPresentation.NONE,
        href: str | None = None,
        icon: str | None = None,
    ) -> Notification:
        """Persist one notification, then best-effort publish its created event."""
        context = self._require_context()
        validated_user_id = validate_user_id(user_id)
        payload, encoded = _build_payload(
            title=title,
            body=body,
            level=level,
            format=format,
            presentation=presentation,
            href=href,
            icon=icon,
            allow_silent=True,
        )
        from oldman.web.messages.notifications.models import Notification

        async with db_manager.get_session() as session:
            notification = Notification(
                recipient_id=validated_user_id,
                payload=encoded,
            )
            session.add(notification)
            await session.flush()

        if context.settings.web.sse.enabled:
            created_payload = NotificationCreatedPayload(
                notification_id=notification.id,
                notification=payload,
                created_at=_as_utc_aware(notification.created_at),
            )
            try:
                await self._publisher_for_current_process().publish_user(
                    user_id=validated_user_id,
                    event=NOTIFICATION_CREATED_EVENT,
                    payload=created_payload,
                )
            except SSEMessageTooLargeError:
                _logger.error(
                    "Notification %s was persisted, but its SSE envelope exceeded the %s-byte limit (business payload: %s bytes)",
                    notification.id,
                    context.settings.web.sse.max_message_size,
                    len(encoded),
                )
        return notification

    async def push(
        self,
        *,
        user_id: int,
        title: str | LazyTranslation,
        body: str | LazyTranslation | None = None,
        level: MessageLevel = MessageLevel.INFO,
        format: MessageFormat = MessageFormat.TEXT,
        presentation: NotificationPresentation = NotificationPresentation.TOAST,
        href: str | None = None,
        icon: str | None = None,
    ) -> bool:
        """Best-effort publish one temporary notification without database writes."""
        context = self._require_context()
        validated_user_id = validate_user_id(user_id)
        if not context.settings.web.sse.enabled:
            raise RuntimeError("SSE is disabled; temporary notifications cannot be delivered")
        payload, _encoded = _build_payload(
            title=title,
            body=body,
            level=level,
            format=format,
            presentation=presentation,
            href=href,
            icon=icon,
            allow_silent=False,
        )
        return await self._publisher_for_current_process().publish_user(
            user_id=validated_user_id,
            event=NOTIFICATION_PUSH_EVENT,
            payload=NotificationPushPayload(notification=payload),
        )

    async def list_for_user(
        self,
        user_id: int,
        *,
        state: NotificationState = NotificationState.ALL,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResult[Notification]:
        """Return one recipient-scoped, stably ordered page."""
        self._require_context()
        validated_user_id = validate_user_id(user_id)
        if not isinstance(state, NotificationState):
            raise TypeError("state must be a NotificationState")
        validated_page = _validate_positive_integer(
            page,
            field_name="page",
        )
        validated_page_size = _validate_bounded_integer(
            page_size,
            field_name="page_size",
            minimum=1,
            maximum=100,
        )
        from oldman.web.messages.notifications.models import Notification

        conditions = [Notification.recipient_id == validated_user_id]
        if state is NotificationState.UNREAD:
            conditions.append(Notification.read_at.is_(None))
        elif state is NotificationState.READ:
            conditions.append(Notification.read_at.is_not(None))

        async with db_manager.get_read_session() as session:
            total_result = await session.exec(select(func.count()).select_from(Notification).where(*conditions))
            total = int(total_result.one())
            result = await session.exec(
                select(Notification)
                .where(*conditions)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((validated_page - 1) * validated_page_size)
                .limit(validated_page_size)
            )
            items = list(result.all())
        return PageResult(
            items=items,
            total=total,
            page=validated_page,
            page_size=validated_page_size,
        )

    async def topbar_for_user(
        self,
        user_id: int,
        *,
        limit: int = 5,
    ) -> list[Notification]:
        """Return the recipient's newest unread rows."""
        self._require_context()
        validated_user_id = validate_user_id(user_id)
        validated_limit = _validate_bounded_integer(
            limit,
            field_name="limit",
            minimum=1,
            maximum=20,
        )
        from oldman.web.messages.notifications.models import Notification

        async with db_manager.get_read_session() as session:
            result = await session.exec(
                select(Notification)
                .where(
                    Notification.recipient_id == validated_user_id,
                    Notification.read_at.is_(None),
                )
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(validated_limit)
            )
            return list(result.all())

    async def unread_count(self, user_id: int) -> int:
        """Count unread rows for exactly one recipient."""
        self._require_context()
        validated_user_id = validate_user_id(user_id)
        from oldman.web.messages.notifications.models import Notification

        async with db_manager.get_read_session() as session:
            result = await session.exec(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.recipient_id == validated_user_id,
                    Notification.read_at.is_(None),
                )
            )
            return int(result.one())

    async def get_for_user(
        self,
        user_id: int,
        notification_id: int,
    ) -> Notification | None:
        """Return a row only when both recipient and id match."""
        self._require_context()
        validated_user_id = validate_user_id(user_id)
        validated_notification_id = _validate_positive_integer(
            notification_id,
            field_name="notification_id",
        )
        from oldman.web.messages.notifications.models import Notification

        async with db_manager.get_read_session() as session:
            result = await session.exec(
                select(Notification).where(
                    Notification.recipient_id == validated_user_id,
                    Notification.id == validated_notification_id,
                )
            )
            return result.one_or_none()

    async def mark_read(
        self,
        user_id: int,
        notification_ids: Sequence[int],
    ) -> int:
        """Mark selected recipient rows read and return the changed count."""
        context = self._require_context()
        validated_user_id = validate_user_id(user_id)
        normalized_ids = _normalize_notification_ids(notification_ids)
        if not normalized_ids:
            return 0
        from oldman.web.messages.notifications.models import Notification

        changed_at = naive_utcnow()
        async with db_manager.get_session() as session:
            result = await session.exec(
                update(Notification)
                .where(
                    Notification.recipient_id == validated_user_id,
                    Notification.id.in_(normalized_ids),
                    Notification.read_at.is_(None),
                )
                .values(read_at=changed_at)
            )
            changed_count = int(cast(Any, result).rowcount)
        await self._publish_sync(
            context,
            user_id=validated_user_id,
            changed_count=changed_count,
        )
        return changed_count

    async def mark_all_read(self, user_id: int) -> int:
        """Mark every unread row for one recipient and return the changed count."""
        context = self._require_context()
        validated_user_id = validate_user_id(user_id)
        from oldman.web.messages.notifications.models import Notification

        changed_at = naive_utcnow()
        async with db_manager.get_session() as session:
            result = await session.exec(
                update(Notification)
                .where(
                    Notification.recipient_id == validated_user_id,
                    Notification.read_at.is_(None),
                )
                .values(read_at=changed_at)
            )
            changed_count = int(cast(Any, result).rowcount)
        await self._publish_sync(
            context,
            user_id=validated_user_id,
            changed_count=changed_count,
        )
        return changed_count

    async def delete(
        self,
        user_id: int,
        notification_ids: Sequence[int],
    ) -> int:
        """Delete selected recipient rows and return the changed count."""
        context = self._require_context()
        validated_user_id = validate_user_id(user_id)
        normalized_ids = _normalize_notification_ids(notification_ids)
        if not normalized_ids:
            return 0
        from oldman.web.messages.notifications.models import Notification

        async with db_manager.get_session() as session:
            result = await session.exec(
                sql_delete(Notification).where(
                    Notification.recipient_id == validated_user_id,
                    Notification.id.in_(normalized_ids),
                )
            )
            changed_count = int(cast(Any, result).rowcount)
        await self._publish_sync(
            context,
            user_id=validated_user_id,
            changed_count=changed_count,
        )
        return changed_count

    def _require_context(self) -> ServiceBootstrapContext:
        """Require installation and a completed Registry model phase."""
        context = _get_bootstrap_context()
        context.apps.get_by_package(_NOTIFICATIONS_PACKAGE)
        _ = context.apps.models
        return context

    def _publisher_for_current_process(self) -> SSEPublisher:
        """Create the process publisher once without locking the hot path."""
        publisher = self._publisher
        if publisher is not None:
            return publisher
        with self._publisher_lock:
            if self._publisher is None:
                self._publisher = self._publisher_factory()
            return self._publisher

    async def _publish_sync(
        self,
        context: ServiceBootstrapContext,
        *,
        user_id: int,
        changed_count: int,
    ) -> None:
        """Publish committed state changes without weakening database success."""
        if changed_count <= 0 or not context.settings.web.sse.enabled:
            return
        payload = NotificationSyncPayload(changed_count=changed_count)
        try:
            await self._publisher_for_current_process().publish_user(
                user_id=user_id,
                event=NOTIFICATION_SYNC_EVENT,
                payload=payload,
            )
        except SSEMessageTooLargeError:
            _logger.error(
                "Notification state change for user %s was committed, but its SSE envelope exceeded the %s-byte limit (business payload: %s bytes)",
                user_id,
                context.settings.web.sse.max_message_size,
                len(payload.to_msgpack()),
            )


notifications = Notifications()

__all__ = [
    "NOTIFICATION_CREATED_EVENT",
    "NOTIFICATION_PUSH_EVENT",
    "NOTIFICATION_SYNC_EVENT",
    "Notifications",
    "notifications",
]
