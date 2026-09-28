"""Installable Auth application metadata."""

from oldman.apps import AppConfig
from oldman.auth.settings import AuthSettings
from oldman.i18n import gettext_lazy as _


class AuthAppConfig(AppConfig[AuthSettings]):
    """Describe the framework Auth application and its settings owner."""

    label = "auth"
    display_name = _("Authentication")
    icon = "ri-shield-user-line"
    settings_model = AuthSettings
    # oldman.auth.permissions is the declaration machinery every service imports.
    permissions_module = "user_permissions"


app = AuthAppConfig()

__all__ = ["AuthAppConfig", "app"]
