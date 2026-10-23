# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_url.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import ValidationError, url
from tests.form_core.support import UpstreamTestCase, raises


class TestUrlValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_valid_url_passes(self):
        """
        Valid url should pass without raising
        """
        for url_val in [
            "http://foobar.dk",
            "http://foobar.dk/",
            "http://foo-bar.dk/",
            "http://foo--bar.dk/",
            "http://foo_bar.dk/",
            "http://foobar.dk?query=param",
            "http://foobar.dk/path?query=param",
            "http://foobar.dk/path?query=param&foo=faa",
            "http://foobar.museum/foobar",
            "http://192.168.0.1/foobar",
            "http://192.168.0.1:9000/fake",
            "http://مثال.إختبار/foo.com",
            "http://उदाहरण.परीक्षा/",
            "http://실례.테스트",
        ]:
            with self.subTest(url_val=url_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = url()
                dummy_field.data = url_val
                validator(dummy_form, dummy_field)

    def test_valid_url_notld_passes(self):
        """
        Require TLD option set to false, correct URL should pass without raising
        """
        for url_val in [
            "http://localhost/foobar",
            "http://foobar",
            "http://foobar?query=param&foo=faa",
            "http://foobar:5000?query=param&foo=faa",
            "http://foobar/path?query=param&foo=faa",
            "http://foobar:1234/path?query=param&foo=faa",
        ]:
            with self.subTest(url_val=url_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = url(require_tld=False)
                dummy_field.data = url_val
                validator(dummy_form, dummy_field)

    def test_bad_url_raises(self):
        """
        Bad url should raise ValidationError
        """
        for url_val in [
            "http://foobar",
            "http://-foobar.dk/",
            "http://foobar-.dk/",
            "foobar.dk",
            "http://127.0.0/asdf",
            "http://foobar.d",
            "http://foobar.12",
            "http://localhost:abc/a",
        ]:
            with self.subTest(url_val=url_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = url()
                dummy_field.data = url_val
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)
