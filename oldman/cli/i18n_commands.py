"""Thin CLI delegation to the framework catalog operations."""

from __future__ import annotations

from oldman.i18n import LanguageRegistry


def normalize_catalog_locale(language: str) -> tuple[str, str]:
    """Return canonical BCP 47 and Babel locale codes for one language."""
    registry = LanguageRegistry({language: {}})
    definition = next(iter(registry))
    return definition.code, definition.babel_locale


def extract_catalog() -> None:
    """Delegate catalog extraction to the i18n implementation."""
    from oldman.i18n.commands import extract

    extract()


def initialize_catalog(locale_name: str) -> None:
    """Delegate catalog initialization with a Babel locale identifier."""
    from oldman.i18n.commands import init

    init(locale_name)


def update_catalogs() -> None:
    """Delegate catalog update to the i18n implementation."""
    from oldman.i18n.commands import update

    update()


def compile_catalogs() -> None:
    """Delegate catalog compilation to the i18n implementation."""
    from oldman.i18n.commands import compile_translations

    compile_translations()


__all__ = [
    "compile_catalogs",
    "extract_catalog",
    "initialize_catalog",
    "normalize_catalog_locale",
    "update_catalogs",
]
