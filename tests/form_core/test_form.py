# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/test_form.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core.fields import IntegerField, StringField
from oldman.web.components.forms._core.form import BaseForm, Form
from oldman.web.components.forms._core.meta import DefaultMeta
from oldman.web.components.forms._core.utils import SanicFormData
from oldman.web.components.forms._core.validators import DataRequired, ValidationError
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


def get_form(**kwargs):

    def validate_test(form, field):
        if field.data != "foobar":
            raise ValidationError("error")

    return BaseForm({"test": StringField(validators=[validate_test])}, **kwargs)


class F(Form):
    test = StringField()

    def validate_test(self, field):
        if field.data != "foobar":
            raise ValidationError("error")


class H(Form):
    class Meta:
        foo = 9

    test = StringField()


class G(Form):
    class Meta:
        foo = 12
        bar = 8


class Basic(H, G):
    class Meta:
        quux = 42


class MissingDiamond(H, G):
    pass


class TestForm(UpstreamTestCase):
    fixture_functions = {}

    def test_baseform_data_proxy(self):
        # Oldman: `data` is the raw input, not the field values.
        form = get_form()
        form.process(SanicFormData({"test": "foo"}))
        assert form.data == {"test": "foo"}

    def test_baseform_errors_proxy(self):
        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = get_form()
        form.process(DummyPostData(test="foobar"))
        asyncio.run(form.validate())
        assert form.errors == {}
        form = get_form()
        form.process(DummyPostData())
        asyncio.run(form.validate())
        assert form.errors == {"test": ["error"]}

    def test_baseform_contains(self):
        form = get_form()
        assert "test" in form
        assert "abcd" not in form

    def test_baseform_field_removal(self):
        form = get_form()
        del form["test"]
        with raises(AttributeError):
            form.test  # noqa: B018 -- the access itself must raise
        assert "test" not in form

    def test_baseform_field_adding(self):
        form = get_form()
        assert len(list(form)) == 1
        form["foo"] = StringField()
        assert len(list(form)) == 2
        form.process(DummyPostData(foo=["hello"]))
        assert form["foo"].data == "hello"
        form["test"] = IntegerField()
        assert isinstance(form["test"], IntegerField)
        assert len(list(form)) == 2
        with raises(AttributeError):
            form["test"].data  # noqa: B018 -- the access itself must raise
        form.process(DummyPostData(test=["1"]))
        assert form["test"].data == 1
        assert form["foo"].data is None

    def test_baseform_populate_obj(self):
        m = type("Model", (object,), {})
        # Oldman: populate_obj writes cleaned_data, so the input is submitted and validated first.
        form = get_form()
        form.process(DummyPostData(test="foobar"))
        assert asyncio.run(form.validate())
        form.populate_obj(m)
        assert m.test == "foobar"
        assert [k for k in dir(m) if not k.startswith("_")] == ["test"]

    def test_baseform_prefixes(self):
        form = get_form(prefix="foo")
        assert form["test"].name == "foo-test"
        assert form["test"].short_name == "test"
        assert form["test"].id == "foo-test"
        form = get_form(prefix="foo.")
        form.process(DummyPostData({"foo.test": ["hello"], "test": ["bye"]}))
        assert form["test"].data == "hello"
        assert get_form(prefix="foo[")["test"].name == "foo[-test"

    def test_baseform_formdata_wrapper_error(self):
        form = get_form()
        with raises(TypeError):
            form.process([])

    def test_form_meta_monkeypatch(self):

        class F(Form):
            a = StringField()

        assert F._unbound_fields is None
        F()
        assert F._unbound_fields == [("a", F.a)]
        F.b = StringField()
        assert F._unbound_fields is None
        F()
        assert F._unbound_fields == [("a", F.a), ("b", F.b)]
        del F.a
        with raises(AttributeError):
            F.a  # noqa: B018 -- the access itself must raise
        F()
        assert F._unbound_fields == [("b", F.b)]
        F._m = StringField()
        assert F._unbound_fields == [("b", F.b)]

    def test_form_meta_subclassing(self):

        class A(Form):
            a = StringField()
            c = StringField()

        class B(A):
            b = StringField()
            c = StringField()

        A()
        B()
        assert A.a is B.a
        assert A.c is not B.c
        assert A._unbound_fields == [("a", A.a), ("c", A.c)]
        assert B._unbound_fields == [("a", B.a), ("b", B.b), ("c", B.c)]

    def test_form_meta_class_meta_reassign(self):

        class MetaA:
            pass

        class MetaB:
            pass

        class F(Form):
            Meta = MetaA

        assert F._wtforms_meta is None
        assert isinstance(F().meta, MetaA)
        assert issubclass(F._wtforms_meta, MetaA)
        F.Meta = MetaB
        assert F._wtforms_meta is None
        assert isinstance(F().meta, MetaB)
        assert issubclass(F._wtforms_meta, MetaB)

    def test_validate(self):
        # Oldman: only a bound form validates; the unbound one below fails for that reason too.
        form = F(DummyPostData(test="foobar"))
        assert asyncio.run(form.validate()) is True
        form = F()
        assert asyncio.run(form.validate()) is False

    def test_validate_with_extra(self):

        class F2(F):
            other = StringField()

        def extra(form, field):
            if field.data != "extra":
                raise ValidationError("error")

        # Oldman: only a bound form validates.
        form = F2(DummyPostData(test="foobar", other="extra"))
        assert asyncio.run(form.validate(extra_validators={"other": [extra]}))
        form = F2(DummyPostData(test="foobar", other="nope"))
        assert not asyncio.run(form.validate(extra_validators={"other": [extra]}))
        form = F2(DummyPostData(test="nope", other="extra"))
        assert not asyncio.run(form.validate(extra_validators={"other": [extra]}))

    def test_form_level_errors(self):

        class F(Form):
            a = IntegerField()
            b = IntegerField()

            # Oldman: an error that belongs to no field is raised from clean() and becomes error_message;
            # there is no form_errors list and no "" key in errors.
            async def clean(self):
                if (self.a.data + self.b.data) % 2 != 0:
                    raise ValidationError("a + b should be even")

        f = F(DummyPostData(a="1", b="1"))
        assert asyncio.run(f.validate())
        assert f.error_message is None
        assert not f.errors
        f = F(DummyPostData(a="0", b="1"))
        assert not asyncio.run(f.validate())
        assert "a + b should be even" == f.error_message
        assert not f.errors

    def test_field_adding_disabled(self):
        form = F()
        with raises(TypeError):
            form.__setitem__("foo", StringField())

    def test_field_removal(self):
        form = F()
        del form.test
        assert "test" not in form
        assert form.test is None
        assert len(list(form)) == 0
        with raises(AttributeError):
            form.__delattr__("fake")

    def test_delattr_idempotency(self):
        form = F()
        del form.test
        assert form.test is None
        form.foo = 9
        del form.foo
        with raises(AttributeError):
            form.__delattr__("foo")
        del form.test
        assert form.test is None

    def test_ordered_fields(self):

        class MyForm(Form):
            strawberry = StringField()
            banana = StringField()
            kiwi = StringField()

        assert [x.name for x in MyForm()] == ["strawberry", "banana", "kiwi"]
        MyForm.apple = StringField()
        assert [x.name for x in MyForm()], ["strawberry", "banana", "kiwi", "apple"]
        del MyForm.banana
        assert [x.name for x in MyForm()] == ["strawberry", "kiwi", "apple"]
        MyForm.strawberry = StringField()
        assert [x.name for x in MyForm()] == ["kiwi", "apple", "strawberry"]
        MyForm.cherry = MyForm.kiwi
        assert [x.name for x in MyForm()] == ["cherry", "kiwi", "apple", "strawberry"]

    def test_data_arg(self):
        data = {"test": "foo"}
        form = F(initial=data)
        assert form.test.data == "foo"
        form = F(initial=data, test="bar")
        assert form.test.data == "bar"

    def test_empty_formdata(self):
        """If formdata is empty, field.process_formdata should still
        run to handle empty data.
        """

        class EmptyStringField(StringField):
            def process_formdata(self, valuelist):
                self.data = valuelist[0] if valuelist else "processed"

        class F(Form):
            test = EmptyStringField()

        assert F().test.data is None
        assert F(test="test").test.data == "test"
        assert F(DummyPostData({"other": "other"})).test.data == "processed"
        assert F(DummyPostData()).test.data == "processed"
        assert F(DummyPostData(), test="test").test.data == "processed"
        assert F(DummyPostData({"test": "foo"}), test="test").test.data == "foo"

    def test_errors_access_during_validation(self):

        class F(Form):
            foo = StringField(validators=[DataRequired()])

            # Oldman: validate() is asynchronous, so an override awaits the parent.
            async def validate(self, extra_validators=None):
                await super().validate(extra_validators)
                self.errors  # noqa: B018 -- reading the property is the behaviour under test
                self.foo.errors.append("bar")
                return True

        form = F(DummyPostData(foo="whatever"))
        asyncio.run(form.validate())
        assert {"foo": ["bar"]} == form.errors

    def test_meta_basic(self):
        form = Basic()
        meta = form.meta
        assert meta.foo == 9
        assert meta.bar == 8
        assert meta.csrf is False
        assert isinstance(meta, H.Meta)
        assert isinstance(meta, G.Meta)
        assert type(meta).__bases__ == (Basic.Meta, H.Meta, G.Meta, DefaultMeta)

    def test_meta_missing_diamond(self):
        meta = MissingDiamond().meta
        assert type(meta).__bases__ == (H.Meta, G.Meta, DefaultMeta)
