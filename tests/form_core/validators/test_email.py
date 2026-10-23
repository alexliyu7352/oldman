# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_email.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import ValidationError, email
from tests.form_core.support import UpstreamTestCase, raises


class TestEmailValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_valid_email_passes(self):
        """
        Valid email address should pass without raising
        """
        for email_address in ["foo@bar.dk", "123@bar.dk", "foo@456.dk", "foo@bar456.info", "foo@bücher.中国"]:
            with self.subTest(email_address=email_address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = email()
                dummy_field.data = email_address
                validator(dummy_form, dummy_field)

    def test_invalid_email_raises(self):
        """
        Bad email address should raise ValidationError
        """
        for email_address in [
            None,
            "",
            "  ",
            "foo",
            "bar.dk",
            "foo@",
            "@bar.dk",
            "foo@bar",
            "foo@bar.ab12",
            "foo@.bar.ab",
            "foo.@bar.co",
            "foo@foo@bar.co",
            "fo o@bar.co",
        ]:
            with self.subTest(email_address=email_address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = email()
                dummy_field.data = email_address
                with raises(ValidationError) as e:
                    validator(dummy_form, dummy_field)
                assert str(e.value) == "Invalid email address."

    def test_invalid_email_raises_granular_message(self):
        """
        When granular_message=True uses message from email_validator library.
        """
        for email_address in ["foo@"]:
            with self.subTest(email_address=email_address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = email(granular_message=True)
                dummy_field.data = email_address
                with raises(ValidationError) as e:
                    validator(dummy_form, dummy_field)
                assert str(e.value) == "There must be something after the @-sign."
