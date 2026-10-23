"""The form core does not carry WTForms' CSRF; a form that asks for it must not run unprotected."""

import unittest

from oldman.web.components.forms._core import Form, StringField


class CsrfFlagTest(unittest.TestCase):
    def test_asking_for_wtforms_csrf_fails_and_names_the_framework_decorator(self):
        class F(Form):
            class Meta:
                csrf = True
                csrf_secret = b"secret"

            a = StringField()

        with self.assertRaisesRegex(TypeError, r"@csrf_protect\(\) from oldman\.web\.security\.csrf"):
            F()

    def test_forms_without_the_flag_are_unaffected(self):
        class F(Form):
            a = StringField()

        self.assertEqual({"a": None}, F().data)
