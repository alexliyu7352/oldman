# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/fields/test_file.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.fields import FileField, MultipleFileField
from oldman.web.components.forms._core.form import Form
from oldman.web.components.forms._core.widgets import TextInput
from tests.form_core.support import DummyPostData, UpstreamTestCase


class TestFileFields(UpstreamTestCase):
    fixture_functions = {}

    def test_file_field(self):

        class F(Form):
            file = FileField()

        assert F(DummyPostData(file=["test.txt"])).file.data == "test.txt"
        assert F(DummyPostData()).file.data is None
        assert F(DummyPostData(file=["test.txt", "multiple.txt"])).file.data == "test.txt"

    def test_multiple_file_field(self):

        class F(Form):
            # A field may take the name of a form attribute (here the uploaded files); the field wins.
            files = MultipleFileField()  # pyrefly: ignore[bad-override]

        assert F(DummyPostData(files=["test.txt"])).files.data == ["test.txt"]
        assert F(DummyPostData()).files.data == []
        assert F(DummyPostData(files=["test.txt", "multiple.txt"])).files.data == ["test.txt", "multiple.txt"]

    def test_file_field_without_file_input(self):

        class F(Form):
            file = FileField(widget=TextInput())

        f = F(DummyPostData(file=["test.txt"]))
        assert f.file.data == "test.txt"
        assert f.file() == '<input id="file" name="file" type="text">'
