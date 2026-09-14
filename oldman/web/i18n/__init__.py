"""Web internationalization service."""

from oldman.web.i18n.translation import (
    TranslationService,
    build_i18n_url,
    build_i18n_url_with_request,
    translation,
)

__all__ = [
    "TranslationService",
    "build_i18n_url",
    "build_i18n_url_with_request",
    "translation",
]
