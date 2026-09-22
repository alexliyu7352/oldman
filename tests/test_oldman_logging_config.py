"""Logging configuration contracts for the final direct-writer runtime."""

from __future__ import annotations

import importlib
import logging
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from oldman.conf.schemas import LoggingConfig


class LoggingConfigTest(unittest.TestCase):
    """Verify the remaining user-facing logging settings."""

    def test_runtime_defaults_are_explicit(self) -> None:
        """Defaults expose level, directory, console color policy and file rollover."""
        config = LoggingConfig()

        self.assertEqual(logging.INFO, config.level)
        self.assertIsInstance(config.dir, Path)
        self.assertEqual("auto", config.color)
        # Rollover joined the surface once the sinks stopped hardcoding it; the defaults
        # reproduce exactly what was hardcoded, so an untouched deployment is unaffected.
        self.assertEqual("D", config.rotate_when)
        self.assertEqual(1, config.rotate_interval)
        self.assertEqual(0, config.max_bytes)
        self.assertEqual(3, config.backup_count)
        self.assertEqual(
            {"level", "dir", "color", "rotate_when", "rotate_interval", "max_bytes", "backup_count"},
            set(type(config).model_fields),
        )

    def test_valid_runtime_options_are_preserved(self) -> None:
        """Supported values survive validation without a topology selector."""
        config = LoggingConfig.model_validate(
            {
                "level": "DEBUG",
                "dir": "/tmp/oldman-logs",
                "color": "never",
            }
        )

        self.assertEqual(logging.DEBUG, config.level)
        self.assertEqual(Path("/tmp/oldman-logs"), config.dir)
        self.assertEqual("never", config.color)

    def test_invalid_supported_options_are_rejected(self) -> None:
        """Invalid levels and color policies fail while loading settings."""
        invalid_values = (
            {"level": "TRACE"},
            {"color": "rich"},
        )

        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                LoggingConfig.model_validate(values)


class LoggingConfigBuilderTest(unittest.TestCase):
    """Verify pure direct-writer configuration generation."""

    def logging_config_module(self):
        """Load the logging config module and report a clear missing-package failure."""
        try:
            return importlib.import_module("oldman.logging.config")
        except ModuleNotFoundError as exc:
            self.fail(f"oldman.logging.config is missing: {exc}")

    def test_build_keeps_routes_and_declares_atomic_rotation(self) -> None:
        """All built-in file routes use one atomic handler and retain their filenames."""
        config_module = self.logging_config_module()
        with tempfile.TemporaryDirectory() as tmp:
            config = config_module.build_sink_config(
                "Demo App",
                Path(tmp),
                logging.INFO,
                "never",
            )

            self.assertEqual(
                "oldman.logging.handlers.AtomicAppendFileHandler",
                config["handlers"]["file"]["class"],
            )
            for name in ("file", "access_file", "database_file"):
                handler = config["handlers"][name]
                self.assertEqual("D", handler["when"])
                self.assertEqual(1, handler["interval"])
                self.assertEqual(3, handler["backupCount"])
            self.assertEqual(str(Path(tmp) / "demo_app.log"), config["handlers"]["file"]["filename"])
            self.assertEqual(
                str(Path(tmp) / "demo_app_access.log"),
                config["handlers"]["access_file"]["filename"],
            )
            self.assertEqual(
                str(Path(tmp) / "demo_app_database.log"),
                config["handlers"]["database_file"]["filename"],
            )

    def test_each_build_is_independent_and_overrides_merge_deeply(self) -> None:
        """One application override cannot mutate defaults or erase sibling keys."""
        config_module = self.logging_config_module()
        with tempfile.TemporaryDirectory() as tmp:
            configured = config_module.build_sink_config(
                "configured",
                Path(tmp),
                logging.INFO,
                "always",
                overrides={
                    "handlers": {"file": {"backupCount": 7}},
                    "loggers": {"default": {"level": "DEBUG"}},
                },
            )
            untouched = config_module.build_sink_config(
                "untouched",
                Path(tmp),
                logging.WARNING,
                "never",
            )

        self.assertEqual(7, configured["handlers"]["file"]["backupCount"])
        self.assertEqual(
            "oldman.logging.handlers.AtomicAppendFileHandler",
            configured["handlers"]["file"]["class"],
        )
        self.assertEqual("DEBUG", configured["loggers"]["default"]["level"])
        self.assertEqual(3, untouched["handlers"]["file"]["backupCount"])
        self.assertEqual(logging.WARNING, untouched["loggers"]["default"]["level"])
        self.assertEqual("always", configured["formatters"]["generic"]["color"])
        self.assertEqual("never", untouched["formatters"]["generic"]["color"])

        configured["root"]["handlers"].append("custom")
        self.assertNotIn("custom", configured["loggers"]["default"]["handlers"])


