"""Framework runtime defaults stay stable across releases."""

from __future__ import annotations

import unittest

from oldman.conf.schemas import DefaultSettings


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

    def test_root_schema_has_apps_but_no_profile_or_hash_api(self) -> None:
        settings = DefaultSettings()

        self.assertEqual((), settings.apps)
        self.assertNotIn("app_settings", type(settings).model_fields)


if __name__ == "__main__":
    unittest.main()
