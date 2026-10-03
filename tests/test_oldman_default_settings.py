"""Framework runtime defaults stay stable across releases."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from oldman.conf.schemas import AccountConfig, DefaultSettings, I18nConfig


class DefaultSettingsTest(unittest.TestCase):
    """Keep framework values typed even though YAML persistence is service-scoped."""

    def test_runtime_defaults_are_stable(self) -> None:
        settings = DefaultSettings()

        self.assertEqual("Asia/Singapore", settings.core.time_zone)
        self.assertEqual("::", settings.web.listen_host)
        self.assertEqual(17998, settings.web.listen_port)
        self.assertFalse(settings.web.access_log)
        self.assertEqual("http://localhost:17998", settings.web.domain)
        self.assertEqual("/static/", settings.web.static.url)
        self.assertEqual("/media/", settings.web.media.url)
        self.assertEqual("okhttp/3.8.7", settings.http_client.user_agent)
        self.assertEqual(300, settings.http_client.max_connections)
        self.assertEqual(5, settings.proxy.connect_timeout)
        self.assertEqual(10, settings.proxy.read_timeout)
        self.assertEqual("en", settings.i18n.default_language)
        self.assertFalse(settings.i18n.use_i18n)
        self.assertEqual("/login", settings.web.account.login_url)
        self.assertEqual("/preferences/language", settings.i18n.preference_url)

    def test_page_addresses_are_plain_same_site_paths(self) -> None:
        """Routes are registered at these and browsers redirected to them, so nothing but a local path."""
        for value in ("login", "//evil.example/login", "https://evil.example/login", "/login?next=/", "/login#form"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    AccountConfig(login_url=value)
                with self.assertRaises(ValidationError):
                    I18nConfig(preference_url=value)
        self.assertEqual("/signin", AccountConfig(login_url="/signin").login_url)
        for field in ("logout_url", "login_redirect_url", "password_reset_url", "profile_url", "user_events_url", "users_url"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                AccountConfig(**{field: "https://evil.example/"})
        self.assertIsNone(AccountConfig().password_reset_url)

    def test_root_schema_has_apps_but_no_profile_or_hash_api(self) -> None:
        settings = DefaultSettings()

        self.assertEqual((), settings.apps)
        self.assertNotIn("app_settings", type(settings).model_fields)


if __name__ == "__main__":
    unittest.main()
