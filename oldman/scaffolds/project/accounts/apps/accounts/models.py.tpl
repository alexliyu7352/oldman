"""The project's User model."""

from oldman.auth import AbstractUser
from oldman.i18n import gettext_lazy as _


class User(AbstractUser):
    """Every account of {{ project_name }}. Add fields here; `./run.sh db makemigrations` writes their migration.

    The table stays the framework's `oldman_user` (`app_settings.auth.user_model` points here).
    """

    class Meta:
        """Names the built-in Admin and the user pages show."""

        verbose_name = _("User")
        verbose_name_plural = _("Users")
