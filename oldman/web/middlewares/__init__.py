"""Web middleware entry points."""

from oldman.web.middlewares.i18n import cleanup_i18n, install_i18n
from oldman.web.middlewares.timezone import add_timezone_info, install_timezone

__all__ = ["add_timezone_info", "cleanup_i18n", "install_i18n", "install_timezone"]
