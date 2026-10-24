# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_list.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio
from collections import namedtuple

from oldman.web.components.forms._core import validators
from oldman.web.components.forms._core.fields import FieldList, FormField, StringField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


class AttrDict:
    def __init__(self, *args, **kw):
        self.__dict__.update(*args, **kw)


def make_form(name="F", **fields):
    return type(str(name), (Form,), fields)


t = StringField(validators=[validators.DataRequired()])


class TestListFields(UpstreamTestCase):
    fixture_functions = {}

    def test_form(self):
        F = make_form(a=FieldList(t))
        data = ["foo", "hi", "rawr"]
        a = F(a=data).a
        assert a.entries[1].data == "hi"
        assert a.entries[1].name == "a-1"
        assert a.data == data
        assert len(a.entries) == 3
        pdata = DummyPostData({"a-0": ["bleh"], "a-3": ["yarg"], "a-4": [""], "a-7": ["mmm"]})
        form = F(pdata)
        assert len(form.a.entries) == 4
        assert form.a.data == ["bleh", "yarg", "", "mmm"]
        assert not asyncio.run(form.validate())
        form = F(pdata, a=data)
        assert form.a.data == ["bleh", "yarg", "", "mmm"]
        assert not asyncio.run(form.validate())
        pdata = DummyPostData({"a-0": ["a"], "a-1": ["b"]})
        form = F(pdata, a=data)
        assert len(form.a.entries) == 2
        assert form.a.data == ["a", "b"]
        assert list(iter(form.a)) == list(form.a.entries)

    def test_enclosed_subform(self):

        def make_inner():
            return AttrDict(a=None)

        F = make_form(a=FieldList(FormField(make_form("FChild", a=t), default=make_inner)))
        data = [{"a": "hello"}]
        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = F(DummyPostData(), a=data)
        assert form.a.data == data
        assert asyncio.run(form.validate())
        form.a.append_entry()
        assert form.a.data == data + [{"a": None}]
        assert not asyncio.run(form.validate())
        pdata = DummyPostData({"a-0": ["fake"], "a-0-a": ["foo"], "a-1-a": ["bar"]})
        form = F(pdata, a=data)
        assert form.a.data == [{"a": "foo"}, {"a": "bar"}]
        inner_obj = make_inner()
        inner_list = [inner_obj]
        obj = AttrDict(a=inner_list)
        # Oldman: populate_obj writes cleaned_data, so the form is validated first.
        assert asyncio.run(form.validate())
        form.populate_obj(obj)
        assert obj.a is not inner_list
        assert len(obj.a) == 2
        assert obj.a[0] is inner_obj
        assert obj.a[0].a == "foo"
        assert obj.a[1].a == "bar"
        obj2 = AttrDict(a=42)
        with raises(TypeError):
            form.populate_obj(obj2)

    def test_enclosed_subform_custom_name(self):

        class Inside(Form):
            foo = StringField(name="bar", default="default")

        class Outside(Form):
            subforms = FieldList(FormField(Inside), min_entries=1)

        o = Outside()
        assert o.subforms[0].foo.data == "default"
        pdata = DummyPostData({"subforms-0-bar": "form"})
        o = Outside(pdata)
        assert o.subforms[0].foo.data == "form"
        pdata = DummyPostData({"subforms-0-foo": "form"})
        o = Outside(pdata)
        assert o.subforms[0].foo.data == "default"

    def test_custom_separator(self):
        F = make_form(a=FieldList(t, separator="_"))
        pdata = DummyPostData({"a_0": "0_a", "a_1": "1_a"})
        f = F(pdata)
        assert f.a[0].data == "0_a"
        assert f.a[1].data == "1_a"

    def test_enclosed_subform_list_separator(self):

        class Inside(Form):
            foo = StringField(default="default")

        class Outside(Form):
            subforms = FieldList(FormField(Inside), min_entries=1, separator="_")

        o = Outside()
        assert o.subforms[0].foo.data == "default"
        assert o.subforms[0].foo.name == "subforms_0-foo"
        pdata = DummyPostData({"subforms_0-foo": "0-foo", "subforms_1-foo": "1-foo"})
        o = Outside(pdata)
        assert o.subforms[0].foo.data == "0-foo"
        assert o.subforms[1].foo.data == "1-foo"

    def test_enclosed_subform_uniform_separators(self):

        class Inside(Form):
            foo = StringField(default="default")

        class Outside(Form):
            subforms = FieldList(FormField(Inside, separator="_"), min_entries=1, separator="_")

        o = Outside()
        assert o.subforms[0].foo.data == "default"
        assert o.subforms[0].foo.name == "subforms_0_foo"
        pdata = DummyPostData({"subforms_0_foo": "0_foo", "subforms_1_foo": "1_foo"})
        o = Outside(pdata)
        assert o.subforms[0].foo.data == "0_foo"
        assert o.subforms[1].foo.data == "1_foo"

    def test_enclosed_subform_mixed_separators(self):

        class Inside(Form):
            foo = StringField(default="default")

        class Outside(Form):
            subforms = FieldList(FormField(Inside, separator="_"), min_entries=1)

        o = Outside()
        assert o.subforms[0].foo.data == "default"
        assert o.subforms[0].foo.name == "subforms-0_foo"
        pdata = DummyPostData({"subforms-0_foo": "0_foo", "subforms-1_foo": "1_foo"})
        o = Outside(pdata)
        assert o.subforms[0].foo.data == "0_foo"
        assert o.subforms[1].foo.data == "1_foo"

    def test_entry_management(self):
        F = make_form(a=FieldList(t))
        a = F(a=["hello", "bye"]).a
        assert a.pop_entry().name == "a-1"
        assert a.data == ["hello"]
        a.append_entry("orange")
        assert a.data == ["hello", "orange"]
        assert a[-1].name == "a-1"
        assert a.pop_entry().data == "orange"
        assert a.pop_entry().name == "a-0"
        with raises(IndexError):
            a.pop_entry()

    def test_min_max_entries(self):
        F = make_form(a=FieldList(t, min_entries=1, max_entries=3))
        a = F().a
        assert len(a) == 1
        assert a[0].data is None
        big_input = ["foo", "flaf", "bar", "baz"]
        with raises(AssertionError):
            F(a=big_input)
        pdata = DummyPostData(((f"a-{i}", v) for i, v in enumerate(big_input)))
        a = F(pdata).a
        assert a.data == ["foo", "flaf", "bar"]
        with raises(AssertionError):
            a.append_entry()

    def test_validators(self):

        def validator(form, field):
            if field.data and field.data[0] == "fail":
                raise validators.ValidationError("fail")
            elif len(field.data) > 2:
                raise validators.ValidationError("too many")

        F = make_form(a=FieldList(t, validators=[validator]))
        fdata = DummyPostData({"a-0": ["hello"], "a-1": ["bye"], "a-2": ["test3"]})
        form = F(fdata)
        assert not asyncio.run(form.validate())
        assert form.a.errors == ["too many"]
        fdata["a-0"] = ["fail"]
        form = F(fdata)
        assert not asyncio.run(form.validate())
        assert form.a.errors == ["fail"]
        form = F(DummyPostData({"a-0": [""]}))
        assert not asyncio.run(form.validate())
        assert form.a.errors == [["This field is required."]]

    def test_no_filters(self):
        with raises(TypeError):
            FieldList(t, filters=[str], _form=Form(), name="foo")

    def test_process_prefilled(self):
        data = ["foo", "hi", "rawr"]
        Obj = namedtuple("Obj", "a")
        obj = Obj(data)
        F = make_form(a=FieldList(t))
        form = F(obj=obj)
        assert len(form.a.entries) == 3
        pdata = DummyPostData({"a-0": ["foo"], "a-1": ["hi"], "a-2": ["rawr"]})
        form.process(formdata=pdata)
        assert len(form.a.entries) == 3
        assert form.a.data == data

    def test_errors(self):
        F = make_form(a=FieldList(t))
        form = F(DummyPostData({"a-0": ["a"], "a-1": ""}))
        assert not asyncio.run(form.validate())
        assert form.a.errors == [[], ["This field is required."]]
