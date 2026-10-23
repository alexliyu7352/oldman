# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_noneof.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import NoneOf
from tests.form_core.support import UpstreamTestCase, raises


class TestNoneofValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_none_of_passes(self):
        """
        it should pass if the value is not present in list
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        dummy_field.data = "d"
        validator = NoneOf(["a", "b", "c"])
        validator(dummy_form, dummy_field)

    def test_none_of_raises(self):
        """
        it should raise ValueError if the value is present in list
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        dummy_field.data = "a"
        validator = NoneOf(["a", "b", "c"])
        with raises(ValueError):
            validator(dummy_form, dummy_field)

    def test_none_of_multiple_values(self):
        """
        the validator should work with multiple values like produced
        by SelectMultiple fields
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        dummy_field.data = ["d", "e"]
        validator = NoneOf(["a", "b", "c"])
        validator(dummy_form, dummy_field)
        dummy_field.data = ["a", "e"]
        validator = NoneOf(["a", "b", "c"])
        with raises(ValueError):
            validator(dummy_form, dummy_field)
