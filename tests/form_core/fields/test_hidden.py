# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_hidden.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import HiddenField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class F(Form):
    a = HiddenField(default="LE DEFAULT")


class TestHiddenFields(UpstreamTestCase):
    fixture_functions = {}

    def test_hidden_field(self):
        form = F()
        assert form.a() == '<input id="a" name="a" type="hidden" value="LE DEFAULT">'
        assert form.a.flags.hidden
