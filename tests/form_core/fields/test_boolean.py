# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_boolean.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import BooleanField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class AttrDict:
    def __init__(self, *args, **kw):
        self.__dict__.update(*args, **kw)


class BoringForm(Form):
    bool1 = BooleanField()
    bool2 = BooleanField(default=True, false_values=())


obj = AttrDict(bool1=None, bool2=True)


class TestBooleanFields(UpstreamTestCase):
    fixture_functions = {}

    def test_defaults(self):
        form = BoringForm()
        assert form.bool1.raw_data is None
        assert form.bool1.data is False
        assert form.bool2.data is True

    def test_rendering(self):
        form = BoringForm(DummyPostData(bool2="x"))
        assert form.bool1() == '<input id="bool1" name="bool1" type="checkbox" value="y">'
        assert form.bool2() == '<input checked id="bool2" name="bool2" type="checkbox" value="x">'
        assert form.bool2.raw_data == ["x"]

    def test_with_postdata(self):
        form = BoringForm(DummyPostData(bool1=["a"]))
        assert form.bool1.raw_data == ["a"]
        assert form.bool1.data is True
        form = BoringForm(DummyPostData(bool1=["false"], bool2=["false"]))
        assert form.bool1.data is False
        assert form.bool2.data is True

    def test_with_model_data(self):
        form = BoringForm(obj=obj)
        assert form.bool1.data is False
        assert form.bool1.raw_data is None
        assert form.bool2.data is True

    def test_with_postdata_and_model(self):
        form = BoringForm(DummyPostData(bool1=["y"]), obj=obj)
        assert form.bool1.data is True
        assert form.bool2.data is False
