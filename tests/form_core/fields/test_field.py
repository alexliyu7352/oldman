# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_field.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio
from typing import cast

from markupsafe import Markup

from oldman.web.components.forms._core import meta, validators
from oldman.web.components.forms._core.fields import Field, StringField
from oldman.web.components.forms._core.fields.core import UnboundField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase, raises


class F(Form):
    a = StringField(default="hello", render_kw={"readonly": True, "foo": "bar"})
    b = StringField(validators=[validators.InputRequired()])


class PrePostTestField(StringField):
    def pre_validate(self, form):
        if self.data == "stoponly":
            raise validators.StopValidation()
        elif self.data.startswith("stop"):
            raise validators.StopValidation("stop with message")

    def post_validate(self, form, validation_stopped):
        if self.data == "p":
            raise validators.ValidationError("Post")
        elif validation_stopped and self.data == "stop-post":
            raise validators.ValidationError("Post-stopped")


def _init_field(value):

    class F(Form):
        a = PrePostTestField(validators=[validators.Length(max=1, message="too long")])

    # Oldman: only a bound form validates; empty input keeps the initial values.
    form = F(DummyPostData(), a=value)
    asyncio.run(form.validate())
    return form.a


class TestFieldFields(UpstreamTestCase):
    fixture_functions = {}

    def test_unbound_field(self):
        unbound = cast(UnboundField, F.a)
        assert unbound.creation_counter != 0
        assert unbound.field_class is StringField
        assert unbound.args == ()
        assert unbound.kwargs == {"default": "hello", "render_kw": {"readonly": True, "foo": "bar"}}
        assert repr(unbound).startswith("<UnboundField(StringField")

    def test_htmlstring(self):
        assert isinstance(F().a.__html__(), Markup)

    def test_str_coerce(self):
        field = F().a
        assert isinstance(str(field), str)
        assert str(field) == str(field)

    def test_unicode_coerce(self):
        field = F().a
        assert str(field) == field()

    def test_process_formdata(self):
        field = F().a
        Field.process_formdata(field, [42])
        assert field.data == 42

    def test_meta_attribute(self):
        form = F()
        assert form.a.meta is form.meta
        form_meta = meta.DefaultMeta()
        field = StringField(name="Foo", _form=None, _meta=form_meta)
        assert field.meta is form_meta
        with raises(TypeError):
            StringField(name="foo", _form=None)

    def test_render_kw(self):
        form = F()
        assert form.a() == '<input foo="bar" id="a" name="a" readonly type="text" value="hello">'
        assert form.a(foo="baz") == '<input foo="baz" id="a" name="a" readonly type="text" value="hello">'
        assert form.a(foo="baz", readonly=False, other="hello") == '<input foo="baz" id="a" name="a" other="hello" type="text" value="hello">'

    def test_render_special(self):

        class F(Form):
            s = StringField(render_kw={"class_": "foo"})

        assert F().s() == '<input class="foo" id="s" name="s" type="text" value="">'
        assert F().s(**{"class": "bar"}) == '<input class="bar" id="s" name="s" type="text" value="">'
        assert F().s(**{"class_": "bar"}) == '<input class="bar" id="s" name="s" type="text" value="">'

        class G(Form):
            s = StringField(render_kw={"class__": "foo"})

        assert G().s() == '<input class="foo" id="s" name="s" type="text" value="">'
        assert G().s(**{"class__": "bar"}) == '<input class="bar" id="s" name="s" type="text" value="">'

        class H(Form):
            s = StringField(render_kw={"for_": "foo"})

        assert H().s() == '<input for="foo" id="s" name="s" type="text" value="">'
        assert H().s(**{"for": "bar"}) == '<input for="bar" id="s" name="s" type="text" value="">'
        assert H().s(**{"for_": "bar"}) == '<input for="bar" id="s" name="s" type="text" value="">'

    def test_required_flag(self):
        form = F()
        assert form.b() == '<input id="b" name="b" required type="text" value="">'

    def test_check_validators(self):
        v1 = "Not callable"
        v2 = validators.DataRequired
        with raises(TypeError, match=f"{v1} is not a valid validator because it is not callable"):
            Field(validators=[v1])
        with raises(TypeError, match=f"{v2} is not a valid validator because it is a class, it should be an instance"):
            Field(validators=[v2])

    def test_custom_name(self):

        class F(Form):
            foo = StringField(name="bar", default="default")
            x = StringField()

        class ObjFoo:
            foo = "obj"

        class ObjBar:
            bar = "obj"

        f = F(DummyPostData(foo="data"))
        assert f.foo.data == "default"
        assert 'value="default"' in f.foo()
        f = F(DummyPostData(bar="data"))
        assert f.foo.data == "data"
        assert 'value="data"' in f.foo()
        f = F(foo="kwarg")
        assert f.foo.data == "kwarg"
        assert 'value="kwarg"' in f.foo()
        f = F(bar="kwarg")
        assert f.foo.data == "default"
        assert 'value="default"' in f.foo()
        f = F(obj=ObjFoo())
        assert f.foo.data == "obj"
        assert 'value="obj"' in f.foo()
        f = F(obj=ObjBar())
        assert f.foo.data == "default"
        assert 'value="default"' in f.foo()

    def test_pre_stop(self):
        a = _init_field("long")
        assert a.errors == ["too long"]
        stoponly = _init_field("stoponly")
        assert stoponly.errors == []
        stopmessage = _init_field("stopmessage")
        assert stopmessage.errors == ["stop with message"]

    def test_post(self):
        a = _init_field("p")
        assert a.errors == ["Post"]
        stopped = _init_field("stop-post")
        assert stopped.errors == ["stop with message", "Post-stopped"]
