# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_color.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import widgets
from oldman.web.components.forms._core.fields import ColorField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class F(Form):
    a = ColorField(widget=widgets.ColorInput(), default="#ff0000")
    b = ColorField(default="#00ff00")


class TestColorFields(UpstreamTestCase):
    fixture_functions = {}

    def test_color_field(self):
        form = F()
        assert form.a() == '<input id="a" name="a" type="color" value="#ff0000">'
        assert form.b() == '<input id="b" name="b" type="color" value="#00ff00">'
