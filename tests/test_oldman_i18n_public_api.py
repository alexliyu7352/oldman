"""Public and Web i18n contracts."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from jinja2 import DictLoader, Environment
from pydantic import ValidationError
from sanic.compat import Header

from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings, I18nConfig
from oldman.i18n import (
    CatalogLoader,
    LanguageRegistry,
    bind_translations,
    canonical_language_code,
    gettext,
    normalize_lang_code,
    reset_translations,
)
from oldman.i18n.utils import normalize_lang_code as source_normalize_lang_code
from oldman.runtime import ServiceDefinition
from oldman.web.i18n import TranslationService, translation
from oldman.web.i18n.request import I18nRequest
from oldman.web.i18n.translation import translation as canonical_translation
from oldman.web.template.i18n_extension import I18nExtension


class _Catalog:
    """Small test catalog implementing the core translation protocol."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def gettext(self, message: str) -> str:
        """Translate one singular test message."""
        return f"{self.prefix}:{message}"

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        """Translate one plural test message."""
        return f"{self.prefix}:{singular if n == 1 else plural}"

    def pgettext(self, context: str, message: str) -> str:
        """Translate one contextual test message."""
        return f"{self.prefix}:{context}:{message}"


def _write_catalog(root: Path, locale: str, message: str) -> None:
    """Write one compiled catalog for precedence tests."""
    target = root / locale / "LC_MESSAGES" / "messages.mo"
    target.parent.mkdir(parents=True)
    catalog = Catalog(locale=locale)
    catalog.add("Save", message)
    with target.open("wb") as output:
        write_mo(output, catalog)


def _new_translation_service() -> TranslationService:
    """Construct the undecorated service for isolated lifecycle tests."""
    return cast(Any, TranslationService).__wrapped__()


