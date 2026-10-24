# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_radio.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio
from typing import Any

from oldman.web.components.forms._core import validators
from oldman.web.components.forms._core.fields import RadioField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


def make_form(name="F", **fields) -> Any:
    return type(str(name), (Form,), fields)


class F(Form):
    a = RadioField(choices=[("a", "hello"), ("b", "bye")], default="a")
    b = RadioField(choices=[(1, "Item 1"), (2, "Item 2")], coerce=int)
    c = RadioField(choices=[("a", "Item 1"), ("b", "Item 2")], validators=[validators.InputRequired()])


class TestRadioFields(UpstreamTestCase):
    fixture_functions = {}

    def test_radio_field(self):
        form = F()
        assert form.a.data == "a"
        assert form.b.data is None
        assert asyncio.run(form.validate()) is False
        assert (
            form.a()
            == '<ul id="a"><li><input checked id="a-0" name="a" type="radio" value="a"> <label for="a-0">hello</label></li><li><input id="a-1" name="a" type="radio" value="b"> <label for="a-1">bye</label></li></ul>'
        )
        assert (
            form.b()
            == '<ul id="b"><li><input id="b-0" name="b" type="radio" value="1"> <label for="b-0">Item 1</label></li><li><input id="b-1" name="b" type="radio" value="2"> <label for="b-1">Item 2</label></li></ul>'
        )
        assert [str(x) for x in form.a] == [
            '<input checked id="a-0" name="a" type="radio" value="a">',
            '<input id="a-1" name="a" type="radio" value="b">',
        ]

    def test_text_coercion(self):
        F = make_form(a=RadioField(choices=[(True, "yes"), (False, "no")], coerce=lambda x: False if x == "False" else bool(x)))
        form = F()
        assert (
            form.a()
            == '<ul id="a"><li><input id="a-0" name="a" type="radio" value="True"> <label for="a-0">yes</label></li><li><input id="a-1" name="a" type="radio" value="False"> <label for="a-1">no</label></li></ul>'
        )

    def test_callable_choices(self):

        def choices():
            return [("a", "hello"), ("b", "bye")]

        class F(Form):
            a = RadioField(choices=choices, default="a")

        form = F()
        assert form.a.data == "a"
        assert (
            form.a()
            == '<ul id="a"><li><input checked id="a-0" name="a" type="radio" value="a"> <label for="a-0">hello</label></li><li><input id="a-1" name="a" type="radio" value="b"> <label for="a-1">bye</label></li></ul>'
        )

    def test_required_flag(self):
        form = F()
        assert (
            form.c()
            == '<ul id="c"><li><input id="c-0" name="c" required type="radio" value="a"> <label for="c-0">Item 1</label></li><li><input id="c-1" name="c" required type="radio" value="b"> <label for="c-1">Item 2</label></li></ul>'
        )

    def test_required_validator(self):
        form = F(DummyPostData(b=1, c="a"))
        assert asyncio.run(form.validate())
        assert form.c.errors == []
        form = F(DummyPostData(b=1))
        assert asyncio.run(form.validate()) is False
        assert form.c.errors == ["This field is required."]

    def test_render_kw_preserved(self):
        F = make_form(a=RadioField(choices=[(True, "yes"), (False, "no")], render_kw={"disabled": True}))
        form = F()
        assert (
            form.a()
            == '<ul disabled id="a"><li><input disabled id="a-0" name="a" type="radio" value="True"> <label for="a-0">yes</label></li><li><input disabled id="a-1" name="a" type="radio" value="False"> <label for="a-1">no</label></li></ul>'
        )
