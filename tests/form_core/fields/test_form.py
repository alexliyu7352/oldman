# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_form.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio
from typing import Any

from oldman.web.components.forms._core import validators
from oldman.web.components.forms._core.fields import FormField, StringField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


class AttrDict:
    def __init__(self, *args, **kw):
        self.__dict__.update(*args, **kw)

    def __getattr__(self, name: str) -> Any:
        # Only reached for a missing attribute, which still raises; it tells type checkers any is allowed.
        raise AttributeError(name)


class ClassWithProperty(AttrDict):
    @property
    def a(self):
        return AttrDict(self.a_) if getattr(self, "a_", None) else AttrDict()

    @a.setter
    def a(self, value):
        self.a_ = vars(value)


def make_form(name="F", **fields) -> Any:
    return type(str(name), (Form,), fields)


def F1():
    F = make_form(a=StringField(validators=[validators.DataRequired()]), b=StringField())
    return make_form("F1", a=FormField(F))


def F2():
    F = make_form(a=StringField(validators=[validators.DataRequired()]), b=StringField())
    return make_form("F2", a=FormField(F, separator="::"))


class TestFormFields(UpstreamTestCase):
    fixture_functions = {"F1": F1, "F2": F2}

    def test_formdata(self):
        (F1,) = self.fixtures("F1")
        form = F1(DummyPostData({"a-a": ["moo"]}))
        assert form.a.form.a.name == "a-a"
        assert form.a["a"].data == "moo"
        assert form.a["b"].data is None
        assert asyncio.run(form.validate())

    def test_iteration(self):
        (F1,) = self.fixtures("F1")
        assert [x.name for x in F1().a] == ["a-a", "a-b"]

    def test_with_obj(self):
        (F1,) = self.fixtures("F1")
        obj = AttrDict(a=AttrDict(a="mmm"))
        form = F1(obj=obj)
        assert form.a.form.a.data == "mmm"
        assert form.a.form.b.data is None
        obj_inner = AttrDict(a=None, b="rawr")
        obj2 = AttrDict(a=obj_inner)
        # Oldman: populate_obj writes cleaned_data, so the nested values are submitted and validated first.
        form = F1(DummyPostData({"a-a": "mmm"}))
        assert asyncio.run(form.validate())
        form.populate_obj(obj2)
        assert obj2.a is obj_inner
        assert obj_inner.a == "mmm"
        assert obj_inner.b is None

    def test_widget(self):
        (F1,) = self.fixtures("F1")
        assert (
            F1().a()
            == '<table id="a"><tr><th><label for="a-a">A</label></th><td><input id="a-a" name="a-a" required type="text" value=""></td></tr><tr><th><label for="a-b">B</label></th><td><input id="a-b" name="a-b" type="text" value=""></td></tr></table>'
        )

    def test_separator(self):
        (F2,) = self.fixtures("F2")
        form = F2(DummyPostData({"a-a": "fake", "a::a": "real"}))
        assert form.a.a.name == "a::a"
        assert form.a.a.data == "real"
        assert asyncio.run(form.validate())

    def test_no_validators_or_filters(self):
        (F1,) = self.fixtures("F1")

        class A(Form):
            a = FormField(F1, validators=[validators.DataRequired()])

        with raises(TypeError):
            A()

        class B(Form):
            a = FormField(F1, filters=[str])

        with raises(TypeError):
            B()

        class C(Form):
            a = FormField(F1)

            def validate_a(self, field):
                pass

        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = C(DummyPostData())
        with raises(TypeError):
            asyncio.run(form.validate())

    def test_populate_missing_obj(self):
        (F1,) = self.fixtures("F1")
        obj = AttrDict(a=None)
        obj2 = AttrDict(a=AttrDict(a="mmm"))
        # Oldman: populate_obj writes cleaned_data, so the form is submitted and validated first.
        form = F1(DummyPostData({"a-a": "x"}))
        assert asyncio.run(form.validate())
        with raises(TypeError):
            form.populate_obj(obj)
        form.populate_obj(obj2)

    def test_populate_property(self):
        (F1,) = self.fixtures("F1")
        obj1 = ClassWithProperty(a_={"a": "old_a", "b": "old_b"})
        form = F1(DummyPostData({"a-a": "new_a", "a-b": "new_b"}))
        # Oldman: populate_obj writes cleaned_data, so the form is validated first.
        assert asyncio.run(form.validate())
        form.populate_obj(obj1)
        assert obj1.a_ == {"a": "new_a", "b": "new_b"}
        obj2 = ClassWithProperty()
        form.populate_obj(obj2)
        assert obj1.a_ == {"a": "new_a", "b": "new_b"}
