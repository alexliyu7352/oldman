"""Built-in Admin user command behavior."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, patch

from oldman.apps.admin.commands import SUPERUSER_PASSWORD_ENV, ChangePassword, CreateSuperuser


class AdminUserCommandTests(unittest.IsolatedAsyncioTestCase):
    """Verify Admin commands remain thin, secure Auth service adapters."""

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
            patch("oldman.apps.admin.commands.get_user_by_username", lookup),
            patch("oldman.apps.admin.commands.ensure_superuser", create),
            patch(
                "oldman.apps.admin.commands.typer.prompt",
                side_effect=["root@example.com", "Secret123"],
            ) as prompt,
        ):
            result = await CreateSuperuser().handle(username=" root ")

        lookup.assert_awaited_once_with("root")
        create.assert_awaited_once_with("root", "Secret123", "root@example.com")
        self.assertEqual("User created", result)
        self.assertEqual("Email", prompt.call_args_list[0].args[0])
        self.assertEqual("Password", prompt.call_args_list[1].args[0])
        self.assertTrue(prompt.call_args_list[1].kwargs["hide_input"])
        self.assertEqual(
            "Confirm Password",
            prompt.call_args_list[1].kwargs["confirmation_prompt"],
        )

    async def test_noinput_reads_the_password_from_the_environment(self) -> None:
        """脚本和门禁用 --noinput：密码来自环境变量，不进命令行参数。"""
        create = AsyncMock()
        with (
            patch("oldman.apps.admin.commands.get_user_by_username", AsyncMock(return_value=None)),
            patch("oldman.apps.admin.commands.ensure_superuser", create),
            patch("oldman.apps.admin.commands.typer.prompt") as prompt,
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: "Scripted123"}),
        ):
            result = await CreateSuperuser().handle(username="gate", email="gate@example.test", noinput=True)

        create.assert_awaited_once_with("gate", "Scripted123", "gate@example.test")
        self.assertEqual("User created", result)
        prompt.assert_not_called()

    async def test_an_existing_user_needs_update_even_without_input(self) -> None:
        """ensure_superuser 会覆盖密码并提成超管，所以"有就更新"必须显式要求。"""
        create = AsyncMock()
        with (
            patch("oldman.apps.admin.commands.get_user_by_username", AsyncMock(return_value=object())),
            patch("oldman.apps.admin.commands.ensure_superuser", create),
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: "Scripted123"}),
        ):
            with self.assertRaisesRegex(ValueError, "Username already exists"):
                await CreateSuperuser().handle(username="gate", noinput=True)
            create.assert_not_awaited()

            result = await CreateSuperuser().handle(username="gate", email="", noinput=True, update=True)

        create.assert_awaited_once_with("gate", "Scripted123", None)
        self.assertEqual("User updated", result)

    async def test_noinput_without_a_username_says_so_instead_of_prompting(self) -> None:
        """无 tty 下 typer.prompt 只会 abort，报错和"非交互"无关，排查成本很高。"""
        with (
            patch("oldman.apps.admin.commands.typer.prompt") as prompt,
            patch("oldman.apps.admin.commands.ensure_superuser", AsyncMock()) as create,
            self.assertRaisesRegex(ValueError, "--username"),
        ):
            await CreateSuperuser().handle(noinput=True)

        prompt.assert_not_called()
        create.assert_not_awaited()

    async def test_noinput_without_the_password_variable_fails_before_writing(self) -> None:
        create = AsyncMock()
        with (
            patch("oldman.apps.admin.commands.get_user_by_username", AsyncMock(return_value=None)),
            patch("oldman.apps.admin.commands.ensure_superuser", create),
            patch.dict("os.environ", {SUPERUSER_PASSWORD_ENV: ""}),
            self.assertRaisesRegex(ValueError, SUPERUSER_PASSWORD_ENV),
        ):
            await CreateSuperuser().handle(username="gate", noinput=True)

        create.assert_not_awaited()

    async def test_createsuperuser_rejects_an_existing_username_before_prompting(self) -> None:
        with (
            patch(
                "oldman.apps.admin.commands.get_user_by_username",
                AsyncMock(return_value=object()),
            ),
            patch("oldman.apps.admin.commands.ensure_superuser", AsyncMock()) as create,
            patch("oldman.apps.admin.commands.typer.prompt") as prompt,
        ):
            with self.assertRaisesRegex(ValueError, "Username already exists"):
                await CreateSuperuser().handle(username="root")

        create.assert_not_awaited()
        prompt.assert_not_called()

    async def test_changepassword_updates_the_selected_user(self) -> None:
        user = object()
        change = AsyncMock(return_value=user)
        with (
            patch(
                "oldman.apps.admin.commands.get_user_by_username",
                AsyncMock(return_value=user),
            ),
            patch("oldman.apps.admin.commands.user_identity", return_value=7),
            patch("oldman.apps.admin.commands.change_user_password", change),
            patch(
                "oldman.apps.admin.commands.typer.prompt",
                return_value="Changed123",
            ),
        ):
            result = await ChangePassword().handle("root")

        change.assert_awaited_once_with(7, "Changed123")
        self.assertEqual("Password changed", result)

    async def test_changepassword_rejects_an_unknown_user_before_prompting(self) -> None:
        with (
            patch(
                "oldman.apps.admin.commands.get_user_by_username",
                AsyncMock(return_value=None),
            ),
            patch("oldman.apps.admin.commands.typer.prompt") as prompt,
        ):
            with self.assertRaisesRegex(ValueError, "User not found"):
                await ChangePassword().handle("missing")

        prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
