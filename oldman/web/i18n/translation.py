"""Process-level Web translation service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote, urlencode

from babel.support import Translations
from jinja2 import pass_context

import oldman.conf as conf
from oldman.i18n.catalogs import CatalogLoader
from oldman.i18n.registry import LanguageDefinition, LanguageRegistry
from oldman.i18n.translations import gettext, ngettext, pgettext
from oldman.logging import logger
from oldman.utils.singleton import singleton_adv
from oldman.web.i18n.assets import direct_flag_url
from oldman.web.request import Request, get_current_request
from oldman.web.routing import WebApp


class I18nSettings(Protocol):
    """Settings fields required by the Web translation service."""

    @property
    def default_language(self) -> str:
        """Return the configured default language value."""
        ...

    @property
    def languages(self) -> Mapping[str, object]:
        """Return canonical project language definitions."""
        ...

    @property
    def use_i18n_path(self) -> bool:
        """Return whether language-prefixed routes are enabled."""
        ...


@singleton_adv
class TranslationService:
    """Own one project's immutable language registry and lazy catalog cache."""

    def __init__(self) -> None:
        """Create an uninitialized process-level service."""
        self.is_initialized = False
        self.default_language = "en"
        self.use_i18n_path = False
        self.public_domain = ""
        self.static_url = ""
        self.registry = LanguageRegistry({})
        self._loader = CatalogLoader(())
        self._translations_cache: dict[str, Translations] = {}

    @property
    def definitions(self) -> tuple[LanguageDefinition, ...]:
        """Return configured languages in stable project order."""
        return tuple(self.registry)

    def initialize(
        self,
        app: WebApp,
        config: I18nSettings,
        *,
        catalog_roots: Sequence[str | Path],
        public_domain: str = "",
        static_url: str = "",
    ) -> None:
        """Initialize the unique Sanic/Jinja environment exactly once."""
        if self.is_initialized:
            return

        registry = LanguageRegistry(config.languages)
        if not registry:
            raise ValueError("i18n.languages must not be empty when i18n is enabled")
        default_language = registry.resolve(config.default_language)
        if not default_language:
            raise ValueError("i18n.default_language must resolve to one configured language")

        loader = CatalogLoader(catalog_roots)
        environment = app.ext.environment
        environment.add_extension("jinja2.ext.i18n")
        if config.use_i18n_path:
            from oldman.web.template.i18n_extension import I18nExtension

            environment.add_extension(I18nExtension)

        # Request middleware binds the catalog ContextVar used by these helpers.
        environment.globals["_"] = gettext
        environment.globals["gettext"] = gettext
        environment.globals["ngettext"] = ngettext
        environment.globals["pgettext"] = pgettext

        @pass_context
        def get_current_locale(context: Mapping[str, Any]) -> str:
            """Return the request locale or the configured default."""
            request = context.get("request")
            request_context = getattr(request, "ctx", None)
            return str(getattr(request_context, "locale", "") or default_language)

        environment.globals["get_locale"] = get_current_locale

        # Publish state only after every initialization step succeeds.
        self.registry = registry
        self.default_language = default_language
        self.use_i18n_path = bool(config.use_i18n_path)
        self.public_domain = public_domain.rstrip("/")
        self.static_url = static_url.rstrip("/")
        self._loader = loader
        self._translations_cache.clear()
        self.is_initialized = True
        logger.info("Web i18n initialized for languages: %s", ", ".join(registry.codes))

    def resolve_language(self, value: str | None) -> str:
        """Resolve a request value to a canonical configured code."""
        return self.registry.resolve(value)

    def get_translations(self, language: str) -> Translations:
        """Return the lazily loaded catalog for a code, locale, or alias."""
        if not self.is_initialized:
            raise RuntimeError("Web i18n is not initialized")

        definition = self.registry.definition(language)
        catalog = self._translations_cache.get(definition.babel_locale)
        if catalog is None:
            catalog = self._loader.load(definition.babel_locale)
            self._translations_cache[definition.babel_locale] = catalog
            logger.info("Loaded translations: %s", definition.babel_locale)
        return catalog

    def get_locale(self, request: Request, *, auto_detect: bool = True) -> str:
        """Select a canonical request language using the migrated priority order."""
        if not self.is_initialized:
            raise RuntimeError("Web i18n is not initialized")

        detected = self.resolve_language(str(getattr(request.ctx, "detected_lang", "") or ""))
        if detected:
            return detected
        if not auto_detect:
            return self.default_language

        request_language = self.resolve_language(str(request.args.get("lang", "") or ""))
        if request_language:
            return request_language

        for cookie_name in ("lang", "preferred_language"):
            cookie_language = self.resolve_language(str(request.cookies.get(cookie_name, "") or ""))
            if cookie_language:
                return cookie_language

        accept_language = str(request.headers.get("accept-language", "") or "")
        for entry in accept_language.split(","):
            requested = entry.split(";", 1)[0].strip()
            resolved = self.resolve_language(requested)
            if resolved:
                return resolved

            prefix = requested.replace("_", "-").split("-", 1)[0].lower()
            resolved = self.resolve_language(prefix)
            if resolved:
                return resolved

        return self.default_language

    def build_url(
        self,
        app: WebApp,
        route_name: str,
        current_language: str,
        *,
        target_language: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Build a route URL with a non-default canonical language prefix."""
        language = self.resolve_language(target_language or current_language)
        if not language:
            raise ValueError(f"unsupported language: {target_language or current_language!r}")

        base_path = app.url_for(route_name, **kwargs)
        if language == self.default_language:
            return base_path
        return f"/{language}{base_path}"


translation = TranslationService()


def build_i18n_url(
    app: WebApp,
    route_name: str,
    current_lang: str,
    target_lang: str | None = None,
    _lang: str | None = None,
    **kwargs: Any,
) -> str:
    """Build an i18n URL through the configured process-level service."""
    return translation.build_url(
        app,
        route_name,
        current_lang,
        target_language=_lang or target_lang,
        **kwargs,
    )


def build_i18n_url_with_request(route: str, **kwargs: Any) -> str:
    """Build an i18n URL from the current Sanic request."""
    request = get_current_request()
    return translation.build_url(
        request.app,
        route,
        str(request.ctx.locale),
        target_language=kwargs.pop("_lang", None) or kwargs.pop("target_lang", None),
        **kwargs,
    )


__all__ = [
    "I18nSettings",
    "TranslationService",
    "build_i18n_url",
    "build_i18n_url_with_request",
    "translation",
]


def language_registry(request: Any = None) -> LanguageRegistry:
    """The project's language registry: the initialized service's, else the settings', never empty.

    Without i18n a one-entry registry is built from the request locale or the default language so
    templates and menus keep working.
    """
    if translation.is_initialized and translation.registry:
        return translation.registry
    config = conf.settings.i18n
    if config.use_i18n:
        registry = LanguageRegistry(config.languages)
        if registry:
            return registry
    fallback = str(getattr(getattr(request, "ctx", None), "locale", "") or config.default_language or "en")
    return LanguageRegistry({fallback: {"aliases": [], "name": fallback, "flag": ""}})


def current_language(request: Any = None) -> str:
    """The canonical language of a request: its resolved locale, then the language cookies, then the default."""
    registry = language_registry(request)
    cookies = getattr(request, "cookies", None) or {}
    candidates = (
        str(getattr(getattr(request, "ctx", None), "locale", "") or ""),
        str(cookies.get("lang", "") or ""),
        str(cookies.get("preferred_language", "") or ""),
        str(conf.settings.i18n.default_language or ""),
    )
    for candidate in candidates:
        resolved = registry.resolve(candidate)
        if resolved:
            return resolved
    return registry.codes[0]


def language_switch_url(request: Any, language: str, *, default_language: str, use_i18n_path: bool) -> str:
    """The current page in `language`: a path prefix when i18n paths are on, never a stale ?lang= override."""
    request_context = getattr(request, "ctx", None)
    clean_path = str(getattr(request_context, "clean_path", "") or getattr(request, "path", "") or "/")
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    target_path = clean_path
    if use_i18n_path and language != default_language:
        target_path = f"/{quote(language, safe='')}{clean_path}"
    query_items = [
        (key, value)
        for key, value in parse_qsl(str(getattr(request, "query_string", "") or ""), keep_blank_values=True)
        if key != "lang"
    ]
    query = urlencode(query_items)
    return f"{target_path}?{query}" if query else target_path


def language_menu_items(request: Any = None) -> list[dict[str, Any]]:
    """The language menu entries: code, locale, aliases, name, flag, flagUrl, is_current and url."""
    config = conf.settings.i18n
    registry = language_registry(request)
    current = current_language(request)
    default_language = registry.resolve(config.default_language) or registry.codes[0]
    items: list[dict[str, Any]] = []
    for definition in registry:
        try:
            flag_url = direct_flag_url(definition.flag, static_url=conf.settings.web.static.url)
        except ValueError as exc:
            raise RuntimeError(f"Language {definition.code} flag {definition.flag!r} cannot be resolved without settings.web.static.url") from exc
        items.append(
            {
                "code": definition.code,
                "locale": definition.code,
                "aliases": list(definition.aliases),
                "name": definition.name,
                "flag": definition.flag,
                "flagUrl": flag_url,
                "is_current": definition.code == current,
                "url": language_switch_url(request, definition.code, default_language=default_language, use_i18n_path=bool(config.use_i18n_path)),
            }
        )
    return items
