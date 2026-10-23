# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_time.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from datetime import datetime

from oldman.web.components.forms._core.fields import TimeField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = TimeField()
    b = TimeField(format="%H:%M")


class TestTimeFields(UpstreamTestCase):
    fixture_functions = {}

    def test_basic(self):
        d = datetime(2008, 5, 5, 4, 30, 0, 0).time()
        form = F(DummyPostData(a=["4:30"], b=["04:30"]))
        assert form.a.data == d
        assert form.a() == '<input id="a" name="a" type="time" value="4:30">'
        assert form.b.data == d
        assert form.b() == '<input id="b" name="b" type="time" value="04:30">'
        assert form.validate()
        form = F(DummyPostData(a=["04"]))
        assert not form.validate()
        assert form.a.errors[0] == "Not a valid time value."
