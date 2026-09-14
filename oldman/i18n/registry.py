"""Canonical language definitions shared by Web, CLI, and built-in applications."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from oldman.i18n.profiles import BUILTIN_LANGUAGE_PROFILES
from oldman.i18n.utils import (
    babel_locale_code,
    canonical_language_code,
    language_display_name,
)


def language_code_variants(value: str) -> tuple[str, ...]:
    """Return canonical and case-insensitive lookup forms for one language value."""
    try:
        canonical = canonical_language_code(value)
    except (TypeError, ValueError):
        return ()
    return tuple(dict.fromkeys((canonical, canonical.casefold())))


def _config_value(config: object, name: str, default: Any) -> Any:
    """Read one language field from a typed settings model or plain mapping."""
    if isinstance(config, Mapping):
        return config.get(name, default)
    return getattr(config, name, default)


def _has_config_override(config: object, name: str) -> bool:
    """Return whether one user field was explicitly configured."""
    if isinstance(config, Mapping):
        return name in config
    fields_set = getattr(config, "model_fields_set", ())
    return name in fields_set


@dataclass(frozen=True, slots=True)
class LanguageDefinition:
    """One canonical project language and its accepted external aliases."""

    code: str
    aliases: tuple[str, ...]
    name: str
    flag: str

    @property
    def babel_locale(self) -> str:
        """Return the derived gettext filesystem identifier."""
        return babel_locale_code(self.code)

    @classmethod
    def from_config(cls, code: str, config: object) -> LanguageDefinition:
        """Merge generic metadata, an optional built-in profile, and user overrides."""
        canonical_code = canonical_language_code(code)
        profile = BUILTIN_LANGUAGE_PROFILES.get(canonical_code, {})

        raw_aliases = (
            _config_value(config, "aliases", ())
            if _has_config_override(config, "aliases")
            else profile.get("aliases", ())
        )
        if isinstance(raw_aliases, str) or not isinstance(raw_aliases, (list, tuple)):
            raise TypeError(f"i18n.languages.{canonical_code}.aliases must be a list")
        if not all(isinstance(alias, str) for alias in raw_aliases):
            raise TypeError(
                f"i18n.languages.{canonical_code}.aliases must contain strings"
            )
        aliases = tuple(canonical_language_code(alias) for alias in raw_aliases)
        if len(aliases) != len(set(aliases)):
            raise ValueError(
                f"i18n.languages.{canonical_code}.aliases contains duplicates"
            )

        configured_name = (
            _config_value(config, "name", "")
            if _has_config_override(config, "name")
            else profile.get("name", "")
        )
        if not isinstance(configured_name, str):
            raise TypeError(f"i18n.languages.{canonical_code}.name must be a string")
        name = (configured_name or language_display_name(canonical_code)).strip()
        if not name:
            raise ValueError(f"i18n.languages.{canonical_code}.name must not be blank")

        configured_flag = (
            _config_value(config, "flag", "")
            if _has_config_override(config, "flag")
            else profile.get("flag", "")
        )
        if not isinstance(configured_flag, str):
            raise TypeError(f"i18n.languages.{canonical_code}.flag must be a string")

        return cls(
            code=canonical_code,
            aliases=aliases,
            name=name,
            flag=configured_flag,
        )


class LanguageRegistry:
    """Resolve configured codes, locales, and aliases to canonical project languages."""

    def __init__(self, languages: Mapping[str, object]) -> None:
        """Freeze definitions in configuration order and reject ambiguous aliases."""
        self._definitions: dict[str, LanguageDefinition] = {}
        self._aliases: dict[str, str] = {}

        for raw_code, config in languages.items():
            definition = LanguageDefinition.from_config(str(raw_code), config)
            if definition.code in self._definitions:
                raise ValueError(f"duplicate canonical language code: {definition.code}")
            self._definitions[definition.code] = definition

        for definition in self._definitions.values():
            for candidate in (definition.code, *definition.aliases):
                if candidate != definition.code and candidate in self._definitions:
                    raise ValueError(
                        f"language alias {candidate!r} conflicts with a canonical language code"
                    )
                if candidate == definition.code and candidate in definition.aliases:
                    raise ValueError(
                        f"language alias {candidate!r} duplicates its canonical language code"
                    )
                for variant in language_code_variants(candidate):
                    current = self._aliases.get(variant)
                    if current is not None and current != definition.code:
                        raise ValueError(f"language alias {candidate!r} is ambiguous between {current!r} and {definition.code!r}")
                    self._aliases[variant] = definition.code

    def __bool__(self) -> bool:
        """Return whether at least one language is configured."""
        return bool(self._definitions)

    def __contains__(self, value: object) -> bool:
        """Return whether a value resolves to a configured language."""
        return isinstance(value, str) and bool(self.resolve(value))

    def __iter__(self) -> Iterator[LanguageDefinition]:
        """Iterate definitions in stable configuration order."""
        return iter(self._definitions.values())

    def __len__(self) -> int:
        """Return the number of canonical languages."""
        return len(self._definitions)

    @property
    def codes(self) -> tuple[str, ...]:
        """Return canonical language codes in configuration order."""
        return tuple(self._definitions)

    def resolve(self, value: str | None) -> str:
        """Resolve a code, locale, or configured alias to one canonical code."""
        if not value:
            return ""
        for variant in language_code_variants(value):
            resolved = self._aliases.get(variant)
            if resolved is not None:
                return resolved
        return ""

    def definition(self, value: str) -> LanguageDefinition:
        """Return the definition for a code, locale, or alias."""
        resolved = self.resolve(value)
        if not resolved:
            raise KeyError(value)
        return self._definitions[resolved]

    def babel_locale_for(self, value: str) -> str:
        """Return the Babel/gettext locale for a configured language."""
        return self.definition(value).babel_locale


__all__ = [
    "LanguageDefinition",
    "LanguageRegistry",
    "canonical_language_code",
    "language_code_variants",
]
