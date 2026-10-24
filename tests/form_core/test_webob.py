# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/test_webob.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from typing import Any

from oldman.web.components.forms._core.fields import Field
from oldman.web.components.forms._core.form import BaseForm
from oldman.web.components.forms._core.utils import WebobInputWrapper, unset_value
from tests.form_core.support import UpstreamTestCase

try:
    # Optional: WebOb is not a dependency, and the tests that need it are skipped without it.
    from webob.multidict import MultiDict  # pyright: ignore[reportMissingModuleSource]  # pyrefly: ignore[missing-import]

    has_webob = True
except ImportError:
    has_webob = False


class MockMultiDict:
    def __init__(self, tuples):
        self.tuples = tuples

    def __len__(self):
        return len(self.tuples)

    def __iter__(self):
        for k, _ in self.tuples:
            yield k

    def __contains__(self, key):
        for k, _ in self.tuples:
            if k == key:
                return True
        return False

    def getall(self, key):
        result = []
        for k, v in self.tuples:
            if key == k:
                result.append(v)
        return result


class SneakyField(Field):
    def __init__(self, sneaky_callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sneaky_callable = sneaky_callable

    def process(self, formdata, data: Any = unset_value, extra_filters=None):
        self.sneaky_callable(formdata)


def webob_class():
    return MultiDict if has_webob else MockMultiDict


def test_values():
    return [("a", "Apple"), ("b", "Banana"), ("a", "Cherry")]


def empty_mdict(webob_class):
    return webob_class([])


def filled_mdict(webob_class, test_values):
    return webob_class(test_values)


class TestWebob(UpstreamTestCase):
    fixture_functions = {"webob_class": webob_class, "test_values": test_values, "empty_mdict": empty_mdict, "filled_mdict": filled_mdict}

    def test_automatic_wrapping(self):
        (filled_mdict,) = self.fixtures("filled_mdict")

        def _check(formdata):
            assert isinstance(formdata, WebobInputWrapper)

        form = BaseForm({"a": SneakyField(_check)})
        form.process(filled_mdict)

    def test_empty(self):
        (empty_mdict,) = self.fixtures("empty_mdict")
        formdata = WebobInputWrapper(empty_mdict)
        assert not formdata
        assert len(formdata) == 0
        assert list(formdata) == []
        assert formdata.getlist("fake") == []

    def test_filled(self):
        (filled_mdict,) = self.fixtures("filled_mdict")
        formdata = WebobInputWrapper(filled_mdict)
        assert formdata
        assert len(formdata) == 3
        assert list(formdata) == ["a", "b", "a"]
        assert "b" in formdata
        assert "fake" not in formdata
        assert formdata.getlist("a") == ["Apple", "Cherry"]
        assert formdata.getlist("b") == ["Banana"]
        assert formdata.getlist("fake") == []
