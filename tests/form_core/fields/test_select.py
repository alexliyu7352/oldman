# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_select.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core import validators, widgets
from oldman.web.components.forms._core.fields import SelectField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


def make_form(name="F", **fields):
    return type(str(name), (Form,), fields)


class F(Form):
    a = SelectField(choices=[("a", "hello"), ("btest", "bye")], default="a")
    b = SelectField(choices=[(1, "Item 1"), (2, "Item 2")], coerce=int, option_widget=widgets.TextInput())


class TestSelectFields(UpstreamTestCase):
    fixture_functions = {}

    def test_select_field_copies_choices(self):

        class F(Form):
            items = SelectField(choices=[])

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            def add_choice(self, choice):
                self.items.choices.append((choice, choice))

        f1 = F()
        f2 = F()
        f1.add_choice("a")
        f2.add_choice("b")
        assert f1.items.choices == [("a", "a")]
        assert f2.items.choices == [("b", "b")]
        assert f1.items.choices is not f2.items.choices

    def test_defaults(self):
        form = F()
        assert form.a.data == "a"
        assert form.b.data is None
        assert asyncio.run(form.validate()) is False
        assert form.a() == '<select id="a" name="a"><option selected value="a">hello</option><option value="btest">bye</option></select>'
        assert form.b() == '<select id="b" name="b"><option value="1">Item 1</option><option value="2">Item 2</option></select>'

    def test_with_data(self):
        form = F(DummyPostData(a=["btest"]))
        assert form.a.data == "btest"
        assert form.a() == '<select id="a" name="a"><option value="a">hello</option><option selected value="btest">bye</option></select>'

    def test_value_coercion(self):
        form = F(DummyPostData(b=["2"]))
        assert form.b.data == 2
        assert form.b.validate(form)
        form = F(DummyPostData(b=["b"]))
        assert form.b.data is None
        assert not form.b.validate(form)

    def test_iterable_options(self):
        form = F()
        first_option = list(form.a)[0]
        assert isinstance(first_option, form.a._Option)
        assert [str(x) for x in form.a] == ['<option selected value="a">hello</option>', '<option value="btest">bye</option>']
        assert isinstance(first_option.widget, widgets.Option)
        assert isinstance(list(form.b)[0].widget, widgets.TextInput)
        assert first_option(disabled=True) == '<option disabled selected value="a">hello</option>'

    def test_default_coerce(self):
        F = make_form(a=SelectField(choices=[("a", "Foo")]))
        form = F(DummyPostData(a=[]))
        assert not asyncio.run(form.validate())
        assert form.a.data is None
        assert len(form.a.errors) == 1
        assert form.a.errors[0] == "Not a valid choice."

    def test_validate_choices(self):
        F = make_form(a=SelectField(choices=[("a", "Foo")]))
        form = F(DummyPostData(a=["b"]))
        assert not asyncio.run(form.validate())
        assert form.a.data == "b"
        assert len(form.a.errors) == 1
        assert form.a.errors[0] == "Not a valid choice."

    def test_validate_choices_when_empty(self):
        F = make_form(a=SelectField(choices=[]))
        form = F(DummyPostData(a=["b"]))
        assert not asyncio.run(form.validate())
        assert form.a.data == "b"
        assert len(form.a.errors) == 1
        assert form.a.errors[0] == "Not a valid choice."

    def test_validate_choices_when_none(self):
        F = make_form(a=SelectField())
        form = F(DummyPostData(a="b"))
        with raises(TypeError, match="Choices cannot be None"):
            asyncio.run(form.validate())

    def test_dont_validate_choices(self):
        F = make_form(a=SelectField(choices=[("a", "Foo")], validate_choice=False))
        form = F(DummyPostData(a=["b"]))
        assert asyncio.run(form.validate())
        assert form.a.data == "b"
        assert len(form.a.errors) == 0

    def test_choices_can_be_none_when_choice_validation_is_disabled(self):
        F = make_form(a=SelectField(validate_choice=False))
        form = F(DummyPostData(a="b"))
        assert asyncio.run(form.validate())

    def test_choice_shortcut(self):
        F = make_form(a=SelectField(choices=["foo", "bar"], validate_choice=False))
        form = F(a="bar")
        assert '<option value="foo">foo</option>' in form.a()

    def test_choice_shortcut_post(self):
        F = make_form(a=SelectField(choices=["foo", "bar"]))
        form = F(DummyPostData(a=["foo"]))
        assert asyncio.run(form.validate())
        assert form.a.data == "foo"
        assert len(form.a.errors) == 0

    def test_empty_choice(self):
        for choices in [[], None, {}]:
            with self.subTest(choices=choices):
                F = make_form(a=SelectField(choices=choices, validate_choice=False))
                form = F(a="bar")
                assert form.a() == '<select id="a" name="a"></select>'

    def test_callable_choices(self):

        def choices():
            return ["foo", "bar"]

        F = make_form(a=SelectField(choices=choices))
        form = F(a="bar")
        assert [str(x) for x in form.a] == ['<option value="foo">foo</option>', '<option selected value="bar">bar</option>']

    def test_requried_flag(self):
        F = make_form(c=SelectField(choices=[("a", "hello"), ("b", "bye")], validators=[validators.InputRequired()]))
        form = F(DummyPostData(c="a"))
        assert form.c() == '<select id="c" name="c" required><option selected value="a">hello</option><option value="b">bye</option></select>'

    def test_required_validator(self):
        F = make_form(c=SelectField(choices=[("a", "hello"), ("b", "bye")], validators=[validators.InputRequired()]))
        form = F(DummyPostData(c="b"))
        assert asyncio.run(form.validate())
        assert form.c.errors == []
        # Oldman: an unbound form only reports False; the required error needs a submission without the field.
        form = F(DummyPostData())
        assert asyncio.run(form.validate()) is False
        assert form.c.errors == ["This field is required."]

    def test_render_kw_preserved(self):
        F = make_form(a=SelectField(choices=["foo", "bar"], render_kw={"disabled": True}))
        form = F()
        assert form.a() == '<select disabled id="a" name="a"><option value="foo">foo</option><option value="bar">bar</option></select>'

    def test_optgroup(self):
        F = make_form(a=SelectField(choices={"hello": [("a", "Foo")]}))
        form = F(a="a")
        assert '<optgroup label="hello"><option selected value="a">Foo</option></optgroup>' in form.a()
        assert list(form.a.iter_choices()) == [("a", "Foo", True, {})]

    def test_optgroup_shortcut(self):
        F = make_form(a=SelectField(choices={"hello": ["foo", "bar"]}))
        form = F(a="bar")
        assert '<optgroup label="hello"><option value="foo">foo</option><option selected value="bar">bar</option></optgroup>' in form.a()
        assert list(form.a.iter_choices()) == [("foo", "foo", False, {}), ("bar", "bar", True, {})]

    def test_empty_optgroup(self):
        for choices in [[], ()]:
            with self.subTest(choices=choices):
                F = make_form(a=SelectField(choices={"hello": choices}))
                form = F(a="bar")
                assert '<optgroup label="hello"></optgroup>' in form.a()
                assert list(form.a.iter_choices()) == []

    def test_option_render_kw(self):
        F = make_form(a=SelectField(choices=[("a", "Foo", {"title": "foobar", "data-foo": "bar"})]))
        form = F(a="a")
        assert '<option data-foo="bar" selected title="foobar" value="a">Foo</option>' in form.a()
        assert list(form.a.iter_choices()) == [("a", "Foo", True, {"title": "foobar", "data-foo": "bar"})]

    def test_optgroup_option_render_kw(self):
        F = make_form(a=SelectField(choices={"hello": [("a", "Foo", {"title": "foobar", "data-foo": "bar"})]}))
        form = F(a="a")
        assert '<optgroup label="hello"><option data-foo="bar" selected title="foobar" value="a">Foo</option></optgroup>' in form.a()
        assert list(form.a.iter_choices()) == [("a", "Foo", True, {"title": "foobar", "data-foo": "bar"})]
