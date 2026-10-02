"""Strongly typed settings owned by the Admin application."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oldman.utils.http import is_plain_site_path


class AdminSettings(BaseModel):
    """Configure access policy specific to the built-in Admin UI."""

    model_config = ConfigDict(extra="forbid")

    require_superuser: bool = Field(
        default=False,
        description="Require superuser access to Admin",
    )
    prefix: str = Field(
        default="/admin",
        description="URL path the Admin is mounted under; its own pages (login, sign-out, session) sit beneath it",
    )

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        """A same-site path below the site root; a trailing slash is dropped so pages join it with one."""
        normalized = value.rstrip("/")
        if not normalized or not is_plain_site_path(normalized):
            raise ValueError("app_settings.admin.prefix must be a same-site path below the root, such as /admin")
        return normalized


__all__ = ["AdminSettings"]
