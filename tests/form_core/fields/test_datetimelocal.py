# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_datetimelocal.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import os
from datetime import datetime

from oldman.web.components.forms._core.fields import DateTimeLocalField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


def make_form(name="F", **fields):
    return type(str(name), (Form,), fields)


class F(Form):
    a = DateTimeLocalField()
    b = DateTimeLocalField(format="%Y-%m-%d %H:%M")
    c = DateTimeLocalField(format="%#m/%#d/%Y %#I:%M" if os.name == "nt" else "%-m/%-d/%Y %-I:%M")


class TestDatetimelocalFields(UpstreamTestCase):
    fixture_functions = {}

    def test_basic(self):
        d = datetime(2008, 5, 5, 4, 30, 0, 0)
        form = F(DummyPostData(a=["2008-05-05", "04:30:00"], b=["2008-05-05 04:30"], c=["5/5/2008 4:30"]))
        assert form.a.data == d
        assert form.a() == '<input id="a" name="a" type="datetime-local" value="2008-05-05 04:30:00">'
        assert form.b.data == d
        assert form.b() == '<input id="b" name="b" type="datetime-local" value="2008-05-05 04:30">'
        assert form.c.data == d
        assert form.c() == '<input id="c" name="c" type="datetime-local" value="5/5/2008 4:30">'
        assert form.validate()
        form = F(DummyPostData(a=["2008-05-05"]))
        assert not form.validate()
        assert form.a.errors[0] == "Not a valid datetime value."
        form = F(a=d, b=d, c=d)
        assert form.validate()
        assert form.a._value() == "2008-05-05 04:30:00"
        assert form.b._value() == "2008-05-05 04:30"
        assert form.c._value() == "5/5/2008 4:30"

    def test_microseconds(self):
        d = datetime(2011, 5, 7, 3, 23, 14, 424200)
        F = make_form(a=DateTimeLocalField(format="%Y-%m-%d %H:%M:%S.%f"))
        form = F(DummyPostData(a=["2011-05-07 03:23:14.4242"]))
        assert d == form.a.data

    def test_separators(self):
        dt = datetime(2008, 5, 5, 4, 30, 0, 0)
        form = F(DummyPostData(a=["2008-05-05 04:30:00"]))
        assert form.a.data == dt
        assert form.validate()
        form = F(DummyPostData(a=["2008-05-05T04:30:00"]))
        assert form.a.data == dt
        assert form.validate()
