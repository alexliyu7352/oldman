# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/test_i18n.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core import StringField, form, validators
from oldman.web.components.forms._core.i18n import get_translations
from tests.form_core.support import UpstreamTestCase, raises


def gettext_lower(self, s):
    return s.lower()


def ngettext_lower(self, singular, plural, n):
    if n == 1:
        return singular.lower()
    else:
        return plural.lower()


class Lower_Translator:
    """A fake translator that just converts everything to lowercase."""

    gettext = gettext_lower
    ngettext = ngettext_lower


def _test_converter(translator):
    translations = get_translations([], getter=lambda x: translator)
    assert translations.gettext("Foo") == "foo"
    assert translations.ngettext("Foo", "Foos", 1) == "foo"
    assert translations.ngettext("Foo", "Foos", 2) == "foos"
    return translations


class CoreForm1(form.Form):
    class Meta:
        locales = ["en_US", "en"]

    a = StringField(validators=[validators.DataRequired()])


class CoreForm2(form.Form):
    a = StringField(validators=[validators.DataRequired(), validators.Length(max=3)])


class CoreForm3(form.Form):
    a = StringField(validators=[validators.Length(max=1)])


def _common_test(expected_error, form_kwargs, form_class=None):
    if not form_class:
        form_class = CoreForm1
    form = form_class(**form_kwargs)
    assert not form.validate()
    assert form.a.errors[0] == expected_error
    return form


class TranslationsForm1(form.Form):
    a = StringField(validators=[validators.Length(max=5)])


class TranslationsForm2(form.Form):
    class Meta:
        def get_translations(self, form):
            return Lower_Translator()

    a = StringField("", [validators.Length(max=5)])


class TestI18n(UpstreamTestCase):
    fixture_functions = {}

    def test_failure(self):
        with raises(IOError):
            get_translations([])

    def test_python3_nowrap(self):
        translator = Lower_Translator()
        translations = _test_converter(translator)
        assert translations is translator

    def test_core_fallback(self):
        form = _common_test("This field is required.", {"meta": {"locales": False}})
        assert form.a.gettext("") == ""

    def test_gettext(self):
        x = "foo"
        assert TranslationsForm1().a.gettext(x) is x

    def test_translations_ngettext(self):

        def getit(n):
            return TranslationsForm1().a.ngettext("antelope", "antelopes", n)

        assert getit(0) == "antelopes"
        assert getit(1) == "antelope"
        assert getit(2) == "antelopes"

    def test_translations_validator_translation(self):
        form = TranslationsForm2(a="hellobye")
        assert not form.validate()
        assert form.a.errors[0] == "field cannot be longer than 5 characters."
        form = TranslationsForm1(a="hellobye")
        assert not form.validate()
        assert form.a.errors[0] == "Field cannot be longer than 5 characters."
