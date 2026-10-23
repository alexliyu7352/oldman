# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_number_range.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import decimal

from oldman.web.components.forms._core.validators import NumberRange, ValidationError
from tests.form_core.support import UpstreamTestCase, raises


class TestNumberRangeValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_number_range_passes(self):
        """
        It should pass if the test_v is between min_v and max_v
        """
        for min_v, max_v, test_v in [(5, 10, 7), (5, None, 7), (None, 100, 70)]:
            with self.subTest(min_v=min_v, max_v=max_v, test_v=test_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = test_v
                validator = NumberRange(min_v, max_v)
                validator(dummy_form, dummy_field)

    def test_number_range_raises(self):
        """
        It should raise ValidationError if the test_v is not between min_v and max_v
        """
        for min_v, max_v, test_v in [(5, 10, None), (5, 10, 0), (5, 10, 12), (5, 10, -5), (5, None, 4), (None, 100, 500)]:
            with self.subTest(min_v=min_v, max_v=max_v, test_v=test_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                dummy_field.data = test_v
                validator = NumberRange(min_v, max_v)
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)

    def test_number_range_nan(self):
        for nan in [float("NaN"), decimal.Decimal("NaN")]:
            with self.subTest(nan=nan):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = NumberRange(0, 10)
                dummy_field.data = nan
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)
