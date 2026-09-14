"""Strongly typed settings owned by the Admin application."""

from pydantic import BaseModel, ConfigDict, Field


class AdminSettings(BaseModel):
    """Configure access policy specific to the built-in Admin UI."""

    model_config = ConfigDict(extra="forbid")

    require_superuser: bool = Field(
        default=False,
        description="Require superuser access to Admin",
    )


__all__ = ["AdminSettings"]
