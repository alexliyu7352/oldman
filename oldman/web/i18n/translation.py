"""Process-level Web translation service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from babel.support import Translations
from jinja2 import pass_context

from oldman.i18n.catalogs import CatalogLoader
from oldman.i18n.registry import LanguageDefinition, LanguageRegistry
from oldman.i18n.translations import gettext, ngettext, pgettext
from oldman.logging import logger
from oldman.utils.singleton import singleton_adv
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

        cookie_language = self.resolve_language(str(request.cookies.get("lang", "") or ""))
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
