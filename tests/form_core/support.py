# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/conftest.py and tests/common.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.
"""Shared helpers for the ported WTForms tests: conftest fixtures, DummyPostData and pytest.raises."""

import inspect
import re
import unittest
from collections.abc import Callable
from typing import Any

from oldman.web.components.forms._core.i18n import DummyTranslations


class DummyPostData(dict):
    def getlist(self, key):
        v = self[key]
        if not isinstance(v, list | tuple):
            v = [v]
        return v


class DummyField:
    _translations = DummyTranslations()

    def __init__(
        self,
        data=None,
        name=None,
        errors=(),
        raw_data=None,
        label=None,
        id=None,
        field_type="StringField",
    ):
        self.data: Any = data
        self.name = name
        self.errors = list(errors)
        self.raw_data = raw_data
        self.label = label
        self.id = id if id else ""
        self.type = field_type

    def __call__(self, **other):
        return self.data

    def __str__(self):
        return self.data

    def __iter__(self):
        return iter(self.data)

    def _value(self):
        return self.data

    def iter_choices(self):
        return iter(self.data)

    def iter_groups(self):
        return []

    def has_groups(self):
        return False

    def gettext(self, string):
        return self._translations.gettext(string)

    def ngettext(self, singular, plural, n):
        return self._translations.ngettext(singular, plural, n)


class DummyForm(dict):
    pass


class ReallyLazyProxy:
    def __str__(self):
        raise Exception("Translator function called during form declaration: it should be called at response time.")


def dummy_form():
    return DummyForm()


def dummy_field():
    return DummyField()


def dummy_field_class():
    return DummyField


def basic_widget_dummy_field(dummy_field_class):
    return dummy_field_class("foo", name="bar", label="label", id="id")


def select_dummy_field(dummy_field_class):
    return dummy_field_class([("foo", "lfoo", True, {}), ("bar", "lbar", False, {})])


def html5_dummy_field(dummy_field_class):
    return dummy_field_class("42", name="bar", id="id")


def really_lazy_proxy():
    return ReallyLazyProxy()


CONFTEST_FIXTURES: dict[str, Callable[..., Any]] = {
    "dummy_form": dummy_form,
    "dummy_field": dummy_field,
    "dummy_field_class": dummy_field_class,
    "basic_widget_dummy_field": basic_widget_dummy_field,
    "select_dummy_field": select_dummy_field,
    "html5_dummy_field": html5_dummy_field,
    "really_lazy_proxy": really_lazy_proxy,
}


class UpstreamTestCase(unittest.TestCase):
    """Resolve pytest-style fixtures by parameter name, fresh for every call like pytest does per test."""

    fixture_functions: dict[str, Callable[..., Any]] = {}

    def fixtures(self, *names: str) -> tuple[Any, ...]:
        cache: dict[str, Any] = {}

        def get(name: str) -> Any:
            if name not in cache:
                function = self.fixture_functions.get(name) or CONFTEST_FIXTURES[name]
                cache[name] = function(*(get(parameter) for parameter in inspect.signature(function).parameters))
            return cache[name]

        return tuple(get(name) for name in names)


class _Raises:
    """The context-manager form of pytest.raises: keeps ``.value``, supports ``match=``."""

    def __init__(self, expected, match=None):
        self.expected = expected
        self.match = match
        self.value = None
        self.type = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            raise AssertionError(f"DID NOT RAISE {self.expected!r}")
        if not issubclass(exc_type, self.expected):
            return False
        if self.match is not None and not re.search(self.match, str(exc)):
            raise AssertionError(f"Regex pattern {self.match!r} does not match {str(exc)!r}")
        self.type = exc_type
        self.value = exc
        return True


def raises(expected, *, match=None):
    return _Raises(expected, match)
