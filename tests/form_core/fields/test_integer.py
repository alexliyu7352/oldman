# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_integer.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core.fields import IntegerField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = IntegerField()
    b = IntegerField(default=48)


class TestIntegerFields(UpstreamTestCase):
    fixture_functions = {}

    def test_integer_field(self):
        form = F(DummyPostData(a=["v"], b=["-15"]))
        assert form.a.data is None
        assert form.a.raw_data == ["v"]
        assert form.a() == '<input id="a" name="a" type="number" value="v">'
        assert form.b.data == -15
        assert form.b() == '<input id="b" name="b" type="number" value="-15">'
        assert not form.a.validate(form)
        assert form.b.validate(form)
        form = F(DummyPostData(a=[], b=[""]))
        assert form.a.data is None
        assert form.a.raw_data == []
        assert form.b.data is None
        assert form.b.raw_data == [""]
        assert not asyncio.run(form.validate())
        assert len(form.b.process_errors) == 1
        assert len(form.b.errors) == 1
        form = F(b=9)
        assert form.b.data == 9
        assert form.a._value() == ""
        assert form.b._value() == "9"
        form = F(DummyPostData(), initial={"b": "v"})
        assert form.b.data is None
        assert form.a._value() == ""
        assert form.b._value() == ""
        assert not asyncio.run(form.validate())
        assert len(form.b.process_errors) == 1
        assert len(form.b.errors) == 1
