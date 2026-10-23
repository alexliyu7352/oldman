# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_lazy_proxy.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import NumberRange, data_required, email, equal_to, ip_address, length, regexp, url
from tests.form_core.support import UpstreamTestCase, raises


class TestLazyProxyValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_lazy_proxy_raises(self):
        """
        Tests that the validators support lazy translation strings for messages.
        """
        (really_lazy_proxy,) = self.fixtures("really_lazy_proxy")
        with raises(Exception, match="Translator function called during form declaration: it should be called at response time."):
            str(really_lazy_proxy)

    def test_lazy_proxy_fixture(self):
        """
        Tests that the validators support lazy translation strings for messages.
        """
        (really_lazy_proxy,) = self.fixtures("really_lazy_proxy")
        equal_to("fieldname", message=really_lazy_proxy)
        length(min=1, message=really_lazy_proxy)
        NumberRange(1, 5, message=really_lazy_proxy)
        data_required(message=really_lazy_proxy)
        regexp(".+", message=really_lazy_proxy)
        email(message=really_lazy_proxy)
        ip_address(message=really_lazy_proxy)
        url(message=really_lazy_proxy)
