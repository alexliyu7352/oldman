"""Installable persistent notifications application metadata."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class NotificationsAppConfig(AppConfig):
    """Describe the framework-owned persistent notifications application."""

    label = "notifications"
    display_name = _("Notifications")
    icon = "ri-notification-3-line"


app = NotificationsAppConfig()

__all__ = ["NotificationsAppConfig", "app"]
