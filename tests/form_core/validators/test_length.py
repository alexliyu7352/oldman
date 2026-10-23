# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_length.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import ValidationError, length
from tests.form_core.support import UpstreamTestCase, raises


class TestLengthValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_correct_length_passes(self):
        """
        It should pass for the string with correct length
        """
        for min_v, max_v in [(2, 6), (6, -1), (-1, 6), (6, 6)]:
            with self.subTest(min_v=min_v, max_v=max_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = "foobar"
                validator = length(min_v, max_v)
                validator(dummy_form, dummy_field)

    def test_bad_length_raises(self):
        """
        It should raise ValidationError for string with incorrect length
        """
        for min_v, max_v in [(7, -1), (-1, 5)]:
            with self.subTest(min_v=min_v, max_v=max_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = "foobar"
                validator = length(min_v, max_v)
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)

    def test_bad_length_init_raises(self):
        """
        It should raise AssertionError if the validator constructor got wrong values
        """
        for min_v, max_v in [(-1, -1), (5, 2)]:
            with self.subTest(min_v=min_v, max_v=max_v):
                with raises(AssertionError):
                    length(min_v, max_v)

    def test_length_messages(self):
        """
        It should raise ValidationError for string with incorrect length
        """
        for validator, message in (
            (length(2, 5, "%(min)d and %(max)d"), "2 and 5"),
            (length(8, -1), "at least 8"),
            (length(-1, 5), "longer than 5"),
            (length(2, 5), "between 2 and 5"),
            (length(5, 5), "exactly 5"),
        ):
            with self.subTest(validator=validator, message=message):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = "foobar"
                with raises(ValidationError) as e:
                    validator(dummy_form, dummy_field)
                assert message in str(e.value)
