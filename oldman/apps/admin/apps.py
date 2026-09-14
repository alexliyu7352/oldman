"""Installable Admin application metadata."""

from oldman.apps import AppConfig
from oldman.apps.admin.settings import AdminSettings
from oldman.i18n import gettext_lazy as _


class AdminAppConfig(AppConfig[AdminSettings]):
    """Describe the built-in Admin application and its settings owner."""

    label = "admin"
    display_name = _("Administration")
    icon = "ri-admin-line"
    settings_model = AdminSettings


app = AdminAppConfig()

__all__ = ["AdminAppConfig", "app"]
