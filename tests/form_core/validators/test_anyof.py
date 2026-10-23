# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_anyof.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import AnyOf, ValidationError
from tests.form_core.support import UpstreamTestCase, raises


class TestAnyofValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_anyof_passes(self):
        """
        it should pass if the test_v is present in the test_list
        """
        for test_v, test_list in [("b", ["a", "b", "c"]), (2, [1, 2, 3])]:
            with self.subTest(test_v=test_v, test_list=test_list):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = AnyOf(test_list)
                dummy_field.data = test_v
                validator(dummy_form, dummy_field)

    def test_anyof_raisses(self):
        """
        it should raise ValueError if the test_v is not present in the test_list
        """
        for test_v, test_list in [("d", ["a", "b", "c"]), (6, [1, 2, 3])]:
            with self.subTest(test_v=test_v, test_list=test_list):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = AnyOf(test_list)
                dummy_field.data = test_v
                with raises(ValueError):
                    validator(dummy_form, dummy_field)

    def test_any_of_values_formatter(self):
        """
        Test AnyOf values_formatter formating of error message
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")

        def formatter(values):
            return "::".join(str(x) for x in reversed(values))

        validator = AnyOf([7, 8, 9], message="test %(values)s", values_formatter=formatter)
        dummy_field.data = 4
        with raises(ValidationError) as e:
            validator(dummy_form, dummy_field)
        assert str(e.value) == "test 9::8::7"

    def test_none_multiple_values(self):
        """
        the validator should work with multiple values like produced
        by SelectMultiple fields
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        dummy_field.data = ["a", "e"]
        validator = AnyOf(["a", "b", "c"])
        validator(dummy_form, dummy_field)
        dummy_field.data = ["d", "e"]
        validator = AnyOf(["a", "b", "c"])
        with raises(ValueError):
            validator(dummy_form, dummy_field)
