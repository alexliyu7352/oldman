"""Web middleware entry points."""

from oldman.web.middlewares.i18n import cleanup_i18n, install_i18n

__all__ = ["cleanup_i18n", "install_i18n"]
