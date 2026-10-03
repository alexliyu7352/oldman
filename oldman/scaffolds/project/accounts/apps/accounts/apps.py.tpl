"""The project's accounts: its own User model."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class AccountsAppConfig(AppConfig):
    """Own the project's User model, the one `app_settings.auth.user_model` names."""

    label = "accounts"
    display_name = _("Accounts")
    icon = "ri-user-settings-line"


app = AccountsAppConfig()

__all__ = ["AccountsAppConfig", "app"]
