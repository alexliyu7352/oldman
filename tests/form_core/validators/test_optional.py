# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_optional.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import StopValidation, optional
from tests.form_core.support import UpstreamTestCase, raises


class TestOptionalValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_input_optional_passes(self):
        """
        optional should pause with given values
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = optional()
        dummy_field.data = "foobar"
        dummy_field.raw_data = ["foobar"]
        validator(dummy_form, dummy_field)

    def test_input_optional_raises(self):
        """
        optional should stop the validation chain if the data are not given
        errors should be erased because the value is optional
        white space should be considered as empty string too
        """
        for data_v, raw_data_v in [("", ""), ("   ", "   "), ("\t", "\t")]:
            with self.subTest(data_v=data_v, raw_data_v=raw_data_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = optional()
                dummy_field.data = data_v
                dummy_field.raw_data = raw_data_v
                with raises(StopValidation):
                    validator(dummy_form, dummy_field)
                assert validator.field_flags == {"optional": True}
                dummy_field.errors = ["Invalid Integer Value"]
                assert len(dummy_field.errors) == 1
                with raises(StopValidation):
                    validator(dummy_form, dummy_field)
                assert len(dummy_field.errors) == 0
