# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_decimal.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from decimal import ROUND_DOWN, ROUND_UP, Decimal

from oldman.web.components.forms._core.fields import DecimalField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


def make_form(name="F", **fields):
    return type(str(name), (Form,), fields)


class TestDecimalFields(UpstreamTestCase):
    fixture_functions = {}

    def test_decimal_field(self):
        F = make_form(a=DecimalField())
        form = F(DummyPostData(a="2.1"))
        assert form.a.data == Decimal("2.1")
        assert form.a._value() == "2.1"
        form.a.raw_data = None
        assert form.a._value() == "2.10"
        assert form.validate()
        form = F(DummyPostData(a="2,1"), a=Decimal(5))
        assert form.a.data is None
        assert form.a.raw_data == ["2,1"]
        assert not form.validate()
        form = F(DummyPostData(a="asdf"), a=Decimal(".21"))
        assert form.a._value() == "asdf"
        assert not form.validate()

    def test_quantize(self):
        F = make_form(a=DecimalField(places=3, rounding=ROUND_UP), b=DecimalField(places=None))
        form = F(a=Decimal("3.1415926535"))
        assert form.a._value() == "3.142"
        form.a.rounding = ROUND_DOWN
        assert form.a._value() == "3.141"
        assert form.b._value() == ""
        form = F(a=3.14159265, b=72)
        assert form.a._value() == "3.142"
        assert isinstance(form.a.data, float)
        assert form.b._value() == "72"
