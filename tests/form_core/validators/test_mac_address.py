# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_mac_address.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import ValidationError, mac_address
from tests.form_core.support import UpstreamTestCase, raises


class TestMacAddressValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_valid_mac_passes(self):
        """
        Valid MAC address should pass without raising
        """
        for mac_addr_val in ["01:23:45:67:ab:CD"]:
            with self.subTest(mac_addr_val=mac_addr_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = mac_address()
                dummy_field.data = mac_addr_val
                validator(dummy_form, dummy_field)

    def test_bad_mac_raises(self):
        """
        Bad MAC address should raise ValidatioError
        """
        for mac_addr_val in ["00:00:00:00:00", "01:23:45:67:89:", "01:23:45:67:89:gh", "123:23:45:67:89:00"]:
            with self.subTest(mac_addr_val=mac_addr_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = mac_address()
                dummy_field.data = mac_addr_val
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)
