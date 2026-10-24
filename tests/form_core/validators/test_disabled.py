# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_disabled.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core import Form, StringField
from oldman.web.components.forms._core.validators import Disabled
from tests.form_core.support import DummyPostData, UpstreamTestCase


class TestDisabledValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_disabled(self):

        class F(Form):
            disabled = StringField(validators=[Disabled()])

        form = F(disabled="foobar")
        assert "disabled" in form.disabled.flags
        assert form.disabled() == '<input disabled id="disabled" name="disabled" type="text" value="foobar">'
        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = F(DummyPostData(), disabled="foobar")
        assert asyncio.run(form.validate())
        form = F(DummyPostData())
        assert asyncio.run(form.validate())
        form = F(DummyPostData(disabled=["foobar"]))
        assert not asyncio.run(form.validate())
