# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_input_required.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import StopValidation, input_required
from tests.form_core.support import UpstreamTestCase, raises


class TestInputRequiredValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_input_required(self):
        """
        it should pass if the required value is present
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = input_required()
        dummy_field.data = "foobar"
        dummy_field.raw_data = ["foobar"]
        validator(dummy_form, dummy_field)
        assert validator.field_flags == {"required": True}

    def test_input_required_raises(self):
        """
        It should stop the validation chain if the required value is not present
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = input_required()
        dummy_field.data = ""
        dummy_field.raw_data = [""]
        with raises(StopValidation):
            validator(dummy_form, dummy_field)

    def test_input_required_error_message(self):
        """
        It should return error message when the required value is not present
        """
        for validator, message in ((input_required(), "This field is required."), (input_required(message="foo"), "foo")):
            with self.subTest(validator=validator, message=message):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = ""
                dummy_field.raw_data = [""]
                with raises(StopValidation) as e:
                    validator(dummy_form, dummy_field)
                assert str(e.value) == message
