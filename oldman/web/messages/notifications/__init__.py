"""Public strong types for persistent and realtime user notifications."""

from oldman.web.messages.notifications.payloads import (
    NotificationCreatedPayload,
    NotificationPayload,
    NotificationPresentation,
    NotificationPushPayload,
    NotificationState,
    NotificationSyncPayload,
)
from oldman.web.messages.notifications.rendering import (
    render_center_content,
    render_topbar_fragment,
)
from oldman.web.messages.notifications.runtime import NotificationRoutes, init_app
from oldman.web.messages.notifications.service import (
    NOTIFICATION_CREATED_EVENT,
    NOTIFICATION_PUSH_EVENT,
    NOTIFICATION_SYNC_EVENT,
    notifications,
)

__all__ = [
    "NOTIFICATION_CREATED_EVENT",
    "NOTIFICATION_PUSH_EVENT",
    "NOTIFICATION_SYNC_EVENT",
    "NotificationCreatedPayload",
    "NotificationPayload",
    "NotificationPresentation",
    "NotificationPushPayload",
    "NotificationRoutes",
    "NotificationState",
    "NotificationSyncPayload",
    "init_app",
    "notifications",
    "render_center_content",
    "render_topbar_fragment",
]
