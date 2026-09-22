"""Web internationalization service."""

from oldman.web.i18n.assets import ensure_frontend_catalogs
from oldman.web.i18n.translation import (
    TranslationService,
    build_i18n_url,
    build_i18n_url_with_request,
    current_language,
    language_menu_items,
    language_registry,
    language_switch_url,
    translation,
)

__all__ = [
    "TranslationService",
    "build_i18n_url",
    "build_i18n_url_with_request",
    "current_language",
    "ensure_frontend_catalogs",
    "language_menu_items",
    "language_registry",
    "language_switch_url",
    "translation",
]
