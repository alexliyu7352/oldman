"""The project's accounts: its User model, and the sign-in and account pages."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class AccountsAppConfig(AppConfig):
    """Own the project's User model; the pages come from the framework's account flows (routes.py)."""

    label = "accounts"
    display_name = _("Accounts")
    icon = "ri-user-settings-line"


app = AccountsAppConfig()

__all__ = ["AccountsAppConfig", "app"]
