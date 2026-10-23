# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_validators.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import Form, StringField
from tests.form_core.support import UpstreamTestCase, raises


class TestValidatorsValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_raise_exceptions(self):
        for exc in [IndexError, ZeroDivisionError, ValueError]:
            with self.subTest(exc=exc):

                def validate(form, field):
                    raise exc  # noqa: B023 -- the closure is called within the same iteration

                class F(Form):
                    field = StringField(validators=[validate])

                f = F()
                with raises(exc):
                    f.validate()
