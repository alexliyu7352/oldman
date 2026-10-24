# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_flags.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from typing import cast

from oldman.web.components.forms._core import validators
from oldman.web.components.forms._core.fields import StringField
from oldman.web.components.forms._core.fields.core import UnboundField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase, raises


def flags():
    return cast(UnboundField, StringField(validators=[validators.DataRequired()])).bind(Form(), "a").flags


class TestFlagsFields(UpstreamTestCase):
    fixture_functions = {"flags": flags}

    def test_existing_values(self):
        (flags,) = self.fixtures("flags")
        assert flags.required is True
        assert "required" in flags
        assert flags.optional is None
        assert "optional" not in flags

    def test_assignment(self):
        (flags,) = self.fixtures("flags")
        assert "optional" not in flags
        flags.optional = True
        assert flags.optional is True
        assert "optional" in flags

    def test_unset(self):
        (flags,) = self.fixtures("flags")
        flags.required = False
        assert flags.required is False
        assert "required" not in flags

    def test_repr(self):
        (flags,) = self.fixtures("flags")
        # Oldman: the repr no longer names the wtforms package.
        assert repr(flags) == "<Flags: {required=True}>"

    def test_underscore_property(self):
        (flags,) = self.fixtures("flags")
        with raises(AttributeError):
            flags._foo  # noqa: B018 -- the access itself must raise
        flags._foo = 42
        assert flags._foo == 42
