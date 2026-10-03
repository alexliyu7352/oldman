"""The site's welcome page."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class HomeAppConfig(AppConfig):
    """Own the page at `/`; replace it with this project's own, or remove the App from the settings."""

    label = "home"
    display_name = _("Home")
    icon = "ri-home-4-line"


app = HomeAppConfig()

__all__ = ["HomeAppConfig", "app"]
