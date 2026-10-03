"""The Auth App's account commands."""

from __future__ import annotations

import inspect
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from oldman.auth.commands import SUPERUSER_PASSWORD_ENV, ChangePassword, CreateSuperuser
from oldman.cli import tui
from tests.tui_support import without_preset_answers

ROOT = Path(__file__).resolve().parents[1]


def setUpModule() -> None:
    unittest.enterModuleContext(without_preset_answers())


class AuthUserCommandTests(unittest.IsolatedAsyncioTestCase):
    """Verify the account commands remain thin, secure Auth service adapters."""

    def test_the_auth_app_owns_the_commands_and_importing_them_needs_no_web_layer(self) -> None:
        """A dashboard without the built-in Admin creates its first account with them; oldman.auth never imports oldman.web."""
        probe = textwrap.dedent(
            """
            import sys

            import oldman.auth.commands

            assert not [name for name in sys.modules if name.startswith("oldman.web")], "importing the commands imported oldman.web"

            from oldman.apps import AppRegistry
            from oldman.apps.admin.settings import AdminSettings
            from oldman.auth.settings import AuthSettings

            registry = AppRegistry()
            registry.register_packages(("oldman.auth", "oldman.apps.admin"))
            registry.bind_settings("auth", AuthSettings())
            registry.bind_settings("admin", AdminSettings())
            registry.load_models()
            registry.load_commands()
            print([command.name for command in registry.get_app_commands("auth")], [command.name for command in registry.get_app_commands("admin")])
            """
        )
        completed = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("['createsuperuser', 'changepassword'] []", completed.stdout.strip())

    def test_command_contract_does_not_expose_password_arguments(self) -> None:
        self.assertEqual("createsuperuser", CreateSuperuser.name)
        self.assertEqual("changepassword", ChangePassword.name)
        # 没有 --password：密码只走隐藏输入或环境变量，不进命令行参数。
        self.assertEqual(
            ["self", "username", "email", "noinput", "update"],
            list(inspect.signature(CreateSuperuser.handle).parameters),
        )
        self.assertEqual(
            ["self", "username"],
            list(inspect.signature(ChangePassword.handle).parameters),
        )

    async def test_createsuperuser_prompts_securely_and_uses_auth_service(self) -> None:
        lookup = AsyncMock(return_value=None)
        create = AsyncMock()
        with (
            patch("oldman.auth.commands.get_user_by_username", lookup),
            patch("oldman.auth.commands.ensure_superuser", create),
            patch("oldman.web.auth.end_user_logins", AsyncMock()) as end_logins,
            tui.simulate_input(["root@example.com", "Secret123", "Other123", "Secret123", "Secret123"]) as terminal,
        ):
            result = await CreateSuperuser().handle(username=" root ")

        lookup.assert_awaited_once_with("root")
        create.assert_awaited_once_with("root", "Secret123", "root@example.com")
        self.assertEqual("User created", result)
        end_logins.assert_not_awaited()
        self.assertTrue(terminal.stdout.startswith("Email: root@example.com\nPassword: \nConfirm Password: \n"))
        self.assertIn("The two entries do not match.", terminal.stdout)
        self.assertNotIn("Secret123", terminal.stdout)

    async def test_createsuperuser_email_may_be_left_empty(self) -> None:
        create = AsyncMock()
        with (
            patch("oldman.auth.commands.get_user_by_username", AsyncMock(return_value=None)),
            patch("oldman.auth.commands.ensure_superuser", create),
            tui.simulate_input(["", "Secret123", "Secret123"]),
        ):
            await CreateSuperuser().handle(username="root")

        create.assert_awaited_once_with("root", "Secret123", None)

    async def test_noinput_reads_the_password_from_the_environment(self) -> None:
        """脚本和门禁用 --noinput：密码来自环境变量，不进命令行参数。"""
        create = AsyncMock()
        with (
            patch("oldman.auth.commands.get_user_by_username", AsyncMock(return_value=None)),
            patch("oldman.auth.commands.ensure_superuser", create),
            tui.simulate_input([]),
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: "Scripted123"}),
        ):
            result = await CreateSuperuser().handle(username="gate", email="gate@example.test", noinput=True)

        create.assert_awaited_once_with("gate", "Scripted123", "gate@example.test")
        self.assertEqual("User created", result)

    async def test_an_existing_user_needs_update_even_without_input(self) -> None:
        """ensure_superuser 会覆盖密码并提成超管，所以"有就更新"必须显式要求。"""
        create = AsyncMock()
        existing = object()
        with (
            patch("oldman.auth.commands.get_user_by_username", AsyncMock(return_value=existing)),
            patch("oldman.auth.commands.ensure_superuser", create),
            patch("oldman.auth.commands.user_identity", return_value=7) as identity,
            patch("oldman.web.auth.end_user_logins", AsyncMock()) as end_logins,
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: "Scripted123"}),
        ):
            with self.assertRaisesRegex(ValueError, "Username already exists"):
                await CreateSuperuser().handle(username="gate", noinput=True)
            create.assert_not_awaited()
            end_logins.assert_not_awaited()

            result = await CreateSuperuser().handle(username="gate", email="", noinput=True, update=True)

        create.assert_awaited_once_with("gate", "Scripted123", None)
        self.assertEqual("User updated", result)
        # The password was overwritten: logins opened under the old one end with it.
        identity.assert_called_once_with(existing)
        end_logins.assert_awaited_once_with(7)

    async def test_noinput_without_a_username_says_so_instead_of_prompting(self) -> None:
        """`--noinput` 下直接说缺了 `--username`，而不是提问后才报"需要终端"。"""
        with (
            tui.simulate_input([]),
            patch("oldman.auth.commands.ensure_superuser", AsyncMock()) as create,
            self.assertRaisesRegex(ValueError, "--username"),
        ):
            await CreateSuperuser().handle(noinput=True)

        create.assert_not_awaited()

    async def test_noinput_without_the_password_variable_fails_before_writing(self) -> None:
        create = AsyncMock()
        with (
            patch("oldman.auth.commands.get_user_by_username", AsyncMock(return_value=None)),
            patch("oldman.auth.commands.ensure_superuser", create),
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: ""}),
            self.assertRaisesRegex(ValueError, SUPERUSER_PASSWORD_ENV),
        ):
            await CreateSuperuser().handle(username="gate", noinput=True)

        create.assert_not_awaited()

    async def test_createsuperuser_rejects_an_existing_username_before_prompting(self) -> None:
        with (
            patch(
                "oldman.auth.commands.get_user_by_username",
                AsyncMock(return_value=object()),
            ),
            patch("oldman.auth.commands.ensure_superuser", AsyncMock()) as create,
            tui.simulate_input([]),
        ):
            with self.assertRaisesRegex(ValueError, "Username already exists"):
                await CreateSuperuser().handle(username="root")

        create.assert_not_awaited()

    async def test_changepassword_updates_the_selected_user(self) -> None:
        user = object()
        change = AsyncMock(return_value=user)
        with (
            patch(
                "oldman.auth.commands.get_user_by_username",
                AsyncMock(return_value=user),
            ),
            patch("oldman.auth.commands.user_identity", return_value=7),
            patch("oldman.auth.commands.change_user_password", change),
            patch("oldman.web.auth.end_user_logins", AsyncMock()) as end_logins,
            tui.simulate_input(["Changed123", "Changed123"]),
        ):
            result = await ChangePassword().handle("root")

        change.assert_awaited_once_with(7, "Changed123")
        self.assertEqual("Password changed", result)
        end_logins.assert_awaited_once_with(7)

    async def test_changepassword_takes_a_preset_password_for_scripts(self) -> None:
        change = AsyncMock(return_value=object())
        with (
            patch("oldman.auth.commands.get_user_by_username", AsyncMock(return_value=object())),
            patch("oldman.auth.commands.user_identity", return_value=7),
            patch("oldman.auth.commands.change_user_password", change),
            patch("oldman.web.auth.end_user_logins", AsyncMock()),
            patch.dict("os.environ", {"OLDMAN_ANSWER_CHANGEPASSWORD_PASSWORD": "Scripted123"}),
            tui.simulate_input([]) as terminal,
        ):
            await ChangePassword().handle("root")

        change.assert_awaited_once_with(7, "Scripted123")
        self.assertEqual("Password: *** (OLDMAN_ANSWER_CHANGEPASSWORD_PASSWORD)\n", terminal.stdout)

    async def test_changepassword_rejects_an_unknown_user_before_prompting(self) -> None:
        with (
            patch(
                "oldman.auth.commands.get_user_by_username",
                AsyncMock(return_value=None),
            ),
            tui.simulate_input([]),
        ):
            with self.assertRaisesRegex(ValueError, "User not found"):
                await ChangePassword().handle("missing")


if __name__ == "__main__":
    unittest.main()
