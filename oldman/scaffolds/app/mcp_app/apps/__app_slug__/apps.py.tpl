"""Installable metadata for the {{ app_slug }} App."""

from oldman.apps import AppConfig
from oldman.i18n import gettext_lazy as _


class {{ app_class }}AppConfig(AppConfig):
    """Describe the {{ app_slug }} App."""

    label = "{{ app_slug }}"
    display_name = _({{ display_name_literal }})


app = {{ app_class }}AppConfig()

__all__ = ["{{ app_class }}AppConfig", "app"]
