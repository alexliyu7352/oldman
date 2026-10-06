"""Typed settings for {{ project_name }}."""

from __future__ import annotations

from pydantic import Field

from oldman.conf import DefaultSettings
from oldman.conf.schemas import CoreConfig


class CoreSettings(CoreConfig):
    """Core settings with this project's own Redis namespace.

    Every service of the project shares it, and another project on the same Redis keeps
    its keys apart. A service that must stay apart sets core.namespace in its YAML.
    """

    namespace: str | None = Field(
        default="{{ project_slug }}",
        description=CoreConfig.model_fields["namespace"].description,
    )


class Settings(DefaultSettings):
    """Project settings schema."""

    # Narrowing a section's type is how a project gives it other defaults;
    # pydantic validates `core` with this class.
    core: CoreSettings = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default_factory=CoreSettings,
        description=DefaultSettings.model_fields["core"].description,
    )
