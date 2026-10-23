# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_readonly.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import Form, StringField
from oldman.web.components.forms._core.validators import readonly
from tests.form_core.support import DummyPostData, UpstreamTestCase


class TestReadonlyValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_readonly(self):

        class F(Form):
            ro = StringField(validators=[readonly()])

        form = F(ro="foobar")
        assert "readonly" in form.ro.flags
        assert form.ro() == '<input id="ro" name="ro" readonly type="text" value="foobar">'
        assert form.validate()
        form = F(DummyPostData(ro=["foobar"]), data={"ro": "foobar"})
        assert form.validate()
        form = F(DummyPostData(ro=["foobar"]), data={"ro": "foobarbaz"})
        assert not form.validate()
        form = F(DummyPostData(ro=["foobar"]))
        assert not form.validate()

    def test_readonly_with_default(self):

        class F(Form):
            ro = StringField(validators=[readonly()], default="foobar")

        form = F(DummyPostData(ro=["foobar"]))
        assert form.validate()
        form = F(DummyPostData(ro=["foobar"]), data={"ro": "foobarbaz"})
        assert not form.validate()
        form = F(DummyPostData(ro=["foobarbaz"]), data={"ro": "foobarbaz"})
        assert form.validate()
