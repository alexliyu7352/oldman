"""The shared account forms' own rules, which every host's password pages rely on."""

from __future__ import annotations

import asyncio
import unittest

from oldman.web.auth import UserPasswordForm


class UserPasswordFormTest(unittest.TestCase):
    def test_a_new_password_needs_its_confirmation_and_letters_with_numbers(self) -> None:
        for data, field in (
            ({"password": "Str0ngPass!2026", "confirm_password": "different1"}, "confirm_password"),
            ({"password": "abcdefgh", "confirm_password": "abcdefgh"}, "password"),
        ):
            with self.subTest(data=data):
                form = UserPasswordForm(data=data)
                self.assertFalse(asyncio.run(form.validate()))
                self.assertIn(field, form.errors)
        self.assertTrue(asyncio.run(UserPasswordForm(data={"password": "Str0ngPass2026", "confirm_password": "Str0ngPass2026"}).validate()))

    def test_the_browser_is_told_the_same_rules(self) -> None:
        """The HTML attributes match the validators, so the browser refuses what the server would."""
        attributes = UserPasswordForm().password.render_kw

        self.assertEqual(8, attributes["minlength"])
        self.assertIn("pattern", attributes)


if __name__ == "__main__":
    unittest.main()
