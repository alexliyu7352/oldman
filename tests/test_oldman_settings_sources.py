"""Business settings values come only from the selected YAML file."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import AliasChoices, Field

from oldman.conf.base import settings_source_context
from oldman.conf.manager import SettingsManager
from oldman.conf.schemas import DefaultSettings
from oldman.runtime import ServiceDefinition


class SourceSettings(DefaultSettings):
    """Custom project fields used to probe all former source types."""

    auth_token: str = Field(
        default="default-token",
        validation_alias=AliasChoices("auth_token", "AUTH_TOKEN"),
    )
    json_looking_text: str = "default-text"
    nullable_text: str = "default-null"


class SettingsSourcesTest(unittest.TestCase):
    """Ensure environment, dotenv, secrets and init values cannot override YAML."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.settings_file = self.root / "worker_settings.yaml"
        self.env_file = self.root / ".env"
        self.secrets_dir = self.root / "secrets"
        self.secrets_dir.mkdir()
        self.settings_file.write_text(
            "AUTH_TOKEN: yaml-token\njson_looking_text: '123'\nnullable_text: 'null'\n",
            encoding="utf-8",
        )
        self.env_file.write_text("AUTH_TOKEN=dotenv-token\n", encoding="utf-8")
        (self.secrets_dir / "AUTH_TOKEN").write_text("secret-token", encoding="utf-8")
        self.service = ServiceDefinition(
            "worker",
            self.root / "services" / "worker.py",
            "simple",
        )

    def test_manager_ignores_environment_dotenv_and_secrets(self) -> None:
        with patch.dict(os.environ, {"AUTH_TOKEN": "environment-token"}, clear=False):
            loaded = SettingsManager(
                SourceSettings,
                self.service,
                self.settings_file,
            ).load()

        self.assertEqual("yaml-token", loaded.auth_token)
        self.assertEqual("123", loaded.json_looking_text)
        self.assertEqual("null", loaded.nullable_text)

    def test_pydantic_init_values_are_not_a_settings_source(self) -> None:
        with (
            patch.dict(os.environ, {"AUTH_TOKEN": "environment-token"}, clear=False),
            settings_source_context(self.settings_file),
        ):
            loaded = SourceSettings(
                auth_token="init-token",
            )

        self.assertEqual("yaml-token", loaded.auth_token)

    def test_explicit_model_validate_still_validates_the_supplied_mapping(self) -> None:
        loaded = SourceSettings.model_validate({"AUTH_TOKEN": "explicit-token"})

        self.assertEqual("explicit-token", loaded.auth_token)

    def test_yaml_remains_required_when_other_sources_have_values(self) -> None:
        self.settings_file.unlink()
        with patch.dict(os.environ, {"AUTH_TOKEN": "environment-token"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "worker_settings.yaml"):
                SettingsManager(
                    SourceSettings,
                    self.service,
                    self.settings_file,
                ).load()


if __name__ == "__main__":
    unittest.main()
