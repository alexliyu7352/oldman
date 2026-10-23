# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_textarea.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import TextAreaField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class F(Form):
    a = TextAreaField(default="LE DEFAULT")


class TestTextareaFields(UpstreamTestCase):
    fixture_functions = {}

    def test_textarea_field(self):
        form = F()
        assert form.a() == '<textarea id="a" name="a">\r\nLE DEFAULT</textarea>'
