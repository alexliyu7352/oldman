"""Public browser user-message APIs."""

from oldman.web.messages._cookie_storage import init_app
from oldman.web.messages.actions import DashboardActivityAction
from oldman.web.messages.flash import (
    FlashMessage,
    MessageFormat,
    MessageLevel,
    add_message,
    error,
    info,
    success,
    warning,
)
from oldman.web.messages.notifications import (
    NotificationPresentation,
    NotificationState,
    notifications,
)

__all__ = [
    "DashboardActivityAction",
    "FlashMessage",
    "MessageFormat",
    "MessageLevel",
    "NotificationPresentation",
    "NotificationState",
    "add_message",
    "error",
    "info",
    "init_app",
    "notifications",
    "success",
    "warning",
]
