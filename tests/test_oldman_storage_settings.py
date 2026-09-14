"""Typed canonical storage settings tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

import oldman.conf as conf
from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings, MediaConfig, StorageBackendConfig, StoragesConfig
from oldman.runtime import ServiceDefinition


def _manager(settings_class: type[DefaultSettings], settings_file: Path) -> SettingsManager:
    """Build a Simple-service manager for isolated storage validation."""
    definition = ServiceDefinition(
        "worker",
        settings_file.parent / "services" / "worker.py",
        "simple",
    )
    return SettingsManager(settings_class, definition, settings_file)


class StorageSettingsTest(unittest.TestCase):
    """Keep storage selection typed and canonical."""

    def test_default_storage_owns_the_framework_media_location(self) -> None:
        settings = DefaultSettings()

        self.assertEqual("default", settings.web.media.storage)
        self.assertNotIn("root", MediaConfig.model_fields)
        self.assertEqual(
            "oldman.storage.backends.filesystem.FileSystemStorage",
            settings.storages["default"].backend,
        )
        self.assertEqual(
            Path(conf.PROJECT_BASE_PATH) / "media",
            Path(settings.storages["default"].options["location"]),
        )

    def test_storage_options_and_named_aliases_are_independent(self) -> None:
        first = StorageBackendConfig(backend="package.First")
        second = StorageBackendConfig(backend="package.Second")
        storages = StoragesConfig.model_validate({"default": first, "archive": second})

        first.options["marker"] = "first"

        self.assertEqual(["default", "archive"], list(storages))
        self.assertEqual(2, len(storages))
        self.assertEqual({}, storages["archive"].options)

    def test_reserved_memory_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.yaml"
            settings_file.write_text(
                "storages:\n  default:\n    backend: package.Storage\n  memory:\n    backend: package.MemoryStorage\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError):
                _manager(DefaultSettings, settings_file).load()

    def test_invalid_aliases_and_backend_paths_are_rejected(self) -> None:
        sources = (
            ("storages:\n  default:\n    backend: package.Storage\n  '':\n    backend: package.OtherStorage\n"),
            "storages:\n  default:\n    backend: Storage\n",
            "storages:\n  default:\n    backend: ' .Storage'\n",
            ("storages:\n  default:\n    backend: package.Storage\n  ' memory ':\n    backend: package.OtherStorage\n"),
        )
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                settings_file = Path(tmp) / "settings.yaml"
                settings_file.write_text(source, encoding="utf-8")

                with self.assertRaises(ValidationError):
                    _manager(DefaultSettings, settings_file).load()

    def test_backend_path_requires_valid_identifier_segments(self) -> None:
        invalid_paths = (
            "package..Storage",
            "package. .Storage",
            "package.mod. Storage",
            "package.some module.Storage",
            "package.123module.Storage",
        )

        for backend in invalid_paths:
            with self.subTest(backend=backend), self.assertRaises(ValidationError):
                StorageBackendConfig(backend=backend)

    def test_explicit_storages_without_default_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.yaml"
            settings_file.write_text(
                "storages:\n  archive:\n    backend: package.ArchiveStorage\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError):
                _manager(DefaultSettings, settings_file).load()

if __name__ == "__main__":
    unittest.main()
