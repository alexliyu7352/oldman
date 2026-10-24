# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_month.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio
from datetime import date

from oldman.web.components.forms._core.fields import MonthField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = MonthField()
    b = MonthField(format="%m/%Y")


class TestMonthFields(UpstreamTestCase):
    fixture_functions = {}

    def test_basic(self):
        d = date(2008, 5, 1)
        form = F(DummyPostData(a=["2008-05"], b=["05/2008"]))
        assert d == form.a.data
        assert "2008-05" == form.a._value()
        assert d == form.b.data

    def test_failure(self):
        form = F(DummyPostData(a=["2008-bb"]))
        assert not asyncio.run(form.validate())
        assert 1 == len(form.a.process_errors)
        assert 1 == len(form.a.errors)
        assert "Not a valid date value." == form.a.process_errors[0]
