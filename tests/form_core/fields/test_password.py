# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_password.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import widgets
from oldman.web.components.forms._core.fields import PasswordField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class F(Form):
    a = PasswordField(widget=widgets.PasswordInput(hide_value=False), default="LE DEFAULT")
    b = PasswordField(default="Hai")


class TestPasswordFields(UpstreamTestCase):
    fixture_functions = {}

    def test_password_field(self):
        form = F()
        assert form.a() == '<input id="a" name="a" type="password" value="LE DEFAULT">'
        assert form.b() == '<input id="b" name="b" type="password" value="">'