if __name__ == "__main__":
    unittest.main()


class LogRotationSettingsTest(unittest.TestCase):
    """Rotation is configuration, not a constant compiled into the sink builder.

    The three file sinks were hardcoded to daily with three backups, so a deployment
    could not keep more history or switch to size-based rollover without replacing the
    whole config dict. conf/constants.py carried LOG_MAX_BYTES and LOG_BACKUP_COUNT that
    nothing ever read - the values existed, the wiring did not.
    """

    HANDLERS = ("file", "access_file", "database_file")

    def _built(
        self,
        *,
        when: str | None = "D",
        interval: int = 1,
        max_bytes: int = 0,
        backup_count: int = 3,
    ) -> dict:
        from oldman.logging.config import RotationSettings, build_sink_config

        rotation = RotationSettings(when=when, interval=interval, max_bytes=max_bytes, backup_count=backup_count)
        return build_sink_config("demo", "/tmp/oldman-test-logs", 20, "never", None, rotation=rotation)

    def test_the_default_keeps_the_previous_hardcoded_behaviour(self) -> None:
        config = self._built()
        for name in self.HANDLERS:
            with self.subTest(handler=name):
                handler = config["handlers"][name]
                self.assertEqual("D", handler["when"])
                self.assertEqual(1, handler["interval"])
                self.assertEqual(3, handler["backupCount"])
                self.assertNotIn("maxBytes", handler)

    def test_size_rollover_replaces_the_time_keys(self) -> None:
        """The handler refuses both at once, so the builder must not emit both."""
        config = self._built(when=None, max_bytes=10 * 1024 * 1024, backup_count=7)
        for name in self.HANDLERS:
            with self.subTest(handler=name):
                handler = config["handlers"][name]
                self.assertEqual(10 * 1024 * 1024, handler["maxBytes"])
                self.assertEqual(7, handler["backupCount"])
                self.assertNotIn("when", handler)
                self.assertNotIn("interval", handler)

    def test_every_file_sink_follows_the_setting(self) -> None:
        config = self._built(when="midnight", interval=1, backup_count=14)
        for name in self.HANDLERS:
            with self.subTest(handler=name):
                self.assertEqual("midnight", config["handlers"][name]["when"])
                self.assertEqual(14, config["handlers"][name]["backupCount"])

    def test_the_settings_refuse_to_rotate_two_ways_at_once(self) -> None:
        from pydantic import ValidationError

        from oldman.conf.schemas import LoggingConfig

        self.assertEqual("D", LoggingConfig().rotate_when)
        self.assertEqual(10, LoggingConfig(rotate_when=None, max_bytes=10).max_bytes)
        with self.assertRaises(ValidationError):
            LoggingConfig(rotate_when="D", max_bytes=10)

    def test_constants_no_longer_shadow_the_settings_defaults(self) -> None:
        """Two sources for one default drift apart; settings is the one that is read."""
        from oldman.conf import constants

        for removed in ("LOG_LEVEL", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT", "LOGS_DIR", "TIME_ZONE", "DOMAIN"):
            with self.subTest(constant=removed):
                self.assertFalse(hasattr(constants, removed))

        for kept in ("PROJECT_ROOT", "BASE_DIR", "BASE_PATH", "DEBUG", "TEMPLATE_DEBUG", "USER_AGENT_DICT_DEFINE"):
            with self.subTest(constant=kept):
                self.assertTrue(hasattr(constants, kept))
