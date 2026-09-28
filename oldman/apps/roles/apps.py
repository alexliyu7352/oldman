"""Installable roles application metadata."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class RolesAppConfig(AppConfig):
    """Roles and who holds them: the data behind permission checks.

    It is its own App, not part of ``oldman.auth``, because a project with its own User model
    does not load ``oldman.auth``'s models, and every project that wants roles needs these tables.
    """

    label = "roles"
    display_name = _("Roles")
    icon = "ri-shield-user-line"


app = RolesAppConfig()

__all__ = ["RolesAppConfig", "app"]
