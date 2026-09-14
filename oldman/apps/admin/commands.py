"""User administration commands provided by the built-in Admin app."""

from __future__ import annotations

import typer

from oldman.auth import (
    change_user_password,
    ensure_superuser,
    get_user_by_username,
    user_identity,
)
from oldman.cli import Command
from oldman.i18n import gettext
from oldman.i18n import gettext_lazy as _


def _username(value: str | None) -> str:
    """Return one non-empty username from an option or interactive prompt."""
    username = (value if value is not None else typer.prompt(gettext("Username"))).strip()
    if not username:
        raise ValueError(gettext("Username cannot be empty."))
    return username


def _prompt_password() -> str:
    """Read one password without exposing it in command arguments or terminal output."""
    return str(
        typer.prompt(
            gettext("Password"),
            hide_input=True,
            confirmation_prompt=gettext("Confirm Password"),
        )
    )


class CreateSuperuser(Command):
    """Create one new active staff superuser."""

    name = "createsuperuser"
    help = _("Create Superuser")

    async def handle(
        self,
        username: str | None = None,
        email: str | None = None,
    ) -> str:
        """Prompt for missing credentials and create one configured User."""
        selected_username = _username(username)
        if await get_user_by_username(selected_username) is not None:
            raise ValueError(gettext("Username already exists"))

        selected_email = (
            email
            if email is not None
            else str(
                typer.prompt(
                    gettext("Email"),
                    default="",
                    show_default=False,
                )
            )
        )
        await ensure_superuser(
            selected_username,
            _prompt_password(),
            selected_email.strip() or None,
        )
        return gettext("User created")


class ChangePassword(Command):
    """Change one existing configured User password."""

    name = "changepassword"
    help = _("Change Password")

    async def handle(self, username: str) -> str:
        """Find the selected User and replace its password."""
        selected_username = _username(username)
        user = await get_user_by_username(selected_username)
        if user is None:
            raise ValueError(gettext("User not found."))

        changed = await change_user_password(
            user_identity(user),
            _prompt_password(),
        )
        if changed is None:
            raise ValueError(gettext("User not found."))
        return gettext("Password changed")


__all__ = ["ChangePassword", "CreateSuperuser"]
