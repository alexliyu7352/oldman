# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_regexp.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import re

from oldman.web.components.forms._core.validators import ValidationError, regexp
from tests.form_core.support import UpstreamTestCase, raises


def grab_error_message(callable, form, field):
    try:
        callable(form, field)
    except ValidationError as e:
        return e.args[0]


class TestRegexpValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_regex_passes(self):
        """
        Regex should pass if there is a match.
        Should work for complie regex too
        """
        for re_pattern, re_flags, test_v, expected_v in [
            ("^a", None, "abcd", "a"),
            ("^a", re.I, "ABcd", "A"),
            (re.compile("^a"), None, "abcd", "a"),
            (re.compile("^a", re.I), None, "ABcd", "A"),
        ]:
            with self.subTest(re_pattern=re_pattern, re_flags=re_flags, test_v=test_v, expected_v=expected_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = regexp(re_pattern, re_flags) if re_flags else regexp(re_pattern)
                dummy_field.data = test_v
                assert validator(dummy_form, dummy_field).group(0) == expected_v

    def test_regex_raises(self):
        """
        Regex should raise ValidationError if there is no match
        Should work for complie regex too
        """
        for re_pattern, re_flags, test_v in [
            ("^a", None, "ABC"),
            ("^a", re.I, "foo"),
            ("^a", None, None),
            (re.compile("^a"), None, "foo"),
            (re.compile("^a", re.I), None, None),
        ]:
            with self.subTest(re_pattern=re_pattern, re_flags=re_flags, test_v=test_v):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = regexp(re_pattern, re_flags) if re_flags else regexp(re_pattern)
                dummy_field.data = test_v
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)

    def test_regexp_message(self):
        """
        Regexp validator should return given message
        """
        dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
        validator = regexp("^a", message="foo")
        dummy_field.data = "f"
        assert grab_error_message(validator, dummy_form, dummy_field) == "foo"
