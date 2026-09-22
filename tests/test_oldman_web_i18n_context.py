"""Shared language and CSRF template helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import oldman.conf as conf
from oldman.i18n.registry import LanguageRegistry
from oldman.web.i18n import TranslationService, current_language, language_menu_items, language_registry
from oldman.web.security.csrf import csrf_token_for

LANGUAGES = {
    "en": {"aliases": ["en-US"], "name": "English", "flag": "oldman/images/flags/us.svg"},
    "zh-Hans": {"aliases": ["zh-CN"], "name": "简体中文", "flag": "oldman/images/flags/cn.svg"},
}


def fake_settings(*, use_i18n: bool = True, use_i18n_path: bool = False) -> Any:
    return SimpleNamespace(
        i18n=SimpleNamespace(use_i18n=use_i18n, languages=LANGUAGES, default_language="en", use_i18n_path=use_i18n_path),
        web=SimpleNamespace(static=SimpleNamespace(url="/static")),
    )


def request_with(*, locale: str = "", cookies: dict[str, str] | None = None, path: str = "/users", query: str = "") -> Any:
    return SimpleNamespace(ctx=SimpleNamespace(locale=locale, clean_path=path), cookies=cookies or {}, path=path, query_string=query)


class LanguageContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(conf.__dict__, {"settings": fake_settings()}))

    def test_current_language_prefers_the_request_locale_then_the_cookies_then_the_default(self) -> None:
        self.assertEqual("zh-Hans", current_language(request_with(locale="zh-CN", cookies={"lang": "en"})))
        self.assertEqual("zh-Hans", current_language(request_with(cookies={"lang": "zh-Hans"})))
        self.assertEqual("zh-Hans", current_language(request_with(cookies={"preferred_language": "zh-CN"})))
        self.assertEqual("en", current_language(request_with(cookies={"lang": "fr"})))
        self.assertEqual("en", current_language(None))

    def test_menu_items_carry_flags_current_marker_and_switch_urls(self) -> None:
        items = language_menu_items(request_with(locale="zh-Hans", query="lang=en&page=2"))

        self.assertEqual(["en", "zh-Hans"], [item["code"] for item in items])
        self.assertEqual(("简体中文", ["zh-CN"], True), (items[1]["name"], items[1]["aliases"], items[1]["is_current"]))
        self.assertFalse(items[0]["is_current"])
        self.assertTrue(items[1]["flagUrl"].startswith("/static/"))
        # The stale ?lang= override is dropped; without i18n paths both point at the same page.
        self.assertEqual(["/users?page=2", "/users?page=2"], [item["url"] for item in items])

        with patch.dict(conf.__dict__, {"settings": fake_settings(use_i18n_path=True)}):
            urls = [item["url"] for item in language_menu_items(request_with(locale="en"))]
        self.assertEqual(["/users", "/zh-Hans/users"], urls)

    def test_registry_falls_back_to_one_language_without_i18n(self) -> None:
        with patch.dict(conf.__dict__, {"settings": fake_settings(use_i18n=False)}):
            registry = language_registry(request_with(locale="de"))
            self.assertEqual(["de"], list(registry.codes))
            self.assertEqual("de", current_language(request_with(locale="de")))
            self.assertEqual(1, len(language_menu_items(request_with(locale="de"))))

    def test_get_locale_honours_the_preferred_language_cookie(self) -> None:
        service = cast(Any, TranslationService).__wrapped__()
        service.registry = LanguageRegistry(LANGUAGES)
        service.default_language = "en"
        service.is_initialized = True
        request = SimpleNamespace(ctx=SimpleNamespace(), args={}, cookies={"preferred_language": "zh-CN"}, headers={})

        self.assertEqual("zh-Hans", service.get_locale(request))


class CsrfTokenForTest(unittest.TestCase):
    def test_token_comes_from_the_installed_manager_or_is_empty(self) -> None:
        manager = SimpleNamespace(generate_token=lambda request: f"token-for-{request.path}")
        self.assertEqual("token-for-/x", csrf_token_for(SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace(csrf=manager)), path="/x")))
        self.assertEqual("", csrf_token_for(SimpleNamespace(app=SimpleNamespace(ctx=SimpleNamespace()))))
        self.assertEqual("", csrf_token_for(None))


if __name__ == "__main__":
    unittest.main()
