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
        """Defaults expose only level, directory and console color policy."""
        config = LoggingConfig()

        self.assertEqual(logging.INFO, config.level)
        self.assertIsInstance(config.dir, Path)
        self.assertEqual("auto", config.color)
        self.assertEqual({"level", "dir", "color"}, set(type(config).model_fields))

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
