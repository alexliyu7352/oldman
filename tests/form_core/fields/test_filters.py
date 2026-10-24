# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_filters.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

import asyncio

from oldman.web.components.forms._core.fields import StringField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import DummyPostData, UpstreamTestCase


class F(Form):
    a = StringField(default=" hello", filters=[lambda x: x.strip()])
    b = StringField(default="42", filters=[int, lambda x: -x])


class TestFiltersFields(UpstreamTestCase):
    fixture_functions = {}

    def test_working(self):
        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = F(DummyPostData())
        assert form.a.data == "hello"
        assert form.b.data == -42
        assert asyncio.run(form.validate())

    def test_failure(self):
        form = F(DummyPostData(a=["  foo bar  "], b=["hi"]))
        assert form.a.data == "foo bar"
        assert form.b.data == "hi"
        assert len(form.b.process_errors) == 1
        assert not asyncio.run(form.validate())

    def test_extra(self):

        class F(Form):
            a = StringField(default=" hello ")
            b = StringField(default="42")

        def filter_a(value):
            return value.strip()

        def filter_b(value):
            return -int(value)

        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = F(DummyPostData(), extra_filters={"a": [filter_a], "b": [filter_b]})
        assert "hello" == form.a.data
        assert -42 == form.b.data
        assert asyncio.run(form.validate())

    def test_inline(self):

        class F(Form):
            a = StringField(default=" hello ")
            b = StringField(default="42")

            def filter_a(self, value):
                return value.strip()

            def filter_b(self, value):
                return -int(value)

        # Oldman: only a bound form validates; empty input keeps the initial values.
        form = F(DummyPostData())
        assert "hello" == form.a.data
        assert -42 == form.b.data
        assert asyncio.run(form.validate())