class OldmanI18nPublicApiTest(unittest.TestCase):
    """Keep one canonical language and catalog implementation."""

    def test_public_normalizer_is_the_migrated_source_function(self) -> None:
        """The public normalizer must produce standard Babel-supported tags."""
        self.assertIs(normalize_lang_code, source_normalize_lang_code)
        expected = {
            "zh-hans": "zh-Hans",
            "ZH-hans": "zh-Hans",
            "es-419": "es-419",
            "fil": "fil",
            "sr-Latn-RS": "sr-Latn-RS",
        }
        for source, canonical in expected.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_lang_code(source), canonical)
                self.assertEqual(canonical_language_code(source), canonical)

        for invalid in ("", "zh_CN", "english", "x-private"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_lang_code(invalid)

    def test_web_package_exports_one_process_service(self) -> None:
        """The aggregate and canonical Web modules must expose one singleton."""
        self.assertIs(translation, canonical_translation)
        self.assertIsInstance(translation, TranslationService)

    def test_config_uses_languages_as_its_only_language_source(self) -> None:
        """Shorthand languages inherit built-in metadata and remain compact."""
        config = I18nConfig.model_validate(
            {
                "use_i18n": True,
                "default_language": "ZH-CN",
                "languages": {
                    "EN": {},
                    "ZH-HANS": {},
                },
            }
        )

        self.assertEqual(config.default_language, "zh-Hans")
        self.assertEqual(list(config.languages), ["en", "zh-Hans"])
        self.assertEqual(
            config.model_dump()["languages"],
            {"en": {}, "zh-Hans": {}},
        )
        definition = LanguageRegistry(config.languages).definition("zh-Hans")
        self.assertEqual(definition.aliases, ("zh-CN", "zh-SG"))
        self.assertEqual(definition.name, "简体中文")
        self.assertEqual(definition.babel_locale, "zh_Hans")
        self.assertEqual(definition.flag, "")
        self.assertNotIn("supported_languages", I18nConfig.model_fields)

    def test_ambiguous_aliases_are_rejected(self) -> None:
        """One valid external alias cannot silently select two languages."""
        with self.assertRaises(ValidationError):
            I18nConfig.model_validate(
                {
                    "use_i18n": True,
                    "languages": {
                        "en": {
                            "aliases": ["fr-CA"],
                        },
                        "fr": {
                            "aliases": ["fr-CA"],
                        },
                    },
                }
            )

    def test_registry_resolves_standard_mixed_case_codes_and_aliases(self) -> None:
        """Input matching is case-insensitive while stored output is canonical."""
        registry = LanguageRegistry({"zh-Hans": {}})

        for value in ("ZH-HANS", "zh-Hans", "zh-CN"):
            with self.subTest(value=value):
                self.assertEqual(registry.resolve(value), "zh-Hans")
                self.assertEqual(registry.babel_locale_for(value), "zh_Hans")
        self.assertEqual(registry.resolve("ZH_CN"), "")

    def test_user_overrides_can_clear_built_in_metadata(self) -> None:
        """Explicit empty values clear defaults while omitted fields inherit."""
        config = I18nConfig.model_validate(
            {
                "use_i18n": True,
                "languages": {
                    "en": {},
                    "zh-Hans": {
                        "aliases": [],
                        "name": "中文",
                        "flag": "/static/custom/cn.svg",
                    },
                    "de": {},
                },
            }
        )
        registry = LanguageRegistry(config.languages)

        self.assertEqual(registry.definition("zh-Hans").aliases, ())
        self.assertEqual(registry.definition("zh-Hans").name, "中文")
        self.assertEqual(
            registry.definition("zh-Hans").flag,
            "/static/custom/cn.svg",
        )
        self.assertEqual(registry.definition("de").name, "Deutsch")
        self.assertEqual(
            config.model_dump()["languages"]["en"],
            {},
        )

    def test_i18n_config_rejects_invalid_or_inconsistent_states(self) -> None:
        """The settings model must fail before runtime sees an invalid contract."""
        invalid_configs = (
            {
                "use_i18n": False,
                "use_i18n_path": True,
                "languages": {"en": {}},
            },
            {
                "use_i18n": True,
                "languages": {},
            },
            {
                "use_i18n": True,
                "default_language": "fr",
                "languages": {"en": {}},
            },
            {
                "use_i18n": True,
                "languages": {"zh_CN": {}},
            },
            {
                "use_i18n": True,
                "languages": {"en": {"locale": "en"}},
            },
            {
                "use_i18n": True,
                "languages": {"en": {"aliases": ["zh_CN"]}},
            },
            {
                "use_i18n": True,
                "languages": {"en": {}, "en-US": {}},
            },
        )

        for value in invalid_configs:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                I18nConfig.model_validate(value)

    def test_settings_sync_preserves_language_shorthand_and_explicit_clears(self) -> None:
        """Settings synchronization must not expand resolved profile metadata."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "settings.yaml"
            settings_file.write_text(
                "i18n:\n"
                "  use_i18n: true\n"
                "  default_language: en\n"
                "  languages:\n"
                "    en: {}\n"
                "    zh-Hans:\n"
                "      aliases: []\n"
                '      flag: ""\n',
                encoding="utf-8",
            )
            definition = ServiceDefinition(
                "worker",
                settings_file.parent / "services" / "worker.py",
                "simple",
            )
            manager = SettingsManager(
                DefaultSettings,
                definition,
                settings_file,
            )

            manager.sync_config()
            synced = manager.read_config()["i18n"]["languages"]

        self.assertEqual(synced["en"], {})
        self.assertEqual(synced["zh-Hans"], {"aliases": [], "flag": ""})

    def test_catalog_loader_applies_documented_override_order(self) -> None:
        """Project catalogs override lower-priority built-in catalogs."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "project"
            built_in = root / "built-in"
            _write_catalog(built_in, "zh_Hans", "内置保存")
            _write_catalog(project, "zh_Hans", "项目保存")

            catalog = CatalogLoader([project, built_in]).load("zh_Hans")

        self.assertEqual(catalog.gettext("Save"), "项目保存")

    def test_catalog_loader_preserves_babel_locale_fallback(self) -> None:
        """A regional locale can reuse its configured parent-language catalog."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_catalog(root, "zh", "保存")

            catalog = CatalogLoader([root]).load("zh_Hans")

        self.assertEqual(catalog.gettext("Save"), "保存")

    def test_service_initializes_once_and_loads_catalog_by_alias(self) -> None:
        """A repeated startup call is a no-op and catalogs remain lazy."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_catalog(root, "zh_Hans", "保存")
            environment = Environment(enable_async=True)
            app = cast(
                Any,
                SimpleNamespace(ext=SimpleNamespace(environment=environment)),
            )
            service = _new_translation_service()
            first = I18nConfig.model_validate(
                {
                    "use_i18n": True,
                    "default_language": "zh-CN",
                    "languages": {"zh-Hans": {}},
                }
            )
            second = I18nConfig.model_validate(
                {
                    "use_i18n": True,
                    "default_language": "fr",
                    "languages": {"fr": {}},
                }
            )

            service.initialize(app, first, catalog_roots=[root])
            service.initialize(app, second, catalog_roots=[])
            catalog = service.get_translations("ZH-HANS")

        self.assertEqual(service.default_language, "zh-Hans")
        self.assertEqual(catalog.gettext("Save"), "保存")
        self.assertEqual(len(service._translations_cache), 1)
        self.assertIs(environment.globals["gettext"], gettext)

    def test_web_switcher_preserves_the_configured_final_language_name(self) -> None:
        """The generic Web switcher must not localize or replace an explicit name."""
        service = _new_translation_service()
        environment = Environment(
            loader=DictLoader(
                {
                    "switcher.html": (
                        "{% for language in languages %}"
                        "{{ language.name }}={{ language.flagUrl }};"
                        "{% endfor %}"
                    )
                }
            ),
            enable_async=True,
        )
        app = cast(
            Any,
            SimpleNamespace(ext=SimpleNamespace(environment=environment)),
        )
        config = I18nConfig.model_validate(
            {
                "use_i18n": True,
                "use_i18n_path": True,
                "default_language": "en",
                "languages": {
                    "en": {},
                    "fr": {
                        "name": "Project French",
                        "flag": "cn",
                    },
                },
            }
        )
        service.initialize(
            app,
            config,
            catalog_roots=[],
            static_url="/assets/",
        )
        request = cast(
            Any,
            SimpleNamespace(
                ctx=SimpleNamespace(locale="en"),
                path="/dashboard",
                query_string="",
            ),
        )
        extension = I18nExtension(environment)

        with patch.object(I18nExtension, "_service", return_value=service):
            rendered = asyncio.run(
                extension._render_lang_switcher(
                    request,
                    "switcher.html",
                )
            )

        self.assertIn("Project French", rendered)
        self.assertNotIn("French", rendered.replace("Project French", ""))
        self.assertIn(
            "Project French=/assets/oldman/images/flags/cn.svg",
            rendered,
        )

    def test_request_language_priority_matches_migrated_behavior(self) -> None:
        """Path, query, cookie, header, and default retain their source priority."""
        service = _new_translation_service()
        environment = Environment(enable_async=True)
        app = cast(
            Any,
            SimpleNamespace(ext=SimpleNamespace(environment=environment)),
        )
        config = I18nConfig.model_validate(
            {
                "use_i18n": True,
                "default_language": "en",
                "languages": {
                    "en": {},
                    "zh-Hans": {},
                    "zh-Hant": {},
                },
            }
        )
        service.initialize(app, config, catalog_roots=[])
        request = cast(
            Any,
            SimpleNamespace(
                ctx=SimpleNamespace(detected_lang=""),
                args={"lang": "zh-CN"},
                cookies={"lang": "zh-TW"},
                headers={"accept-language": "en"},
            ),
        )

        self.assertEqual(service.get_locale(request), "zh-Hans")
        request.ctx.detected_lang = "zh-TW"
        self.assertEqual(service.get_locale(request), "zh-Hant")
        self.assertEqual(
            service.get_locale(request, auto_detect=False),
            "zh-Hant",
        )

        request.ctx.detected_lang = ""
        request.args = {}
        request.cookies = {}
        request.headers = {"accept-language": "zh"}
        self.assertEqual(service.get_locale(request), "en")

        request.headers = {"accept-language": "zh-CN"}
        self.assertEqual(service.get_locale(request), "zh-Hans")

    def test_request_subclass_delegates_the_first_path_segment_to_registry(self) -> None:
        """Every Babel-supported tag shape must use the same Registry resolver."""
        service = _new_translation_service()
        service.registry = LanguageRegistry(
            {
                "en": {},
                "zh-Hans": {},
                "zh-Hant": {},
                "fil": {},
                "es-419": {},
                "sr-Latn-RS": {},
            }
        )
        service.is_initialized = True

        cases = {
            b"/fil/dashboard": ("fil", "/dashboard"),
            b"/es-419/dashboard": ("es-419", "/dashboard"),
            b"/zh-Hant/dashboard": ("zh-Hant", "/dashboard"),
            b"/sr-Latn-RS/dashboard": ("sr-Latn-RS", "/dashboard"),
            b"/zh-hans/dashboard": ("zh-Hans", "/dashboard"),
            b"/zh-CN/example?item=1": ("zh-Hans", "/example"),
            b"/fil": ("fil", "/"),
        }
        with patch("oldman.web.i18n.translation.translation", service):
            for raw_path, (expected_language, expected_path) in cases.items():
                with self.subTest(path=raw_path):
                    request = I18nRequest(
                        raw_path,
                        Header({}),
                        "1.1",
                        "GET",
                        None,
                        SimpleNamespace(),
                    )
                    self.assertEqual(request.path, expected_path)
                    self.assertEqual(request.ctx.detected_lang, expected_language)
                    self.assertEqual(
                        request.ctx.original_path,
                        raw_path.decode().split("?", 1)[0],
                    )

            request = I18nRequest(
                b"/products/dashboard",
                Header({}),
                "1.1",
                "GET",
                None,
                SimpleNamespace(),
            )

        self.assertEqual(request.path, "/products/dashboard")
        self.assertIsNone(request.ctx.detected_lang)
        self.assertIsNone(request.ctx.clean_path)
        self.assertIsNone(request.ctx.original_path)

    def test_contextvar_keeps_concurrent_translations_isolated(self) -> None:
        """Concurrent async tasks must not overwrite each other's catalog."""

        async def translate(prefix: str) -> str:
            token = bind_translations(_Catalog(prefix))
            try:
                await asyncio.sleep(0)
                return gettext("Save")
            finally:
                reset_translations(token)

        async def run() -> tuple[str, str]:
            first, second = await asyncio.gather(
                translate("one"),
                translate("two"),
            )
            return first, second

        self.assertEqual(asyncio.run(run()), ("one:Save", "two:Save"))

    def test_contextvar_restores_nested_catalog_bindings(self) -> None:
        """Nested framework work must restore the caller's active catalog."""
        outer = bind_translations(_Catalog("outer"))
        try:
            self.assertEqual(gettext("Save"), "outer:Save")
            inner = bind_translations(_Catalog("inner"))
            try:
                self.assertEqual(gettext("Save"), "inner:Save")
            finally:
                reset_translations(inner)
            self.assertEqual(gettext("Save"), "outer:Save")
        finally:
            reset_translations(outer)
        self.assertEqual(gettext("Save"), "Save")


if __name__ == "__main__":
    unittest.main()
