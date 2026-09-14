"""Strongly typed settings owned by the Auth application."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuthSettings(BaseModel):
    """Select the sole concrete User model used by one service."""

    model_config = ConfigDict(extra="forbid")

    user_model: str = Field(
        default="oldman.auth.models.User",
        min_length=1,
        description="Import path of the configured User model",
    )

    @field_validator("user_model")
    @classmethod
    def normalize_user_model_path(cls, value: str) -> str:
        """Strip the import path and require a module attribute."""
        normalized = value.strip()
        module_name, separator, attribute = normalized.rpartition(".")
        if not separator or not module_name or not attribute:
            raise ValueError("auth.user_model must be a dotted import path")
        return normalized


__all__ = ["AuthSettings"]
