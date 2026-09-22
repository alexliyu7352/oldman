"""Strongly typed settings owned by the Auth application."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PasswordResetSettings(BaseModel):
    """How long a reset link lives and how often one client may ask for one."""

    model_config = ConfigDict(extra="forbid")

    expiry: int = Field(default=60 * 60 * 24, gt=0, description="Seconds a password reset link stays valid")
    ip_limit: int = Field(default=5, ge=0, description="Reset requests one IP may make per ip_window; more get a 429")
    ip_window: int = Field(default=60 * 15, gt=0, description="Window in seconds for ip_limit")
    email_limit: int = Field(default=3, ge=0, description="Reset mails one address may receive per email_window; more are silently skipped")
    email_window: int = Field(default=60 * 60, gt=0, description="Window in seconds for email_limit")


class LoginSettings(BaseModel):
    """How many failed sign-ins one caller or one account may spend before it has to wait.

    Only failures count, so an ordinary visitor who signs in on the first try never reaches
    these numbers. The address limit is the looser of the two because a whole office can
    share one: the username limit is what actually protects a single account.
    """

    model_config = ConfigDict(extra="forbid")

    ip_limit: int = Field(default=20, ge=0, description="Failed sign-ins one IP may make per ip_window; more get a 429. 0 disables")
    ip_window: int = Field(default=60 * 15, gt=0, description="Window in seconds for ip_limit")
    username_limit: int = Field(
        default=5, ge=0, description="Failed sign-ins one username may collect per username_window; more get a 429. 0 disables"
    )
    username_window: int = Field(default=60 * 15, gt=0, description="Window in seconds for username_limit")


class AuthSettings(BaseModel):
    """Select the sole concrete User model used by one service."""

    model_config = ConfigDict(extra="forbid")

    user_model: str = Field(
        default="oldman.auth.models.User",
        min_length=1,
        description="Import path of the configured User model",
    )
    password_reset: PasswordResetSettings = Field(
        default_factory=PasswordResetSettings,
        description="Password reset link lifetime and request limits",
    )
    login: LoginSettings = Field(
        default_factory=LoginSettings,
        description="Failed sign-in limits per client address and per username",
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


__all__ = ["AuthSettings", "PasswordResetSettings"]
