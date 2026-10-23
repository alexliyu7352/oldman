# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_ipaddress.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import ValidationError, ip_address
from tests.form_core.support import UpstreamTestCase, raises


class TestIpaddressValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_ip4address_passes(self):
        for address in ["147.230.23.25", "147.230.23.0", "127.0.0.1"]:
            with self.subTest(address=address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                adr = ip_address()
                dummy_field.data = address
                adr(dummy_form, dummy_field)

    def test_good_ip6address_passes(self):
        for address in ["2001:718:1C01:1111::1111", "2001:718:1C01:1111::", "::1", "dead:beef:0:0:0:0:42:1", "abcd:ef::42:1"]:
            with self.subTest(address=address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                adr = ip_address(ipv6=True)
                dummy_field.data = address
                adr(dummy_form, dummy_field)

    def test_bad_ip6address_raises(self):
        for address in ["2001:718:1C01:1111::1111", "2001:718:1C01:1111::", "abc.0.0.1", "abcd:1234::123::1", "1:2:3:4:5:6:7:8:9", "abcd::1ffff"]:
            with self.subTest(address=address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                adr = ip_address()
                dummy_field.data = address
                with raises(ValidationError):
                    adr(dummy_form, dummy_field)

    def test_bad_ip4address_raises(self):
        for address in ["147.230.1000.25", "2001:718::::", "abc.0.0.1", "1278.0.0.1", "127.0.0.abc", "900.200.100.75"]:
            with self.subTest(address=address):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                adr = ip_address(ipv6=True)
                dummy_field.data = address
                with raises(ValidationError):
                    adr(dummy_form, dummy_field)

    def test_ip_address_raises_on_bad_init(self):
        """
        IpAddress validator should raise ValueError when ipv6=False and ipv4=False
        """
        with raises(ValueError):
            ip_address(ipv4=False, ipv6=False)
