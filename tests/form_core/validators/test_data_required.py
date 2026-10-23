# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_data_required.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import StopValidation, data_required
from tests.form_core.support import UpstreamTestCase, raises


class TestDataRequiredValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_data_required(self):
        """
        Should pass if the required data are present
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = data_required()
        dummy_field.data = "foobar"
        validator(dummy_form, dummy_field)
        assert validator.field_flags == {"required": True}

    def test_data_required_raises(self):
        """
        data_required should stop the validation chain if data are not present
        """
        for bad_val in [None, "", " ", "\t\t"]:
            with self.subTest(bad_val=bad_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = data_required()
                dummy_field.data = bad_val
                with raises(StopValidation):
                    validator(dummy_form, dummy_field)

    def test_data_required_clobber(self):
        """
        Data required should clobber the errors
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = data_required()
        dummy_field.data = ""
        dummy_field.errors = ["Invalid Integer Value"]
        assert len(dummy_field.errors) == 1
        with raises(StopValidation):
            validator(dummy_form, dummy_field)
        assert len(dummy_field.errors) == 0

    def test_data_required_messages(self):
        """
        Check data_required message and custom message
        """
        for validator, message in ((data_required(), "This field is required."), (data_required(message="foo"), "foo")):
            with self.subTest(validator=validator, message=message):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = ""
                with raises(StopValidation) as e:
                    validator(dummy_form, dummy_field)
                assert str(e.value) == message

    def test_required_passes(self):
        """
        It should pass when required value is present
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = data_required()
        dummy_field.data = "foobar"
        validator(dummy_form, dummy_field)

    def test_required_stops_validation(self):
        """
        It should raise stop the validation chain if required value is not present
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = data_required()
        dummy_field.data = ""
        with raises(StopValidation):
            validator(dummy_form, dummy_field)
