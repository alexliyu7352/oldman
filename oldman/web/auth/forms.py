"""Forms shared by Web account and Admin user-session flows."""

from __future__ import annotations

from typing import cast

from wtforms import PasswordField
from wtforms.validators import DataRequired, Length, Regexp

from oldman.i18n import gettext, gettext_lazy
from oldman.web.components.forms import FieldLayout, TailwindForm

PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$"
PASSWORD_MESSAGE = cast(
    str,
    gettext_lazy("Password must be 8-128 characters and include letters and numbers"),
)


class UserPasswordForm(TailwindForm):
    """Validate a new password through the shared Web account policy."""

    password = PasswordField(
        cast(str, gettext_lazy("New Password")),
        validators=[
            DataRequired(),
            Length(min=8, max=128),
            Regexp(PASSWORD_PATTERN, message=PASSWORD_MESSAGE),
        ],
        render_kw={
            "required": True,
            "minlength": 8,
            "maxlength": 128,
            "pattern": PASSWORD_PATTERN,
            "autocomplete": "new-password",
        },
    )
    confirm_password = PasswordField(
        cast(str, gettext_lazy("Confirm Password")),
        validators=[DataRequired(), Length(min=8, max=128)],
        render_kw={
            "required": True,
            "minlength": 8,
            "maxlength": 128,
            "autocomplete": "new-password",
        },
    )

    field_layout = (
        FieldLayout("password", "md:col-span-12"),
        FieldLayout("confirm_password", "md:col-span-12"),
    )

    async def clean(self) -> None:
        """Require the confirmation to match the new password."""
        if self.password.data != self.confirm_password.data:
            self.add_error("confirm_password", gettext("Passwords do not match"))


__all__ = ["PASSWORD_MESSAGE", "PASSWORD_PATTERN", "UserPasswordForm"]
