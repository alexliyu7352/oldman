"""Language-code and path helpers shared by core and Web i18n."""

from babel import Locale
from babel.core import UnknownLocaleError, get_locale_identifier, parse_locale


def normalize_lang_code(lang: str) -> str:
    """Validate and return one canonical Babel-supported BCP 47 language tag."""
    if not isinstance(lang, str):
        raise TypeError("language code must be a string")

    raw = lang.strip()
    if not raw:
        raise ValueError("language code must not be blank")
    if "_" in raw:
        raise ValueError(f"language code {lang!r} must use BCP 47 hyphens")

    try:
        parsed = parse_locale(raw, sep="-")
        canonical = get_locale_identifier(parsed, sep="-")
        Locale.parse(canonical, sep="-")
    except (TypeError, ValueError, UnknownLocaleError) as exc:
        raise ValueError(
            f"language code {lang!r} is not a Babel-supported BCP 47 tag"
        ) from exc
    return canonical


def canonical_language_code(value: str) -> str:
    """Return the public canonical form of one configured language code."""
    return normalize_lang_code(value)


def babel_locale_code(value: str) -> str:
    """Return the derived Babel/gettext identifier for one language tag."""
    return canonical_language_code(value).replace("-", "_")


def language_display_name(value: str) -> str:
    """Return CLDR's self-localized display name for one language tag."""
    canonical = canonical_language_code(value)
    locale = Locale.parse(canonical, sep="-")
    return str(locale.get_display_name(locale) or canonical)


def split_language_from_path(path: str) -> tuple[str, str]:
    """Split the first URL path segment without guessing whether it is a language."""
    if not path.startswith("/") or path == "/":
        return "", path

    prefix, separator, remainder = path[1:].partition("/")
    if not prefix:
        return "", path
    clean_path = f"/{remainder}" if separator else "/"
    return prefix, clean_path
