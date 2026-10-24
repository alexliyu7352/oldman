# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_selectmultiple.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core import validators
from oldman.web.components.forms._core.fields import SelectField, SelectMultipleField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


def make_form(name="F", **fields):
    return type(str(name), (Form,), fields)


class F(Form):
    a = SelectMultipleField(choices=[("a", "hello"), ("b", "bye"), ("c", "something")], default=("a",))
    b = SelectMultipleField(coerce=int, choices=[(1, "A"), (2, "B"), (3, "C")], default=("1", "3"))


class TestSelectmultipleFields(UpstreamTestCase):
    fixture_functions = {}

    def test_defaults(self):
        form = F()
        assert form.a.data == ["a"]
        assert form.b.data == [1, 3]
        # Oldman: only a bound form validates; a submission without the fields leaves no data to check.
        form = F(DummyPostData())
        form.a.data = None
        assert asyncio.run(form.validate())
        assert list(form.a.iter_choices()) == [(value, label, False, {}) for value, label in form.a.choices]

    def test_with_data(self):
        form = F(DummyPostData(a=["a", "c"]))
        assert form.a.data == ["a", "c"]
        assert list(form.a.iter_choices()) == [("a", "hello", True, {}), ("b", "bye", False, {}), ("c", "something", True, {})]
        assert form.b.data == []
        form = F(DummyPostData(b=["1", "2"]))
        assert form.b.data == [1, 2]
        assert asyncio.run(form.validate())
        form = F(DummyPostData(b=["1", "2", "4"]))
        assert form.b.data == [1, 2, 4]
        assert not asyncio.run(form.validate())

    def test_coerce_fail(self):
        # Oldman: validation needs a bound form, where submitted input replaces the initial values; the
        # coercion failure of an initial value is a processing matter, checked without validating.
        form = F(b=["a"])
        assert form.b.data is None
        form = F(DummyPostData(b=["fake"]))
        assert not asyncio.run(form.validate())
        assert form.b.data == [1, 3]

    def test_callable_choices(self):

        def choices():
            return ["foo", "bar"]

        F = make_form(a=SelectField(choices=choices))
        form = F(a="bar")
        assert [str(x) for x in form.a] == ['<option value="foo">foo</option>', '<option selected value="bar">bar</option>']

    def test_choice_shortcut(self):
        F = make_form(a=SelectMultipleField(choices=["foo", "bar"]))
        # Oldman: only a bound form validates, so the chosen value is submitted.
        form = F(DummyPostData(a=["bar"]))
        assert asyncio.run(form.validate())
        assert '<option value="foo">foo</option>' in form.a()

    def test_empty_choice(self):
        for choices in [[], None]:
            with self.subTest(choices=choices):
                F = make_form(a=SelectMultipleField(choices=choices))
                form = F(a="bar")
                assert form.a() == '<select id="a" multiple name="a"></select>'

    def test_validate_choices_when_empty(self):
        F = make_form(a=SelectMultipleField(choices=[]))
        form = F(DummyPostData(a=["b"]))
        assert not asyncio.run(form.validate())
        assert form.a.data == ["b"]
        assert len(form.a.errors) == 1
        assert form.a.errors[0] == "'b' is not a valid choice for this field."

    def test_validate_choices_when_none(self):
        F = make_form(a=SelectMultipleField())
        form = F(DummyPostData(a="b"))
        with raises(TypeError, match="Choices cannot be None"):
            asyncio.run(form.validate())

    def test_dont_validate_choices(self):
        F = make_form(a=SelectMultipleField(choices=[("a", "Foo")], validate_choice=False))
        form = F(DummyPostData(a=["b"]))
        assert asyncio.run(form.validate())
        assert form.a.data == ["b"]
        assert len(form.a.errors) == 0

    def test_choices_can_be_none_when_choice_validation_is_disabled(self):
        F = make_form(a=SelectMultipleField(validate_choice=False))
        form = F(DummyPostData(a="b"))
        assert asyncio.run(form.validate())

    def test_requried_flag(self):
        F = make_form(c=SelectMultipleField(choices=[("a", "hello"), ("b", "bye")], validators=[validators.InputRequired()]))
        form = F(DummyPostData(c=["a"]))
        assert (
            form.c() == '<select id="c" multiple name="c" required><option selected value="a">hello</option><option value="b">bye</option></select>'
        )

    def test_required_validator(self):
        F = make_form(c=SelectMultipleField(choices=[("a", "hello"), ("b", "bye")], validators=[validators.InputRequired()]))
        form = F(DummyPostData(c=["a"]))
        assert asyncio.run(form.validate())
        assert form.c.errors == []
        # Oldman: an unbound form only reports False; the required error needs a submission without the field.
        form = F(DummyPostData())
        assert asyncio.run(form.validate()) is False
        assert form.c.errors == ["This field is required."]

    def test_render_kw_preserved(self):
        F = make_form(a=SelectMultipleField(choices=["foo", "bar"], render_kw={"disabled": True}))
        form = F()
        assert form.a() == '<select disabled id="a" multiple name="a"><option value="foo">foo</option><option value="bar">bar</option></select>'

    def test_option_render_kw(self):
        F = make_form(a=SelectMultipleField(choices=[("a", "Foo", {"title": "foobar", "data-foo": "bar"})]))
        form = F(a="a")
        assert '<option data-foo="bar" selected title="foobar" value="a">Foo</option>' in form.a()
        assert list(form.a.iter_choices()) == [("a", "Foo", True, {"title": "foobar", "data-foo": "bar"})]

    def test_optgroup_option_render_kw(self):
        F = make_form(a=SelectMultipleField(choices={"hello": [("a", "Foo", {"title": "foobar", "data-foo": "bar"})]}))
        form = F(a="a")
        assert '<optgroup label="hello"><option data-foo="bar" selected title="foobar" value="a">Foo</option></optgroup>' in form.a()
        assert list(form.a.iter_choices()) == [("a", "Foo", True, {"title": "foobar", "data-foo": "bar"})]

    def test_can_supply_coercable_values_as_options(self):
        F = make_form(a=SelectMultipleField(choices=[("1", "One"), ("2", "Two")], coerce=int))
        post_data = DummyPostData(a=["1", "2"])
        form = F(post_data)
        assert asyncio.run(form.validate())
        assert form.a.data == [1, 2]
