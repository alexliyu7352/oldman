# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_defaults.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import StringField
from oldman.web.components.forms._core.form import Form
from oldman.web.components.forms._core.utils import unset_value
from tests.form_core.support import UpstreamTestCase


class TestDefaultsFields(UpstreamTestCase):
    fixture_functions = {}

    def test_defaults(self):
        expected = 42

        def default_callable():
            return expected

        test_value = StringField(default=expected).bind(Form(), "a")
        test_value.process(None)
        assert test_value.data == expected
        test_callable = StringField(default=default_callable).bind(Form(), "a")
        test_callable.process(None)
        assert test_callable.data == expected

    def test_unset_value(self):
        assert str(unset_value) == "<unset value>"
        assert repr(unset_value) == "<unset value>"
        assert bool(unset_value) is False
        assert not unset_value
        assert unset_value.__nonzero__() is False
        assert unset_value.__bool__() is False
