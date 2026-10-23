# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_date.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from datetime import date

from oldman.web.components.forms._core.fields import DateField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = DateField()
    b = DateField(format="%m/%d %Y")
    c = DateField(format="%-m/%-d %Y")


class TestDateFields(UpstreamTestCase):
    fixture_functions = {}

    def test_basic(self):
        d = date(2008, 5, 7)
        form = F(DummyPostData(a=["2008-05-07"], b=["05/07", "2008"], c=["5/7 2008"]))
        assert form.a.data == d
        assert form.a._value() == "2008-05-07"
        assert form.b.data == d
        assert form.b._value() == "05/07 2008"
        assert form.c.data == d
        assert form.c._value() == "5/7 2008"

    def test_failure(self):
        form = F(DummyPostData(a=["2008-bb-cc"], b=["hi"]))
        assert not form.validate()
        assert len(form.a.process_errors) == 1
        assert len(form.a.errors) == 1
        assert len(form.b.errors) == 1
        assert form.a.process_errors[0] == "Not a valid date value."
