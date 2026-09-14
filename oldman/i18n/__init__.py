"""Runtime-independent internationalization API."""

from oldman.i18n.catalogs import CatalogLoader
from oldman.i18n.registry import (
    LanguageDefinition,
    LanguageRegistry,
    canonical_language_code,
    language_code_variants,
)
from oldman.i18n.serialization import TranslatableMsgspecModel
from oldman.i18n.translations import (
    LazyTranslation,
    bind_translations,
    gettext,
    gettext_lazy,
    gettext_noop,
    ngettext,
    ngettext_lazy,
    pgettext,
    reset_translations,
)
from oldman.i18n.utils import normalize_lang_code

_ = gettext_lazy
N_ = ngettext_lazy

__all__ = [
    "N_",
    "_",
    "CatalogLoader",
    "LanguageDefinition",
    "LanguageRegistry",
    "LazyTranslation",
    "TranslatableMsgspecModel",
    "bind_translations",
    "canonical_language_code",
    "gettext",
    "gettext_lazy",
    "gettext_noop",
    "language_code_variants",
    "ngettext",
    "ngettext_lazy",
    "normalize_lang_code",
    "pgettext",
    "reset_translations",
]
