# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_submit.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import SubmitField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class F(Form):
    a = SubmitField("Label")


class TestSubmitFields(UpstreamTestCase):
    fixture_functions = {}

    def test_submit_field(self):
        assert F().a() == '<input id="a" name="a" type="submit" value="Label">'
