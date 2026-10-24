# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_label.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from typing import cast

from oldman.web.components.forms._core.fields import Label, StringField
from oldman.web.components.forms._core.fields.core import UnboundField
from oldman.web.components.forms._core.form import Form
from tests.form_core.support import UpstreamTestCase


class TestLabelFields(UpstreamTestCase):
    fixture_functions = {}

    def test_label(self):
        expected = '<label for="test">Caption</label>'
        label = Label("test", "Caption")
        assert label() == expected
        assert str(label) == expected
        assert str(label) == expected
        assert label.__html__() == expected
        assert label().__html__() == expected
        assert label("hello") == '<label for="test">hello</label>'
        assert cast(UnboundField, StringField("hi")).bind(Form(), "a").label.text == "hi"
        assert repr(label) == "Label('test', 'Caption')"

    def test_auto_label(self):
        t1 = cast(UnboundField, StringField()).bind(Form(), "foo_bar")
        assert t1.label.text == "Foo Bar"
        t2 = cast(UnboundField, StringField("")).bind(Form(), "foo_bar")
        assert t2.label.text == ""

    def test_override_for(self):
        label = Label("test", "Caption")
        assert label(for_="foo") == '<label for="foo">Caption</label>'
        assert label(**{"for": "bar"}) == '<label for="bar">Caption</label>'

    def test_escaped_label_text(self):
        label = Label("test", '<script>alert("test");</script>')
        assert label(for_="foo") == '<label for="foo">&lt;script&gt;alert(&#34;test&#34;);&lt;/script&gt;</label>'
        assert label(**{"for": "bar"}) == '<label for="bar">&lt;script&gt;alert(&#34;test&#34;);&lt;/script&gt;</label>'
