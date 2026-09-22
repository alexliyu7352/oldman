"""User administration commands provided by the built-in Admin app."""

from __future__ import annotations

import os

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


def _username(value: str | None, *, noinput: bool = False) -> str:
    """Return one non-empty username from an option or interactive prompt.

    `--noinput` 下不能弹提示：无 tty 时 typer 只会 abort，报错和"非交互"没关系，排查成本很高。
    """
    if value is None and noinput:
        raise ValueError(gettext("--username is required for a non-interactive run."))
    username = (value if value is not None else typer.prompt(gettext("Username"))).strip()
    if not username:
        raise ValueError(gettext("Username cannot be empty."))
    return username


SUPERUSER_PASSWORD_ENV = "OLDMAN_SUPERUSER_PASSWORD"


def _prompt_password() -> str:
    """Read one password without exposing it in command arguments or terminal output."""
    return str(
        typer.prompt(
            gettext("Password"),
            hide_input=True,
            confirmation_prompt=gettext("Confirm Password"),
        )
    )


def _noninteractive_password() -> str:
    """Read the password from the environment for scripted runs.

    命令行参数会进入进程列表和 shell 历史，所以自动化场景用环境变量，不加 --password。
    """
    password = os.environ.get(SUPERUSER_PASSWORD_ENV, "")
    if not password:
        raise ValueError(gettext("%(variable)s must be set for a non-interactive run.", variable=SUPERUSER_PASSWORD_ENV))
    return password


class CreateSuperuser(Command):
    """Create one new active staff superuser."""

    name = "createsuperuser"
    help = _("Create Superuser")

    async def handle(
        self,
        username: str | None = None,
        email: str | None = None,
        noinput: bool = False,
        update: bool = False,
    ) -> str:
        """Prompt for missing credentials and create one configured User.

        `--noinput` 给脚本和门禁用：用户名和邮箱来自参数，密码来自 `OLDMAN_SUPERUSER_PASSWORD`。

        同名用户存在时默认拒绝，`--noinput` 也一样：`ensure_superuser` 会覆盖密码并把账号提成
        active+staff+superuser，发布脚本重复执行会静默回滚管理员自己改过的密码，拿一个普通用户名
        执行则等于提权。要这种"有就更新"的语义得显式写 `--update`。
        """
        selected_username = _username(username, noinput=noinput)
        existing = await get_user_by_username(selected_username)
        if existing is not None and not update:
            raise ValueError(gettext("Username already exists"))

        selected_email = (
            email
            if email is not None or noinput
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
            _noninteractive_password() if noinput else _prompt_password(),
            (selected_email or "").strip() or None,
        )
        return gettext("User updated") if existing is not None else gettext("User created")


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


__all__ = ["SUPERUSER_PASSWORD_ENV", "ChangePassword", "CreateSuperuser"]
