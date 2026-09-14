"""Permanent contracts for Oldman's single YAML settings implementation."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from ruamel.yaml.representer import RepresenterError

import oldman.conf.schemas as framework_schemas
from oldman.conf.manager import SettingsFileMissingError, SettingsManager
from oldman.conf.schemas import DefaultSettings
from oldman.runtime import ServiceDefinition


def _simple_service(root: Path) -> ServiceDefinition:
    """Return the static service facts required by SettingsManager."""
    return ServiceDefinition("worker", root / "services" / "worker.py", "simple")


def _manager(
    settings_class: type[DefaultSettings],
    settings_file: Path,
) -> SettingsManager:
    """Build one Simple-service manager for local settings behavior tests."""
    return SettingsManager(settings_class, _simple_service(settings_file.parent), settings_file)


class AliasedProjectSettings(DefaultSettings):
    """Project settings may use normal Pydantic field aliases in YAML."""

    token: str = Field(default="default", validation_alias="TOKEN")


class ProjectSettings(DefaultSettings):
    """Project settings retain custom fields alongside framework defaults."""

    project_name: str = "example"


class RequiredSettings(DefaultSettings):
    """Project settings with one operator-supplied required value."""

    required_token: str
    optional_value: str = "defaulted"


class UnrenderableValue:
    """Value accepted by Pydantic but unsupported by the YAML representer."""


class UnrenderableSettings(DefaultSettings):
    """Project settings used to verify render-before-write ordering."""

    payload: object


class ConfSingleSettingsTest(unittest.TestCase):
    """Verify one Settings type and one explicitly selected YAML per process."""

    def test_framework_owned_schemas_use_canonical_field_names(self) -> None:
        for value in vars(framework_schemas).values():
            if not (isinstance(value, type) and issubclass(value, BaseModel) and value.__module__ == framework_schemas.__name__):
                continue
            for field_name, field_info in value.model_fields.items():
                with self.subTest(model=value.__name__, field=field_name):
                    self.assertIsNone(field_info.alias)
                    self.assertIsNone(field_info.validation_alias)
                    self.assertIsNone(field_info.serialization_alias)

    def test_project_field_alias_is_read_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text("TOKEN: operator\n", encoding="utf-8")

            settings = _manager(AliasedProjectSettings, settings_file).load()

        self.assertEqual(settings.token, "operator")

    def test_missing_yaml_is_not_replaced_by_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "worker_settings.yaml"

            with self.assertRaises(SettingsFileMissingError):
                _manager(ProjectSettings, missing).load()

    def test_read_only_load_creates_no_lock_or_sidecar_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_dir = Path(temporary_directory) / "readonly"
            config_dir.mkdir()
            settings_file = config_dir / "worker_settings.yaml"
            settings_file.write_text("project_name: operator\n", encoding="utf-8")
            config_dir.chmod(0o555)

            try:
                settings = _manager(ProjectSettings, settings_file).load()
            finally:
                config_dir.chmod(0o755)

            self.assertEqual(settings.project_name, "operator")
            self.assertEqual([settings_file], list(config_dir.iterdir()))

    def test_init_creates_private_simple_service_yaml_without_schema_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            manager = _manager(ProjectSettings, settings_file)

            manager.init_config()
            raw = manager.read_config()

            self.assertEqual(0o600, stat.S_IMODE(settings_file.stat().st_mode))
            self.assertNotIn("_schema_hash", raw)
            self.assertNotIn("web", raw)
            self.assertEqual([], raw["apps"])
            self.assertEqual({}, raw["app_settings"])
            for section in (
                "core",
                "logging",
                "process",
                "i18n",
                "database",
                "redis",
                "cache",
                "http_client",
                "storages",
                "proxy",
            ):
                self.assertIn(section, raw)

    def test_init_refuses_to_overwrite_an_existing_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text("project_name: operator\n", encoding="utf-8")
            before = settings_file.read_bytes()

            with self.assertRaises(FileExistsError):
                _manager(ProjectSettings, settings_file).init_config()

            self.assertEqual(before, settings_file.read_bytes())

    def test_sync_preserves_permissions_comments_and_operator_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text(
                "# deployment owner: platform\nproject_name: operator\n",
                encoding="utf-8",
            )
            settings_file.chmod(0o640)
            manager = _manager(ProjectSettings, settings_file)

            manager.sync_config()
            source = settings_file.read_text(encoding="utf-8")

            self.assertEqual(0o640, stat.S_IMODE(settings_file.stat().st_mode))
            self.assertIn("# deployment owner: platform", source)
            self.assertEqual("operator", manager.read_config()["project_name"])

    def test_sync_accepts_required_yaml_value_and_adds_optional_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text("required_token: operator\n", encoding="utf-8")
            manager = _manager(RequiredSettings, settings_file)

            manager.sync_config()
            synced = manager.read_config()

            self.assertEqual("operator", synced["required_token"])
            self.assertEqual("defaulted", synced["optional_value"])

    def test_sync_missing_required_value_does_not_rewrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text("{}\n", encoding="utf-8")
            manager = _manager(RequiredSettings, settings_file)
            before = settings_file.read_bytes()

            with self.assertRaises(ValidationError):
                manager.sync_config()

            self.assertEqual(before, settings_file.read_bytes())

    def test_render_failure_does_not_rewrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_file = Path(temporary_directory) / "worker_settings.yaml"
            settings_file.write_text("payload: original\n", encoding="utf-8")
            manager = _manager(UnrenderableSettings, settings_file)
            before = settings_file.read_bytes()

            with self.assertRaises(RepresenterError):
                manager.write_config({"payload": UnrenderableValue()})

            self.assertEqual(before, settings_file.read_bytes())

if __name__ == "__main__":
    unittest.main()
