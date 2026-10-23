# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_custom.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import StringField
from oldman.web.components.forms._core.fields.choices import SelectFieldBase
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase, raises


class MyCustomField(StringField):
    def process_data(self, data):
        if data == "fail":
            raise ValueError("Contrived Failure")
        return super().process_data(data)


class F(Form):
    a = MyCustomField()
    b = SelectFieldBase()


class TestCustomFields(UpstreamTestCase):
    fixture_functions = {}

    def test_processing_failure(self):
        form = F(a="42")
        assert form.validate()
        form = F(a="fail")
        assert not form.validate()

    def test_default_impls(self):
        f = F()
        with raises(NotImplementedError):
            f.b.iter_choices()
