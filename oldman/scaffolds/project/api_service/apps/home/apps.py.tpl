"""The API's front door: a health check and one endpoint for each way a program signs in."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class HomeAppConfig(AppConfig):
    """Own `/`, `/api/caller` and `/api/ops`; replace them with this project's own, or remove the App from the settings."""

    label = "home"
    display_name = _("Home")
    icon = "ri-home-4-line"


app = HomeAppConfig()

__all__ = ["HomeAppConfig", "app"]
