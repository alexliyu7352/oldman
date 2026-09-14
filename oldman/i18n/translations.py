"""Core-safe translation functions shared by CLI and Web consumers."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Protocol


class TranslationCatalog(Protocol):
    """Small Babel-compatible catalog contract used by the public helpers."""

    def gettext(self, message: str, /) -> str: ...

    def ngettext(self, singular: str, plural: str, n: int, /) -> str: ...

    def pgettext(self, context: str, message: str, /) -> str | object: ...


current_translations: ContextVar[TranslationCatalog | None] = ContextVar("current_translations", default=None)


def bind_translations(catalog: TranslationCatalog) -> Token[TranslationCatalog | None]:
    """Bind a request catalog without importing a Web runtime from this module."""
    return current_translations.set(catalog)


def reset_translations(token: Token[TranslationCatalog | None]) -> None:
    """Restore the translation context associated with a completed request."""
    current_translations.reset(token)


def _catalog(request: Any | None) -> TranslationCatalog | None:
    """Resolve an explicit request catalog before the current task binding."""
    if request is not None:
        context = getattr(request, "ctx", None)
        catalog = getattr(context, "translations", None)
        if catalog is not None:
            return catalog
    return current_translations.get()


def gettext(message: str, request: Any | None = None, **variables: Any) -> str:
    """Translate a singular message, falling back to the source string outside Web requests."""
    catalog = _catalog(request)
    result = catalog.gettext(message) if catalog is not None else message
    return result % variables if variables else result


def gettext_noop(message: str) -> str:
    """Mark deferred source text for extraction without translating it."""
    return message


def ngettext(singular: str, plural: str, n: int, request: Any | None = None, **variables: Any) -> str:
    """Translate a plural message, falling back to the matching source string."""
    catalog = _catalog(request)
    result = catalog.ngettext(singular, plural, n) if catalog is not None else (singular if n == 1 else plural)
    variables = dict(variables)
    variables.setdefault("num", n)
    return result % variables if variables else result


def pgettext(context: str, message: str, request: Any | None = None, **variables: Any) -> str:
    """Translate a contextual message, falling back to the source string."""
    catalog = _catalog(request)
    result = str(catalog.pgettext(context, message)) if catalog is not None else message
    return result % variables if variables else result


class LazyTranslation:
    """Resolve a message only when converted to text."""

    def __init__(self, singular: str, plural: str | None = None, n: int | None = None, **variables: Any) -> None:
        """Store source messages without resolving the current task catalog."""
        self.singular = singular
        self.plural = plural
        self.n = n
        self.variables = dict(variables)

    def __str__(self) -> str:
        if self.plural is None:
            return gettext(self.singular, **self.variables)
        assert self.n is not None
        return ngettext(self.singular, self.plural, self.n, **self.variables)


def gettext_lazy(message: str, **variables: Any) -> LazyTranslation:
    """Create a lazy singular translation."""
    return LazyTranslation(message, **variables)


def ngettext_lazy(singular: str, plural: str, n: int, **variables: Any) -> LazyTranslation:
    """Create a lazy plural translation."""
    return LazyTranslation(singular, plural, n, **variables)


__all__ = [
    "LazyTranslation",
    "TranslationCatalog",
    "bind_translations",
    "current_translations",
    "gettext",
    "gettext_noop",
    "gettext_lazy",
    "ngettext",
    "ngettext_lazy",
    "pgettext",
    "reset_translations",
]
