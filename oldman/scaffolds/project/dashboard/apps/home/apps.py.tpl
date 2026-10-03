"""The first page after signing in."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class HomeAppConfig(AppConfig):
    """Own the home page; replace its content with this project's own."""

    label = "home"
    display_name = _("Home")
    icon = "ri-home-4-line"


app = HomeAppConfig()

__all__ = ["HomeAppConfig", "app"]
