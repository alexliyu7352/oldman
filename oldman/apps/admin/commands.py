"""User administration commands provided by the built-in Admin app."""

from __future__ import annotations

import os

from oldman.auth import (
    change_user_password,
    ensure_superuser,
    get_user_by_username,
    user_identity,
)
from oldman.cli import Command, tui
from oldman.i18n import gettext
from oldman.i18n import gettext_lazy as _
from oldman.web.auth import end_user_logins


def _username(value: str | None, *, noinput: bool = False) -> str:
    """Return one non-empty username from an option or a question.

    `--noinput` 下不提问：要么有参数，要么直接说缺了 `--username`，比"需要终端"的报错更好查。
    """
    if value is None and noinput:
        raise ValueError(gettext("--username is required for a non-interactive run."))
    username = (value if value is not None else tui.ask(gettext("Username"))).strip()
    if not username:
        raise ValueError(gettext("Username cannot be empty."))
    return username


SUPERUSER_PASSWORD_ENV = "OLDMAN_SUPERUSER_PASSWORD"


def _prompt_password(*, key: str | None = None) -> str:
    """Read one password twice without exposing it in command arguments or terminal output.

    With `key` the password can be preset through the environment (see `tui.answer_variable`),
    which, like `OLDMAN_SUPERUSER_PASSWORD`, keeps it out of the process list and shell history.
    """
    return str(tui.ask(gettext("Password"), secret=True, confirm_secret=True, key=key))


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
        执行则等于提权。要这种"有就更新"的语义得显式写 `--update`。更新时该用户已有的登录
        全部结束，和其他改密入口一样。
        """
        selected_username = _username(username, noinput=noinput)
        existing = await get_user_by_username(selected_username)
        if existing is not None and not update:
            raise ValueError(gettext("Username already exists"))

        selected_email = email if email is not None or noinput else tui.ask(gettext("Email"), required=False)
        await ensure_superuser(
            selected_username,
            _noninteractive_password() if noinput else _prompt_password(),
            (selected_email or "").strip() or None,
        )
        if existing is None:
            return gettext("User created")
        await end_user_logins(user_identity(existing))
        return gettext("User updated")


class ChangePassword(Command):
    """Change one existing configured User password."""

    name = "changepassword"
    help = _("Change Password")

    async def handle(self, username: str) -> str:
        """Find the selected User, replace its password and end the logins opened under the old one."""
        selected_username = _username(username)
        user = await get_user_by_username(selected_username)
        if user is None:
            raise ValueError(gettext("User not found."))

        user_id = user_identity(user)
        changed = await change_user_password(user_id, _prompt_password(key="changepassword.password"))
        if changed is None:
            raise ValueError(gettext("User not found."))
        await end_user_logins(user_id)
        return gettext("Password changed")


__all__ = ["SUPERUSER_PASSWORD_ENV", "ChangePassword", "CreateSuperuser"]
