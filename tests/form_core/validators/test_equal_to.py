# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_equal_to.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import Label
from oldman.web.components.forms._core.validators import ValidationError, equal_to
from tests.form_core.support import UpstreamTestCase, raises


class TestEqualToValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_equal_to_passes(self):
        """
        Equal values should pass
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        dummy_field.data = "test"
        dummy_form["foo"] = dummy_field
        validator = equal_to("foo")
        validator(dummy_form, dummy_form["foo"])

    def test_equal_to_raises(self):
        """
        It should raise ValidationError if the values are not equal
        """
        for field_val, equal_val in [("test", "invalid_field_name"), ("bad_value", "foo")]:
            with self.subTest(field_val=field_val, equal_val=equal_val):
                dummy_form, dummy_field, dummy_field_class = self.fixtures("dummy_form", "dummy_field", "dummy_field_class")
                dummy_form["foo"] = dummy_field_class("test", label=Label("foo", "foo"))
                dummy_field.data = field_val
                validator = equal_to(equal_val)
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)
