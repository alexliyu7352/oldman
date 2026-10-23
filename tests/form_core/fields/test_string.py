# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_string.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import StringField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = StringField()


class TestStringFields(UpstreamTestCase):
    fixture_functions = {}

    def test_string_field(self):
        form = F()
        assert form.a.data is None
        assert form.a() == '<input id="a" name="a" type="text" value="">'
        form = F(DummyPostData(a=["hello"]))
        assert form.a.data == "hello"
        assert form.a() == '<input id="a" name="a" type="text" value="hello">'
        form = F(DummyPostData(b=["hello"]))
        assert form.a.data is None
